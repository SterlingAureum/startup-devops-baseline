#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_SELECTOR="${DEMO_SELECTOR:-app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"
FAILOVER_TIMEOUT_SECONDS="${FAILOVER_TIMEOUT_SECONDS:-1200}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
MARKER_ID="v0.6.5-failover-${RUN_ID}"
PRE_FAILOVER_VALUE="committed-before-primary-failover"
POST_FAILOVER_VALUE="committed-after-primary-failover"

for command in aws kubectl jq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

diagnostics() {
  local exit_code=$?
  if (( exit_code == 0 )); then
    return
  fi

  echo "==> Failover diagnostics" >&2
  kubectl get cluster,pods,pvc \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output wide >&2 || true
  kubectl get endpoints "${POSTGRES_CLUSTER}-rw" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output wide >&2 || true
  kubectl get pods \
    --namespace "${DEMO_NAMESPACE}" \
    --selector "${DEMO_SELECTOR}" \
    --output wide >&2 || true
}
trap diagnostics EXIT

cat <<EOF
WARNING: this test deletes the current PostgreSQL primary Pod.

CloudNativePG must promote a replica, move the ${POSTGRES_CLUSTER}-rw Service,
recreate the former primary with its existing PVC, and restore demo-api
database access. It does not terminate an EC2 node or simulate an AZ failure.

Type 'failover-primary' to continue:
EOF

if [[ "${CONFIRM_POSTGRES_FAILOVER:-}" == "failover-primary" ]]; then
  confirmation="failover-primary"
else
  read -r confirmation
fi

if [[ "${confirmation}" != "failover-primary" ]]; then
  echo "CloudNativePG primary failover test cancelled."
  exit 0
fi

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}"

echo "==> Running non-disruptive preflight validation"
"${ROOT_DIR}/scripts/validate-cloudnative-pg-persistence.sh"
"${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"

get_demo_pod() {
  kubectl get pods \
    --namespace "${DEMO_NAMESPACE}" \
    --selector "${DEMO_SELECTOR}" \
    --field-selector status.phase=Running \
    --output jsonpath='{.items[0].metadata.name}'
}

demo_database_command() {
  local demo_pod
  demo_pod="$(get_demo_pod)"
  if [[ -z "${demo_pod}" ]]; then
    return 1
  fi

  kubectl exec \
    --namespace "${DEMO_NAMESPACE}" \
    "${demo_pod}" -- \
    python -m src.database "$@"
}

mapfile -t PRIMARY_PODS < <(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#PRIMARY_PODS[@]} != 1 )); then
  echo "Expected exactly one running PostgreSQL primary before the test." >&2
  exit 1
fi

ORIGINAL_PRIMARY="${PRIMARY_PODS[0]}"
ORIGINAL_PRIMARY_UID="$(
  kubectl get pod "${ORIGINAL_PRIMARY}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
ORIGINAL_PRIMARY_IP="$(
  kubectl get pod "${ORIGINAL_PRIMARY}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.podIP}'
)"
ORIGINAL_PRIMARY_PVC="${ORIGINAL_PRIMARY}"
ORIGINAL_PVC_UID="$(
  kubectl get pvc "${ORIGINAL_PRIMARY_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
ORIGINAL_PV="$(
  kubectl get pvc "${ORIGINAL_PRIMARY_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.volumeName}'
)"
ORIGINAL_VOLUME_ID="$(
  kubectl get pv "${ORIGINAL_PV}" \
    --output jsonpath='{.spec.csi.volumeHandle}'
)"

if [[ -z "${ORIGINAL_PRIMARY_UID}" || -z "${ORIGINAL_PRIMARY_IP}" || \
      -z "${ORIGINAL_PVC_UID}" || -z "${ORIGINAL_PV}" || \
      "${ORIGINAL_VOLUME_ID}" != vol-* ]]; then
  echo "Could not record the original primary and persistent-volume identity." >&2
  exit 1
fi

echo "==> Writing and reading a committed marker through demo-api"
WRITE_RESULT="$(
  demo_database_command \
    write-marker \
    --id "${MARKER_ID}" \
    --value "${PRE_FAILOVER_VALUE}"
)"
READ_RESULT="$(
  demo_database_command \
    read-marker \
    --id "${MARKER_ID}"
)"
if [[ "$(jq -r '.value // empty' <<< "${WRITE_RESULT}")" != \
      "${PRE_FAILOVER_VALUE}" || \
      "$(jq -r '.value // empty' <<< "${READ_RESULT}")" != \
      "${PRE_FAILOVER_VALUE}" ]]; then
  echo "demo-api did not commit and read the pre-failover marker." >&2
  exit 1
fi

echo "==> Deleting current primary Pod ${ORIGINAL_PRIMARY}"
FAILOVER_STARTED_AT="$(date +%s)"
kubectl delete pod "${ORIGINAL_PRIMARY}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Waiting for a different PostgreSQL primary"
deadline=$((SECONDS + FAILOVER_TIMEOUT_SECONDS))
NEW_PRIMARY=""
while [[ -z "${NEW_PRIMARY}" ]]; do
  candidate="$(
    kubectl get pods \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
      --field-selector status.phase=Running \
      --output jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
  )"
  candidate_ready=""
  if [[ -n "${candidate}" ]]; then
    candidate_ready="$(
      kubectl get pod "${candidate}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.status.conditions[?(@.type=="Ready")].status}' \
        2>/dev/null || true
    )"
  fi

  if [[ -n "${candidate}" && "${candidate}" != "${ORIGINAL_PRIMARY}" && \
        "${candidate_ready}" == "True" ]]; then
    NEW_PRIMARY="${candidate}"
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for a different PostgreSQL primary." >&2
    exit 1
  fi
  sleep 5
done

PROMOTION_SECONDS=$(( $(date +%s) - FAILOVER_STARTED_AT ))
NEW_PRIMARY_IP="$(
  kubectl get pod "${NEW_PRIMARY}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.podIP}'
)"

echo "==> Waiting for the RW Service to point to the new primary"
deadline=$((SECONDS + FAILOVER_TIMEOUT_SECONDS))
while true; do
  mapfile -t RW_ENDPOINTS < <(
    kubectl get endpoints "${POSTGRES_CLUSTER}-rw" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{range .subsets[*].addresses[*]}{.ip}{"\n"}{end}' \
      2>/dev/null || true
  )
  if (( ${#RW_ENDPOINTS[@]} == 1 )) && \
     [[ "${RW_ENDPOINTS[0]}" == "${NEW_PRIMARY_IP}" ]]; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the RW Service to select the new primary." >&2
    exit 1
  fi
  sleep 5
done

echo "==> Waiting for demo-api to reconnect through the RW Service"
deadline=$((SECONDS + FAILOVER_TIMEOUT_SECONDS))
while true; do
  HEALTH_RESULT="$(demo_database_command health 2>/dev/null || true)"
  HEALTH_CONTRACT="$(
    jq -r '
      [
        .status // "",
        .database // "",
        .user // "",
        .server_address // "",
        (.in_recovery | tostring)
      ] | join(":")
    ' <<< "${HEALTH_RESULT:-{}}" 2>/dev/null || true
  )"
  if [[ "${HEALTH_CONTRACT}" == "ok:app:app:${NEW_PRIMARY_IP}:false" ]]; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for demo-api to reconnect to the new primary." >&2
    exit 1
  fi
  sleep 5
done
APPLICATION_RECOVERY_SECONDS=$(( $(date +%s) - FAILOVER_STARTED_AT ))

echo "==> Verifying pre-failover data and a new post-failover write"
READ_RESULT="$(
  demo_database_command \
    read-marker \
    --id "${MARKER_ID}"
)"
if [[ "$(jq -r '.value // empty' <<< "${READ_RESULT}")" != \
      "${PRE_FAILOVER_VALUE}" ]]; then
  echo "The committed pre-failover marker was not preserved." >&2
  exit 1
fi

demo_database_command \
  write-marker \
  --id "${MARKER_ID}" \
  --value "${POST_FAILOVER_VALUE}" >/dev/null
READ_RESULT="$(
  demo_database_command \
    read-marker \
    --id "${MARKER_ID}"
)"
if [[ "$(jq -r '.value // empty' <<< "${READ_RESULT}")" != \
      "${POST_FAILOVER_VALUE}" ]]; then
  echo "demo-api could not write through the new primary." >&2
  exit 1
fi

echo "==> Waiting for the former primary to return as a replica"
deadline=$((SECONDS + FAILOVER_TIMEOUT_SECONDS))
while true; do
  CURRENT_UID="$(
    kubectl get pod "${ORIGINAL_PRIMARY}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.metadata.uid}' 2>/dev/null || true
  )"
  CURRENT_ROLE="$(
    kubectl get pod "${ORIGINAL_PRIMARY}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.metadata.labels.cnpg\.io/instanceRole}' \
      2>/dev/null || true
  )"
  CURRENT_READY="$(
    kubectl get pod "${ORIGINAL_PRIMARY}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.status.conditions[?(@.type=="Ready")].status}' \
      2>/dev/null || true
  )"

  if [[ -n "${CURRENT_UID}" && \
        "${CURRENT_UID}" != "${ORIGINAL_PRIMARY_UID}" && \
        "${CURRENT_ROLE}" == "replica" && \
        "${CURRENT_READY}" == "True" ]]; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the former primary to return as a replica." >&2
    exit 1
  fi
  sleep 5
done

CURRENT_PVC_UID="$(
  kubectl get pvc "${ORIGINAL_PRIMARY_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
CURRENT_PV="$(
  kubectl get pvc "${ORIGINAL_PRIMARY_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.volumeName}'
)"
CURRENT_VOLUME_ID="$(
  kubectl get pv "${CURRENT_PV}" \
    --output jsonpath='{.spec.csi.volumeHandle}'
)"

if [[ "${CURRENT_PVC_UID}" != "${ORIGINAL_PVC_UID}" || \
      "${CURRENT_PV}" != "${ORIGINAL_PV}" || \
      "${CURRENT_VOLUME_ID}" != "${ORIGINAL_VOLUME_ID}" ]]; then
  echo "The former primary did not reuse its original PVC, PV, and EBS volume." >&2
  exit 1
fi

echo "==> Running final database, backup, and application validation"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
"${ROOT_DIR}/scripts/validate-cloudnative-pg-persistence.sh"
"${ROOT_DIR}/scripts/validate-cloudnative-pg-backup.sh"
"${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"

trap - EXIT
echo "Database promotion time: ${PROMOTION_SECONDS}s"
echo "Application recovery time: ${APPLICATION_RECOVERY_SECONDS}s"
echo "CloudNativePG primary failover and demo-api reconnect validation passed."

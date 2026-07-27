#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"
RESTART_TIMEOUT_SECONDS="${RESTART_TIMEOUT_SECONDS:-1200}"
MARKER_VALUE="v0.6.2-replica-persistence-verified"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

cat <<EOF
WARNING: this test restarts one PostgreSQL replica.

The primary and the second replica remain available. The recreated replica
must reuse its existing PVC and EBS volume and recover the replicated marker.
This does not replace the separate v0.6.5 primary failover drill.

Type 'restart-replica' to continue:
EOF

if [[ "${CONFIRM_POSTGRES_RESTART:-}" == "restart-replica" ]]; then
  confirmation="restart-replica"
else
  read -r confirmation
fi

if [[ "${confirmation}" != "restart-replica" ]]; then
  echo "PostgreSQL replica persistence test cancelled."
  exit 0
fi

aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}"

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/validate-cloudnative-pg-persistence.sh"

PRIMARY_POD="$(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --output jsonpath='{.items[0].metadata.name}'
)"
REPLICA_POD="$(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=replica" \
    --output jsonpath='{.items[0].metadata.name}'
)"

if [[ -z "${PRIMARY_POD}" || -z "${REPLICA_POD}" ]]; then
  echo "Could not resolve the PostgreSQL primary and replica Pods." >&2
  exit 1
fi

ORIGINAL_PRIMARY_UID="$(
  kubectl get pod "${PRIMARY_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
ORIGINAL_REPLICA_UID="$(
  kubectl get pod "${REPLICA_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
REPLICA_PVC="${REPLICA_POD}"
ORIGINAL_PVC_UID="$(
  kubectl get pvc "${REPLICA_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
ORIGINAL_PV="$(
  kubectl get pvc "${REPLICA_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.volumeName}'
)"
ORIGINAL_VOLUME_ID="$(
  kubectl get pv "${ORIGINAL_PV}" \
    --output jsonpath='{.spec.csi.volumeHandle}'
)"

echo "==> Writing a marker through the current primary"
kubectl exec \
  --namespace "${POSTGRES_NAMESPACE}" \
  --container postgres \
  "${PRIMARY_POD}" -- \
  psql -U postgres -d app -v ON_ERROR_STOP=1 -qc \
  "CREATE TABLE IF NOT EXISTS public.platform_persistence_validation (
     id text PRIMARY KEY,
     value text NOT NULL
   );
   INSERT INTO public.platform_persistence_validation (id, value)
   VALUES ('ha-replica', '${MARKER_VALUE}')
   ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;"

echo "==> Restarting replica ${REPLICA_POD}"
kubectl delete pod "${REPLICA_POD}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Waiting for CloudNativePG to recreate the replica"
deadline=$((SECONDS + RESTART_TIMEOUT_SECONDS))
NEW_REPLICA_UID=""
while [[ -z "${NEW_REPLICA_UID}" || \
         "${NEW_REPLICA_UID}" == "${ORIGINAL_REPLICA_UID}" ]]; do
  if (( SECONDS >= deadline )); then
    kubectl get cluster,pods,pvc \
      --namespace "${POSTGRES_NAMESPACE}" || true
    echo "Timed out waiting for replacement replica ${REPLICA_POD}." >&2
    exit 1
  fi
  NEW_REPLICA_UID="$(
    kubectl get pod "${REPLICA_POD}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.metadata.uid}' 2>/dev/null || true
  )"
  sleep 5
done

kubectl wait \
  --for=condition=Ready \
  "pod/${REPLICA_POD}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

CURRENT_PRIMARY_UID="$(
  kubectl get pod "${PRIMARY_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
CURRENT_PRIMARY_ROLE="$(
  kubectl get pod "${PRIMARY_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.labels.cnpg\.io/instanceRole}'
)"
CURRENT_REPLICA_ROLE="$(
  kubectl get pod "${REPLICA_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.labels.cnpg\.io/instanceRole}'
)"
CURRENT_PVC_UID="$(
  kubectl get pvc "${REPLICA_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
CURRENT_PV="$(
  kubectl get pvc "${REPLICA_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.volumeName}'
)"
CURRENT_VOLUME_ID="$(
  kubectl get pv "${CURRENT_PV}" \
    --output jsonpath='{.spec.csi.volumeHandle}'
)"

if [[ "${CURRENT_PRIMARY_UID}" != "${ORIGINAL_PRIMARY_UID}" || \
      "${CURRENT_PRIMARY_ROLE}" != "primary" || \
      "${CURRENT_REPLICA_ROLE}" != "replica" ]]; then
  echo "Replica recreation unexpectedly changed the primary role." >&2
  exit 1
fi

if [[ "${CURRENT_PVC_UID}" != "${ORIGINAL_PVC_UID}" || \
      "${CURRENT_PV}" != "${ORIGINAL_PV}" || \
      "${CURRENT_VOLUME_ID}" != "${ORIGINAL_VOLUME_ID}" ]]; then
  echo "Replica ${REPLICA_POD} did not reuse its original persistent volume." >&2
  exit 1
fi

echo "==> Reading the replicated marker from the recreated replica"
deadline=$((SECONDS + RESTART_TIMEOUT_SECONDS))
PERSISTED_VALUE=""
while [[ "${PERSISTED_VALUE}" != "${MARKER_VALUE}" ]]; do
  if (( SECONDS >= deadline )); then
    echo "The marker did not become visible on the recreated replica." >&2
    exit 1
  fi
  PERSISTED_VALUE="$(
    kubectl exec \
      --namespace "${POSTGRES_NAMESPACE}" \
      --container postgres \
      "${REPLICA_POD}" -- \
      psql -U postgres -d app -Atqc \
      "SELECT value
         FROM public.platform_persistence_validation
        WHERE id = 'ha-replica';" 2>/dev/null || true
  )"
  if [[ "${PERSISTED_VALUE}" != "${MARKER_VALUE}" ]]; then
    sleep 5
  fi
done

echo "CloudNativePG replica recreation and persistent-volume reuse validation passed."

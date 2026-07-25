#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-15m}"
RESTART_TIMEOUT_SECONDS="${RESTART_TIMEOUT_SECONDS:-900}"
MARKER_VALUE="v0.6.1-persistence-verified"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

cat <<EOF
WARNING: this test restarts the only PostgreSQL instance.

The app database will be unavailable while CloudNativePG recreates the Pod.
The existing PVC and EBS volume must be reused; the test does not create an
additional database instance.

Type 'restart' to continue:
EOF

if [[ "${CONFIRM_POSTGRES_RESTART:-}" == "restart" ]]; then
  confirmation="restart"
else
  read -r confirmation
fi

if [[ "${confirmation}" != "restart" ]]; then
  echo "PostgreSQL persistence test cancelled."
  exit 0
fi

aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}"

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/validate-cloudnative-pg-persistence.sh"

POSTGRES_POD="$(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --output jsonpath='{.items[0].metadata.name}'
)"
if [[ -z "${POSTGRES_POD}" ]]; then
  echo "Could not find the PostgreSQL primary Pod." >&2
  exit 1
fi

ORIGINAL_POD_UID="$(
  kubectl get pod "${POSTGRES_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
POSTGRES_PVC="$(
  kubectl get pvc \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
    --output jsonpath='{.items[0].metadata.name}'
)"
ORIGINAL_PVC_UID="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
ORIGINAL_PV="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.volumeName}'
)"
ORIGINAL_VOLUME_ID="$(
  kubectl get pv "${ORIGINAL_PV}" \
    --output jsonpath='{.spec.csi.volumeHandle}'
)"

echo "==> Writing persistence marker"
kubectl exec \
  --namespace "${POSTGRES_NAMESPACE}" \
  --container postgres \
  "${POSTGRES_POD}" -- \
  psql -U postgres -d app -v ON_ERROR_STOP=1 -qc \
  "CREATE TABLE IF NOT EXISTS public.platform_persistence_validation (
     id text PRIMARY KEY,
     value text NOT NULL
   );
   INSERT INTO public.platform_persistence_validation (id, value)
   VALUES ('baseline', '${MARKER_VALUE}')
   ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;"

echo "==> Restarting the single PostgreSQL Pod"
kubectl delete pod "${POSTGRES_POD}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Waiting for CloudNativePG to recreate the Pod"
deadline=$((SECONDS + RESTART_TIMEOUT_SECONDS))
NEW_POD_UID=""
while [[ -z "${NEW_POD_UID}" || "${NEW_POD_UID}" == "${ORIGINAL_POD_UID}" ]]; do
  if (( SECONDS >= deadline )); then
    kubectl get cluster,pods,pvc \
      --namespace "${POSTGRES_NAMESPACE}" || true
    echo "Timed out waiting for a replacement PostgreSQL Pod." >&2
    exit 1
  fi
  NEW_POD_UID="$(
    kubectl get pod "${POSTGRES_POD}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.metadata.uid}' 2>/dev/null || true
  )"
  sleep 5
done

kubectl wait \
  --for=condition=Ready \
  "pod/${POSTGRES_POD}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

CURRENT_PVC_UID="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
CURRENT_PV="$(
  kubectl get pvc "${POSTGRES_PVC}" \
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
  echo "PostgreSQL did not reuse the original PVC, PV, and EBS volume." >&2
  exit 1
fi

echo "==> Reading persistence marker after restart"
PERSISTED_VALUE="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${POSTGRES_POD}" -- \
    psql -U postgres -d app -Atqc \
    "SELECT value
     FROM public.platform_persistence_validation
     WHERE id = 'baseline';"
)"

if [[ "${PERSISTED_VALUE}" != "${MARKER_VALUE}" ]]; then
  echo "The persistence marker was not recovered after Pod recreation." >&2
  exit 1
fi

echo "CloudNativePG PostgreSQL Pod recreation and data persistence validation passed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
NODE_POOL_NAME="${NODE_POOL_NAME:-application-spot}"
TEST_NAMESPACE="${TEST_NAMESPACE:-karpenter-spot-smoke}"
TEST_DEPLOYMENT="${TEST_DEPLOYMENT:-karpenter-spot-scale-test}"
TEST_MANIFEST="${TEST_MANIFEST:-${ROOT_DIR}/examples/karpenter/spot-scale-test.yaml}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-15m}"
SCALE_IN_TIMEOUT_SECONDS="${SCALE_IN_TIMEOUT_SECONDS:-1200}"
TEST_APPLIED=false

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

spot_nodeclaims() {
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
    --output name
}

spot_nodes() {
  kubectl get nodes \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
    --output name
}

cleanup_on_exit() {
  if [[ "${TEST_APPLIED}" == "true" ]]; then
    echo "==> Cleaning up Karpenter Spot scale-test workload"
    kubectl delete -f "${TEST_MANIFEST}" \
      --ignore-not-found=true \
      --wait=false >/dev/null 2>&1 || true
    kubectl delete nodeclaim \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
      --ignore-not-found=true \
      --wait=false >/dev/null 2>&1 || true
  fi
}
trap cleanup_on_exit EXIT

"${ROOT_DIR}/scripts/validate-karpenter-interruption.sh"

echo "==> Waiting for Spot NodePool ${NODE_POOL_NAME}"
kubectl wait --for=condition=Ready \
  ec2nodeclass/application --timeout="${WAIT_TIMEOUT}"
kubectl wait --for=condition=Ready \
  "nodepool/${NODE_POOL_NAME}" --timeout="${WAIT_TIMEOUT}"

if [[ -n "$(spot_nodeclaims)" ]] || [[ -n "$(spot_nodes)" ]]; then
  echo "The Spot test requires an empty ${NODE_POOL_NAME} capacity baseline." >&2
  exit 1
fi

echo "==> Applying temporary Spot scale-test workload"
kubectl apply -f "${TEST_MANIFEST}"
TEST_APPLIED=true

echo "==> Waiting for Karpenter Spot scale-out"
if ! kubectl rollout status "deployment/${TEST_DEPLOYMENT}" \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"; then
  kubectl get pods -n "${TEST_NAMESPACE}" -o wide || true
  kubectl get nodeclaims || true
  kubectl get events -n "${TEST_NAMESPACE}" \
    --sort-by='.metadata.creationTimestamp' || true
  echo "Spot capacity was not provisioned before the timeout." >&2
  exit 1
fi

POD_NODE="$(
  kubectl get pods \
    --namespace "${TEST_NAMESPACE}" \
    --selector app.kubernetes.io/name="${TEST_DEPLOYMENT}" \
    --output jsonpath='{.items[0].spec.nodeName}'
)"
NODE_POOL_LABEL="$(
  kubectl get node "${POD_NODE}" \
    --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}'
)"
CAPACITY_TYPE="$(
  kubectl get node "${POD_NODE}" \
    --output jsonpath='{.metadata.labels.karpenter\.sh/capacity-type}'
)"
CAPACITY_TIER="$(
  kubectl get node "${POD_NODE}" \
    --output jsonpath='{.metadata.labels.capacity-tier}'
)"
PROVIDER_ID="$(
  kubectl get node "${POD_NODE}" \
    --output jsonpath='{.spec.providerID}'
)"
INSTANCE_ID="${PROVIDER_ID##*/}"

if [[ "${NODE_POOL_LABEL}" != "${NODE_POOL_NAME}" ]]; then
  echo "Spot scale-test pod did not run on NodePool ${NODE_POOL_NAME}." >&2
  exit 1
fi

if [[ "${CAPACITY_TYPE}" != "spot" || "${CAPACITY_TIER}" != "spot" ]]; then
  echo "Scale-test node is not labeled as Spot capacity." >&2
  exit 1
fi

if [[ "${INSTANCE_ID}" != i-* ]]; then
  echo "Could not resolve the EC2 instance ID from node providerID." >&2
  exit 1
fi

INSTANCE_LIFECYCLE="$(
  aws ec2 describe-instances \
    --region "${AWS_REGION}" \
    --instance-ids "${INSTANCE_ID}" \
    --query 'Reservations[0].Instances[0].InstanceLifecycle' \
    --output text
)"

if [[ "${INSTANCE_LIFECYCLE}" != "spot" ]]; then
  echo "EC2 reports ${INSTANCE_ID} is not a Spot instance." >&2
  exit 1
fi

if [[ -z "$(spot_nodeclaims)" ]]; then
  echo "No Spot NodeClaim was created for the scale test." >&2
  exit 1
fi

echo "==> Spot scale-out validated on ${POD_NODE} (${INSTANCE_ID})"
kubectl get node "${POD_NODE}" \
  --label-columns karpenter.sh/nodepool,karpenter.sh/capacity-type,capacity-tier
kubectl get nodeclaims \
  --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}"

echo "==> Removing temporary Spot scale-test workload"
kubectl delete -f "${TEST_MANIFEST}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"
TEST_APPLIED=false

echo "==> Waiting for Spot consolidation and scale-in"
deadline=$((SECONDS + SCALE_IN_TIMEOUT_SECONDS))
while [[ -n "$(spot_nodeclaims)" ]] || [[ -n "$(spot_nodes)" ]]; do
  if (( SECONDS >= deadline )); then
    echo "Spot scale-in timed out; deleting test NodeClaims." >&2
    kubectl delete nodeclaim \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
      --wait=true \
      --timeout="${WAIT_TIMEOUT}" || true
    exit 1
  fi
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" || true
  sleep 15
done

echo "Karpenter Spot scale-out and scale-in validation passed."

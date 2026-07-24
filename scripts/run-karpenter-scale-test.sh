#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
NODE_POOL_NAME="${NODE_POOL_NAME:-application-ondemand}"
TEST_NAMESPACE="${TEST_NAMESPACE:-karpenter-smoke}"
TEST_DEPLOYMENT="${TEST_DEPLOYMENT:-karpenter-scale-test}"
TEST_MANIFEST="${TEST_MANIFEST:-${ROOT_DIR}/examples/karpenter/scale-test.yaml}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-15m}"
SCALE_IN_TIMEOUT_SECONDS="${SCALE_IN_TIMEOUT_SECONDS:-1200}"
TEST_APPLIED=false

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

cleanup_on_exit() {
  if [[ "${TEST_APPLIED}" == "true" ]]; then
    echo "==> Cleaning up Karpenter scale-test workload"
    kubectl delete -f "${TEST_MANIFEST}" \
      --ignore-not-found=true \
      --wait=false >/dev/null 2>&1 || true
    # The script requires an empty baseline, so any NodeClaim here belongs to
    # this test. Request deletion immediately if validation exits early.
    kubectl delete nodeclaim --all \
      --ignore-not-found=true \
      --wait=false >/dev/null 2>&1 || true
  fi
}
trap cleanup_on_exit EXIT

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Checking Karpenter capacity baseline"
kubectl wait --for=condition=Ready \
  "ec2nodeclass/application" --timeout="${WAIT_TIMEOUT}"
kubectl wait --for=condition=Ready \
  "nodepool/${NODE_POOL_NAME}" --timeout="${WAIT_TIMEOUT}"

if [[ -n "$(kubectl get nodeclaims --output name)" ]] || \
   [[ -n "$(kubectl get nodes --selector karpenter.sh/nodepool --output name)" ]]; then
  echo "The scale test requires an empty Karpenter capacity baseline." >&2
  exit 1
fi

echo "==> Applying temporary scale-test workload"
kubectl apply -f "${TEST_MANIFEST}"
TEST_APPLIED=true

echo "==> Waiting for Karpenter scale-out"
kubectl rollout status "deployment/${TEST_DEPLOYMENT}" \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

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
WORKLOAD_LABEL="$(
  kubectl get node "${POD_NODE}" \
    --output jsonpath='{.metadata.labels.workload}'
)"

if [[ "${NODE_POOL_LABEL}" != "${NODE_POOL_NAME}" ]]; then
  echo "Scale-test pod did not run on NodePool ${NODE_POOL_NAME}." >&2
  exit 1
fi

if [[ "${CAPACITY_TYPE}" != "on-demand" || \
      "${CAPACITY_TIER}" != "on-demand" ]]; then
  echo "Scale-test node is not labeled as On-Demand capacity." >&2
  exit 1
fi

if [[ "${WORKLOAD_LABEL}" != "application" ]]; then
  echo "Scale-test node is missing workload=application." >&2
  exit 1
fi

if [[ -z "$(kubectl get nodeclaims --output name)" ]]; then
  echo "No NodeClaim was created for the scale test." >&2
  exit 1
fi

echo "==> Scale-out validated on ${POD_NODE}"
kubectl get node "${POD_NODE}" \
  --label-columns karpenter.sh/nodepool,karpenter.sh/capacity-type,capacity-tier,workload
kubectl get nodeclaims

echo "==> Removing temporary scale-test workload"
kubectl delete -f "${TEST_MANIFEST}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"
TEST_APPLIED=false

echo "==> Waiting for consolidation and scale-in"
deadline=$((SECONDS + SCALE_IN_TIMEOUT_SECONDS))
while [[ -n "$(kubectl get nodeclaims --output name)" ]] || \
      [[ -n "$(kubectl get nodes --selector karpenter.sh/nodepool --output name)" ]]; do
  if (( SECONDS >= deadline )); then
    echo "Scale-in timed out; forcing deletion of test NodeClaims." >&2
    kubectl delete nodeclaim --all --wait=true --timeout="${WAIT_TIMEOUT}" || true
    exit 1
  fi
  kubectl get nodeclaims || true
  sleep 15
done

echo "Karpenter On-Demand scale-out and scale-in validation passed."

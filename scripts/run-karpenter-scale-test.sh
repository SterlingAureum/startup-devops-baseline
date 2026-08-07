#!/usr/bin/env bash
set -Eeuo pipefail

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

application_nodeclaims() {
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
    --output name
}

application_nodes() {
  kubectl get nodes \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
    --output name
}

count_nonempty_lines() {
  local content="$1"
  if [[ -z "${content}" ]]; then
    printf '0\n'
  else
    grep -c . <<<"${content}"
  fi
}

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

BASELINE_NODECLAIMS="$(application_nodeclaims)"
BASELINE_NODES="$(application_nodes)"
BASELINE_NODECLAIM_COUNT="$(count_nonempty_lines "${BASELINE_NODECLAIMS}")"
BASELINE_NODE_COUNT="$(count_nonempty_lines "${BASELINE_NODES}")"
NODE_LIMIT="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.limits.nodes}'
)"

if [[ ! "${NODE_LIMIT}" =~ ^[0-9]+$ ]]; then
  echo "NodePool ${NODE_POOL_NAME} has no numeric node limit." >&2
  exit 1
fi

if (( BASELINE_NODECLAIM_COUNT != BASELINE_NODE_COUNT )); then
  echo "The ${NODE_POOL_NAME} baseline is still converging." >&2
  echo "NodeClaims: ${BASELINE_NODECLAIM_COUNT}; nodes: ${BASELINE_NODE_COUNT}." >&2
  exit 1
fi

if (( BASELINE_NODE_COUNT >= NODE_LIMIT )); then
  echo "NodePool ${NODE_POOL_NAME} is already at its ${NODE_LIMIT}-node limit." >&2
  exit 1
fi

TEST_REPLICAS=$((BASELINE_NODE_COUNT + 1))
echo "==> Baseline: ${BASELINE_NODECLAIM_COUNT} NodeClaim(s), ${BASELINE_NODE_COUNT} node(s)"
echo "==> Applying ${TEST_REPLICAS} anti-affined scale-test replica(s)"
kubectl apply -f "${TEST_MANIFEST}"
TEST_APPLIED=true
kubectl scale "deployment/${TEST_DEPLOYMENT}" \
  --namespace "${TEST_NAMESPACE}" \
  --replicas "${TEST_REPLICAS}"

echo "==> Waiting for Karpenter incremental scale-out"
kubectl rollout status "deployment/${TEST_DEPLOYMENT}" \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

CURRENT_NODECLAIMS="$(application_nodeclaims)"
CURRENT_NODES="$(application_nodes)"
CURRENT_NODECLAIM_COUNT="$(count_nonempty_lines "${CURRENT_NODECLAIMS}")"
CURRENT_NODE_COUNT="$(count_nonempty_lines "${CURRENT_NODES}")"

if (( CURRENT_NODECLAIM_COUNT <= BASELINE_NODECLAIM_COUNT )) || \
   (( CURRENT_NODE_COUNT <= BASELINE_NODE_COUNT )); then
  echo "The test workload ran without creating incremental ${NODE_POOL_NAME} capacity." >&2
  exit 1
fi

mapfile -t POD_NODES < <(
  kubectl get pods \
    --namespace "${TEST_NAMESPACE}" \
    --selector app.kubernetes.io/name="${TEST_DEPLOYMENT}" \
    --output jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' |
    sort -u
)

if (( ${#POD_NODES[@]} != TEST_REPLICAS )); then
  echo "Scale-test replicas did not spread one per node." >&2
  exit 1
fi

for pod_node in "${POD_NODES[@]}"; do
  node_pool_label="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}'
  )"
  capacity_type="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/capacity-type}'
  )"
  capacity_tier="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.capacity-tier}'
  )"
  workload_label="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.workload}'
  )"

  if [[ "${node_pool_label}" != "${NODE_POOL_NAME}" ]]; then
    echo "Scale-test Pod ran outside NodePool ${NODE_POOL_NAME}." >&2
    exit 1
  fi

  if [[ "${capacity_type}" != "on-demand" || \
        "${capacity_tier}" != "on-demand" || \
        "${workload_label}" != "application" ]]; then
    echo "Scale-test node ${pod_node} violates the On-Demand application contract." >&2
    exit 1
  fi
done

echo "==> Incremental scale-out validated"
kubectl get nodes "${POD_NODES[@]#node/}" \
  --label-columns karpenter.sh/nodepool,karpenter.sh/capacity-type,capacity-tier,workload
kubectl get nodeclaims \
  --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}"

echo "==> Removing temporary scale-test workload"
kubectl delete -f "${TEST_MANIFEST}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"
TEST_APPLIED=false

echo "==> Waiting for consolidation to restore the baseline"
deadline=$((SECONDS + SCALE_IN_TIMEOUT_SECONDS))
while true; do
  current_nodeclaims="$(application_nodeclaims)"
  current_nodes="$(application_nodes)"
  current_nodeclaim_count="$(count_nonempty_lines "${current_nodeclaims}")"
  current_node_count="$(count_nonempty_lines "${current_nodes}")"

  if (( current_nodeclaim_count <= BASELINE_NODECLAIM_COUNT )) && \
     (( current_node_count <= BASELINE_NODE_COUNT )); then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Scale-in timed out; preserving NodeClaims for safe diagnostics." >&2
    kubectl get nodeclaims \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" >&2 || true
    kubectl get nodes \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" >&2 || true
    exit 1
  fi

  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" || true
  sleep 15
done

if kubectl get deployment/demo-api \
  --namespace startup-apps >/dev/null 2>&1; then
  kubectl rollout status deployment/demo-api \
    --namespace startup-apps \
    --timeout="${WAIT_TIMEOUT}"
fi

echo "Karpenter On-Demand incremental scale-out and baseline restoration validation passed."

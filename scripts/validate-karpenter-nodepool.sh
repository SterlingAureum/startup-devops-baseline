#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
ON_DEMAND_NODE_POOL_NAME="${ON_DEMAND_NODE_POOL_NAME:-application-ondemand}"
SPOT_NODE_POOL_NAME="${SPOT_NODE_POOL_NAME:-application-spot}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

validate_nodepool() {
  local nodepool_name="$1"
  local capacity_type="$2"
  local capacity_tier="$3"
  local expected_taint="$4"

  echo "==> Waiting for NodePool ${nodepool_name}"
  kubectl wait \
    --for=condition=Ready \
    "nodepool/${nodepool_name}" \
    --timeout="${WAIT_TIMEOUT}"

  echo "==> Checking ${nodepool_name} isolation"
  local node_class_name
  local workload_label
  local actual_capacity_tier
  local taint
  local requirements
  local cpu_limit
  local memory_limit
  local node_limit

  node_class_name="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.template.spec.nodeClassRef.name}'
  )"
  workload_label="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.template.metadata.labels.workload}'
  )"
  actual_capacity_tier="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.template.metadata.labels.capacity-tier}'
  )"
  taint="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.template.spec.taints[0].key}={.spec.template.spec.taints[0].value}:{.spec.template.spec.taints[0].effect}'
  )"

  if [[ "${node_class_name}" != "application" ]]; then
    echo "NodePool ${nodepool_name} does not reference EC2NodeClass application." >&2
    exit 1
  fi

  if [[ "${workload_label}" != "application" ]]; then
    echo "NodePool ${nodepool_name} is missing workload=application." >&2
    exit 1
  fi

  if [[ "${actual_capacity_tier}" != "${capacity_tier}" ]]; then
    echo "NodePool ${nodepool_name} has the wrong capacity-tier label." >&2
    exit 1
  fi

  if [[ "${taint}" != "${expected_taint}" ]]; then
    echo "NodePool ${nodepool_name} isolation taint is incorrect." >&2
    exit 1
  fi

  echo "==> Checking ${nodepool_name} capacity constraints"
  requirements="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{range .spec.template.spec.requirements[*]}{.key}={.values[*]}{"\n"}{end}'
  )"

  for expected_requirement in \
    "kubernetes.io/arch=amd64" \
    "kubernetes.io/os=linux" \
    "karpenter.sh/capacity-type=${capacity_type}"; do
    if ! grep -qx "${expected_requirement}" <<< "${requirements}"; then
      echo "NodePool ${nodepool_name} is missing requirement ${expected_requirement}." >&2
      exit 1
    fi
  done

  cpu_limit="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.limits.cpu}'
  )"
  memory_limit="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.limits.memory}'
  )"
  node_limit="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{.spec.limits.nodes}'
  )"

  if [[ "${cpu_limit}" != "4" || \
        "${memory_limit}" != "16Gi" || \
        "${node_limit}" != "2" ]]; then
    echo "NodePool ${nodepool_name} safety limits are incorrect." >&2
    exit 1
  fi
}

validate_nodepool \
  "${ON_DEMAND_NODE_POOL_NAME}" \
  "on-demand" \
  "on-demand" \
  "dedicated=application:NoSchedule"

validate_nodepool \
  "${SPOT_NODE_POOL_NAME}" \
  "spot" \
  "spot" \
  "dedicated=application-spot:NoSchedule"

echo "==> Confirming idle baseline"
if [[ -n "$(kubectl get nodeclaims --output name)" ]]; then
  echo "NodeClaims exist before the controlled scale test." >&2
  exit 1
fi

if [[ -n "$(kubectl get nodes --selector karpenter.sh/nodepool --output name)" ]]; then
  echo "Karpenter-provisioned nodes exist before the controlled scale test." >&2
  exit 1
fi

kubectl get nodepools
echo "Karpenter NodePool validation passed."

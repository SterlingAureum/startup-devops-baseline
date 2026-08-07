#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
ON_DEMAND_NODE_POOL_NAME="${ON_DEMAND_NODE_POOL_NAME:-application-ondemand}"
SPOT_NODE_POOL_NAME="${SPOT_NODE_POOL_NAME:-application-spot}"
FIS_NODE_POOL_NAME="${FIS_NODE_POOL_NAME:-application-spot-fis}"
DATABASE_NODE_POOL_NAME="${DATABASE_NODE_POOL_NAME:-database-ondemand}"
DATABASE_RECOVERY_NODE_POOL_NAME="${DATABASE_RECOVERY_NODE_POOL_NAME:-database-recovery-ondemand}"
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
  local expected_workload="$4"
  local expected_taint="$5"
  local expected_node_class="$6"
  local expected_cpu_limit="$7"
  local expected_memory_limit="$8"
  local expected_node_limit="$9"

  echo "==> Waiting for NodePool ${nodepool_name}"
  kubectl wait \
    --for=condition=Ready \
    "nodepool/${nodepool_name}" \
    --timeout="${WAIT_TIMEOUT}"

  echo "==> Checking ${nodepool_name} isolation and capacity"
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

  if [[ "${node_class_name}" != "${expected_node_class}" || \
        "${workload_label}" != "${expected_workload}" || \
        "${actual_capacity_tier}" != "${capacity_tier}" || \
        "${taint}" != "${expected_taint}" ]]; then
    echo "NodePool ${nodepool_name} isolation contract is incorrect." >&2
    exit 1
  fi

  requirements="$(
    kubectl get nodepool "${nodepool_name}" \
      --output jsonpath='{range .spec.template.spec.requirements[*]}{.key}={.values[*]}{"\n"}{end}'
  )"
  for expected_requirement in \
    "kubernetes.io/arch=amd64" \
    "kubernetes.io/os=linux" \
    "karpenter.sh/capacity-type=${capacity_type}"; do
    if ! grep -qx "${expected_requirement}" <<< "${requirements}"; then
      echo "NodePool ${nodepool_name} is missing ${expected_requirement}." >&2
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

  if [[ "${cpu_limit}" != "${expected_cpu_limit}" || \
        "${memory_limit}" != "${expected_memory_limit}" || \
        "${node_limit}" != "${expected_node_limit}" ]]; then
    echo "NodePool ${nodepool_name} safety limits are incorrect." >&2
    exit 1
  fi
}

validate_nodepool \
  "${ON_DEMAND_NODE_POOL_NAME}" \
  "on-demand" \
  "on-demand" \
  "application" \
  "dedicated=application:NoSchedule" \
  "application" \
  "4" \
  "16Gi" \
  "2"

validate_nodepool \
  "${SPOT_NODE_POOL_NAME}" \
  "spot" \
  "spot" \
  "application" \
  "dedicated=application-spot:NoSchedule" \
  "application" \
  "4" \
  "16Gi" \
  "2"

validate_nodepool \
  "${FIS_NODE_POOL_NAME}" \
  "spot" \
  "spot-fis" \
  "application" \
  "dedicated=application-spot-fis:NoSchedule" \
  "application-fis" \
  "4" \
  "32Gi" \
  "2"

validate_nodepool \
  "${DATABASE_NODE_POOL_NAME}" \
  "on-demand" \
  "on-demand" \
  "database" \
  "dedicated=database:NoSchedule" \
  "database" \
  "6" \
  "24Gi" \
  "3"

validate_nodepool \
  "${DATABASE_RECOVERY_NODE_POOL_NAME}" \
  "on-demand" \
  "recovery" \
  "database-recovery" \
  "dedicated=database-recovery:NoSchedule" \
  "database" \
  "2" \
  "8Gi" \
  "1"

DATABASE_REQUIREMENTS="$(
  kubectl get nodepool "${DATABASE_NODE_POOL_NAME}" \
    --output jsonpath='{range .spec.template.spec.requirements[*]}{.key}={.values[*]}{"\n"}{end}'
)"
for expected_requirement in \
  "topology.kubernetes.io/zone=us-east-1a us-east-1b" \
  "karpenter.k8s.aws/instance-category=c m" \
  "karpenter.k8s.aws/instance-cpu=2"; do
  if ! grep -qx "${expected_requirement}" <<< "${DATABASE_REQUIREMENTS}"; then
    echo "Database NodePool is missing ${expected_requirement}." >&2
    exit 1
  fi
done

DATABASE_DISRUPTION="$(
  kubectl get nodepool "${DATABASE_NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.spec.expireAfter}:{.spec.disruption.consolidationPolicy}:{.spec.disruption.consolidateAfter}'
)"
if [[ "${DATABASE_DISRUPTION}" != "Never:WhenEmpty:10m" ]]; then
  echo "Database NodePool disruption policy is incorrect." >&2
  exit 1
fi

RECOVERY_REQUIREMENTS="$(
  kubectl get nodepool "${DATABASE_RECOVERY_NODE_POOL_NAME}" \
    --output jsonpath='{range .spec.template.spec.requirements[*]}{.key}={.values[*]}{"\n"}{end}'
)"
for expected_requirement in \
  "topology.kubernetes.io/zone=us-east-1a us-east-1b" \
  "karpenter.k8s.aws/instance-category=c m" \
  "karpenter.k8s.aws/instance-cpu=2"; do
  if ! grep -qx "${expected_requirement}" <<< "${RECOVERY_REQUIREMENTS}"; then
    echo "Database recovery NodePool is missing ${expected_requirement}." >&2
    exit 1
  fi
done

RECOVERY_DISRUPTION="$(
  kubectl get nodepool "${DATABASE_RECOVERY_NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.spec.expireAfter}:{.spec.disruption.consolidationPolicy}:{.spec.disruption.consolidateAfter}'
)"
if [[ "${RECOVERY_DISRUPTION}" != "Never:WhenEmpty:1m" ]]; then
  echo "Database recovery NodePool disruption policy is incorrect." >&2
  exit 1
fi

echo "==> Confirming exercise-only application and recovery tiers remain idle"
for nodepool_name in \
  "${SPOT_NODE_POOL_NAME}" \
  "${FIS_NODE_POOL_NAME}" \
  "${DATABASE_RECOVERY_NODE_POOL_NAME}"; do
  if [[ -n "$(
    kubectl get nodeclaims \
      --selector "karpenter.sh/nodepool=${nodepool_name}" \
      --output name
  )" ]] || [[ -n "$(
    kubectl get nodes \
      --selector "karpenter.sh/nodepool=${nodepool_name}" \
      --output name
  )" ]]; then
    echo "Temporary capacity exists for idle NodePool ${nodepool_name}." >&2
    exit 1
  fi
done

kubectl get nodepools
echo "Karpenter NodePool validation passed."

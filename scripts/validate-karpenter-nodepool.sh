#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
NODE_POOL_NAME="${NODE_POOL_NAME:-application-ondemand}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Waiting for NodePool ${NODE_POOL_NAME}"
kubectl wait \
  --for=condition=Ready \
  "nodepool/${NODE_POOL_NAME}" \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Checking NodePool isolation"
NODE_CLASS_NAME="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.spec.nodeClassRef.name}'
)"
WORKLOAD_LABEL="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.metadata.labels.workload}'
)"
TAINT="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.spec.taints[0].key}={.spec.template.spec.taints[0].value}:{.spec.template.spec.taints[0].effect}'
)"

if [[ "${NODE_CLASS_NAME}" != "application" ]]; then
  echo "NodePool does not reference EC2NodeClass application." >&2
  exit 1
fi

if [[ "${WORKLOAD_LABEL}" != "application" ]]; then
  echo "NodePool is missing workload=application." >&2
  exit 1
fi

if [[ "${TAINT}" != "dedicated=application:NoSchedule" ]]; then
  echo "NodePool application isolation taint is incorrect." >&2
  exit 1
fi

echo "==> Checking capacity constraints"
REQUIREMENTS="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{range .spec.template.spec.requirements[*]}{.key}={.values[*]}{"\n"}{end}'
)"

for expected_requirement in \
  "kubernetes.io/arch=amd64" \
  "kubernetes.io/os=linux" \
  "karpenter.sh/capacity-type=on-demand"; do
  if ! grep -qx "${expected_requirement}" <<< "${REQUIREMENTS}"; then
    echo "NodePool is missing requirement ${expected_requirement}." >&2
    exit 1
  fi
done

CPU_LIMIT="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.limits.cpu}'
)"
NODE_LIMIT="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.limits.nodes}'
)"

if [[ "${CPU_LIMIT}" != "4" || "${NODE_LIMIT}" != "2" ]]; then
  echo "NodePool safety limits are incorrect." >&2
  exit 1
fi

echo "==> Confirming idle baseline"
if [[ -n "$(kubectl get nodeclaims --output name)" ]]; then
  echo "NodeClaims exist before the controlled scale test." >&2
  exit 1
fi

if [[ -n "$(kubectl get nodes --selector karpenter.sh/nodepool --output name)" ]]; then
  echo "Karpenter-provisioned nodes exist before the controlled scale test." >&2
  exit 1
fi

kubectl get nodepool "${NODE_POOL_NAME}"
echo "Karpenter NodePool validation passed."

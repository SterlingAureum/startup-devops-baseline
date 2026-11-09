#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"

for command in aws kubectl; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Required command not found: ${command}" >&2
    exit 1
  fi
done

echo "Validating AWS identity..."
aws sts get-caller-identity >/dev/null

echo "Updating kubeconfig for ${CLUSTER_NAME} in ${AWS_REGION}..."
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "Checking cluster endpoint..."
kubectl cluster-info

echo "Checking managed nodes..."
kubectl get nodes -o wide

not_ready_nodes="$(kubectl get nodes --no-headers 2>/dev/null | awk '$2 !~ /^Ready/ { count++ } END { print count+0 }')"
if [[ "${not_ready_nodes}" -ne 0 ]]; then
  echo "One or more Kubernetes nodes are not Ready." >&2
  exit 1
fi

echo "Checking EKS managed add-ons..."
for addon in vpc-cni kube-proxy coredns aws-ebs-csi-driver; do
  status="$(aws eks describe-addon \
    --region "${AWS_REGION}" \
    --cluster-name "${CLUSTER_NAME}" \
    --addon-name "${addon}" \
    --query 'addon.status' \
    --output text)"

  printf '%-24s %s\n' "${addon}" "${status}"

  if [[ "${status}" != "ACTIVE" ]]; then
    echo "EKS add-on ${addon} is not ACTIVE." >&2
    exit 1
  fi
done

echo "Checking kube-system workloads..."
kubectl get pods -n kube-system -o wide

echo "EKS baseline validation passed."

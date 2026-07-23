#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
NODE_CLASS_NAME="${NODE_CLASS_NAME:-application}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Waiting for EC2NodeClass ${NODE_CLASS_NAME}"
kubectl wait \
  --for=condition=Ready \
  "ec2nodeclass/${NODE_CLASS_NAME}" \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Checking Karpenter node role"
EXPECTED_NODE_ROLE="$(
  terraform -chdir="${TF_DIR}" output -raw karpenter_node_role_name
)"
ACTUAL_NODE_ROLE="$(
  kubectl get ec2nodeclass "${NODE_CLASS_NAME}" \
    --output jsonpath='{.spec.role}'
)"

if [[ -z "${EXPECTED_NODE_ROLE}" || "${ACTUAL_NODE_ROLE}" != "${EXPECTED_NODE_ROLE}" ]]; then
  echo "EC2NodeClass role does not match Terraform output." >&2
  echo "Expected: ${EXPECTED_NODE_ROLE}" >&2
  echo "Actual:   ${ACTUAL_NODE_ROLE}" >&2
  exit 1
fi

echo "==> Checking discovered infrastructure"
DISCOVERED_SUBNETS="$(
  kubectl get ec2nodeclass "${NODE_CLASS_NAME}" \
    --output jsonpath='{.status.subnets[*].id}'
)"
DISCOVERED_SECURITY_GROUPS="$(
  kubectl get ec2nodeclass "${NODE_CLASS_NAME}" \
    --output jsonpath='{.status.securityGroups[*].id}'
)"
DISCOVERED_AMIS="$(
  kubectl get ec2nodeclass "${NODE_CLASS_NAME}" \
    --output jsonpath='{.status.amis[*].id}'
)"
INSTANCE_PROFILE="$(
  kubectl get ec2nodeclass "${NODE_CLASS_NAME}" \
    --output jsonpath='{.status.instanceProfile}'
)"
EXPECTED_PRIVATE_SUBNETS_JSON="$(
  terraform -chdir="${TF_DIR}" output -json private_subnet_ids
)"
EXPECTED_CLUSTER_SECURITY_GROUP="$(
  terraform -chdir="${TF_DIR}" output -raw eks_cluster_security_group_id
)"

for discovered_value in \
  "${DISCOVERED_SUBNETS}" \
  "${DISCOVERED_SECURITY_GROUPS}" \
  "${DISCOVERED_AMIS}" \
  "${INSTANCE_PROFILE}"; do
  if [[ -z "${discovered_value}" ]]; then
    echo "EC2NodeClass infrastructure discovery returned an empty value." >&2
    exit 1
  fi
done

read -r -a DISCOVERED_SUBNET_ARRAY <<< "${DISCOVERED_SUBNETS}"
if (( ${#DISCOVERED_SUBNET_ARRAY[@]} < 2 )); then
  echo "EC2NodeClass discovered fewer than two private subnets." >&2
  exit 1
fi

for subnet_id in "${DISCOVERED_SUBNET_ARRAY[@]}"; do
  if [[ "${EXPECTED_PRIVATE_SUBNETS_JSON}" != *"\"${subnet_id}\""* ]]; then
    echo "EC2NodeClass discovered non-Terraform private subnet ${subnet_id}." >&2
    exit 1
  fi
done

if [[ " ${DISCOVERED_SECURITY_GROUPS} " != *" ${EXPECTED_CLUSTER_SECURITY_GROUP} "* ]]; then
  echo "EC2NodeClass did not discover the Terraform EKS cluster security group." >&2
  exit 1
fi

echo "==> Confirming idle Karpenter capacity"
if [[ -n "$(kubectl get nodeclaims --output name)" ]]; then
  echo "NodeClaim resources exist outside the controlled scale test." >&2
  exit 1
fi

if [[ -n "$(kubectl get nodes --selector karpenter.sh/nodepool --output name)" ]]; then
  echo "Karpenter-provisioned nodes exist outside the controlled scale test." >&2
  exit 1
fi

echo "==> EC2NodeClass status"
kubectl get ec2nodeclass "${NODE_CLASS_NAME}"

echo "Karpenter EC2NodeClass validation passed."

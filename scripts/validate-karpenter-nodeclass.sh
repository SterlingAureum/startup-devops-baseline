#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
APPLICATION_NODE_CLASS="${APPLICATION_NODE_CLASS:-application}"
DATABASE_NODE_CLASS="${DATABASE_NODE_CLASS:-database}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

EXPECTED_NODE_ROLE="$(
  terraform -chdir="${TF_DIR}" output -raw karpenter_node_role_name
)"
EXPECTED_PRIVATE_SUBNETS_JSON="$(
  terraform -chdir="${TF_DIR}" output -json private_subnet_ids
)"
EXPECTED_CLUSTER_SECURITY_GROUP="$(
  terraform -chdir="${TF_DIR}" output -raw eks_cluster_security_group_id
)"

validate_nodeclass() {
  local nodeclass_name="$1"

  echo "==> Waiting for EC2NodeClass ${nodeclass_name}"
  kubectl wait \
    --for=condition=Ready \
    "ec2nodeclass/${nodeclass_name}" \
    --timeout="${WAIT_TIMEOUT}"

  echo "==> Checking ${nodeclass_name} node role and discovery"
  local actual_node_role
  local discovered_subnets
  local discovered_security_groups
  local discovered_amis
  local instance_profile
  local discovered_subnet_array

  actual_node_role="$(
    kubectl get ec2nodeclass "${nodeclass_name}" \
      --output jsonpath='{.spec.role}'
  )"
  if [[ -z "${EXPECTED_NODE_ROLE}" || \
        "${actual_node_role}" != "${EXPECTED_NODE_ROLE}" ]]; then
    echo "EC2NodeClass ${nodeclass_name} role does not match Terraform output." >&2
    exit 1
  fi

  discovered_subnets="$(
    kubectl get ec2nodeclass "${nodeclass_name}" \
      --output jsonpath='{.status.subnets[*].id}'
  )"
  discovered_security_groups="$(
    kubectl get ec2nodeclass "${nodeclass_name}" \
      --output jsonpath='{.status.securityGroups[*].id}'
  )"
  discovered_amis="$(
    kubectl get ec2nodeclass "${nodeclass_name}" \
      --output jsonpath='{.status.amis[*].id}'
  )"
  instance_profile="$(
    kubectl get ec2nodeclass "${nodeclass_name}" \
      --output jsonpath='{.status.instanceProfile}'
  )"

  for discovered_value in \
    "${discovered_subnets}" \
    "${discovered_security_groups}" \
    "${discovered_amis}" \
    "${instance_profile}"; do
    if [[ -z "${discovered_value}" ]]; then
      echo "EC2NodeClass ${nodeclass_name} discovery returned an empty value." >&2
      exit 1
    fi
  done

  read -r -a discovered_subnet_array <<< "${discovered_subnets}"
  if (( ${#discovered_subnet_array[@]} < 2 )); then
    echo "EC2NodeClass ${nodeclass_name} discovered fewer than two private subnets." >&2
    exit 1
  fi

  for subnet_id in "${discovered_subnet_array[@]}"; do
    if [[ "${EXPECTED_PRIVATE_SUBNETS_JSON}" != *"\"${subnet_id}\""* ]]; then
      echo "EC2NodeClass ${nodeclass_name} discovered non-Terraform subnet ${subnet_id}." >&2
      exit 1
    fi
  done

  if [[ " ${discovered_security_groups} " != \
        *" ${EXPECTED_CLUSTER_SECURITY_GROUP} "* ]]; then
    echo "EC2NodeClass ${nodeclass_name} missed the EKS cluster security group." >&2
    exit 1
  fi
}

validate_nodeclass "${APPLICATION_NODE_CLASS}"
validate_nodeclass "${DATABASE_NODE_CLASS}"

echo "==> Confirming exercise-only application capacity tiers remain idle"
for nodepool_name in \
  application-spot \
  application-spot-fis; do
  if [[ -n "$(
    kubectl get nodeclaims \
      --selector "karpenter.sh/nodepool=${nodepool_name}" \
      --output name
  )" ]]; then
    echo "Unexpected NodeClaim exists for idle NodePool ${nodepool_name}." >&2
    exit 1
  fi
done

kubectl get ec2nodeclass "${APPLICATION_NODE_CLASS}" "${DATABASE_NODE_CLASS}"
echo "Karpenter EC2NodeClass validation passed."

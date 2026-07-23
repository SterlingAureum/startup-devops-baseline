#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"

for command_name in aws terraform; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

terraform_output() {
  terraform -chdir="${TF_DIR}" output -raw "$1"
}

echo "==> Reading Karpenter Terraform outputs"
controller_role_arn="$(terraform_output karpenter_controller_role_arn)"
node_role_arn="$(terraform_output karpenter_node_role_arn)"
queue_name="$(terraform_output karpenter_interruption_queue_name)"
cluster_security_group_id="$(terraform_output eks_cluster_security_group_id)"

controller_role_name="${controller_role_arn##*/}"
node_role_name="${node_role_arn##*/}"

echo "==> Checking Karpenter IAM roles"
aws iam get-role --role-name "${controller_role_name}" >/dev/null
aws iam get-role --role-name "${node_role_name}" >/dev/null

controller_policy_count="$(aws iam list-attached-role-policies \
  --role-name "${controller_role_name}" \
  --query 'length(AttachedPolicies)' \
  --output text)"

node_policy_count="$(aws iam list-attached-role-policies \
  --role-name "${node_role_name}" \
  --query 'length(AttachedPolicies)' \
  --output text)"

if [[ "${controller_policy_count}" -ne 6 ]]; then
  echo "Expected 6 Karpenter controller policies, found ${controller_policy_count}." >&2
  exit 1
fi

if [[ "${node_policy_count}" -ne 4 ]]; then
  echo "Expected 4 Karpenter node policies, found ${node_policy_count}." >&2
  exit 1
fi

echo "==> Checking Karpenter node EKS access entry"
aws eks describe-access-entry \
  --region "${AWS_REGION}" \
  --cluster-name "${CLUSTER_NAME}" \
  --principal-arn "${node_role_arn}" >/dev/null

echo "==> Checking interruption queue"
queue_url="$(aws sqs get-queue-url \
  --region "${AWS_REGION}" \
  --queue-name "${queue_name}" \
  --query 'QueueUrl' \
  --output text)"

queue_encryption="$(aws sqs get-queue-attributes \
  --region "${AWS_REGION}" \
  --queue-url "${queue_url}" \
  --attribute-names SqsManagedSseEnabled \
  --query 'Attributes.SqsManagedSseEnabled' \
  --output text)"

if [[ "${queue_encryption}" != "true" ]]; then
  echo "Karpenter interruption queue encryption is not enabled." >&2
  exit 1
fi

echo "==> Checking EventBridge interruption rules"
event_rule_count="$(aws events list-rules \
  --region "${AWS_REGION}" \
  --name-prefix "${CLUSTER_NAME}-karpenter-" \
  --query 'length(Rules)' \
  --output text)"

if [[ "${event_rule_count}" -ne 5 ]]; then
  echo "Expected 5 Karpenter interruption rules, found ${event_rule_count}." >&2
  exit 1
fi

echo "==> Checking Karpenter discovery tags"
private_subnet_count="$(aws ec2 describe-subnets \
  --region "${AWS_REGION}" \
  --filters "Name=tag:karpenter.sh/discovery,Values=${CLUSTER_NAME}" \
  --query 'length(Subnets)' \
  --output text)"

if [[ "${private_subnet_count}" -lt 2 ]]; then
  echo "Expected at least 2 Karpenter discovery subnets, found ${private_subnet_count}." >&2
  exit 1
fi

security_group_discovery="$(aws ec2 describe-security-groups \
  --region "${AWS_REGION}" \
  --group-ids "${cluster_security_group_id}" \
  --query "SecurityGroups[0].Tags[?Key=='karpenter.sh/discovery'].Value | [0]" \
  --output text)"

if [[ "${security_group_discovery}" != "${CLUSTER_NAME}" ]]; then
  echo "EKS cluster security group is missing the expected discovery tag." >&2
  exit 1
fi

echo "Karpenter AWS foundation validation passed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
KARPENTER_NAMESPACE="${KARPENTER_NAMESPACE:-kube-system}"
SPOT_RULE_NAME="${SPOT_RULE_NAME:-${CLUSTER_NAME}-karpenter-spot-interruption}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Reading interruption queue contract"
QUEUE_NAME="$(
  terraform -chdir="${TF_DIR}" output -raw karpenter_interruption_queue_name
)"
QUEUE_URL="$(
  aws sqs get-queue-url \
    --region "${AWS_REGION}" \
    --queue-name "${QUEUE_NAME}" \
    --query QueueUrl \
    --output text
)"
QUEUE_ARN="$(
  aws sqs get-queue-attributes \
    --region "${AWS_REGION}" \
    --queue-url "${QUEUE_URL}" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text
)"
QUEUE_ENCRYPTION="$(
  aws sqs get-queue-attributes \
    --region "${AWS_REGION}" \
    --queue-url "${QUEUE_URL}" \
    --attribute-names SqsManagedSseEnabled \
    --query Attributes.SqsManagedSseEnabled \
    --output text
)"

if [[ "${QUEUE_ENCRYPTION}" != "true" ]]; then
  echo "Karpenter interruption queue encryption is not enabled." >&2
  exit 1
fi

echo "==> Checking controller interruption queue setting"
CONTROLLER_QUEUE="$(
  kubectl get deployment karpenter \
    --namespace "${KARPENTER_NAMESPACE}" \
    --output jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="INTERRUPTION_QUEUE")].value}'
)"

if [[ "${CONTROLLER_QUEUE}" != "${QUEUE_NAME}" ]]; then
  echo "Karpenter controller is not using Terraform interruption queue ${QUEUE_NAME}." >&2
  exit 1
fi

echo "==> Checking Spot interruption EventBridge rule"
RULE_STATE="$(
  aws events describe-rule \
    --region "${AWS_REGION}" \
    --name "${SPOT_RULE_NAME}" \
    --query State \
    --output text
)"
RULE_PATTERN="$(
  aws events describe-rule \
    --region "${AWS_REGION}" \
    --name "${SPOT_RULE_NAME}" \
    --query EventPattern \
    --output text
)"

if [[ "${RULE_STATE}" != "ENABLED" ]]; then
  echo "Spot interruption EventBridge rule is not enabled." >&2
  exit 1
fi

if [[ "${RULE_PATTERN}" != *"EC2 Spot Instance Interruption Warning"* ]]; then
  echo "Spot interruption EventBridge rule has the wrong event pattern." >&2
  exit 1
fi

mapfile -t TARGET_ARNS < <(
  aws events list-targets-by-rule \
    --region "${AWS_REGION}" \
    --rule "${SPOT_RULE_NAME}" \
    --query 'Targets[].Arn' \
    --output text |
    tr '\t' '\n'
)

TARGET_FOUND=false
for target_arn in "${TARGET_ARNS[@]}"; do
  if [[ "${target_arn}" == "${QUEUE_ARN}" ]]; then
    TARGET_FOUND=true
    break
  fi
done

if [[ "${TARGET_FOUND}" != "true" ]]; then
  echo "Spot interruption EventBridge rule does not target the Karpenter queue." >&2
  exit 1
fi

echo "Karpenter Spot interruption readiness validation passed."

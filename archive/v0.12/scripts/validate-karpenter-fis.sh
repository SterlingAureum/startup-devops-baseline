#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
NODE_CLASS_NAME="${FIS_NODE_CLASS_NAME:-application-fis}"
NODE_POOL_NAME="${FIS_NODE_POOL_NAME:-application-spot-fis}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

terraform_output() {
  terraform -chdir="${TF_DIR}" output -raw "$1"
}

echo "==> Reading AWS FIS Terraform outputs"
ROLE_ARN="$(terraform_output karpenter_fis_role_arn)"
TEMPLATE_ID="$(terraform_output karpenter_fis_experiment_template_id)"
TARGET_TAG_KEY="$(terraform_output karpenter_fis_target_tag_key)"
TARGET_TAG_VALUE="$(terraform_output karpenter_fis_target_tag_value)"
ROLE_NAME="${ROLE_ARN##*/}"

for output_value in \
  "${ROLE_ARN}" \
  "${TEMPLATE_ID}" \
  "${TARGET_TAG_KEY}" \
  "${TARGET_TAG_VALUE}"; do
  if [[ -z "${output_value}" ]]; then
    echo "A required AWS FIS Terraform output is empty." >&2
    exit 1
  fi
done

echo "==> Checking AWS FIS experiment role"
ACCOUNT_ID="$(
  aws sts get-caller-identity \
    --query Account \
    --output text
)"
ACCOUNT_ARN="$(
  aws sts get-caller-identity \
    --query Arn \
    --output text
)"
ARN_WITHOUT_PREFIX="${ACCOUNT_ARN#arn:}"
AWS_PARTITION="${ARN_WITHOUT_PREFIX%%:*}"
TRUSTED_SERVICE="$(
  aws iam get-role \
    --role-name "${ROLE_NAME}" \
    --query 'Role.AssumeRolePolicyDocument.Statement[0].Principal.Service' \
    --output text
)"
TRUST_SOURCE_ACCOUNT="$(
  aws iam get-role \
    --role-name "${ROLE_NAME}" \
    --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.StringEquals."aws:SourceAccount"' \
    --output text
)"
TRUST_SOURCE_ARN="$(
  aws iam get-role \
    --role-name "${ROLE_NAME}" \
    --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition.ArnLike."aws:SourceArn"' \
    --output text
)"

if [[ "${TRUSTED_SERVICE}" != "fis.amazonaws.com" || \
      "${TRUST_SOURCE_ACCOUNT}" != "${ACCOUNT_ID}" || \
      "${TRUST_SOURCE_ARN}" != "arn:${AWS_PARTITION}:fis:${AWS_REGION}:${ACCOUNT_ID}:experiment/*" ]]; then
  echo "The FIS role trust policy does not match the expected service and source scope." >&2
  exit 1
fi

mapfile -t INLINE_POLICIES < <(
  aws iam list-role-policies \
    --role-name "${ROLE_NAME}" \
    --query 'PolicyNames[]' \
    --output text |
    tr '\t' '\n'
)

if (( ${#INLINE_POLICIES[@]} != 1 )); then
  echo "Expected exactly one inline policy on the FIS role." >&2
  exit 1
fi

ATTACHED_POLICY_COUNT="$(
  aws iam list-attached-role-policies \
    --role-name "${ROLE_NAME}" \
    --query 'length(AttachedPolicies)' \
    --output text
)"
mapfile -t POLICY_ACTIONS < <(
  aws iam get-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${INLINE_POLICIES[0]}" \
    --query 'PolicyDocument.Statement[].Action' \
    --output text |
    tr '\t' '\n'
)
INTERRUPTION_RESOURCE="$(
  aws iam get-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "${INLINE_POLICIES[0]}" \
    --query "PolicyDocument.Statement[?Sid=='SendSpotInterruption'].Resource | [0]" \
    --output text
)"

for expected_action in \
  "ec2:DescribeInstances" \
  "ec2:SendSpotInstanceInterruptions"; do
  ACTION_FOUND=false
  for policy_action in "${POLICY_ACTIONS[@]}"; do
    if [[ "${policy_action}" == "${expected_action}" ]]; then
      ACTION_FOUND=true
      break
    fi
  done

  if [[ "${ACTION_FOUND}" != "true" ]]; then
    echo "The FIS role is missing ${expected_action}." >&2
    exit 1
  fi
done

if [[ "${ATTACHED_POLICY_COUNT}" != "0" || \
      "${#POLICY_ACTIONS[@]}" -ne 2 || \
      "${INTERRUPTION_RESOURCE}" != "arn:${AWS_PARTITION}:ec2:${AWS_REGION}:${ACCOUNT_ID}:instance/*" ]]; then
  echo "The FIS role permission scope does not match the expected two-action policy." >&2
  exit 1
fi

echo "==> Checking AWS FIS experiment template"
TEMPLATE_ROLE_ARN="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.roleArn' \
    --output text
)"
STOP_CONDITION="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.stopConditions[0].source' \
    --output text
)"
ACTION_ID="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.actions.interruptKarpenterSpotInstance.actionId' \
    --output text
)"
DURATION="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.actions.interruptKarpenterSpotInstance.parameters.durationBeforeInterruption' \
    --output text
)"
ACTION_TARGET="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.actions.interruptKarpenterSpotInstance.targets.SpotInstances' \
    --output text
)"
RESOURCE_TYPE="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.targets.oneKarpenterSpotInstance.resourceType' \
    --output text
)"
SELECTION_MODE="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query 'experimentTemplate.targets.oneKarpenterSpotInstance.selectionMode' \
    --output text
)"
TEMPLATE_TAG_VALUE="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query "experimentTemplate.targets.oneKarpenterSpotInstance.resourceTags.\"${TARGET_TAG_KEY}\"" \
    --output text
)"
STATE_FILTER="$(
  aws fis get-experiment-template \
    --region "${AWS_REGION}" \
    --id "${TEMPLATE_ID}" \
    --query "experimentTemplate.targets.oneKarpenterSpotInstance.filters[?path=='State.Name'].values[0] | [0]" \
    --output text
)"

if [[ "${TEMPLATE_ROLE_ARN}" != "${ROLE_ARN}" || \
      "${STOP_CONDITION}" != "none" || \
      "${ACTION_ID}" != "aws:ec2:send-spot-instance-interruptions" || \
      "${DURATION}" != "PT2M" || \
      "${ACTION_TARGET}" != "oneKarpenterSpotInstance" || \
      "${RESOURCE_TYPE}" != "aws:ec2:spot-instance" || \
      "${SELECTION_MODE}" != "COUNT(1)" || \
      "${TEMPLATE_TAG_VALUE}" != "${TARGET_TAG_VALUE}" || \
      "${STATE_FILTER}" != "running" ]]; then
  echo "The AWS FIS experiment template does not match the safe Spot interruption contract." >&2
  exit 1
fi

echo "==> Checking isolated Karpenter FIS capacity contract"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}" >/dev/null
kubectl wait \
  --for=condition=Ready \
  "ec2nodeclass/${NODE_CLASS_NAME}" \
  "nodepool/${NODE_POOL_NAME}" \
  --timeout="${WAIT_TIMEOUT}"

NODE_CLASS_TAG="$(
  kubectl get ec2nodeclass "${NODE_CLASS_NAME}" \
    --output "jsonpath={.spec.tags.${TARGET_TAG_KEY}}"
)"
NODE_POOL_CLASS="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.spec.nodeClassRef.name}'
)"
NODE_POOL_CAPACITY="$(
  kubectl get nodepool "${NODE_POOL_NAME}" \
    --output jsonpath='{.spec.template.spec.requirements[?(@.key=="karpenter.sh/capacity-type")].values[0]}'
)"

if [[ "${NODE_CLASS_TAG}" != "${TARGET_TAG_VALUE}" || \
      "${NODE_POOL_CLASS}" != "${NODE_CLASS_NAME}" || \
      "${NODE_POOL_CAPACITY}" != "spot" ]]; then
  echo "The isolated Karpenter FIS capacity contract is incorrect." >&2
  exit 1
fi

echo "AWS FIS Spot interruption foundation validation passed."

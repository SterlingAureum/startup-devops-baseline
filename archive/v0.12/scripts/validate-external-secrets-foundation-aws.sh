#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
readonly AWS_REGION="${AWS_REGION:-us-east-1}"
readonly EXPECTED_SERVICE_ACCOUNT_SUBJECT="system:serviceaccount:external-secrets:external-secrets"

for command in aws jq terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

tf_output() {
  terraform -chdir="${TF_DIR}" output -raw "$1"
}

echo "==> Reading non-sensitive Terraform outputs"
SECRET_NAME="$(tf_output external_secrets_secret_name)"
SECRET_ARN="$(tf_output external_secrets_secret_arn)"
ROLE_ARN="$(tf_output external_secrets_role_arn)"
ROLE_NAME="$(tf_output external_secrets_role_name)"
POLICY_ARN="$(tf_output external_secrets_policy_arn)"
OIDC_PROVIDER_ARN="$(tf_output eks_oidc_provider_arn)"
OIDC_PROVIDER_PATH="${OIDC_PROVIDER_ARN#*:oidc-provider/}"

for value_name in \
  SECRET_NAME \
  SECRET_ARN \
  ROLE_ARN \
  ROLE_NAME \
  POLICY_ARN \
  OIDC_PROVIDER_ARN; do
  [[ -n "${!value_name}" ]] || {
    echo "Terraform output ${value_name} is empty." >&2
    exit 1
  }
done

echo "==> Validating Secrets Manager container metadata"
SECRET_METADATA="$(
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
)"
jq --exit-status \
  --arg expected_name "${SECRET_NAME}" \
  --arg expected_arn "${SECRET_ARN}" \
  '
    .Name == $expected_name and
    .ARN == $expected_arn and
    (.DeletedDate == null)
  ' <<<"${SECRET_METADATA}" >/dev/null

echo "==> Validating ServiceAccount-scoped IRSA trust"
TRUST_DOCUMENT="$(
  aws iam get-role \
    --role-name "${ROLE_NAME}" \
    --query 'Role.AssumeRolePolicyDocument' \
    --output json
)"
jq --exit-status \
  --arg provider "${OIDC_PROVIDER_ARN}" \
  --arg audience_key "${OIDC_PROVIDER_PATH}:aud" \
  --arg subject_key "${OIDC_PROVIDER_PATH}:sub" \
  --arg subject "${EXPECTED_SERVICE_ACCOUNT_SUBJECT}" \
  '
    (.Statement | length) == 1 and
    .Statement[0].Effect == "Allow" and
    .Statement[0].Principal.Federated == $provider and
    .Statement[0].Action == "sts:AssumeRoleWithWebIdentity" and
    .Statement[0].Condition.StringEquals[$audience_key] == "sts.amazonaws.com" and
    .Statement[0].Condition.StringEquals[$subject_key] == $subject
  ' <<<"${TRUST_DOCUMENT}" >/dev/null

if [[ "${ROLE_ARN}" != "arn:"*":iam::"*":role/${ROLE_NAME}" ]]; then
  echo "Terraform role ARN and role name are inconsistent." >&2
  exit 1
fi

echo "==> Validating least-privilege Secrets Manager policy"
ATTACHED_POLICIES="$(
  aws iam list-attached-role-policies \
    --role-name "${ROLE_NAME}" \
    --query 'AttachedPolicies' \
    --output json
)"
jq --exit-status \
  --arg policy_arn "${POLICY_ARN}" \
  'any(.[]; .PolicyArn == $policy_arn)' \
  <<<"${ATTACHED_POLICIES}" >/dev/null

POLICY_VERSION="$(
  aws iam get-policy \
    --policy-arn "${POLICY_ARN}" \
    --query 'Policy.DefaultVersionId' \
    --output text
)"
POLICY_DOCUMENT="$(
  aws iam get-policy-version \
    --policy-arn "${POLICY_ARN}" \
    --version-id "${POLICY_VERSION}" \
    --query 'PolicyVersion.Document' \
    --output json
)"
jq --exit-status \
  --arg secret_arn "${SECRET_ARN}" \
  '
    (.Statement | length) == 1 and
    .Statement[0].Effect == "Allow" and
    ([.Statement[0].Action] | flatten | sort) == [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue"
    ] and
    ([.Statement[0].Resource] | flatten) == [$secret_arn]
  ' <<<"${POLICY_DOCUMENT}" >/dev/null

echo "==> Confirming Terraform manages no secret version"
mapfile -t SECRET_STATE_RESOURCES < <(
  terraform -chdir="${TF_DIR}" state list |
    grep 'module.external_secrets.aws_secretsmanager_secret' || true
)
if (( ${#SECRET_STATE_RESOURCES[@]} != 1 )) || \
   [[ "${SECRET_STATE_RESOURCES[0]}" != \
     "module.external_secrets.aws_secretsmanager_secret.this" ]]; then
  echo "Unexpected External Secrets Terraform state resources:" >&2
  printf '%s\n' "${SECRET_STATE_RESOURCES[@]}" >&2
  exit 1
fi

echo "External Secrets AWS foundation runtime validation passed."

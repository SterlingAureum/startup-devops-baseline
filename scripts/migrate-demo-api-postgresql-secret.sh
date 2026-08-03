#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
SOURCE_NAMESPACE="${SOURCE_NAMESPACE:-data-platform}"
SOURCE_SECRET="${SOURCE_SECRET:-postgresql-baseline-app}"
SOURCE_KEY="${SOURCE_KEY:-fqdn-uri}"
REMOTE_KEY="${REMOTE_KEY:-DATABASE_URL}"

for command in aws base64 jq kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before migrating a credential." >&2
  exit 1
fi

if [[ "${CONFIRM_EXTERNAL_SECRETS_MIGRATION:-}" != "seed-from-cnpg" ]]; then
  cat >&2 <<'EOF'
This guarded operation reads the CloudNativePG application URI and writes it
as the first AWS Secrets Manager version without printing the value.

Re-run with:
  CONFIRM_EXTERNAL_SECRETS_MIGRATION=seed-from-cnpg \
    ./scripts/migrate-demo-api-postgresql-secret.sh
EOF
  exit 1
fi

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

SECRET_ARN="$(
  terraform -chdir="${TF_DIR}" output -raw external_secrets_secret_arn
)"
SECRET_NAME="$(
  terraform -chdir="${TF_DIR}" output -raw external_secrets_secret_name
)"

if [[ -z "${SECRET_ARN}" || -z "${SECRET_NAME}" ]]; then
  echo "External Secrets Terraform outputs are empty." >&2
  exit 1
fi

echo "==> Reading the CloudNativePG application credential without printing it"
SOURCE_BASE64="$(
  kubectl get secret "${SOURCE_SECRET}" \
    --namespace "${SOURCE_NAMESPACE}" \
    --output json |
    jq -er --arg key "${SOURCE_KEY}" '.data[$key] | select(length > 0)'
)"
SOURCE_VALUE="$(printf '%s' "${SOURCE_BASE64}" | base64 --decode)"

if [[ -z "${SOURCE_VALUE}" || "${SOURCE_VALUE}" != postgresql://* ]]; then
  echo "The source key is empty or is not a PostgreSQL URI." >&2
  exit 1
fi

echo "==> Checking the Terraform-managed Secrets Manager container"
SECRET_METADATA="$(
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
)"
jq --exit-status \
  --arg name "${SECRET_NAME}" \
  --arg arn "${SECRET_ARN}" \
  '.Name == $name and .ARN == $arn and (.DeletedDate == null)' \
  <<<"${SECRET_METADATA}" >/dev/null

HAS_CURRENT_VERSION="$(
  jq -r '
    [(.VersionIdsToStages // {}) | to_entries[]
      | select(.value | index("AWSCURRENT"))] | length > 0
  ' <<<"${SECRET_METADATA}"
)"

if [[ "${HAS_CURRENT_VERSION}" == "true" ]]; then
  echo "==> Confirming the existing AWSCURRENT value is idempotent"
  REMOTE_DOCUMENT="$(
    aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSCURRENT \
      --query SecretString \
      --output text
  )"
  REMOTE_VALUE="$(
    jq -er --arg key "${REMOTE_KEY}" '.[$key] | select(type == "string" and length > 0)' \
      <<<"${REMOTE_DOCUMENT}"
  )"

  if [[ "${REMOTE_VALUE}" != "${SOURCE_VALUE}" ]]; then
    echo "AWSCURRENT differs from the CloudNativePG credential; refusing to overwrite it." >&2
    echo "Credential rotation belongs to v0.8.5 and requires a separate plan." >&2
    exit 1
  fi
else
  echo "==> Creating the first AWSCURRENT version from protected standard input"
  printf '%s' "${SOURCE_VALUE}" |
    jq -Rsc '{DATABASE_URL: .}' |
    aws secretsmanager put-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --secret-string file:///dev/stdin \
      --output json >/dev/null

  REMOTE_DOCUMENT="$(
    aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSCURRENT \
      --query SecretString \
      --output text
  )"
  REMOTE_VALUE="$(
    jq -er --arg key "${REMOTE_KEY}" '.[$key] | select(type == "string" and length > 0)' \
      <<<"${REMOTE_DOCUMENT}"
  )"

  if [[ "${REMOTE_VALUE}" != "${SOURCE_VALUE}" ]]; then
    echo "The first Secrets Manager value does not match the source credential." >&2
    exit 1
  fi
fi

unset SOURCE_BASE64 SOURCE_VALUE REMOTE_DOCUMENT REMOTE_VALUE

echo "demo-api PostgreSQL credential migration passed."
echo "The credential value was not printed, committed to Git, or written to Terraform state."

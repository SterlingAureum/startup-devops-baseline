#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
TARGET_NAMESPACE="${TARGET_NAMESPACE:-startup-apps}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-demo-api-postgresql}"

for command in aws awk base64 jq kubectl python3 sha256sum terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before validating credentials." >&2
  exit 1
fi

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

SECRET_ARN="$(
  terraform -chdir="${TF_DIR}" output -raw external_secrets_secret_arn
)"
[[ -n "${SECRET_ARN}" ]] || {
  echo "Terraform output external_secrets_secret_arn is empty." >&2
  exit 1
}

echo "==> Checking AWSCURRENT and AWSPENDING version-stage isolation"
METADATA="$({
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
})"
CURRENT_VERSION_ID="$(
  jq -r '
    [(.VersionIdsToStages // {}) | to_entries[]
      | select(.value | index("AWSCURRENT")) | .key]
    | if length == 1 then .[0] else empty end
  ' <<<"${METADATA}"
)"
PENDING_VERSION_ID="$(
  jq -r '
    [(.VersionIdsToStages // {}) | to_entries[]
      | select(.value | index("AWSPENDING")) | .key]
    | if length == 1 then .[0] else empty end
  ' <<<"${METADATA}"
)"
if [[ -z "${CURRENT_VERSION_ID}" || -z "${PENDING_VERSION_ID}" || \
      "${CURRENT_VERSION_ID}" == "${PENDING_VERSION_ID}" ]]; then
  echo "Expected distinct, singular AWSCURRENT and AWSPENDING versions." >&2
  exit 1
fi

echo "==> Validating candidate structure without printing either URI"
python3 - \
  <(aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSCURRENT \
      --query SecretString \
      --output text) \
  <(aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSPENDING \
      --query SecretString \
      --output text) <<'PY'
import json
import sys
from urllib.parse import unquote, urlsplit

key = "DATABASE_URL"
with open(sys.argv[1], encoding="utf-8") as current_file:
    current_document = json.load(current_file)
with open(sys.argv[2], encoding="utf-8") as pending_file:
    pending_document = json.load(pending_file)
if set(current_document) != {key} or set(pending_document) != {key}:
    raise SystemExit("Credential documents must contain exactly DATABASE_URL.")
current = urlsplit(current_document[key])
pending = urlsplit(pending_document[key])
for field in ("scheme", "username", "hostname", "port", "path", "query", "fragment"):
    if getattr(current, field) != getattr(pending, field):
        raise SystemExit(f"Candidate changed protected URI field: {field}")
current_password = unquote(current.password or "")
pending_password = unquote(pending.password or "")
if not current_password or pending_password == current_password or len(pending_password) < 48:
    raise SystemExit("Candidate password contract failed.")
PY

secret_digest() {
  local stage="$1"
  aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --version-stage "${stage}" \
    --query SecretString \
    --output text |
    jq --exit-status --join-output --raw-output \
      '.DATABASE_URL | select(type == "string" and length > 0)' |
    sha256sum |
    awk '{print $1}'
}

kubernetes_digest() {
  local namespace="$1"
  local secret_name="$2"
  local key="$3"
  kubectl get secret "${secret_name}" \
    --namespace "${namespace}" \
    --output json |
    jq --exit-status --join-output --raw-output --arg key "${key}" \
      '.data[$key] | select(length > 0)' |
    base64 --decode |
    sha256sum |
    awk '{print $1}'
}

CURRENT_DIGEST="$(secret_digest AWSCURRENT)"
PENDING_DIGEST="$(secret_digest AWSPENDING)"
TARGET_DIGEST="$(kubernetes_digest "${TARGET_NAMESPACE}" "${TARGET_SECRET}" DATABASE_URL)"
if [[ "${CURRENT_DIGEST}" == "${PENDING_DIGEST}" || \
      "${CURRENT_DIGEST}" != "${TARGET_DIGEST}" ]]; then
  echo "Candidate isolation or current credential-chain equality failed." >&2
  exit 1
fi

echo "==> Confirming External Secrets still consumes only AWSCURRENT"
EXTERNAL_SECRET_JSON="$(
  kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json
)"
jq --exit-status '
  .spec.data[0].remoteRef.version == "AWSCURRENT" and
  (.metadata.annotations["force-sync"] == null) and
  any(.status.conditions[]?; .type == "Ready" and .status == "True")
' <<<"${EXTERNAL_SECRET_JSON}" >/dev/null || {
  echo "ExternalSecret is not Ready, clean, and pinned to AWSCURRENT." >&2
  exit 1
}

unset CURRENT_DIGEST PENDING_DIGEST TARGET_DIGEST

echo "PostgreSQL credential rotation Checkpoint 1 AWS validation passed."
echo "AWSPENDING is isolated; AWSCURRENT and the live Kubernetes credential remain unchanged."

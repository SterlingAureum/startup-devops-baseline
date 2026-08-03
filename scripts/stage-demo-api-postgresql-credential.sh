#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
TARGET_NAMESPACE="${TARGET_NAMESPACE:-startup-apps}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
TARGET_KEY="${TARGET_KEY:-DATABASE_URL}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-demo-api-postgresql}"

for command in aws awk base64 jq kubectl python3 sha256sum terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before staging a credential." >&2
  exit 1
fi

if [[ "${CONFIRM_POSTGRESQL_CREDENTIAL_STAGE:-}" != "stage-awspending" ]]; then
  cat >&2 <<'EOF'
This guarded operation generates a candidate PostgreSQL URI and stores it only
as AWSPENDING. It does not alter PostgreSQL, move AWSCURRENT, refresh External
Secrets, or restart demo-api Pods.

Re-run with:
  CONFIRM_POSTGRESQL_CREDENTIAL_STAGE=stage-awspending \
    ./scripts/stage-demo-api-postgresql-credential.sh
EOF
  exit 1
fi

tf_output() {
  local output_name="$1"
  local value

  value="$(terraform -chdir="${TF_DIR}" output -raw "${output_name}")"
  [[ -n "${value}" ]] || {
    echo "Terraform output ${output_name} is empty." >&2
    exit 1
  }
  printf '%s' "${value}"
}

stage_version_id() {
  local metadata="$1"
  local stage="$2"

  jq -r --arg stage "${stage}" '
    [(.VersionIdsToStages // {}) | to_entries[]
      | select(.value | index($stage))
      | .key]
    | if length == 1 then .[0] else empty end
  ' <<<"${metadata}"
}

remote_digest() {
  local secret_arn="$1"
  local stage="$2"

  aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${secret_arn}" \
    --version-stage "${stage}" \
    --query SecretString \
    --output text |
    jq --exit-status --join-output --raw-output --arg key "${TARGET_KEY}" \
      '.[$key] | select(type == "string" and length > 0)' |
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

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

SECRET_ARN="$(tf_output external_secrets_secret_arn)"
SECRET_NAME="$(tf_output external_secrets_secret_name)"

echo "==> Checking the current credential chain without printing values"
SECRET_METADATA="$({
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
})"

jq --exit-status \
  --arg name "${SECRET_NAME}" \
  --arg arn "${SECRET_ARN}" \
  '.Name == $name and .ARN == $arn and (.DeletedDate == null)' \
  <<<"${SECRET_METADATA}" >/dev/null

CURRENT_VERSION_ID="$(stage_version_id "${SECRET_METADATA}" AWSCURRENT)"
PENDING_VERSION_ID="$(stage_version_id "${SECRET_METADATA}" AWSPENDING)"
[[ -n "${CURRENT_VERSION_ID}" ]] || {
  echo "Secrets Manager does not have exactly one AWSCURRENT version." >&2
  exit 1
}
if [[ -n "${PENDING_VERSION_ID}" ]]; then
  cat >&2 <<EOF
An AWSPENDING candidate already exists. Refusing to replace it.
Validate it with:
  ./scripts/validate-postgresql-credential-rotation-aws.sh
Or discard it with the separately guarded discard script.
EOF
  exit 1
fi

CURRENT_DIGEST="$(remote_digest "${SECRET_ARN}" AWSCURRENT)"
TARGET_DIGEST="$(kubernetes_digest "${TARGET_NAMESPACE}" "${TARGET_SECRET}" "${TARGET_KEY}")"
if [[ "${CURRENT_DIGEST}" != "${TARGET_DIGEST}" ]]; then
  echo "AWSCURRENT and the ESO target Secret differ." >&2
  exit 1
fi

EXTERNAL_SECRET_JSON="$(
  kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json
)"
jq --exit-status '
  .spec.data[0].remoteRef.version == "AWSCURRENT" and
  any(.status.conditions[]?; .type == "Ready" and .status == "True")
' <<<"${EXTERNAL_SECRET_JSON}" >/dev/null || {
  echo "ExternalSecret is not Ready or is not pinned to AWSCURRENT." >&2
  exit 1
}

echo "==> Generating and storing one AWSPENDING candidate through protected pipes"
PUT_RESULT="$(
  python3 - "${TARGET_KEY}" \
    <(aws secretsmanager get-secret-value \
        --region "${AWS_REGION}" \
        --secret-id "${SECRET_ARN}" \
        --version-stage AWSCURRENT \
        --query SecretString \
        --output text) <<'PY' |
import json
import secrets
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit

key = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as current_file:
    document = json.load(current_file)
if set(document) != {key} or not isinstance(document[key], str):
    raise SystemExit("The current Secret document does not contain exactly DATABASE_URL.")

current = urlsplit(document[key])
if current.scheme not in {"postgres", "postgresql"}:
    raise SystemExit("The current credential is not a PostgreSQL URI.")
if current.username is None or current.password is None or current.hostname is None:
    raise SystemExit("The current PostgreSQL URI is incomplete.")

new_password = secrets.token_urlsafe(48)
username = quote(unquote(current.username), safe="")
host = current.hostname
if ":" in host and not host.startswith("["):
    host = f"[{host}]"
port = f":{current.port}" if current.port is not None else ""
netloc = f"{username}:{quote(new_password, safe='')}@{host}{port}"
candidate = urlunsplit(
    (current.scheme, netloc, current.path, current.query, current.fragment)
)
json.dump({key: candidate}, sys.stdout, separators=(",", ":"))
PY
  aws secretsmanager put-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --secret-string file:///dev/stdin \
    --version-stages AWSPENDING \
    --output json
)"

NEW_PENDING_VERSION_ID="$(jq -er '.VersionId | select(length > 0)' <<<"${PUT_RESULT}")"
unset PUT_RESULT

echo "==> Proving AWSCURRENT stayed fixed and the candidate is structurally safe"
SECRET_METADATA_AFTER="$({
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
})"
CURRENT_VERSION_ID_AFTER="$(stage_version_id "${SECRET_METADATA_AFTER}" AWSCURRENT)"
PENDING_VERSION_ID_AFTER="$(stage_version_id "${SECRET_METADATA_AFTER}" AWSPENDING)"

if [[ "${CURRENT_VERSION_ID_AFTER}" != "${CURRENT_VERSION_ID}" || \
      "${PENDING_VERSION_ID_AFTER}" != "${NEW_PENDING_VERSION_ID}" || \
      "${CURRENT_VERSION_ID_AFTER}" == "${PENDING_VERSION_ID_AFTER}" ]]; then
  echo "Secrets Manager version stages do not match the staging contract." >&2
  exit 1
fi

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
      --output text) \
  "${TARGET_KEY}" <<'PY'
import json
import sys
from urllib.parse import unquote, urlsplit

with open(sys.argv[1], encoding="utf-8") as current_file:
    current_document = json.load(current_file)
with open(sys.argv[2], encoding="utf-8") as pending_file:
    pending_document = json.load(pending_file)
key = sys.argv[3]

if set(current_document) != {key} or set(pending_document) != {key}:
    raise SystemExit("Credential documents must contain exactly DATABASE_URL.")

current = urlsplit(current_document[key])
pending = urlsplit(pending_document[key])
stable_fields = (
    "scheme", "username", "hostname", "port", "path", "query", "fragment"
)
for field in stable_fields:
    if getattr(current, field) != getattr(pending, field):
        raise SystemExit(f"Candidate changed protected URI field: {field}")

current_password = unquote(current.password or "")
pending_password = unquote(pending.password or "")
if not current_password or pending_password == current_password:
    raise SystemExit("Candidate password is empty or unchanged.")
if len(pending_password) < 48:
    raise SystemExit("Candidate password is shorter than 48 characters.")
PY

PENDING_DIGEST="$(remote_digest "${SECRET_ARN}" AWSPENDING)"
TARGET_DIGEST_AFTER="$(kubernetes_digest "${TARGET_NAMESPACE}" "${TARGET_SECRET}" "${TARGET_KEY}")"
if [[ "${PENDING_DIGEST}" == "${CURRENT_DIGEST}" || \
      "${TARGET_DIGEST_AFTER}" != "${CURRENT_DIGEST}" ]]; then
  echo "The candidate is not distinct or the Kubernetes Secret changed unexpectedly." >&2
  exit 1
fi

unset CURRENT_DIGEST TARGET_DIGEST TARGET_DIGEST_AFTER PENDING_DIGEST

echo "PostgreSQL credential candidate staging passed."
echo "AWSPENDING version: ${NEW_PENDING_VERSION_ID}"
echo "AWSCURRENT, PostgreSQL, ExternalSecret, Kubernetes Secret, and demo-api were not changed."

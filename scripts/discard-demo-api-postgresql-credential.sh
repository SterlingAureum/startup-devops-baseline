#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"

for command in aws jq terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before discarding a credential candidate." >&2
  exit 1
fi

if [[ "${CONFIRM_POSTGRESQL_CREDENTIAL_DISCARD:-}" != "discard-awspending" ]]; then
  cat >&2 <<'EOF'
This guarded operation removes only the AWSPENDING staging label. It does not
delete the Secrets Manager container or move AWSCURRENT.

Re-run with:
  CONFIRM_POSTGRESQL_CREDENTIAL_DISCARD=discard-awspending \
    ./scripts/discard-demo-api-postgresql-credential.sh
EOF
  exit 1
fi

SECRET_ARN="$(
  terraform -chdir="${TF_DIR}" output -raw external_secrets_secret_arn
)"
[[ -n "${SECRET_ARN}" ]] || {
  echo "Terraform output external_secrets_secret_arn is empty." >&2
  exit 1
}

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

[[ -n "${CURRENT_VERSION_ID}" ]] || {
  echo "Secrets Manager does not have exactly one AWSCURRENT version." >&2
  exit 1
}
[[ -n "${PENDING_VERSION_ID}" ]] || {
  echo "Secrets Manager does not have exactly one AWSPENDING candidate." >&2
  exit 1
}
[[ "${PENDING_VERSION_ID}" != "${CURRENT_VERSION_ID}" ]] || {
  echo "Refusing to remove AWSPENDING because it is attached to AWSCURRENT." >&2
  exit 1
}

echo "==> Removing only the AWSPENDING label"
aws secretsmanager update-secret-version-stage \
  --region "${AWS_REGION}" \
  --secret-id "${SECRET_ARN}" \
  --version-stage AWSPENDING \
  --remove-from-version-id "${PENDING_VERSION_ID}" \
  --output json >/dev/null

METADATA_AFTER="$({
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
})"
jq --exit-status \
  --arg current "${CURRENT_VERSION_ID}" \
  --arg pending "${PENDING_VERSION_ID}" '
    (.VersionIdsToStages[$current] | index("AWSCURRENT")) != null and
    ((.VersionIdsToStages[$pending] // []) | index("AWSPENDING")) == null and
    ([.VersionIdsToStages[] | select(index("AWSPENDING"))] | length) == 0
  ' <<<"${METADATA_AFTER}" >/dev/null || {
  echo "The candidate label was not removed cleanly or AWSCURRENT moved." >&2
  exit 1
}

echo "PostgreSQL credential candidate discard passed."
echo "AWSCURRENT was not moved. The unlabeled candidate version is left for AWS cleanup."

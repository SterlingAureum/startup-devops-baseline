#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_ROLE="${POSTGRES_ROLE:-app}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_DEPLOYMENT="${DEMO_DEPLOYMENT:-demo-api}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
TARGET_KEY="${TARGET_KEY:-DATABASE_URL}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-demo-api-postgresql}"
DEMO_APPLICATION="${DEMO_APPLICATION:-demo-api-aws-dev}"
EXTERNAL_SECRETS_APPLICATION="${EXTERNAL_SECRETS_APPLICATION:-external-secrets-startup-apps}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-1200}"
POLL_SECONDS="${POLL_SECONDS:-5}"
RELOAD_SCRIPT="${ROOT_DIR}/scripts/reload-demo-api-postgresql-workload.sh"

for command in aws awk base64 date jq kubectl python3 sha256sum terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done
[[ -x "${RELOAD_SCRIPT}" ]] || {
  echo "Required executable is missing: ${RELOAD_SCRIPT}" >&2
  exit 1
}

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before activating a credential." >&2
  exit 1
fi

if [[ "${CONFIRM_POSTGRESQL_CREDENTIAL_ACTIVATION:-}" != "activate-awspending" ]]; then
  cat >&2 <<'EOF'
This guarded operation changes the PostgreSQL application role, promotes the
existing AWSPENDING version to AWSCURRENT, refreshes External Secrets, and
replaces demo-api Pods one at a time. A failed partial cutover triggers an
automatic compensation attempt back to the original credential.

Re-run with:
  CONFIRM_POSTGRESQL_CREDENTIAL_ACTIVATION=activate-awspending \
    ./scripts/activate-demo-api-postgresql-credential.sh
EOF
  exit 1
fi

DB_CHANGED=0
FORCE_SYNC_PRESENT=0
COMPENSATING=0
SECRET_ARN=""
CURRENT_VERSION_ID=""
PENDING_VERSION_ID=""
CURRENT_DIGEST=""
PENDING_DIGEST=""
PRIMARY_POD=""

tf_output() {
  local output_name="$1"
  local value

  value="$(terraform -chdir="${TF_DIR}" output -raw "${output_name}")"
  [[ -n "${value}" ]] || {
    echo "Terraform output ${output_name} is empty." >&2
    return 1
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

secret_digest_by_version() {
  local version_id="$1"

  aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --version-id "${version_id}" \
    --query SecretString \
    --output text |
    jq --exit-status --join-output --raw-output --arg key "${TARGET_KEY}" \
      '.[$key] | select(type == "string" and length > 0)' |
    sha256sum |
    awk '{print $1}'
}

kubernetes_digest() {
  kubectl get secret "${TARGET_SECRET}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json |
    jq --exit-status --join-output --raw-output --arg key "${TARGET_KEY}" \
      '.data[$key] | select(length > 0)' |
    base64 --decode |
    sha256sum |
    awk '{print $1}'
}

application_ready() {
  local application_name="$1"

  kubectl wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${application_name}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}" >/dev/null
  kubectl wait \
    --for=jsonpath='{.status.health.status}'=Healthy \
    "application/${application_name}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}" >/dev/null
}

credential_connects() {
  local version_id="$1"
  local pod_name="$2"

  aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --version-id "${version_id}" \
    --query SecretString \
    --output text |
    kubectl exec -i \
      --namespace "${DEMO_NAMESPACE}" \
      "${pod_name}" -- \
      python -c '
import json
import sys
import psycopg

try:
    document = json.load(sys.stdin)
    uri = document["DATABASE_URL"]
    with psycopg.connect(uri, connect_timeout=5) as connection:
        row = connection.execute(
            "SELECT current_database(), current_user, pg_is_in_recovery()"
        ).fetchone()
    if row != ("app", "app", False):
        raise RuntimeError("unexpected database identity")
except Exception:
    raise SystemExit(1)
'
}

write_postgres_role_password() {
  local version_id="$1"

  python3 - \
    "${POSTGRES_ROLE}" \
    <(aws secretsmanager get-secret-value \
        --region "${AWS_REGION}" \
        --secret-id "${SECRET_ARN}" \
        --version-id "${version_id}" \
        --query SecretString \
        --output text) <<'PY' |
import json
import sys
from urllib.parse import unquote, urlsplit

role = sys.argv[1]
with open(sys.argv[2], encoding="utf-8") as credential_file:
    document = json.load(credential_file)
if set(document) != {"DATABASE_URL"}:
    raise SystemExit("Credential document must contain exactly DATABASE_URL.")
uri = urlsplit(document["DATABASE_URL"])
username = unquote(uri.username or "")
password = unquote(uri.password or "")
if username != role or not password:
    raise SystemExit("Credential role or password does not match the rotation contract.")
identifier = role.replace('"', '""')
literal = password.replace("'", "''")
print("SET log_statement = 'none';")
print(f'ALTER ROLE "{identifier}" PASSWORD \'{literal}\';')
PY
    kubectl exec -i \
      --namespace "${POSTGRES_NAMESPACE}" \
      "${PRIMARY_POD}" \
      --container postgres -- \
      psql \
        --dbname postgres \
        --username postgres \
        --no-psqlrc \
        --set ON_ERROR_STOP=1 \
        --quiet >/dev/null
}

remove_force_sync_annotation() {
  if (( FORCE_SYNC_PRESENT == 1 )); then
    kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
      --namespace "${DEMO_NAMESPACE}" \
      force-sync- >/dev/null 2>&1 || true
    FORCE_SYNC_PRESENT=0
  fi
}

sync_external_secret_to_digest() {
  local expected_digest="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local observed_digest=""

  kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${DEMO_NAMESPACE}" \
    force-sync="$(date +%s%N)" \
    --overwrite >/dev/null
  FORCE_SYNC_PRESENT=1

  while true; do
    if kubectl get secret "${TARGET_SECRET}" \
      --namespace "${DEMO_NAMESPACE}" >/dev/null 2>&1; then
      observed_digest="$(kubernetes_digest || true)"
      if [[ "${observed_digest}" == "${expected_digest}" ]] && \
         kubectl wait \
           --for=condition=Ready \
           "ExternalSecret/${EXTERNAL_SECRET}" \
           --namespace "${DEMO_NAMESPACE}" \
           --timeout=5s >/dev/null 2>&1; then
        break
      fi
    fi
    if (( SECONDS >= deadline )); then
      kubectl describe externalsecret "${EXTERNAL_SECRET}" \
        --namespace "${DEMO_NAMESPACE}" >&2 || true
      echo "Timed out waiting for External Secrets to publish the expected digest." >&2
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done

  remove_force_sync_annotation
  if kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json |
    jq -e '.metadata.annotations["force-sync"] != null' >/dev/null; then
    echo "The temporary force-sync annotation was not removed." >&2
    return 1
  fi
}

restore_version_stages() {
  local metadata current_after pending_after

  metadata="$(
    aws secretsmanager describe-secret \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --output json
  )" || return 1
  current_after="$(stage_version_id "${metadata}" AWSCURRENT)"

  if [[ "${current_after}" == "${PENDING_VERSION_ID}" ]]; then
    aws secretsmanager update-secret-version-stage \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSCURRENT \
      --move-to-version-id "${CURRENT_VERSION_ID}" \
      --remove-from-version-id "${PENDING_VERSION_ID}" \
      --output json >/dev/null || return 1
  elif [[ "${current_after}" != "${CURRENT_VERSION_ID}" ]]; then
    echo "Compensation found an unexpected AWSCURRENT version." >&2
    return 1
  fi

  metadata="$(
    aws secretsmanager describe-secret \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --output json
  )" || return 1
  pending_after="$(stage_version_id "${metadata}" AWSPENDING)"
  if [[ -z "${pending_after}" ]]; then
    aws secretsmanager update-secret-version-stage \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSPENDING \
      --move-to-version-id "${PENDING_VERSION_ID}" \
      --output json >/dev/null || return 1
  elif [[ "${pending_after}" != "${PENDING_VERSION_ID}" ]]; then
    echo "Compensation found AWSPENDING on an unexpected version." >&2
    return 1
  fi
}

compensate_cutover() {
  local compensation_failed=0

  (( COMPENSATING == 0 )) || return 1
  COMPENSATING=1
  set +e
  echo "==> Attempting automatic compensation to the original credential" >&2
  remove_force_sync_annotation

  write_postgres_role_password "${CURRENT_VERSION_ID}" || compensation_failed=1
  restore_version_stages || compensation_failed=1
  sync_external_secret_to_digest "${CURRENT_DIGEST}" || compensation_failed=1

  CONFIRM_POSTGRESQL_WORKLOAD_RELOAD=reload-current-secret \
  EXPECTED_DATABASE_URL_SHA256="${CURRENT_DIGEST}" \
  POSTGRESQL_WORKLOAD_RELOAD_MODE=credential-transition \
    "${RELOAD_SCRIPT}" || compensation_failed=1

  application_ready "${DEMO_APPLICATION}" || compensation_failed=1
  application_ready "${EXTERNAL_SECRETS_APPLICATION}" || compensation_failed=1

  if (( compensation_failed == 0 )); then
    echo "Automatic compensation passed; the original credential is active again." >&2
    echo "The candidate remains AWSPENDING for investigation or retry." >&2
  else
    echo "AUTOMATIC COMPENSATION DID NOT COMPLETE." >&2
    echo "Stop further changes and inspect PostgreSQL, Secrets Manager stages, ESO, and demo-api Pods." >&2
  fi
  return "${compensation_failed}"
}

on_error() {
  local status=$?
  local line_number="${1:-unknown}"

  trap - ERR
  remove_force_sync_annotation
  echo "Credential activation failed near line ${line_number}." >&2
  if (( DB_CHANGED == 1 )); then
    compensate_cutover || true
  else
    echo "PostgreSQL was not changed; no compensation was required." >&2
  fi
  exit "${status}"
}

trap 'on_error ${LINENO}' ERR
trap remove_force_sync_annotation EXIT

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

SECRET_ARN="$(tf_output external_secrets_secret_arn)"

echo "==> Checking Argo CD and the current External Secrets contract"
application_ready "${DEMO_APPLICATION}"
application_ready "${EXTERNAL_SECRETS_APPLICATION}"
external_secret_json="$(
  kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"
jq --exit-status '
  .spec.data[0].remoteRef.version == "AWSCURRENT" and
  (.metadata.annotations["force-sync"] == null) and
  any(.status.conditions[]?; .type == "Ready" and .status == "True")
' <<<"${external_secret_json}" >/dev/null || {
  echo "ExternalSecret is not Ready, clean, and pinned to AWSCURRENT." >&2
  exit 1
}

echo "==> Resolving distinct AWSCURRENT and AWSPENDING versions"
metadata="$(
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
)"
CURRENT_VERSION_ID="$(stage_version_id "${metadata}" AWSCURRENT)"
PENDING_VERSION_ID="$(stage_version_id "${metadata}" AWSPENDING)"
if [[ -z "${CURRENT_VERSION_ID}" || -z "${PENDING_VERSION_ID}" || \
      "${CURRENT_VERSION_ID}" == "${PENDING_VERSION_ID}" ]]; then
  echo "Expected distinct, singular AWSCURRENT and AWSPENDING versions." >&2
  exit 1
fi
CURRENT_DIGEST="$(secret_digest_by_version "${CURRENT_VERSION_ID}")"
PENDING_DIGEST="$(secret_digest_by_version "${PENDING_VERSION_ID}")"
if [[ "${CURRENT_DIGEST}" == "${PENDING_DIGEST}" || \
      "$(kubernetes_digest)" != "${CURRENT_DIGEST}" ]]; then
  echo "The staged candidate is not distinct or the live Secret is not AWSCURRENT." >&2
  exit 1
fi

echo "==> Checking candidate URI structure without printing either credential"
python3 - \
  <(aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-id "${CURRENT_VERSION_ID}" \
      --query SecretString \
      --output text) \
  <(aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-id "${PENDING_VERSION_ID}" \
      --query SecretString \
      --output text) \
  "${POSTGRES_ROLE}" <<'PY'
import json
import sys
from urllib.parse import unquote, urlsplit

with open(sys.argv[1], encoding="utf-8") as current_file:
    current_document = json.load(current_file)
with open(sys.argv[2], encoding="utf-8") as pending_file:
    pending_document = json.load(pending_file)
role = sys.argv[3]
if set(current_document) != {"DATABASE_URL"} or set(pending_document) != {"DATABASE_URL"}:
    raise SystemExit("Credential documents must contain exactly DATABASE_URL.")
current = urlsplit(current_document["DATABASE_URL"])
pending = urlsplit(pending_document["DATABASE_URL"])
for field in ("scheme", "username", "hostname", "port", "path", "query", "fragment"):
    if getattr(current, field) != getattr(pending, field):
        raise SystemExit(f"Candidate changed protected URI field: {field}")
if unquote(pending.username or "") != role:
    raise SystemExit("Candidate username does not match the PostgreSQL role.")
if unquote(current.password or "") == unquote(pending.password or ""):
    raise SystemExit("Candidate password is unchanged.")
PY

echo "==> Checking the healthy two-or-more-replica Deployment"
deployment_json="$(
  kubectl get deployment "${DEMO_DEPLOYMENT}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"
desired_replicas="$(jq -er '.spec.replicas | select(. >= 2)' <<<"${deployment_json}")" || {
  echo "demo-api must have at least two replicas before activation." >&2
  exit 1
}
if (( $(jq -r '.status.readyReplicas // 0' <<<"${deployment_json}") != desired_replicas || \
      $(jq -r '.status.availableReplicas // 0' <<<"${deployment_json}") != desired_replicas )); then
  echo "demo-api is not fully Ready and Available before activation." >&2
  exit 1
fi
selector="$(
  jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' \
    <<<"${deployment_json}"
)"
mapfile -t demo_pods < <(
  kubectl get pods --namespace "${DEMO_NAMESPACE}" \
    --selector "${selector}" --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#demo_pods[@]} != desired_replicas )); then
  echo "The running demo-api Pod count does not match the Deployment." >&2
  exit 1
fi

echo "==> Resolving the PostgreSQL primary"
mapfile -t primary_pods < <(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#primary_pods[@]} != 1 )); then
  echo "Expected exactly one running PostgreSQL primary." >&2
  exit 1
fi
PRIMARY_POD="${primary_pods[0]}"

echo "==> Proving only AWSCURRENT authenticates before database mutation"
credential_connects "${CURRENT_VERSION_ID}" "${demo_pods[0]}"
if credential_connects "${PENDING_VERSION_ID}" "${demo_pods[0]}"; then
  echo "AWSPENDING unexpectedly authenticates before activation." >&2
  exit 1
fi

echo "==> Changing the PostgreSQL role through protected standard input"
DB_CHANGED=1
write_postgres_role_password "${PENDING_VERSION_ID}"

echo "==> Proving the new password is active before moving Secrets Manager stages"
credential_connects "${PENDING_VERSION_ID}" "${demo_pods[0]}"
if credential_connects "${CURRENT_VERSION_ID}" "${demo_pods[0]}"; then
  echo "The previous password still authenticates after PostgreSQL mutation." >&2
  false
fi

echo "==> Promoting AWSPENDING to AWSCURRENT and preserving the old version"
aws secretsmanager update-secret-version-stage \
  --region "${AWS_REGION}" \
  --secret-id "${SECRET_ARN}" \
  --version-stage AWSCURRENT \
  --move-to-version-id "${PENDING_VERSION_ID}" \
  --remove-from-version-id "${CURRENT_VERSION_ID}" \
  --output json >/dev/null
aws secretsmanager update-secret-version-stage \
  --region "${AWS_REGION}" \
  --secret-id "${SECRET_ARN}" \
  --version-stage AWSPENDING \
  --remove-from-version-id "${PENDING_VERSION_ID}" \
  --output json >/dev/null

metadata="$(
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
)"
jq --exit-status \
  --arg current "${PENDING_VERSION_ID}" \
  --arg previous "${CURRENT_VERSION_ID}" '
    ([.VersionIdsToStages[] | select(index("AWSPENDING"))] | length) == 0 and
    (.VersionIdsToStages[$current] | index("AWSCURRENT")) != null and
    (.VersionIdsToStages[$previous] | index("AWSPREVIOUS")) != null
  ' <<<"${metadata}" >/dev/null

echo "==> Refreshing External Secrets and verifying the new target digest"
sync_external_secret_to_digest "${PENDING_DIGEST}"

echo "==> Reloading every demo-api Pod through the current Secret"
CONFIRM_POSTGRESQL_WORKLOAD_RELOAD=reload-current-secret \
EXPECTED_DATABASE_URL_SHA256="${PENDING_DIGEST}" \
POSTGRESQL_WORKLOAD_RELOAD_MODE=credential-transition \
  "${RELOAD_SCRIPT}"

echo "==> Confirming final GitOps health"
application_ready "${DEMO_APPLICATION}"
application_ready "${EXTERNAL_SECRETS_APPLICATION}"

DB_CHANGED=0
unset CURRENT_DIGEST PENDING_DIGEST

echo "PostgreSQL credential activation and workload reload passed."
echo "The candidate is AWSCURRENT; the original version is retained as AWSPREVIOUS."
echo "No AWSPENDING stage or temporary force-sync annotation remains."

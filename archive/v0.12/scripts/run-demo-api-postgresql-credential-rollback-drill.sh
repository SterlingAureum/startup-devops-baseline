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
PRECHECK_SCRIPT="${ROOT_DIR}/scripts/validate-postgresql-credential-activation-aws.sh"

for command in aws awk base64 date jq kubectl python3 sha256sum terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done
for script in "${RELOAD_SCRIPT}" "${PRECHECK_SCRIPT}"; do
  [[ -x "${script}" ]] || {
    echo "Required executable is missing: ${script}" >&2
    exit 1
  }
done

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before exercising credential rollback." >&2
  exit 1
fi

if [[ "${CONFIRM_POSTGRESQL_CREDENTIAL_ROLLBACK_DRILL:-}" != \
      "run-awsprevious-round-trip" ]]; then
  cat >&2 <<'EOF'
This guarded exercise temporarily restores AWSPREVIOUS as the live PostgreSQL
credential, refreshes ESO, and replaces demo-api Pods one at a time. It then
performs the complete forward recovery so the credential that was AWSCURRENT
at the start is AWSCURRENT again at the end.

Re-run with:
  CONFIRM_POSTGRESQL_CREDENTIAL_ROLLBACK_DRILL=run-awsprevious-round-trip \
    ./scripts/run-demo-api-postgresql-credential-rollback-drill.sh
EOF
  exit 1
fi

RESTORE_REQUIRED=0
COMPENSATING=0
FORCE_SYNC_PRESENT=0
SECRET_ARN=""
ORIGINAL_CURRENT_VERSION_ID=""
ORIGINAL_PREVIOUS_VERSION_ID=""
ORIGINAL_CURRENT_DIGEST=""
ORIGINAL_PREVIOUS_DIGEST=""
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

running_demo_pod() {
  local deployment_json selector
  local -a pod_names

  deployment_json="$(
    kubectl get deployment "${DEMO_DEPLOYMENT}" \
      --namespace "${DEMO_NAMESPACE}" \
      --output json
  )"
  selector="$(
    jq -r '
      .spec.selector.matchLabels
      | to_entries
      | map("\(.key)=\(.value)")
      | join(",")
    ' <<<"${deployment_json}"
  )"
  mapfile -t pod_names < <(
    kubectl get pods \
      --namespace "${DEMO_NAMESPACE}" \
      --selector "${selector}" \
      --field-selector status.phase=Running \
      --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
  (( ${#pod_names[@]} > 0 )) || {
    echo "No running demo-api Pod is available for credential verification." >&2
    return 1
  }
  printf '%s' "${pod_names[0]}"
}

credential_connects() {
  local version_id="$1"
  local pod_name

  pod_name="$(running_demo_pod)"
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
    uri = json.load(sys.stdin)["DATABASE_URL"]
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
    raise SystemExit("Credential role or password does not match the rollback contract.")
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

validate_stage_pair() {
  local expected_current="$1"
  local expected_previous="$2"
  local metadata current previous pending

  metadata="$(
    aws secretsmanager describe-secret \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --output json
  )"
  current="$(stage_version_id "${metadata}" AWSCURRENT)"
  previous="$(stage_version_id "${metadata}" AWSPREVIOUS)"
  pending="$(stage_version_id "${metadata}" AWSPENDING)"
  if [[ "${current}" != "${expected_current}" || \
        "${previous}" != "${expected_previous}" || \
        -n "${pending}" ]]; then
    echo "Secrets Manager version stages do not match the expected rollback phase." >&2
    return 1
  fi
}

move_current_stage() {
  local target_version_id="$1"
  local source_version_id="$2"

  aws secretsmanager update-secret-version-stage \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --version-stage AWSCURRENT \
    --move-to-version-id "${target_version_id}" \
    --remove-from-version-id "${source_version_id}" \
    --output json >/dev/null
  validate_stage_pair "${target_version_id}" "${source_version_id}"
}

ensure_original_stages() {
  local metadata current previous pending

  metadata="$(
    aws secretsmanager describe-secret \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --output json
  )" || return 1
  current="$(stage_version_id "${metadata}" AWSCURRENT)"
  previous="$(stage_version_id "${metadata}" AWSPREVIOUS)"
  pending="$(stage_version_id "${metadata}" AWSPENDING)"
  [[ -z "${pending}" ]] || {
    echo "Recovery found an unexpected AWSPENDING version." >&2
    return 1
  }

  if [[ "${current}" == "${ORIGINAL_CURRENT_VERSION_ID}" ]]; then
    [[ "${previous}" == "${ORIGINAL_PREVIOUS_VERSION_ID}" ]] || {
      echo "Recovery found an unexpected AWSPREVIOUS version." >&2
      return 1
    }
    return 0
  fi
  [[ "${current}" == "${ORIGINAL_PREVIOUS_VERSION_ID}" ]] || {
    echo "Recovery found AWSCURRENT on an unexpected version." >&2
    return 1
  }
  move_current_stage \
    "${ORIGINAL_CURRENT_VERSION_ID}" \
    "${ORIGINAL_PREVIOUS_VERSION_ID}"
}

reload_to_digest() {
  local expected_digest="$1"

  CONFIRM_POSTGRESQL_WORKLOAD_RELOAD=reload-current-secret \
  EXPECTED_DATABASE_URL_SHA256="${expected_digest}" \
  POSTGRESQL_WORKLOAD_RELOAD_MODE=credential-transition \
    "${RELOAD_SCRIPT}"
}

validate_phase() {
  local expected_current_id="$1"
  local expected_previous_id="$2"
  local expected_digest="$3"
  local deployment_json desired_replicas selector pod_digest
  local -a pod_names

  validate_stage_pair "${expected_current_id}" "${expected_previous_id}"
  [[ "$(kubernetes_digest)" == "${expected_digest}" ]] || {
    echo "The ESO target Secret does not match the expected rollback phase." >&2
    return 1
  }
  credential_connects "${expected_current_id}"
  if credential_connects "${expected_previous_id}"; then
    echo "AWSPREVIOUS unexpectedly authenticates during rollback validation." >&2
    return 1
  fi

  deployment_json="$(
    kubectl get deployment "${DEMO_DEPLOYMENT}" \
      --namespace "${DEMO_NAMESPACE}" \
      --output json
  )"
  desired_replicas="$(jq -er '.spec.replicas | select(. >= 2)' <<<"${deployment_json}")"
  if (( $(jq -r '.status.readyReplicas // 0' <<<"${deployment_json}") != desired_replicas || \
        $(jq -r '.status.availableReplicas // 0' <<<"${deployment_json}") != desired_replicas )); then
    echo "demo-api is not fully Ready and Available after a rollback phase." >&2
    return 1
  fi
  selector="$(
    jq -r '
      .spec.selector.matchLabels
      | to_entries
      | map("\(.key)=\(.value)")
      | join(",")
    ' <<<"${deployment_json}"
  )"
  mapfile -t pod_names < <(
    kubectl get pods \
      --namespace "${DEMO_NAMESPACE}" \
      --selector "${selector}" \
      --field-selector status.phase=Running \
      --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
  )
  (( ${#pod_names[@]} == desired_replicas )) || {
    echo "The running demo-api Pod count does not match the Deployment." >&2
    return 1
  }
  for pod_name in "${pod_names[@]}"; do
    pod_digest="$(
      kubectl exec --namespace "${DEMO_NAMESPACE}" "${pod_name}" -- \
        python -c \
          'import hashlib, os; print(hashlib.sha256(os.environ["DATABASE_URL"].encode()).hexdigest())'
    )"
    [[ "${pod_digest}" == "${expected_digest}" ]] || {
      echo "Pod ${pod_name} did not load the expected rollback-phase credential." >&2
      return 1
    }
  done
  application_ready "${DEMO_APPLICATION}"
  application_ready "${EXTERNAL_SECRETS_APPLICATION}"
}

transition_to_version() {
  local target_version_id="$1"
  local source_version_id="$2"
  local target_digest="$3"
  local phase_name="$4"

  echo "==> Changing PostgreSQL to ${phase_name} through protected standard input"
  RESTORE_REQUIRED=1
  write_postgres_role_password "${target_version_id}"

  echo "==> Proving only the ${phase_name} credential authenticates"
  credential_connects "${target_version_id}"
  if credential_connects "${source_version_id}"; then
    echo "The displaced credential still authenticates during ${phase_name}." >&2
    return 1
  fi

  echo "==> Moving AWSCURRENT for ${phase_name}"
  move_current_stage "${target_version_id}" "${source_version_id}"

  echo "==> Synchronizing ESO for ${phase_name}"
  sync_external_secret_to_digest "${target_digest}"

  echo "==> Reloading demo-api Pods for ${phase_name}"
  reload_to_digest "${target_digest}"

  echo "==> Validating the complete ${phase_name} state"
  validate_phase "${target_version_id}" "${source_version_id}" "${target_digest}"
}

restore_checkpoint2_state() {
  local recovery_failed=0
  local database_recovered=0
  local stages_recovered=0

  (( COMPENSATING == 0 )) || return 1
  COMPENSATING=1
  set +e
  echo "==> Attempting automatic forward recovery to the original Checkpoint 2 state" >&2
  remove_force_sync_annotation
  write_postgres_role_password "${ORIGINAL_CURRENT_VERSION_ID}" || true
  if credential_connects "${ORIGINAL_CURRENT_VERSION_ID}"; then
    database_recovered=1
  else
    echo "Automatic recovery could not prove the original database password." >&2
    recovery_failed=1
  fi
  if ensure_original_stages; then
    stages_recovered=1
  else
    recovery_failed=1
  fi

  if (( database_recovered == 1 && stages_recovered == 1 )); then
    sync_external_secret_to_digest "${ORIGINAL_CURRENT_DIGEST}" || recovery_failed=1
    reload_to_digest "${ORIGINAL_CURRENT_DIGEST}" || recovery_failed=1
    validate_phase \
      "${ORIGINAL_CURRENT_VERSION_ID}" \
      "${ORIGINAL_PREVIOUS_VERSION_ID}" \
      "${ORIGINAL_CURRENT_DIGEST}" || recovery_failed=1
  else
    echo "Skipping ESO and workload recovery until database and version stages are both restored." >&2
  fi

  if (( recovery_failed == 0 )); then
    echo "Automatic forward recovery passed; the original Checkpoint 2 state is active again." >&2
  else
    echo "AUTOMATIC FORWARD RECOVERY DID NOT COMPLETE." >&2
    echo "Stop further changes and inspect PostgreSQL, Secrets Manager stages, ESO, and demo-api Pods." >&2
  fi
  return "${recovery_failed}"
}

on_error() {
  local status=$?
  local line_number="${1:-unknown}"

  trap - ERR
  remove_force_sync_annotation
  echo "Credential rollback drill failed near line ${line_number}." >&2
  if (( RESTORE_REQUIRED == 1 )); then
    restore_checkpoint2_state || true
  else
    echo "PostgreSQL was not changed; no forward recovery was required." >&2
  fi
  exit "${status}"
}

trap 'on_error ${LINENO}' ERR
trap remove_force_sync_annotation EXIT

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

echo "==> Requiring a valid Checkpoint 2 starting state"
"${PRECHECK_SCRIPT}"

SECRET_ARN="$(tf_output external_secrets_secret_arn)"
metadata="$(
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
)"
ORIGINAL_CURRENT_VERSION_ID="$(stage_version_id "${metadata}" AWSCURRENT)"
ORIGINAL_PREVIOUS_VERSION_ID="$(stage_version_id "${metadata}" AWSPREVIOUS)"
if [[ -z "${ORIGINAL_CURRENT_VERSION_ID}" || \
      -z "${ORIGINAL_PREVIOUS_VERSION_ID}" || \
      "${ORIGINAL_CURRENT_VERSION_ID}" == "${ORIGINAL_PREVIOUS_VERSION_ID}" || \
      -n "$(stage_version_id "${metadata}" AWSPENDING)" ]]; then
  echo "Expected distinct AWSCURRENT/AWSPREVIOUS versions and no AWSPENDING." >&2
  exit 1
fi
ORIGINAL_CURRENT_DIGEST="$(secret_digest_by_version "${ORIGINAL_CURRENT_VERSION_ID}")"
ORIGINAL_PREVIOUS_DIGEST="$(secret_digest_by_version "${ORIGINAL_PREVIOUS_VERSION_ID}")"
[[ "${ORIGINAL_CURRENT_DIGEST}" != "${ORIGINAL_PREVIOUS_DIGEST}" ]] || {
  echo "AWSCURRENT and AWSPREVIOUS must contain distinct credentials." >&2
  exit 1
}

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

transition_to_version \
  "${ORIGINAL_PREVIOUS_VERSION_ID}" \
  "${ORIGINAL_CURRENT_VERSION_ID}" \
  "${ORIGINAL_PREVIOUS_DIGEST}" \
  "AWSPREVIOUS rollback"
echo "AWSPREVIOUS rollback validation passed."
echo "The original credential is temporarily AWSCURRENT and every demo-api Pod loaded it."

transition_to_version \
  "${ORIGINAL_CURRENT_VERSION_ID}" \
  "${ORIGINAL_PREVIOUS_VERSION_ID}" \
  "${ORIGINAL_CURRENT_DIGEST}" \
  "forward recovery"

RESTORE_REQUIRED=0
unset ORIGINAL_CURRENT_DIGEST ORIGINAL_PREVIOUS_DIGEST

echo "PostgreSQL credential rollback and forward-recovery drill passed."
echo "The Checkpoint 2 credential is AWSCURRENT again; the original credential is AWSPREVIOUS and inactive."
echo "No AWSPENDING stage or temporary force-sync annotation remains."

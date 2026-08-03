#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_DEPLOYMENT="${DEMO_DEPLOYMENT:-demo-api}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-demo-api-postgresql}"
SOURCE_NAMESPACE="${SOURCE_NAMESPACE:-data-platform}"
SOURCE_SECRET="${SOURCE_SECRET:-postgresql-baseline-app}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"

for command in aws awk base64 jq kubectl sha256sum terraform; do
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

stage_version_id() {
  local metadata="$1"
  local stage="$2"

  jq -r --arg stage "${stage}" '
    [(.VersionIdsToStages // {}) | to_entries[]
      | select(.value | index($stage)) | .key]
    | if length == 1 then .[0] else empty end
  ' <<<"${metadata}"
}

secret_digest() {
  local version_id="$1"

  aws secretsmanager get-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --version-id "${version_id}" \
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

echo "==> Checking final Secrets Manager version stages"
metadata="$(
  aws secretsmanager describe-secret \
    --region "${AWS_REGION}" \
    --secret-id "${SECRET_ARN}" \
    --output json
)"
CURRENT_VERSION_ID="$(stage_version_id "${metadata}" AWSCURRENT)"
PREVIOUS_VERSION_ID="$(stage_version_id "${metadata}" AWSPREVIOUS)"
PENDING_VERSION_ID="$(stage_version_id "${metadata}" AWSPENDING)"
if [[ -z "${CURRENT_VERSION_ID}" || -z "${PREVIOUS_VERSION_ID}" || \
      "${CURRENT_VERSION_ID}" == "${PREVIOUS_VERSION_ID}" || \
      -n "${PENDING_VERSION_ID}" ]]; then
  echo "Expected distinct AWSCURRENT/AWSPREVIOUS versions and no AWSPENDING." >&2
  if [[ -n "${CURRENT_VERSION_ID}" && -z "${PREVIOUS_VERSION_ID}" && \
        -z "${PENDING_VERSION_ID}" ]]; then
    cat >&2 <<'EOF'
The Secret is in the normal initial state for a rebuilt environment: it has
AWSCURRENT only. Complete the guarded v0.8.5 staging, activation, validation,
and rollback/forward-recovery drill before running the v0.8 final validator.
See docs/archive/V0.8.5_POSTGRESQL_CREDENTIAL_ROTATION.md.
EOF
  fi
  exit 1
fi

CURRENT_DIGEST="$(secret_digest "${CURRENT_VERSION_ID}")"
PREVIOUS_DIGEST="$(secret_digest "${PREVIOUS_VERSION_ID}")"
TARGET_DIGEST="$(
  kubernetes_digest "${DEMO_NAMESPACE}" "${TARGET_SECRET}" DATABASE_URL
)"
LEGACY_SOURCE_DIGEST="$(
  kubernetes_digest "${SOURCE_NAMESPACE}" "${SOURCE_SECRET}" fqdn-uri
)"
if [[ "${CURRENT_DIGEST}" == "${PREVIOUS_DIGEST}" || \
      "${CURRENT_DIGEST}" != "${TARGET_DIGEST}" || \
      "${CURRENT_DIGEST}" == "${LEGACY_SOURCE_DIGEST}" ]]; then
  echo "Current, previous, ESO target, or legacy CNPG credential digests violate the activation contract." >&2
  exit 1
fi

echo "==> Checking the active ExternalSecret and GitOps Applications"
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

for application in demo-api-aws-dev external-secrets-startup-apps; do
  kubectl wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}" >/dev/null
  kubectl wait \
    --for=jsonpath='{.status.health.status}'=Healthy \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}" >/dev/null
done

echo "==> Proving only AWSCURRENT authenticates"
deployment_json="$(
  kubectl get deployment "${DEMO_DEPLOYMENT}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"
desired_replicas="$(jq -er '.spec.replicas | select(. >= 2)' <<<"${deployment_json}")"
if (( $(jq -r '.status.readyReplicas // 0' <<<"${deployment_json}") != desired_replicas || \
      $(jq -r '.status.availableReplicas // 0' <<<"${deployment_json}") != desired_replicas )); then
  echo "demo-api is not fully Ready and Available after activation." >&2
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
credential_connects "${CURRENT_VERSION_ID}" "${demo_pods[0]}"
if credential_connects "${PREVIOUS_VERSION_ID}" "${demo_pods[0]}"; then
  echo "AWSPREVIOUS unexpectedly authenticates after activation." >&2
  exit 1
fi

echo "==> Proving every Pod loaded AWSCURRENT"
for pod_name in "${demo_pods[@]}"; do
  pod_digest="$(
    kubectl exec --namespace "${DEMO_NAMESPACE}" "${pod_name}" -- \
      python -c \
        'import hashlib, os; print(hashlib.sha256(os.environ["DATABASE_URL"].encode()).hexdigest())'
  )"
  if [[ "${pod_digest}" != "${CURRENT_DIGEST}" ]]; then
    echo "Pod ${pod_name} did not load AWSCURRENT." >&2
    exit 1
  fi
done

"${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"

unset CURRENT_DIGEST PREVIOUS_DIGEST TARGET_DIGEST LEGACY_SOURCE_DIGEST

echo "PostgreSQL credential rotation Checkpoint 2 AWS validation passed."
echo "AWSCURRENT authenticates, AWSPREVIOUS is retained but inactive, ESO is converged, and every demo-api Pod loaded the new credential."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
DEMO_APP_NAME="${DEMO_APP_NAME:-demo-api}"
GUARDRAILS_APP_NAME="${GUARDRAILS_APP_NAME:-namespace-guardrails}"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"

require_cmd() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
}

assert_head_revision() {
  local application_name="$1"
  local revision
  revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.spec.source.targetRevision}')"
  if [ "${revision}" != "HEAD" ]; then
    echo "ERROR: Application/${application_name} did not return to HEAD: ${revision:-<empty>}." >&2
    exit 1
  fi
}

for command_name in argocd kubectl; do
  require_cmd "${command_name}"
done

cd "${ROOT_DIR}"

echo "==> Restoring the declarative local HEAD baseline"
TARGET_REVISION=HEAD \
ROOT_SYNC_MODE=automated \
REPO_URL="${REPO_URL}" \
  "${ROOT_DIR}/scripts/deploy-root-app.sh"

argocd app get "${ROOT_APP_NAME}" --hard-refresh >/dev/null
argocd app sync "${ROOT_APP_NAME}"

for application_name in "${GUARDRAILS_APP_NAME}" "${DEMO_APP_NAME}"; do
  argocd app get "${application_name}" --hard-refresh >/dev/null
  argocd app sync "${application_name}"
done

assert_head_revision "${ROOT_APP_NAME}"
assert_head_revision "${GUARDRAILS_APP_NAME}"
assert_head_revision "${DEMO_APP_NAME}"

self_heal="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.syncPolicy.automated.selfHeal}')"
if [ "${self_heal}" != "true" ]; then
  echo "ERROR: root automated self-heal was not restored." >&2
  exit 1
fi

echo "Local GitOps HEAD baseline restored."
echo "The demo-api image and Helm parameters now come only from the HEAD declaration."

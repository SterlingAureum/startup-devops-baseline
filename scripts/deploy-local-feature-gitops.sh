#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
DEMO_APP_NAME="${DEMO_APP_NAME:-demo-api}"
GUARDRAILS_APP_NAME="${GUARDRAILS_APP_NAME:-namespace-guardrails}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
TARGET_REVISION="${TARGET_REVISION:-}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
APPLICATION_VERSION="${APPLICATION_VERSION:-${IMAGE_TAG}}"
EXPECTED_PROMETHEUS_ADDRESS="${EXPECTED_PROMETHEUS_ADDRESS:-http://observability-metrics-prometheus.observability.svc.cluster.local:9090}"
EXPECTED_CHART_VERSION="${EXPECTED_CHART_VERSION:-}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

# shellcheck source=scripts/lib/argocd-operation.sh
source "${ROOT_DIR}/scripts/lib/argocd-operation.sh"
# shellcheck source=scripts/lib/git-revision.sh
source "${ROOT_DIR}/scripts/lib/git-revision.sh"

require_cmd() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
}

wait_for_application() {
  local application_name="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  until kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for Application/${application_name}." >&2
      exit 1
    fi
    sleep 2
  done
}

sync_application_if_needed() {
  local application_name="$1"
  local sync_status

  wait_for_application_idle "${application_name}"
  argocd app get "${application_name}" --hard-refresh >/dev/null
  sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.sync.status}')"
  if [ "${sync_status}" != "Synced" ]; then
    run_argocd_mutation_with_retry \
      "${application_name}" \
      argocd app sync "${application_name}"
  fi
  wait_for_application_idle "${application_name}"
}

assert_equals() {
  local actual="$1"
  local expected="$2"
  local description="$3"

  if [ "${actual}" != "${expected}" ]; then
    echo "ERROR: ${description}: expected ${expected}, found ${actual:-<empty>}." >&2
    exit 1
  fi
}

for command_name in argocd awk git grep kubectl sort wc; do
  require_cmd "${command_name}"
done

validate_argocd_operation_settings

if [ -z "${TARGET_REVISION}" ]; then
  echo "ERROR: TARGET_REVISION is required for feature validation." >&2
  echo "Example: TARGET_REVISION=feature/example IMAGE_TAG=example-local $0" >&2
  exit 1
fi

case "${TARGET_REVISION}" in
  HEAD|main|master)
    echo "ERROR: use deploy-root-app.sh for the stable ${TARGET_REVISION} revision." >&2
    exit 1
    ;;
esac

if ! [[ "${TARGET_REVISION}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]; then
  echo "ERROR: TARGET_REVISION contains unsupported characters: ${TARGET_REVISION}" >&2
  exit 1
fi

if [ -z "${IMAGE_TAG}" ]; then
  echo "ERROR: IMAGE_TAG is required and must already be loaded into the kind cluster." >&2
  exit 1
fi

cd "${ROOT_DIR}"

resolved_target_revision="$(resolve_remote_git_revision "${REPO_URL}" "${TARGET_REVISION}")"
local_commit="$(git rev-parse HEAD)"
assert_equals "${local_commit,,}" "${resolved_target_revision}" "local checkout and remote feature commit"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: tracked repository changes must be committed before GitOps acceptance." >&2
  exit 1
fi

if [ -z "${EXPECTED_CHART_VERSION}" ]; then
  EXPECTED_CHART_VERSION="$(awk '$1 == "version:" {print $2; exit}' "${ROOT_DIR}/apps/demo-api/helm/Chart.yaml")"
fi

echo "==> Deploying one immutable feature revision through the Root App-of-Apps"
echo "Requested revision: ${TARGET_REVISION}"
echo "Resolved commit:   ${resolved_target_revision}"
TARGET_REVISION="${resolved_target_revision}" \
GIT_TARGET_REVISION="${resolved_target_revision}" \
ROOT_SYNC_MODE=manual \
LOCAL_IMAGE_ENABLED=true \
IMAGE_REPOSITORY="${IMAGE_REPOSITORY}" \
IMAGE_TAG="${IMAGE_TAG}" \
IMAGE_PULL_POLICY=Never \
APPLICATION_VERSION="${APPLICATION_VERSION}" \
REPO_URL="${REPO_URL}" \
  "${ROOT_DIR}/scripts/deploy-root-app.sh"

echo "==> Syncing the Root so it declaratively renders same-repository children"
sync_application_if_needed "${ROOT_APP_NAME}"

wait_for_application "${GUARDRAILS_APP_NAME}"
wait_for_application "${DEMO_APP_NAME}"
sync_application_if_needed "${GUARDRAILS_APP_NAME}"
sync_application_if_needed "${DEMO_APP_NAME}"

echo "==> Verifying immutable feature ownership and v0.11 telemetry resources"
for application_name in "${ROOT_APP_NAME}" "${GUARDRAILS_APP_NAME}" "${DEMO_APP_NAME}"; do
  assert_equals \
    "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.spec.source.targetRevision}')" \
    "${resolved_target_revision}" \
    "Application/${application_name} target revision"
  assert_equals \
    "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.sync.revision}')" \
    "${resolved_target_revision}" \
    "Application/${application_name} resolved source commit"
done

assert_equals \
  "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.source.helm.parameters[?(@.name=="git.targetRevision")].value}')" \
  "${resolved_target_revision}" \
  "Root-rendered child revision"
assert_equals \
  "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.source.helm.parameters[?(@.name=="demoApi.localImage.enabled")].value}')" \
  "true" \
  "Root local-image mode"

root_automation="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.syncPolicy.automated}' 2>/dev/null || true)"
assert_equals "${root_automation}" "" "feature Root automated sync policy"

helm_parameter_names="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" -o jsonpath='{range .spec.source.helm.parameters[*]}{.name}{"\n"}{end}')"
sorted_helm_parameter_names="$(sort <<<"${helm_parameter_names}")"
expected_helm_parameter_names="$(printf '%s\n' image.pullPolicy image.repository image.tag release.applicationVersion | sort)"
assert_equals "${sorted_helm_parameter_names}" "${expected_helm_parameter_names}" "demo-api Root-rendered Helm parameter allowlist"

chart_label="$(kubectl -n "${APP_NAMESPACE}" get rollout "${DEMO_APP_NAME}" -o jsonpath='{.metadata.labels.helm\.sh/chart}')"
assert_equals "${chart_label}" "demo-api-${EXPECTED_CHART_VERSION}" "deployed demo-api Chart"

kubectl -n "${APP_NAMESPACE}" get servicemonitor "${DEMO_APP_NAME}" >/dev/null
prometheus_address="$(kubectl -n "${APP_NAMESPACE}" get analysistemplate "${DEMO_APP_NAME}-canary-health" -o jsonpath='{.spec.metrics[0].provider.prometheus.address}')"
assert_equals "${prometheus_address}" "${EXPECTED_PROMETHEUS_ADDRESS}" "AnalysisTemplate Prometheus address"

argocd app get "${ROOT_APP_NAME}" --hard-refresh >/dev/null
root_sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.status.sync.status}')"
assert_equals "${root_sync_status}" "Synced" "Root declarative feature ownership"

echo
echo "Local feature GitOps configuration passed."
echo "Requested: ${TARGET_REVISION}"
echo "Commit:    ${resolved_target_revision}"
echo "Chart:     demo-api-${EXPECTED_CHART_VERSION}"
echo "Image:     ${IMAGE_REPOSITORY}:${IMAGE_TAG}"
echo "Root sync: ${root_sync_status}"
echo
echo "The Root declaratively owns the exact child commit and local-image parameters."
echo "A Root resync is safe during this feature validation; it no longer resets children to HEAD."
echo "Complete any manual Canary pause, then run:"
echo "  ./scripts/validate.sh"
echo "  ./scripts/check-monitoring.sh"
echo "Before merge, restore a clean immutable feature baseline with:"
echo "  TARGET_REVISION=${TARGET_REVISION} ./scripts/restore-local-feature-baseline.sh"
echo "After this increment reaches remote HEAD, restore the stable declaration with:"
echo "  ./scripts/restore-local-gitops-head.sh"
echo "Retry an aborted Rollout only with:"
echo "  kubectl argo rollouts retry rollout ${DEMO_APP_NAME} -n ${APP_NAMESPACE}"

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

assert_equals() {
  local actual="$1"
  local expected="$2"
  local description="$3"

  if [ "${actual}" != "${expected}" ]; then
    echo "ERROR: ${description}: expected ${expected}, found ${actual:-<empty>}." >&2
    exit 1
  fi
}

for command_name in argocd awk grep kubectl; do
  require_cmd "${command_name}"
done

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

if [ -z "${EXPECTED_CHART_VERSION}" ]; then
  EXPECTED_CHART_VERSION="$(awk '$1 == "version:" {print $2; exit}' "${ROOT_DIR}/apps/demo-api/helm/Chart.yaml")"
fi

cd "${ROOT_DIR}"

echo "==> Deploying the local root Application from ${TARGET_REVISION} in manual mode"
TARGET_REVISION="${TARGET_REVISION}" \
ROOT_SYNC_MODE=manual \
REPO_URL="${REPO_URL}" \
  "${ROOT_DIR}/scripts/deploy-root-app.sh"

echo "==> Syncing the root once so child Applications are created from the feature revision"
argocd app sync "${ROOT_APP_NAME}"

wait_for_application "${GUARDRAILS_APP_NAME}"
wait_for_application "${DEMO_APP_NAME}"

echo "==> Pinning same-repository child Applications to ${TARGET_REVISION}"
argocd app set "${GUARDRAILS_APP_NAME}" --revision "${TARGET_REVISION}"
argocd app set "${DEMO_APP_NAME}" \
  --revision "${TARGET_REVISION}" \
  --helm-set "image.repository=${IMAGE_REPOSITORY}" \
  --helm-set "image.tag=${IMAGE_TAG}" \
  --helm-set "image.pullPolicy=Never" \
  --helm-set "release.applicationVersion=${APPLICATION_VERSION}"

argocd app get "${GUARDRAILS_APP_NAME}" --hard-refresh >/dev/null
argocd app sync "${GUARDRAILS_APP_NAME}"
argocd app get "${DEMO_APP_NAME}" --hard-refresh >/dev/null
argocd app sync "${DEMO_APP_NAME}"

echo "==> Verifying feature revision and v0.11 telemetry resources"
assert_equals "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.source.targetRevision}')" "${TARGET_REVISION}" "root target revision"
assert_equals "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${GUARDRAILS_APP_NAME}" -o jsonpath='{.spec.source.targetRevision}')" "${TARGET_REVISION}" "guardrails target revision"
assert_equals "$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" -o jsonpath='{.spec.source.targetRevision}')" "${TARGET_REVISION}" "demo-api target revision"

root_commit="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.status.sync.revision}')"
guardrails_commit="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${GUARDRAILS_APP_NAME}" -o jsonpath='{.status.sync.revision}')"
demo_commit="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" -o jsonpath='{.status.sync.revision}')"
assert_equals "${guardrails_commit}" "${root_commit}" "guardrails resolved source commit"
assert_equals "${demo_commit}" "${root_commit}" "demo-api resolved source commit"

root_automation="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.syncPolicy.automated}' 2>/dev/null || true)"
assert_equals "${root_automation}" "" "feature root automated sync policy"

helm_parameter_names="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" -o jsonpath='{range .spec.source.helm.parameters[*]}{.name}{"\n"}{end}')"
if grep -Fxq "analysis.prometheus.address" <<<"${helm_parameter_names}"; then
  echo "ERROR: analysis.prometheus.address must come from the feature revision, not a live Helm override." >&2
  exit 1
fi

chart_label="$(kubectl -n "${APP_NAMESPACE}" get rollout "${DEMO_APP_NAME}" -o jsonpath='{.metadata.labels.helm\.sh/chart}')"
assert_equals "${chart_label}" "demo-api-${EXPECTED_CHART_VERSION}" "deployed demo-api Chart"

kubectl -n "${APP_NAMESPACE}" get servicemonitor "${DEMO_APP_NAME}" >/dev/null
prometheus_address="$(kubectl -n "${APP_NAMESPACE}" get analysistemplate "${DEMO_APP_NAME}-canary-health" -o jsonpath='{.spec.metrics[0].provider.prometheus.address}')"
assert_equals "${prometheus_address}" "${EXPECTED_PROMETHEUS_ADDRESS}" "AnalysisTemplate Prometheus address"

argocd app get "${ROOT_APP_NAME}" --hard-refresh >/dev/null || true
root_sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"

echo
echo "Local feature GitOps configuration passed."
echo "Revision: ${TARGET_REVISION}"
echo "Chart:    demo-api-${EXPECTED_CHART_VERSION}"
echo "Image:    ${IMAGE_REPOSITORY}:${IMAGE_TAG}"
echo "Root sync status after child overrides: ${root_sync_status:-Unknown}"
echo
echo "The root Application is expected to become OutOfSync because Git keeps child revisions at HEAD."
echo "Do not sync ${ROOT_APP_NAME} again during feature validation."
echo "Complete any manual Canary pause, then run:"
echo "  ./scripts/validate.sh"
echo "  ./scripts/check-monitoring.sh"
echo "Restore the stable declaration with:"
echo "  ./scripts/restore-local-gitops-head.sh"

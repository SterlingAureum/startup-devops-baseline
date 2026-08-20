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

wait_for_application_idle() {
  local application_name="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local idle_observations=0
  local operation
  local phase

  while [ "${SECONDS}" -lt "${deadline}" ]; do
    operation="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.operation}' 2>/dev/null || true)"
    phase="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.operationState.phase}' 2>/dev/null || true)"

    if [ -z "${operation}" ] && [ "${phase}" != "Running" ]; then
      idle_observations=$((idle_observations + 1))
      if [ "${idle_observations}" -ge 2 ]; then
        return 0
      fi
    else
      idle_observations=0
      argocd app wait "${application_name}" --operation --timeout "${WAIT_TIMEOUT_SECONDS}" >/dev/null || true
    fi
    sleep 1
  done

  echo "ERROR: timed out waiting for Application/${application_name} to become idle." >&2
  exit 1
}

set_application_automation() {
  local application_name="$1"
  local mode="$2"

  if [ "${mode}" = "manual" ]; then
    kubectl -n "${ARGOCD_NAMESPACE}" patch application "${application_name}" \
      --type merge \
      -p '{"spec":{"syncPolicy":{"automated":null}}}' >/dev/null
  else
    kubectl -n "${ARGOCD_NAMESPACE}" patch application "${application_name}" \
      --type merge \
      -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' >/dev/null
  fi
}

sync_application_if_needed() {
  local application_name="$1"
  local sync_status

  wait_for_application_idle "${application_name}"
  argocd app get "${application_name}" --hard-refresh >/dev/null
  sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.sync.status}')"
  if [ "${sync_status}" != "Synced" ]; then
    argocd app sync "${application_name}"
  fi
  wait_for_application_idle "${application_name}"
}

remove_unexpected_demo_parameters() {
  local parameter_name

  while IFS= read -r parameter_name; do
    [ -n "${parameter_name}" ] || continue
    case "${parameter_name}" in
      image.repository|image.tag|image.pullPolicy|release.applicationVersion)
        ;;
      *)
        echo "Removing stale demo-api Helm parameter: ${parameter_name}"
        argocd app unset "${DEMO_APP_NAME}" -p "${parameter_name}"
        ;;
    esac
  done < <(
    kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" \
      -o jsonpath='{range .spec.source.helm.parameters[*]}{.name}{"\n"}{end}'
  )
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

for command_name in argocd awk grep kubectl sort; do
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
sync_application_if_needed "${ROOT_APP_NAME}"

wait_for_application "${GUARDRAILS_APP_NAME}"
wait_for_application "${DEMO_APP_NAME}"

echo "==> Pausing child automation while feature overrides are configured"
set_application_automation "${GUARDRAILS_APP_NAME}" manual
set_application_automation "${DEMO_APP_NAME}" manual
wait_for_application_idle "${GUARDRAILS_APP_NAME}"
wait_for_application_idle "${DEMO_APP_NAME}"

echo "==> Removing stale non-image Helm parameters from demo-api"
remove_unexpected_demo_parameters

echo "==> Pinning same-repository child Applications to ${TARGET_REVISION}"
argocd app set "${GUARDRAILS_APP_NAME}" --revision "${TARGET_REVISION}"
argocd app set "${DEMO_APP_NAME}" \
  --revision "${TARGET_REVISION}" \
  --helm-set "image.repository=${IMAGE_REPOSITORY}" \
  --helm-set "image.tag=${IMAGE_TAG}" \
  --helm-set "image.pullPolicy=Never" \
  --helm-set "release.applicationVersion=${APPLICATION_VERSION}"

sync_application_if_needed "${GUARDRAILS_APP_NAME}"
sync_application_if_needed "${DEMO_APP_NAME}"

set_application_automation "${GUARDRAILS_APP_NAME}" automated
set_application_automation "${DEMO_APP_NAME}" automated

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
sorted_helm_parameter_names="$(sort <<<"${helm_parameter_names}")"
expected_helm_parameter_names="$(printf '%s\n' image.pullPolicy image.repository image.tag release.applicationVersion | sort)"
assert_equals "${sorted_helm_parameter_names}" "${expected_helm_parameter_names}" "demo-api local Helm parameter allowlist"

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
echo "Retry an aborted Rollout only with:"
echo "  kubectl argo rollouts retry rollout ${DEMO_APP_NAME} -n ${APP_NAMESPACE}"

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE="${1:-}"
LOCAL_CONTEXT="${LOCAL_CONTEXT:-}"
EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION:-}"
CONFIRM_LOCAL_BASELINE_RECOVERY="${CONFIRM_LOCAL_BASELINE_RECOVERY:-}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"

fail() { echo "ERROR: $*" >&2; exit 1; }

case "${PHASE}" in
  first-analysis|second-analysis|final) ;;
  *) fail "usage: $0 first-analysis|second-analysis|final" ;;
esac

[ -n "${LOCAL_CONTEXT}" ] || fail "LOCAL_CONTEXT is required"
[ -n "${EXPECTED_APPLICATION_VERSION}" ] || fail "EXPECTED_APPLICATION_VERSION is required"
[ "${CONFIRM_LOCAL_BASELINE_RECOVERY}" = "observe-reviewed-local-baseline-recovery" ] \
  || fail "CONFIRM_LOCAL_BASELINE_RECOVERY=observe-reviewed-local-baseline-recovery is required"

for command_name in jq kubectl; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "required command not found: ${command_name}"
done

case "${LOCAL_CONTEXT}" in kind-*) ;;
  *) fail "only an explicit kind context is accepted" ;;
esac

work_dir="$(mktemp -d /tmp/local-baseline-restoration.XXXXXX)"
trap 'rm -rf -- "${work_dir}"' EXIT
kubectl config view --raw --minify --context "${LOCAL_CONTEXT}" >"${work_dir}/kubeconfig"
export KUBECONFIG="${work_dir}/kubeconfig"

excluded_uids="$(kubectl -n "${APP_NAMESPACE}" get analysisrun -o json | jq -c '[.items[].metadata.uid]')"

if [ "${PHASE}" = first-analysis ]; then
  echo "ACTION SIGNAL: observer armed before restoration; now execute exactly one reviewed restore in terminal 1."
  echo "Only an AnalysisRun created after this observer started can satisfy it."
  MINIMUM_MATCHING_ANALYSIS_RUNS=1 \
  ANALYSIS_RUN_EXCLUDED_UIDS_JSON="${excluded_uids}" \
  EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION}" \
    exec "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh"
fi

rollout_json="$(kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o json)"
observed_version="$(jq -r '.metadata.annotations["platform.startup.dev/application-version"] // ""' <<<"${rollout_json}")"
[ "${observed_version}" = "${EXPECTED_APPLICATION_VERSION}" ] \
  || fail "Rollout version mismatch: expected ${EXPECTED_APPLICATION_VERSION}, found ${observed_version:-<empty>}"

if [ "${PHASE}" = final ]; then
  echo "==> Observing final runtime convergence; no promote, retry or abort will be executed"
  CLOSURE_PHASE=final \
  EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION}" \
    exec "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh"
fi

rollout_phase="$(jq -r '.status.phase // "Unknown"' <<<"${rollout_json}")"
rollout_step="$(jq -r '.status.currentStepIndex // -1' <<<"${rollout_json}")"
[ "${rollout_phase}" = Paused ] && [ "${rollout_step}" = 4 ] \
  || fail "second-analysis requires the reviewed 50% pause (observed phase=${rollout_phase}, step=${rollout_step})"
echo "ACTION SIGNAL: wait for 'Generating bounded traffic' and release-scoped request-metric readiness below, then promote exactly once in terminal 1."
echo "Only an AnalysisRun created after this observer started can satisfy it."

MINIMUM_MATCHING_ANALYSIS_RUNS=1 \
ANALYSIS_RUN_EXCLUDED_UIDS_JSON="${excluded_uids}" \
EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION}" \
  exec "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh"

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

release_id="$(jq -r '.metadata.annotations["platform.startup.dev/release-id"] // ""' <<<"${rollout_json}")"
[ -n "${release_id}" ] || fail "Rollout release-id is empty"
existing_count="$(kubectl -n "${APP_NAMESPACE}" get analysisrun -o json | jq --arg release_id "${release_id}" '
  [.items[] | select(any(.spec.args[]?; .name == "expected-release-id" and .value == $release_id))] | length')"
required_count=$((existing_count + 1))

if [ "${PHASE}" = first-analysis ]; then
  echo "ACTION SIGNAL: keep this observer running, then in terminal 1 execute exactly one reviewed restore or Rollout retry."
  echo "This observer requires a new AnalysisRun ${required_count}; earlier failed runs cannot satisfy it."
else
  rollout_phase="$(jq -r '.status.phase // "Unknown"' <<<"${rollout_json}")"
  rollout_step="$(jq -r '.status.currentStepIndex // -1' <<<"${rollout_json}")"
  [ "${rollout_phase}" = Paused ] && [ "${rollout_step}" = 4 ] \
    || fail "second-analysis requires the reviewed 50% pause (observed phase=${rollout_phase}, step=${rollout_step})"
  echo "ACTION SIGNAL: wait for 'Generating bounded traffic' below, then promote exactly once in terminal 1."
  echo "This observer requires a new AnalysisRun ${required_count}; earlier failed runs cannot satisfy it."
fi

MINIMUM_MATCHING_ANALYSIS_RUNS="${required_count}" \
EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION}" \
  exec "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh"

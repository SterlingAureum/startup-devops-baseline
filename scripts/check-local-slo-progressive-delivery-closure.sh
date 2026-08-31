#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOSURE_PHASE="${CLOSURE_PHASE:-}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"
EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION:-}"
CLOSURE_STATE_FIXTURE="${CLOSURE_STATE_FIXTURE:-}"
RUN_FINAL_OBSERVABILITY_CHECKS="${RUN_FINAL_OBSERVABILITY_CHECKS:-true}"

fail() { echo "ERROR: $*" >&2; exit 1; }

case "${CLOSURE_PHASE}" in
  first-analysis|human-review|second-analysis|final) ;;
  *) fail "CLOSURE_PHASE must be first-analysis, human-review, second-analysis, or final" ;;
esac

assert_state() {
  local rollout_file="$1"
  local analysis_file="$2"
  local phase="$3"
  local expected_version="$4"
  local expected_release_id
  expected_release_id="$(jq -r '.metadata.annotations["platform.startup.dev/release-id"] // empty' "${rollout_file}")"
  [ -n "${expected_release_id}" ] || fail "Rollout release ID is empty"
  jq -e --arg version "${expected_version}" \
    '.metadata.annotations["platform.startup.dev/application-version"] == $version' \
    "${rollout_file}" >/dev/null || fail "Rollout application version does not match ${expected_version}"

  successful_count="$(jq --arg release_id "${expected_release_id}" '[
    .items[]
    | select(any(.spec.args[]?; .name == "expected-release-id" and .value == $release_id))
    | select(.status.phase == "Successful")
  ] | length' "${analysis_file}")"

  case "${phase}" in
    human-review)
      jq -e '
        .status.phase == "Paused" and
        .status.currentStepIndex == 4 and
        any(.status.pauseConditions[]?; .reason == "CanaryPauseStep")
      ' "${rollout_file}" >/dev/null || fail "Rollout is not at the 50% human-review pause"
      [ "${successful_count}" -ge 1 ] || fail "No successful first AnalysisRun exists for ${expected_release_id}"
      echo "Human-review evidence is valid. Inspect evidence and follow the explicit promotion command in the v0.11.7.3 runbook."
      ;;
    final)
      jq -e '
        .status.phase == "Healthy" and
        (.status.currentPodHash | length > 0) and
        .status.currentPodHash == .status.stableRS and
        .status.readyReplicas == .spec.replicas and
        .status.availableReplicas == .spec.replicas
      ' "${rollout_file}" >/dev/null || fail "Rollout is not fully Healthy on its current stable ReplicaSet"
      [ "${successful_count}" -ge 2 ] || fail "Fewer than two successful AnalysisRuns exist for ${expected_release_id}"
      ;;
    *) fail "internal unsupported state assertion phase: ${phase}" ;;
  esac
}

if [ -n "${CLOSURE_STATE_FIXTURE}" ]; then
  command -v jq >/dev/null 2>&1 || fail "required command not found: jq"
  [ -n "${EXPECTED_APPLICATION_VERSION}" ] || fail "EXPECTED_APPLICATION_VERSION is required with CLOSURE_STATE_FIXTURE"
  jq '.rollout' "${CLOSURE_STATE_FIXTURE}" >"${CLOSURE_STATE_FIXTURE}.rollout"
  jq '{items:.analysisRuns}' "${CLOSURE_STATE_FIXTURE}" >"${CLOSURE_STATE_FIXTURE}.analysis"
  trap 'rm -f -- "${CLOSURE_STATE_FIXTURE}.rollout" "${CLOSURE_STATE_FIXTURE}.analysis"' EXIT
  assert_state "${CLOSURE_STATE_FIXTURE}.rollout" "${CLOSURE_STATE_FIXTURE}.analysis" "${CLOSURE_PHASE}" "${EXPECTED_APPLICATION_VERSION}"
  echo "v0.11.7.3 ${CLOSURE_PHASE} fixture acceptance passed."
  exit 0
fi

[ -n "${EXPECTED_APPLICATION_VERSION}" ] || fail "EXPECTED_APPLICATION_VERSION is required"

case "${CLOSURE_PHASE}" in
  first-analysis)
    EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION}" \
    MINIMUM_MATCHING_ANALYSIS_RUNS=1 \
      "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh"
    ;;
  second-analysis)
    EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION}" \
    MINIMUM_MATCHING_ANALYSIS_RUNS=2 \
      "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh"
    ;;
  human-review|final)
    for command_name in jq kubectl; do
      command -v "${command_name}" >/dev/null 2>&1 || fail "required command not found: ${command_name}"
    done
    work_dir="$(mktemp -d)"
    trap 'rm -rf -- "${work_dir}"' EXIT
    kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o json >"${work_dir}/rollout.json"
    kubectl -n "${APP_NAMESPACE}" get analysisrun -o json >"${work_dir}/analysisruns.json"
    assert_state "${work_dir}/rollout.json" "${work_dir}/analysisruns.json" "${CLOSURE_PHASE}" "${EXPECTED_APPLICATION_VERSION}"
    if [ "${CLOSURE_PHASE}" = final ] && [ "${RUN_FINAL_OBSERVABILITY_CHECKS}" = true ]; then
      "${ROOT_DIR}/scripts/check-local-slo-burn-rate-alerts.sh"
    fi
    ;;
esac

echo "v0.11.7.3 ${CLOSURE_PHASE} local SLO and progressive-delivery closure passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"
TRAFFIC_REQUESTS="${TRAFFIC_REQUESTS:-40}"
TRAFFIC_DURATION_SECONDS="${TRAFFIC_DURATION_SECONDS:-45}"
TRAFFIC_INTERVAL_SECONDS="${TRAFFIC_INTERVAL_SECONDS:-1}"
ANALYSIS_TIMEOUT_SECONDS="${ANALYSIS_TIMEOUT_SECONDS:-300}"
ROLLOUT_WAIT_SECONDS="${ROLLOUT_WAIT_SECONDS:-300}"
CANARY_IDENTITY_WAIT_SECONDS="${CANARY_IDENTITY_WAIT_SECONDS:-120}"
MINIMUM_MATCHING_ANALYSIS_RUNS="${MINIMUM_MATCHING_ANALYSIS_RUNS:-1}"
EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION:-}"
ANALYSIS_RUN_FIXTURE="${ANALYSIS_RUN_FIXTURE:-}"
CANARY_IDENTITY_FIXTURE="${CANARY_IDENTITY_FIXTURE:-}"

expected_metrics='[
  "canary-prometheus-target-up",
  "canary-minimum-eligible-requests",
  "canary-availability-error-budget-burn-rate",
  "canary-latency-error-budget-burn-rate",
  "stable-availability-error-budget-remaining",
  "stable-latency-error-budget-remaining"
]'

assert_analysis_run() {
  local payload_file="$1"
  local expected_release_id="$2"
  jq -e --arg release_id "${expected_release_id}" --argjson metrics "${expected_metrics}" '
    .status.phase == "Successful" and
    ([.spec.args[] | select(.name == "expected-release-id") | .value] == [$release_id]) and
    ([.status.metricResults[].name] | sort) == ($metrics | sort) and
    all(.status.metricResults[]; .phase == "Successful")
  ' "${payload_file}" >/dev/null || {
    echo "ERROR: SLO-aware AnalysisRun identity, phase, or metric results are invalid." >&2
    jq '{name:.metadata.name, phase:.status.phase, args:.spec.args, metrics:.status.metricResults}' "${payload_file}" >&2 || true
    return 1
  }
}

assert_canary_identity() {
  local payload_file="$1"
  local expected_release_id="$2"
  jq -e --arg release_id "${expected_release_id}" '
    .selectorHash as $selector_hash |
    (.selectorHash | type == "string" and length > 0) and
    (.selectedPods | length > 0) and
    all(.selectedPods[];
      .ready == true and
      .podTemplateHash == $selector_hash and
      .releaseId == $release_id)
  ' "${payload_file}" >/dev/null
}

if [ -n "${CANARY_IDENTITY_FIXTURE}" ]; then
  command -v jq >/dev/null 2>&1 || { echo "ERROR: required command not found: jq" >&2; exit 1; }
  assert_canary_identity "${CANARY_IDENTITY_FIXTURE}" "${EXPECTED_RELEASE_ID:?EXPECTED_RELEASE_ID is required with CANARY_IDENTITY_FIXTURE}" || {
    echo "ERROR: canary Service still selects missing, unready, stale-hash, or wrong-release Pods." >&2
    jq . "${CANARY_IDENTITY_FIXTURE}" >&2 || true
    exit 1
  }
  echo "v0.11.7.2.2 canary Service-to-Pod release identity fixture acceptance passed."
  exit 0
fi

if [ -n "${ANALYSIS_RUN_FIXTURE}" ]; then
  command -v jq >/dev/null 2>&1 || { echo "ERROR: required command not found: jq" >&2; exit 1; }
  assert_analysis_run "${ANALYSIS_RUN_FIXTURE}" "${EXPECTED_RELEASE_ID:?EXPECTED_RELEASE_ID is required with ANALYSIS_RUN_FIXTURE}"
  echo "v0.11.7.2 SLO-aware AnalysisRun fixture acceptance passed."
  exit 0
fi

for command_name in curl jq kubectl python3 seq; do
  command -v "${command_name}" >/dev/null 2>&1 || { echo "ERROR: required command not found: ${command_name}" >&2; exit 1; }
done

if [ -n "${EXPECTED_APPLICATION_VERSION}" ]; then
  echo "==> Waiting for Rollout application version ${EXPECTED_APPLICATION_VERSION}"
  deadline=$((SECONDS + ROLLOUT_WAIT_SECONDS))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    observed_application_version="$(kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o jsonpath='{.metadata.annotations.platform\.startup\.dev/application-version}' 2>/dev/null || true)"
    [ "${observed_application_version}" != "${EXPECTED_APPLICATION_VERSION}" ] || break
    sleep 2
  done
  [ "${observed_application_version:-}" = "${EXPECTED_APPLICATION_VERSION}" ] || {
    echo "ERROR: Rollout did not reach application version ${EXPECTED_APPLICATION_VERSION} within ${ROLLOUT_WAIT_SECONDS}s." >&2
    exit 1
  }
fi

expected_release_id="$(kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o jsonpath='{.metadata.annotations.platform\.startup\.dev/release-id}')"
[ -n "${expected_release_id}" ] || { echo "ERROR: Rollout release-id annotation is empty." >&2; exit 1; }

work_dir="$(mktemp -d)"
stable_pid=""
canary_pid=""
cleanup() {
  for pid in "${canary_pid}" "${stable_pid}"; do
    [ -z "${pid}" ] || kill "${pid}" >/dev/null 2>&1 || true
    [ -z "${pid}" ] || wait "${pid}" >/dev/null 2>&1 || true
  done
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT

capture_canary_identity() {
  local selector_hash
  selector_hash="$(kubectl -n "${APP_NAMESPACE}" get service/demo-api-canary -o jsonpath='{.spec.selector.rollouts-pod-template-hash}' 2>/dev/null || true)"
  if [ -z "${selector_hash}" ]; then
    jq -n '{selectorHash:"",selectedPods:[]}' >"${work_dir}/canary-identity.json"
    return
  fi
  kubectl -n "${APP_NAMESPACE}" get pods \
    -l "rollouts-pod-template-hash=${selector_hash}" -o json \
    | jq --arg selector_hash "${selector_hash}" '{
        selectorHash: $selector_hash,
        selectedPods: [.items[] | {
          name: .metadata.name,
          podTemplateHash: .metadata.labels["rollouts-pod-template-hash"],
          releaseId: .metadata.annotations["platform.startup.dev/release-id"],
          applicationVersion: .metadata.annotations["platform.startup.dev/application-version"],
          ready: any(.status.conditions[]?; .type == "Ready" and .status == "True")
        }]
      }' >"${work_dir}/canary-identity.json"
}

print_canary_identity_diagnostics() {
  echo "==> Canary identity diagnostics" >&2
  kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o wide >&2 || true
  kubectl -n "${APP_NAMESPACE}" get service/demo-api-canary -o wide >&2 || true
  capture_canary_identity || true
  jq . "${work_dir}/canary-identity.json" >&2 || true
}

echo "==> Waiting for canary Service endpoints with release ID ${expected_release_id}"
deadline=$((SECONDS + CANARY_IDENTITY_WAIT_SECONDS))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  capture_canary_identity
  if assert_canary_identity "${work_dir}/canary-identity.json" "${expected_release_id}"; then
    break
  fi
  sleep 2
done
if ! assert_canary_identity "${work_dir}/canary-identity.json" "${expected_release_id}"; then
  echo "ERROR: canary Service did not select Ready Pods for ${expected_release_id} within ${CANARY_IDENTITY_WAIT_SECONDS}s." >&2
  print_canary_identity_diagnostics
  exit 1
fi

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
stable_port="$(free_port)"
canary_port="$(free_port)"
kubectl -n "${APP_NAMESPACE}" port-forward service/demo-api-stable "${stable_port}:80" >"${work_dir}/stable.log" 2>&1 & stable_pid="$!"
kubectl -n "${APP_NAMESPACE}" port-forward service/demo-api-canary "${canary_port}:80" >"${work_dir}/canary.log" 2>&1 & canary_pid="$!"

for endpoint in "http://127.0.0.1:${stable_port}/version" "http://127.0.0.1:${canary_port}/version"; do
  deadline=$((SECONDS + 45))
  until curl -fsS "${endpoint}" >/dev/null 2>&1; do
    [ "${SECONDS}" -lt "${deadline}" ] || { echo "ERROR: timed out waiting for ${endpoint}" >&2; exit 1; }
    sleep 1
  done
done

echo "==> Generating bounded traffic across Prometheus scrape intervals"
traffic_started_at="${SECONDS}"
traffic_sent=0
while [ $((SECONDS - traffic_started_at)) -lt "${TRAFFIC_DURATION_SECONDS}" ] || [ "${traffic_sent}" -lt "${TRAFFIC_REQUESTS}" ]; do
  curl -fsS "http://127.0.0.1:${stable_port}/version" >/dev/null
  curl -fsS "http://127.0.0.1:${canary_port}/version" >/dev/null
  traffic_sent=$((traffic_sent + 1))
  sleep "${TRAFFIC_INTERVAL_SECONDS}"
done
echo "Generated ${traffic_sent} request pairs over $((SECONDS - traffic_started_at))s."

echo "==> Waiting for successful SLO-aware AnalysisRun ${MINIMUM_MATCHING_ANALYSIS_RUNS} for ${expected_release_id}"
deadline=$((SECONDS + ANALYSIS_TIMEOUT_SECONDS))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  kubectl -n "${APP_NAMESPACE}" get analysisrun -o json >"${work_dir}/analysisruns.json"
  matching_count="$(jq --arg release_id "${expected_release_id}" '
    [.items[]
      | select(any(.spec.args[]?; .name == "expected-release-id" and .value == $release_id))]
    | length
  ' "${work_dir}/analysisruns.json")"
  jq -c --arg release_id "${expected_release_id}" --argjson minimum "${MINIMUM_MATCHING_ANALYSIS_RUNS}" '
    [.items[]
      | select(any(.spec.args[]?; .name == "expected-release-id" and .value == $release_id))]
    | sort_by(.metadata.creationTimestamp)
    | if length >= $minimum then .[$minimum - 1] else empty end
  ' "${work_dir}/analysisruns.json" >"${work_dir}/latest.json"
  if [ -s "${work_dir}/latest.json" ]; then
    phase="$(jq -r '.status.phase // "Pending"' "${work_dir}/latest.json")"
    if [ "${phase}" = "Successful" ]; then
      assert_analysis_run "${work_dir}/latest.json" "${expected_release_id}"
      echo "v0.11.7.2 local candidate release identity, SLO-aware metrics, and successful AnalysisRun acceptance passed."
      exit 0
    fi
    case "${phase}" in Failed|Error|Inconclusive)
      assert_analysis_run "${work_dir}/latest.json" "${expected_release_id}" || true
      print_canary_identity_diagnostics
      exit 1
      ;;
    esac
  fi
  printf 'Matching AnalysisRuns: %s/%s\r' "${matching_count}" "${MINIMUM_MATCHING_ANALYSIS_RUNS}"
  sleep 5
done

echo "ERROR: no successful SLO-aware AnalysisRun appeared within ${ANALYSIS_TIMEOUT_SECONDS}s." >&2
kubectl -n "${APP_NAMESPACE}" get analysisrun --sort-by=.metadata.creationTimestamp >&2 || true
print_canary_identity_diagnostics
exit 1

#!/usr/bin/env bash
set -Eeuo pipefail

CONTEXT="${CONTEXT:-}"
NAMESPACE="${NAMESPACE:-startup-apps}"
EXPECTED_CANDIDATE_RELEASE_ID="${EXPECTED_CANDIDATE_RELEASE_ID:-}"
EXPECTED_BASELINE_RELEASE_ID="${EXPECTED_BASELINE_RELEASE_ID:-}"
EXPECTED_TOKEN_SHA256="${EXPECTED_TOKEN_SHA256:-}"
FAULT_TOKEN_FILE="${FAULT_TOKEN_FILE:-}"
MAX_REQUESTS="${MAX_REQUESTS:-80}"
TRAFFIC_INTERVAL_SECONDS="${TRAFFIC_INTERVAL_SECONDS:-2}"
ANALYSIS_WAIT_SECONDS="${ANALYSIS_WAIT_SECONDS:-180}"
CONFIRM_LOCAL_REJECTION_TRAFFIC="${CONFIRM_LOCAL_REJECTION_TRAFFIC:-}"

fail() { echo "ERROR: $*" >&2; exit 1; }
for command_name in curl jq kubectl python3 sha256sum; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "required command not found: ${command_name}"
done
[[ "${CONTEXT}" =~ ^kind-[A-Za-z0-9._-]+$ ]] || fail 'explicit kind context required'
[[ "${EXPECTED_TOKEN_SHA256}" =~ ^[0-9a-f]{64}$ ]] || fail 'expected token digest must be lowercase SHA-256'
[[ "${MAX_REQUESTS}" =~ ^[0-9]+$ ]] && (( MAX_REQUESTS >= 20 && MAX_REQUESTS <= 80 )) \
  || fail 'MAX_REQUESTS must be 20..80'
[[ "${TRAFFIC_INTERVAL_SECONDS}" =~ ^[0-9]+$ ]] && (( TRAFFIC_INTERVAL_SECONDS >= 1 && TRAFFIC_INTERVAL_SECONDS <= 5 )) \
  || fail 'TRAFFIC_INTERVAL_SECONDS must be 1..5'
[[ "${ANALYSIS_WAIT_SECONDS}" =~ ^[0-9]+$ ]] && (( ANALYSIS_WAIT_SECONDS >= 30 && ANALYSIS_WAIT_SECONDS <= 180 )) \
  || fail 'ANALYSIS_WAIT_SECONDS must be 30..180'
[[ "${CONFIRM_LOCAL_REJECTION_TRAFFIC}" == 'generate-reviewed-candidate-fault-traffic' ]] \
  || fail 'explicit traffic confirmation required'
[[ -n "${EXPECTED_CANDIDATE_RELEASE_ID}" && -n "${EXPECTED_BASELINE_RELEASE_ID}" ]] \
  || fail 'candidate and baseline release IDs are required'
[[ "${EXPECTED_CANDIDATE_RELEASE_ID}" != "${EXPECTED_BASELINE_RELEASE_ID}" ]] \
  || fail 'candidate release ID must differ from baseline'
[[ -f "${FAULT_TOKEN_FILE}" && ! -L "${FAULT_TOKEN_FILE}" ]] || fail 'private fault token file required'
[[ "$(stat -c '%a' "${FAULT_TOKEN_FILE}")" == '600' ]] || fail 'fault token file mode must be 600'
[[ "$(sha256sum "${FAULT_TOKEN_FILE}" | awk '{print $1}')" == "${EXPECTED_TOKEN_SHA256}" ]] \
  || fail 'fault token file does not match the prepared digest'

work_dir="$(mktemp -d /tmp/local-candidate-rejection-traffic.XXXXXX)"
stable_pid=''
canary_pid=''
cleanup() {
  for pid in "${stable_pid}" "${canary_pid}"; do
    [[ -z "${pid}" ]] || kill "${pid}" >/dev/null 2>&1 || true
  done
  wait "${stable_pid}" "${canary_pid}" >/dev/null 2>&1 || true
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT

kube() { kubectl --context "${CONTEXT}" -n "${NAMESPACE}" "$@"; }
assert_service_identity() {
  local service="$1" expected_release="$2" expected_mode="$3" expected_digest="$4"
  local selector
  selector="$(kube get "service/${service}" -o jsonpath='{.spec.selector.rollouts-pod-template-hash}')"
  [[ -n "${selector}" ]] || fail "Service/${service} has no Rollout selector"
  kube get pods -l "rollouts-pod-template-hash=${selector}" -o json >"${work_dir}/${service}.pods.json"
  jq -e --arg release "${expected_release}" --arg mode "${expected_mode}" --arg digest "${expected_digest}" '
    [.items[] | select(.metadata.deletionTimestamp == null)] as $pods |
    ($pods | length) > 0 and all($pods[];
      .metadata.annotations["platform.startup.dev/release-id"] == $release and
      any(.status.conditions[]?; .type == "Ready" and .status == "True") and
      any(.spec.containers[]?.env[]?; .name == "REHEARSAL_FAULT_MODE" and .value == $mode) and
      any(.spec.containers[]?.env[]?; .name == "REHEARSAL_FAULT_TOKEN_SHA256" and .value == $digest))
  ' "${work_dir}/${service}.pods.json" >/dev/null \
    || fail "Service/${service} Pod identity/fault configuration mismatch"
}

echo '==> Verifying stable and candidate Service isolation before traffic'
assert_service_identity demo-api-stable "${EXPECTED_BASELINE_RELEASE_ID}" disabled ''
assert_service_identity demo-api-canary "${EXPECTED_CANDIDATE_RELEASE_ID}" availability-503 "${EXPECTED_TOKEN_SHA256}"

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'; }
stable_port="$(free_port)"
canary_port="$(free_port)"
kube port-forward service/demo-api-stable "${stable_port}:80" >"${work_dir}/stable-forward.log" 2>&1 & stable_pid="$!"
kube port-forward service/demo-api-canary "${canary_port}:80" >"${work_dir}/canary-forward.log" 2>&1 & canary_pid="$!"

wait_for_http() {
  local url="$1" deadline=$((SECONDS + 45))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    (( SECONDS < deadline )) || fail "timed out waiting for ${url}"
    sleep 1
  done
}
wait_for_http "http://127.0.0.1:${stable_port}/version"
wait_for_http "http://127.0.0.1:${canary_port}/version"

token="$(<"${FAULT_TOKEN_FILE}")"
[[ -n "${token}" ]] || fail 'fault token is empty'
umask 077
printf 'X-Rehearsal-Fault: %s\n' "${token}" >"${work_dir}/fault-header"
unset token
echo "==> Sending at most ${MAX_REQUESTS} candidate-fault requests with stable controls"
sent=0
while (( sent < MAX_REQUESTS )); do
  curl -fsS "http://127.0.0.1:${stable_port}/version" >/dev/null \
    || fail 'stable control request failed; candidate-only isolation is invalid'
  code="$(curl -sS -o /dev/null -w '%{http_code}' -H @"${work_dir}/fault-header" \
    "http://127.0.0.1:${canary_port}/version")"
  [[ "${code}" == '503' ]] || fail "candidate fault response must be 503, found ${code}"
  sent=$((sent + 1))
  printf 'Verified request pairs: %s/%s\r' "${sent}" "${MAX_REQUESTS}"
  sleep "${TRAFFIC_INTERVAL_SECONDS}"
done
echo

echo '==> Waiting for the exact release-bound availability metric rejection'
deadline=$((SECONDS + ANALYSIS_WAIT_SECONDS))
while (( SECONDS < deadline )); do
  kube get analysisruns -o json >"${work_dir}/analysisruns.json"
  jq -c --arg release "${EXPECTED_CANDIDATE_RELEASE_ID}" '
    [.items[] | select(any(.spec.args[]?; .name == "expected-release-id" and .value == $release))]
    | sort_by(.metadata.creationTimestamp) | last // empty
  ' "${work_dir}/analysisruns.json" >"${work_dir}/candidate-analysis.json"
  if [[ -s "${work_dir}/candidate-analysis.json" ]]; then
    phase="$(jq -r '.status.phase // "Pending"' "${work_dir}/candidate-analysis.json")"
    if [[ "${phase}" == 'Failed' ]]; then
      jq -e '
        any(.status.metricResults[]?;
          .name == "canary-availability-error-budget-burn-rate" and
          .phase == "Failed" and
          ([.measurements[]? | select(.value != null)] | length) > 0) and
        all(.status.metricResults[]?; .phase != "Error" and .phase != "Inconclusive")
      ' "${work_dir}/candidate-analysis.json" >/dev/null \
        || fail 'AnalysisRun failed without the exact measured availability burn-rate rejection'
      echo "Candidate rejection observed after ${sent} bounded request pairs."
      exit 0
    fi
    [[ "${phase}" != 'Error' && "${phase}" != 'Inconclusive' && "${phase}" != 'Successful' ]] \
      || fail "invalid candidate AnalysisRun phase for rejection: ${phase}"
  fi
  sleep 5
done
fail "exact candidate availability rejection did not appear within ${ANALYSIS_WAIT_SECONDS}s"

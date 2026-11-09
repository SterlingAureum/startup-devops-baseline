#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19096}"
PROMETHEUS_RULES_FIXTURE="${PROMETHEUS_RULES_FIXTURE:-}"

assert_burn_rate_rule_inventory() {
  local payload_file="$1"
  local missing_rules

  jq -e '
    .status == "success"
    and (.data.groups | type) == "array"
  ' "${payload_file}" >/dev/null || {
    echo "ERROR: Prometheus rules response is invalid or unsuccessful." >&2
    return 1
  }

  missing_rules="$(jq -r '
    [.data.groups[].rules[] | select(.type == "recording") | .name] as $records |
    [
      ["5m","30m","1h","2h","6h","1d","3d"][] as $w |
      "demo_api:slo_availability_bad:ratio" + $w,
      "demo_api:slo_availability_burn_rate:ratio" + $w,
      "demo_api:slo_latency_bad:ratio" + $w,
      "demo_api:slo_latency_burn_rate:ratio" + $w
    ] as $expected |
    ($expected - $records)[]?
  ' "${payload_file}")" || {
    echo "ERROR: unable to evaluate the Prometheus burn-rate rule inventory." >&2
    return 1
  }

  if [ -n "${missing_rules}" ]; then
    echo "ERROR: the following SLO burn-rate recording rules are not loaded:" >&2
    while IFS= read -r rule_name; do
      [ -n "${rule_name}" ] && printf '  - %s\n' "${rule_name}" >&2
    done <<<"${missing_rules}"
    return 1
  fi
}

if [ -n "${PROMETHEUS_RULES_FIXTURE}" ]; then
  command -v jq >/dev/null 2>&1 || { echo "ERROR: required command not found: jq" >&2; exit 1; }
  [ -r "${PROMETHEUS_RULES_FIXTURE}" ] || { echo "ERROR: Prometheus rules fixture is not readable: ${PROMETHEUS_RULES_FIXTURE}" >&2; exit 1; }
  assert_burn_rate_rule_inventory "${PROMETHEUS_RULES_FIXTURE}"
  echo "v0.11.7.1.3 Prometheus burn-rate rule inventory fixture acceptance passed."
  exit 0
fi

"${ROOT_DIR}/scripts/check-local-slo-foundation.sh"
PROFILE=local "${ROOT_DIR}/scripts/check-actionable-alerts.sh"

for command_name in curl jq kubectl seq; do
  command -v "${command_name}" >/dev/null 2>&1 || { echo "ERROR: required command not found: ${command_name}" >&2; exit 1; }
done

port_is_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }
selected_port=""
for port in $(seq "${PROMETHEUS_LOCAL_PORT}" "$((PROMETHEUS_LOCAL_PORT + 100))"); do
  if ! port_is_open "${port}"; then selected_port="${port}"; break; fi
done
[ -n "${selected_port}" ] || { echo "ERROR: no local Prometheus port is available." >&2; exit 1; }

log_path="$(mktemp)"
rules_payload_file=""
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" "${selected_port}:9090" >"${log_path}" 2>&1 &
port_forward_pid="$!"
cleanup() {
  kill "${port_forward_pid}" >/dev/null 2>&1 || true
  wait "${port_forward_pid}" >/dev/null 2>&1 || true
  rm -f "${log_path}"
  [ -z "${rules_payload_file}" ] || rm -f "${rules_payload_file}"
}
trap cleanup EXIT
prometheus_url="http://127.0.0.1:${selected_port}"
deadline=$((SECONDS + 30))
until curl -fsS "${prometheus_url}/-/ready" >/dev/null 2>&1; do
  [ "${SECONDS}" -lt "${deadline}" ] || { sed -n '1,100p' "${log_path}" >&2; exit 1; }
  sleep 1
done

rules_payload_file="$(mktemp)"
curl -fsS "${prometheus_url}/api/v1/rules" >"${rules_payload_file}"
assert_burn_rate_rule_inventory "${rules_payload_file}"

echo "v0.11.7.1 local multi-window burn-rate recording rules, clean alert inventory, and Dashboard prerequisites passed."

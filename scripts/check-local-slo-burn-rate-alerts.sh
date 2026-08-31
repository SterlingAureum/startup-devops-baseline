#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19096}"

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
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" "${selected_port}:9090" >"${log_path}" 2>&1 &
port_forward_pid="$!"
cleanup() { kill "${port_forward_pid}" >/dev/null 2>&1 || true; wait "${port_forward_pid}" >/dev/null 2>&1 || true; rm -f "${log_path}"; }
trap cleanup EXIT
prometheus_url="http://127.0.0.1:${selected_port}"
deadline=$((SECONDS + 30))
until curl -fsS "${prometheus_url}/-/ready" >/dev/null 2>&1; do
  [ "${SECONDS}" -lt "${deadline}" ] || { sed -n '1,100p' "${log_path}" >&2; exit 1; }
  sleep 1
done

rules_payload="$(curl -fsS "${prometheus_url}/api/v1/rules")"
jq -e '
  [.data.groups[].rules[] | select(.type == "recording") | .name] as $records |
  ["5m","30m","1h","2h","6h","1d","3d"] as $windows |
  all($windows[] as $w;
    ($records | index("demo_api:slo_availability_bad:ratio" + $w)) != null and
    ($records | index("demo_api:slo_availability_burn_rate:ratio" + $w)) != null and
    ($records | index("demo_api:slo_latency_bad:ratio" + $w)) != null and
    ($records | index("demo_api:slo_latency_burn_rate:ratio" + $w)) != null)
' <<<"${rules_payload}" >/dev/null || {
  echo "ERROR: the complete 28-rule SLO burn-rate inventory is not loaded." >&2
  exit 1
}

echo "v0.11.7.1 local multi-window burn-rate recording rules, clean alert inventory, and Dashboard prerequisites passed."

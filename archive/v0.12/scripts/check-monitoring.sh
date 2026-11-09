#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_POD_SELECTOR="${PROMETHEUS_POD_SELECTOR:-app.kubernetes.io/name=prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"
PROMETHEUS_BASE_URL="${PROMETHEUS_BASE_URL:-http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}}"
SERVICE_MONITOR="${SERVICE_MONITOR:-demo-api}"
ROLLOUT_ENABLED="${ROLLOUT_ENABLED:-true}"
TIMEOUT="${TIMEOUT:-180s}"
TRAFFIC_LOCAL_PORT="${TRAFFIC_LOCAL_PORT:-18079}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"
PF_PID=""
PF_LOG=""

# shellcheck source=scripts/lib/observability-live.sh
source "${ROOT_DIR}/scripts/lib/observability-live.sh"

cleanup() {
  if [[ -n "${PF_PID}" ]] && kill -0 "${PF_PID}" >/dev/null 2>&1; then
    kill "${PF_PID}" >/dev/null 2>&1 || true
    wait "${PF_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${PF_LOG}" && -f "${PF_LOG}" ]]; then
    rm -f -- "${PF_LOG}"
  fi
}
trap cleanup EXIT

for command in curl grep jq kubectl seq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

query_prometheus() {
  local query="$1"
  local description="$2"
  local response

  response="$(curl -fsS --get "${PROMETHEUS_BASE_URL}/api/v1/query" --data-urlencode "query=${query}")"
  if jq --exit-status '.status == "success" and (.data.result | length) > 0' <<<"${response}" >/dev/null; then
    echo "PASS: ${description}"
    return 0
  fi

  echo "FAIL: ${description}; query returned no series: ${query}" >&2
  jq . <<<"${response}" >&2 || true
  return 1
}

echo "==> Checking Operator-managed Prometheus and application ServiceMonitor"
kubectl get namespace "${MONITORING_NAMESPACE}" >/dev/null
kubectl get namespace "${APP_NAMESPACE}" >/dev/null
kubectl -n "${MONITORING_NAMESPACE}" wait \
  --for=condition=Ready pod \
  -l "${PROMETHEUS_POD_SELECTOR}" \
  --timeout="${TIMEOUT}"
kubectl -n "${MONITORING_NAMESPACE}" get service "${PROMETHEUS_SERVICE}" >/dev/null
kubectl -n "${APP_NAMESPACE}" get servicemonitor "${SERVICE_MONITOR}" >/dev/null

if ! curl -fsS "${PROMETHEUS_BASE_URL}/-/ready" >/dev/null 2>&1; then
  PF_LOG="$(mktemp)"
  kubectl -n "${MONITORING_NAMESPACE}" port-forward \
    "svc/${PROMETHEUS_SERVICE}" \
    "${PROMETHEUS_LOCAL_PORT}:9090" >"${PF_LOG}" 2>&1 &
  PF_PID="$!"

  for _ in $(seq 1 30); do
    if curl -fsS "${PROMETHEUS_BASE_URL}/-/ready" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

if ! curl -fsS "${PROMETHEUS_BASE_URL}/-/ready" >/dev/null 2>&1; then
  echo "Prometheus did not become ready through ${PROMETHEUS_BASE_URL}." >&2
  [[ -n "${PF_LOG}" ]] && sed -n '1,80p' "${PF_LOG}" >&2 || true
  exit 1
fi

echo "==> Checking demo-api discovery and bounded application signals"
if [[ "${ROLLOUT_ENABLED}" == "true" ]]; then
  observability_assert_prometheus_jobs_up \
    "${PROMETHEUS_BASE_URL}" demo-api-stable demo-api-canary
else
  observability_assert_prometheus_jobs_up "${PROMETHEUS_BASE_URL}" demo-api
fi

echo "==> Generating bounded demo-api telemetry"
observability_generate_demo_api_metrics \
  "${APP_NAMESPACE}" "${ARGOCD_NAMESPACE}" demo-api "${TRAFFIC_LOCAL_PORT}"
echo "==> Waiting ${RULE_WARMUP_SECONDS}s for application scrape"
sleep "${RULE_WARMUP_SECONDS}"

query_prometheus 'sum(demo_api_http_requests_total)' "bounded HTTP request metric exists"
query_prometheus 'sum(demo_api_dependency_checks_total)' "bounded PostgreSQL dependency metric exists"

identity_query='count(demo_api_http_requests_total{service_name!="",service_version!="",deployment_environment_name!="",platform_release_id!="",platform_source_commit!="",container_image_digest!=""})'
query_prometheus "${identity_query}" "all six release-correlation labels exist"

echo "==> Checking core platform telemetry"
for metric in \
  kube_pod_status_ready \
  kube_pod_container_resource_requests \
  node_cpu_seconds_total \
  node_memory_MemAvailable_bytes \
  prometheus_tsdb_head_series; do
  query_prometheus "${metric}" "platform metric exists: ${metric}"
done

echo "v0.11.2 monitoring live check completed successfully."

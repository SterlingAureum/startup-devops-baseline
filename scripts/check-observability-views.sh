#!/usr/bin/env bash
set -Eeuo pipefail

OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
MONITORING_APP="${MONITORING_APP:-monitoring}"
VIEWS_APP="${VIEWS_APP:-observability-views}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-observability-metrics-grafana}"
GRAFANA_SECRET="${GRAFANA_SECRET:-observability-metrics-grafana}"
GRAFANA_DASHBOARD_CONFIGMAP="${GRAFANA_DASHBOARD_CONFIGMAP:-observability-dashboard-service-overview}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"
GRAFANA_LOCAL_PORT="${GRAFANA_LOCAL_PORT:-13000}"
TRAFFIC_LOCAL_PORT="${TRAFFIC_LOCAL_PORT:-18080}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"

for command_name in base64 curl jq kubectl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

prometheus_pid=""
grafana_pid=""
traffic_pid=""
cleanup() {
  for pid in "${traffic_pid}" "${grafana_pid}" "${prometheus_pid}"; do
    if [ -n "${pid}" ]; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for ${url}" >&2
      exit 1
    fi
    sleep 1
  done
}

assert_application() {
  local name="$1"
  local sync health
  sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o jsonpath='{.status.sync.status}')"
  health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o jsonpath='{.status.health.status}')"
  [ "${sync}" = "Synced" ] || { echo "ERROR: Application/${name} is ${sync:-unknown}, not Synced." >&2; exit 1; }
  [ "${health}" = "Healthy" ] || { echo "ERROR: Application/${name} is ${health:-unknown}, not Healthy." >&2; exit 1; }
}

query_nonempty() {
  local expression="$1"
  local description="$2"
  local payload
  payload="$(curl -fsS --get "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/query" --data-urlencode "query=${expression}")"
  jq -e '.status == "success" and (.data.result | length) > 0' <<<"${payload}" >/dev/null || {
    echo "ERROR: ${description} returned no series: ${expression}" >&2
    echo "Generate demo-api traffic and increase RULE_WARMUP_SECONDS if the stack was just deployed." >&2
    exit 1
  }
}

echo "==> Checking Argo CD Applications"
assert_application "${MONITORING_APP}"
assert_application "${VIEWS_APP}"

echo "==> Checking Grafana and observability resources"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status deployment/observability-metrics-grafana --timeout=180s
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule demo-api-operator-recording-rules >/dev/null
dashboard_label="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get configmap "${GRAFANA_DASHBOARD_CONFIGMAP}" \
  -o jsonpath='{.metadata.labels.grafana_dashboard}')"
[ "${dashboard_label}" = "1" ] || {
  echo "ERROR: ConfigMap/${GRAFANA_DASHBOARD_CONFIGMAP} is not labeled grafana_dashboard=1." >&2
  exit 1
}

traffic_service="demo-api-stable"
if ! kubectl -n "${APP_NAMESPACE}" get service "${traffic_service}" >/dev/null 2>&1; then
  traffic_service="demo-api"
fi
kubectl -n "${APP_NAMESPACE}" port-forward "service/${traffic_service}" "${TRAFFIC_LOCAL_PORT}:80" >/tmp/v0.11.4.0-traffic-port-forward.log 2>&1 &
traffic_pid="$!"
wait_http "http://127.0.0.1:${TRAFFIC_LOCAL_PORT}/health"
for _ in $(seq 1 12); do
  curl -fsS "http://127.0.0.1:${TRAFFIC_LOCAL_PORT}/health" >/dev/null
  curl -fsS "http://127.0.0.1:${TRAFFIC_LOCAL_PORT}/ready" >/dev/null || true
done
kill "${traffic_pid}" >/dev/null 2>&1 || true
wait "${traffic_pid}" >/dev/null 2>&1 || true
traffic_pid=""

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for scrape and rule evaluation"
sleep "${RULE_WARMUP_SECONDS}"

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" "${PROMETHEUS_LOCAL_PORT}:9090" >/tmp/v0.11.4.0-prometheus-port-forward.log 2>&1 &
prometheus_pid="$!"
wait_http "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready"

rules_payload="$(curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/rules?type=record")"
for rule_name in \
  demo_api:http_requests:rate5m \
  demo_api:http_errors:rate5m \
  demo_api:http_success_ratio:rate5m \
  demo_api:http_request_duration_seconds:p50_5m \
  demo_api:http_request_duration_seconds:p95_5m \
  demo_api:http_request_duration_seconds:p99_5m \
  demo_api:dependency_checks:rate5m \
  demo_api:dependency_success_ratio:rate5m \
  demo_api:dependency_check_duration_seconds:p95_5m; do
  jq -e --arg name "${rule_name}" \
    '[.data.groups[].rules[] | select(.name == $name and .type == "recording")] | length == 1' \
    <<<"${rules_payload}" >/dev/null || {
      echo "ERROR: Prometheus did not load recording rule ${rule_name}." >&2
      exit 1
    }
done

query_nonempty 'demo_api:http_requests:rate5m' "request-rate rule"
query_nonempty 'demo_api:http_success_ratio:rate5m' "success-ratio rule"
query_nonempty 'demo_api:http_request_duration_seconds:p95_5m' "latency rule"
query_nonempty 'demo_api:dependency_checks:rate5m' "dependency-rate rule"

echo "==> Checking Grafana health and Git-provisioned Dashboard"
admin_user="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" -o jsonpath='{.data.admin-user}' | base64 -d)"
admin_password="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" -o jsonpath='{.data.admin-password}' | base64 -d)"
[ -n "${admin_user}" ] && [ -n "${admin_password}" ] || {
  echo "ERROR: Grafana generated administrator Secret is incomplete." >&2
  exit 1
}

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${GRAFANA_SERVICE}" "${GRAFANA_LOCAL_PORT}:80" >/tmp/v0.11.4.0-grafana-port-forward.log 2>&1 &
grafana_pid="$!"
wait_http "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/health"

curl -fsS -u "${admin_user}:${admin_password}" \
  "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/datasources/uid/prometheus" \
  | jq -e '.uid == "prometheus" and .type == "prometheus"' >/dev/null
curl -fsS -u "${admin_user}:${admin_password}" \
  "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/dashboards/uid/startup-devops-service-overview" \
  | jq -e '.dashboard.uid == "startup-devops-service-overview" and .dashboard.editable == false' >/dev/null

echo "v0.11.4.0 local Grafana, recording-rule, datasource, and Dashboard acceptance passed."

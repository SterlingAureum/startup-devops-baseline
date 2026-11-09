#!/usr/bin/env bash
set -Eeuo pipefail

PROFILE="${PROFILE:-local}"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-observability-metrics-grafana}"
GRAFANA_SECRET="${GRAFANA_SECRET:-observability-metrics-grafana}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19094}"
GRAFANA_LOCAL_PORT="${GRAFANA_LOCAL_PORT:-13003}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"

case "${PROFILE}" in
  local|aws) ;;
  *)
    echo "ERROR: PROFILE must be local or aws, found ${PROFILE}." >&2
    exit 1
    ;;
esac

for command_name in base64 curl jq kubectl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

prometheus_pid=""
grafana_pid=""
prometheus_log="$(mktemp)"
grafana_log="$(mktemp)"
cleanup() {
  for pid in "${grafana_pid}" "${prometheus_pid}"; do
    if [ -n "${pid}" ]; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  rm -f -- "${prometheus_log}" "${grafana_log}"
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local log_file="$2"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for ${url}" >&2
      sed -n '1,80p' "${log_file}" >&2 || true
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
  [ "${sync}" = "Synced" ] || {
    echo "ERROR: Application/${name} is ${sync:-unknown}, not Synced." >&2
    exit 1
  }
  [ "${health}" = "Healthy" ] || {
    echo "ERROR: Application/${name} is ${health:-unknown}, not Healthy." >&2
    exit 1
  }
}

assert_dashboard_configmap() {
  local name="$1"
  local label
  label="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get configmap "${name}" \
    -o jsonpath='{.metadata.labels.grafana_dashboard}')"
  [ "${label}" = "1" ] || {
    echo "ERROR: ConfigMap/${name} is not labeled grafana_dashboard=1." >&2
    exit 1
  }
}

query_payload() {
  local expression="$1"
  curl -fsS --get "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/query" \
    --data-urlencode "query=${expression}"
}

assert_finite_query() {
  local expression="$1"
  local description="$2"
  local payload
  payload="$(query_payload "${expression}")"
  jq -e '
    .status == "success" and
    (.data.result | length) > 0 and
    all(.data.result[]; (.value[1] | test("^(NaN|[+-]Inf)$") | not))
  ' <<<"${payload}" >/dev/null || {
    echo "ERROR: ${description} is empty or non-finite: ${expression}" >&2
    jq . <<<"${payload}" >&2 || true
    exit 1
  }
  echo "PASS: ${description}"
}

wait_dashboard() {
  local uid="$1"
  local panel_count="$2"
  local deadline=$((SECONDS + 30))
  local payload=""
  while true; do
    if payload="$(curl -fsS -u "${admin_user}:${admin_password}" \
      "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/dashboards/uid/${uid}" 2>/dev/null)" && \
      jq -e --arg uid "${uid}" --argjson panel_count "${panel_count}" '
        .dashboard.uid == $uid and
        .dashboard.editable == false and
        (.dashboard.panels | length) == $panel_count
      ' <<<"${payload}" >/dev/null; then
      echo "PASS: Grafana Dashboard is provisioned and immutable: ${uid} panels=${panel_count}"
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: Grafana Dashboard did not become available with the accepted contract: ${uid}" >&2
      exit 1
    fi
    sleep 1
  done
}

if [ "${PROFILE}" = "local" ]; then
  monitoring_application="monitoring"
  views_application="observability-views"
else
  monitoring_application="monitoring-${AWS_ENVIRONMENT}"
  views_application="observability-views-${AWS_ENVIRONMENT}"
fi

echo "==> Checking GitOps Applications and Dashboard ConfigMaps"
assert_application "${monitoring_application}"
assert_application "${views_application}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  deployment/observability-metrics-grafana --timeout=180s
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule \
  capacity-efficiency-recording-rules >/dev/null
for configmap_name in \
  observability-dashboard-service-overview \
  observability-dashboard-delivery-overview \
  observability-dashboard-data-overview \
  observability-dashboard-platform-overview \
  observability-dashboard-capacity-overview; do
  assert_dashboard_configmap "${configmap_name}"
done

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_LOCAL_PORT}:9090" >"${prometheus_log}" 2>&1 &
prometheus_pid="$!"
wait_http "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready" "${prometheus_log}"

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for capacity rule evaluation"
sleep "${RULE_WARMUP_SECONDS}"

echo "==> Checking rule-backed Capacity Dashboard data"
assert_finite_query 'capacity:node_cpu_allocatable_cores:sum' "CPU allocatable"
assert_finite_query 'capacity:node_memory_allocatable_bytes:sum' "memory allocatable"
assert_finite_query 'capacity:running_pods_to_allocatable:ratio' "Pod capacity ratio"
assert_finite_query 'capacity:cpu_requests_to_allocatable:ratio' "CPU request ratio"
assert_finite_query 'capacity:memory_requests_to_allocatable:ratio' "memory request ratio"
assert_finite_query \
  "efficiency:namespace_cpu_usage_to_requests:ratio{namespace=\"${APP_NAMESPACE}\"}" \
  "startup-apps CPU efficiency"
assert_finite_query \
  "efficiency:namespace_memory_usage_to_requests:ratio{namespace=\"${APP_NAMESPACE}\"}" \
  "startup-apps memory efficiency"
assert_finite_query \
  "efficiency:namespace_containers_without_cpu_requests:count{namespace=\"${APP_NAMESPACE}\"}" \
  "startup-apps CPU request coverage"
assert_finite_query \
  "efficiency:namespace_containers_without_memory_requests:count{namespace=\"${APP_NAMESPACE}\"}" \
  "startup-apps memory request coverage"

echo "==> Checking Grafana Dashboard provisioning"
admin_user="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" \
  -o jsonpath='{.data.admin-user}' | base64 -d)"
admin_password="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" \
  -o jsonpath='{.data.admin-password}' | base64 -d)"
[ -n "${admin_user}" ] && [ -n "${admin_password}" ] || {
  echo "ERROR: Grafana generated administrator Secret is incomplete." >&2
  exit 1
}

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${GRAFANA_SERVICE}" \
  "${GRAFANA_LOCAL_PORT}:80" >"${grafana_log}" 2>&1 &
grafana_pid="$!"
wait_http "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/health" "${grafana_log}"

while read -r dashboard_uid panel_count; do
  wait_dashboard "${dashboard_uid}" "${panel_count}"
done <<'DASHBOARDS'
startup-devops-service-overview 5
startup-devops-delivery-overview 8
startup-devops-data-overview 6
startup-devops-platform-overview 6
startup-devops-capacity-overview 12
DASHBOARDS

capacity_payload="$(curl -fsS -u "${admin_user}:${admin_password}" \
  "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/dashboards/uid/startup-devops-capacity-overview")"
jq -e '
  [.dashboard.templating.list[].name] == ["namespace"] and
  (.dashboard.tags | index("capacity") != null) and
  (.dashboard.tags | index("efficiency") != null)
' <<<"${capacity_payload}" >/dev/null || {
  echo "ERROR: Capacity Dashboard variable or tags changed." >&2
  exit 1
}

echo "v0.11.4.2.1 Capacity and Resource Efficiency Dashboard live acceptance passed."

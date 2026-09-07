#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${PROFILE:-local}"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-observability-metrics-grafana}"
GRAFANA_SECRET="${GRAFANA_SECRET:-observability-metrics-grafana}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19092}"
GRAFANA_LOCAL_PORT="${GRAFANA_LOCAL_PORT:-13002}"
TRAFFIC_LOCAL_PORT="${TRAFFIC_LOCAL_PORT:-18082}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"

# shellcheck source=scripts/lib/observability-live.sh
source "${ROOT_DIR}/scripts/lib/observability-live.sh"

case "${PROFILE}" in
  local|aws) ;;
  *)
    echo "ERROR: PROFILE must be local or aws, found ${PROFILE}." >&2
    exit 1
    ;;
esac

for command_name in base64 curl grep jq kubectl seq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

prometheus_pid=""
grafana_pid=""
cleanup() {
  for pid in "${grafana_pid}" "${prometheus_pid}"; do
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

query_count() {
  local expression="$1"
  local payload
  payload="$(curl -fsS --get "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/query" \
    --data-urlencode "query=${expression}")"
  jq -er 'select(.status == "success") | .data.result | length' <<<"${payload}"
}

assert_query_nonempty() {
  local expression="$1"
  local description="$2"
  local count
  count="$(query_count "${expression}")"
  [ "${count}" -gt 0 ] || {
    echo "ERROR: ${description} returned no series: ${expression}" >&2
    exit 1
  }
  echo "PASS: ${description} series=${count}"
}

wait_dashboard() {
  local uid="$1"
  local deadline=$((SECONDS + 30))
  local payload=""
  while true; do
    if payload="$(curl -fsS -u "${admin_user}:${admin_password}" \
      "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/dashboards/uid/${uid}" 2>/dev/null)" && \
      jq -e --arg uid "${uid}" '.dashboard.uid == $uid and .dashboard.editable == false' \
        <<<"${payload}" >/dev/null; then
      echo "PASS: Grafana Dashboard is provisioned and immutable: ${uid}"
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: Grafana Dashboard did not become available and immutable: ${uid}" >&2
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

echo "==> Checking Argo CD Applications and Dashboard ConfigMaps"
assert_application "${monitoring_application}"
assert_application "${views_application}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  deployment/observability-metrics-grafana --timeout=180s
for configmap_name in \
  observability-dashboard-service-overview \
  observability-dashboard-delivery-overview \
  observability-dashboard-data-overview \
  observability-dashboard-platform-overview; do
  assert_dashboard_configmap "${configmap_name}"
done

echo "==> Generating bounded demo-api dependency traffic"
observability_generate_demo_api_metrics \
  "${APP_NAMESPACE}" "${ARGOCD_NAMESPACE}" demo-api "${TRAFFIC_LOCAL_PORT}"

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for scrape and rule evaluation"
sleep "${RULE_WARMUP_SECONDS}"

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_LOCAL_PORT}:9090" >/tmp/v0.11.4.1.1-prometheus-port-forward.log 2>&1 &
prometheus_pid="$!"
wait_http "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready"
observability_assert_prometheus_jobs_up \
  "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}" demo-api-stable demo-api-canary

echo "==> Checking required Delivery, Data, and Platform rule results"
assert_query_nonempty 'delivery:argocd_applications:count' "Argo CD application inventory"
assert_query_nonempty 'delivery:rollouts:count' "Rollout inventory"
assert_query_nonempty 'delivery:rollout_ready_replicas:ratio' "Rollout ready ratio"
assert_query_nonempty 'data:demo_api_dependency_checks:rate5m' "demo-api dependency rate"
assert_query_nonempty 'platform:deployment_desired_replicas:count' "Deployment desired replicas"
assert_query_nonempty 'platform:deployment_ready_replicas:ratio' "Deployment ready ratio"
assert_query_nonempty 'platform:prometheus_targets:count' "Prometheus target inventory"

for cnpg_rule in \
  data:postgresql_instances_up:min \
  data:postgresql_collection_errors:max \
  data:postgresql_nodes_used:max \
  data:postgresql_manual_switchover_required:max; do
  if [ "${PROFILE}" = "aws" ]; then
    assert_query_nonempty "${cnpg_rule}" "AWS CloudNativePG rule ${cnpg_rule}"
  else
    echo "INFO: local CloudNativePG data is optional: ${cnpg_rule} series=$(query_count "${cnpg_rule}")"
  fi
done

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
  "${GRAFANA_LOCAL_PORT}:80" >/tmp/v0.11.4.1.1-grafana-port-forward.log 2>&1 &
grafana_pid="$!"
wait_http "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/health"

for dashboard_uid in \
  startup-devops-service-overview \
  startup-devops-delivery-overview \
  startup-devops-data-overview \
  startup-devops-platform-overview; do
  wait_dashboard "${dashboard_uid}"
done

echo "v0.11.4.1.1 operator Dashboard provisioning and rule-backed live acceptance passed."

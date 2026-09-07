#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${PROFILE:-local}"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19094}"
TRAFFIC_LOCAL_PORT="${TRAFFIC_LOCAL_PORT:-18084}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"
ALERT_RULES_FIXTURE="${ALERT_RULES_FIXTURE:-}"

# shellcheck source=scripts/lib/observability-live.sh
source "${ROOT_DIR}/scripts/lib/observability-live.sh"

case "${PROFILE}" in
  local)
    monitoring_application="monitoring"
    views_application="observability-views"
    expected_environment="local"
    expected_cluster="startup-devops-local"
    ;;
  aws)
    monitoring_application="monitoring-${AWS_ENVIRONMENT}"
    views_application="observability-views-${AWS_ENVIRONMENT}"
    expected_environment="${AWS_ENVIRONMENT}"
    case "${AWS_ENVIRONMENT}" in
      aws-dev) expected_cluster="startup-devops-baseline-dev" ;;
      aws-test) expected_cluster="startup-devops-baseline-test" ;;
      aws-prod) expected_cluster="startup-devops-baseline-prod" ;;
      *)
        echo "ERROR: AWS_ENVIRONMENT must be aws-dev, aws-test, or aws-prod." >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "ERROR: PROFILE must be local or aws, found ${PROFILE}." >&2
    exit 1
    ;;
esac

command -v jq >/dev/null 2>&1 || {
  echo "ERROR: required command not found: jq" >&2
  exit 1
}

expected_alerts='[
  "DemoApiHttpSuccessRatioLowWarning",
  "DemoApiHttpSuccessRatioLowCritical",
  "DemoApiDependencySuccessRatioLowWarning",
  "DemoApiDependencySuccessRatioLowCritical",
  "ArgoRolloutProblem",
  "ArgoCDApplicationUnhealthy",
  "KubernetesDeploymentUnavailable",
  "PrometheusTargetDown",
  "PostgreSQLCollectionFailed"
]'

expected_warning_count=2
expected_critical_count=7
if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json" ]; then
  expected_alerts="$(jq -c '. + [
    "DemoApiAvailabilityErrorBudgetFastBurn",
    "DemoApiAvailabilityErrorBudgetSlowBurn",
    "DemoApiLatencyErrorBudgetFastBurn",
    "DemoApiLatencyErrorBudgetSlowBurn"
  ]' <<<"${expected_alerts}")"
  expected_warning_count=4
  expected_critical_count=9
fi

assert_rules_payload() {
  local rules_payload="$1"
  local warning_count critical_count

  if ! jq -e \
    --argjson expected "${expected_alerts}" \
    --arg environment "${expected_environment}" \
    --arg cluster "${expected_cluster}" '
      .status == "success" and
      ([.data.groups[].rules[] | select(.type == "alerting") | .name] | sort) == ($expected | sort) and
      all(
        .data.groups[].rules[] | select(.type == "alerting");
        .health == "ok" and
        .state == "inactive" and
        (.labels.severity == "warning" or .labels.severity == "critical") and
        .labels.environment == $environment and
        .labels.cluster == $cluster and
        (.labels.component | length) > 0 and
        (.labels.alert_family | length) > 0 and
        (.annotations.summary | length) > 0 and
        (.annotations.description | length) > 0 and
        (.annotations.runbook_url | startswith("https://github.com/SterlingAureum/startup-devops-baseline/blob/main/docs/runbooks/alerts/"))
      )
    ' <<<"${rules_payload}" >/dev/null; then
    echo "ERROR: actionable alert inventory, metadata, health, or clean-baseline state is invalid." >&2
    jq '[.data.groups[].rules[] | select(.type == "alerting") | {
      name, health, state, lastError, labels, annotations
    }]' <<<"${rules_payload}" >&2 || true
    return 1
  fi

  warning_count="$(jq '[.data.groups[].rules[] | select(.type == "alerting" and .labels.severity == "warning")] | length' <<<"${rules_payload}")"
  critical_count="$(jq '[.data.groups[].rules[] | select(.type == "alerting" and .labels.severity == "critical")] | length' <<<"${rules_payload}")"
  if [ "${warning_count}" -ne "${expected_warning_count}" ] || [ "${critical_count}" -ne "${expected_critical_count}" ]; then
    echo "ERROR: expected warning=${expected_warning_count} and critical=${expected_critical_count}; found warning=${warning_count}, critical=${critical_count}." >&2
    return 1
  fi
}

if [ -n "${ALERT_RULES_FIXTURE}" ]; then
  [ -r "${ALERT_RULES_FIXTURE}" ] || {
    echo "ERROR: alert-rules fixture is not readable: ${ALERT_RULES_FIXTURE}" >&2
    exit 1
  }
  assert_rules_payload "$(<"${ALERT_RULES_FIXTURE}")"
  echo "v0.11.5.1.1 actionable alert API fixture acceptance passed."
  exit 0
fi

for command_name in curl kubectl seq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

prometheus_pid=""
prometheus_log=""

cleanup() {
  if [ -n "${prometheus_pid}" ]; then
    observability_stop_port_forward "${prometheus_pid}" "${prometheus_log}"
  fi
}
trap cleanup EXIT

port_is_open() {
  local port="$1"
  (exec 3<>"/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1
}

find_available_port() {
  local start_port="$1"
  local port
  for port in $(seq "${start_port}" "$((start_port + 100))"); do
    if ! port_is_open "${port}"; then
      printf '%s\n' "${port}"
      return 0
    fi
  done
  return 1
}

wait_http() {
  local url="$1"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for ${url}." >&2
      sed -n '1,80p' "${prometheus_log}" >&2 || true
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

echo "==> Checking GitOps Applications and actionable PrometheusRule"
assert_application "${monitoring_application}"
assert_application "${views_application}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule actionable-alerts >/dev/null

echo "==> Generating bounded healthy demo-api telemetry"
selected_traffic_port="$(find_available_port "${TRAFFIC_LOCAL_PORT}")" || {
  echo "ERROR: no traffic port is available from ${TRAFFIC_LOCAL_PORT} through $((TRAFFIC_LOCAL_PORT + 100))." >&2
  exit 1
}
observability_generate_demo_api_metrics \
  "${APP_NAMESPACE}" "${ARGOCD_NAMESPACE}" demo-api "${selected_traffic_port}"

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for scrape and alert evaluation"
sleep "${RULE_WARMUP_SECONDS}"

selected_prometheus_port="$(find_available_port "${PROMETHEUS_LOCAL_PORT}")" || {
  echo "ERROR: no Prometheus port is available from ${PROMETHEUS_LOCAL_PORT} through $((PROMETHEUS_LOCAL_PORT + 100))." >&2
  exit 1
}
prometheus_log="$(mktemp)"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" \
  "${selected_prometheus_port}:9090" >"${prometheus_log}" 2>&1 &
prometheus_pid="$!"
prometheus_url="http://127.0.0.1:${selected_prometheus_port}"
wait_http "${prometheus_url}/-/ready"

echo "==> Checking exact loaded alert inventory and clean state"
rules_payload="$(curl -fsS "${prometheus_url}/api/v1/rules?type=alert")"
assert_rules_payload "${rules_payload}"

echo "v0.11.5.1.1 actionable alert inventory, metadata, rule health, and clean inactive-state acceptance passed."

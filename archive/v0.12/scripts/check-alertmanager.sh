#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
MONITORING_APP="${MONITORING_APP:-monitoring}"
ALERTMANAGER_SERVICE="${ALERTMANAGER_SERVICE:-observability-metrics-alertmanager}"
ALERTMANAGER_POD_SELECTOR="${ALERTMANAGER_POD_SELECTOR:-app.kubernetes.io/name=alertmanager}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
ALERTMANAGER_LOCAL_PORT="${ALERTMANAGER_LOCAL_PORT:-19093}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"
TIMEOUT="${TIMEOUT:-180s}"
DISCOVERY_TIMEOUT_SECONDS="${DISCOVERY_TIMEOUT_SECONDS:-60}"
REQUIRE_NO_ALERT_RULES="${REQUIRE_NO_ALERT_RULES:-false}"
ALERTMANAGER_CONFIG_FIXTURE="${ALERTMANAGER_CONFIG_FIXTURE:-}"
ALERTMANAGER_CONFIG_FIXTURE_URL_MODE="${ALERTMANAGER_CONFIG_FIXTURE_URL_MODE:-auto}"

assert_active_alertmanager_config() {
  local config_text="$1"
  local expect_drill="$2"
  local url_mode="$3"
  local marker severity matcher_pattern matcher_count expected_matcher_count
  local url_line_count redacted_url_count

  for marker in \
    'receiver: platform-observation' \
    'group_wait: 30s' \
    'group_interval: 5m' \
    'repeat_interval: 4h' \
    'alert_family' \
    'name: critical-observation' \
    'name: warning-observation'; do
    grep -F -- "${marker}" <<<"${config_text}" >/dev/null || {
      echo "ERROR: active Alertmanager configuration is missing: ${marker}" >&2
      return 1
    }
  done

  # Alertmanager canonicalizes `severity = "critical"` to
  # `severity="critical"` in /api/v2/status. Validate the matcher meaning,
  # not the serializer's optional whitespace. Two occurrences are required:
  # one route matcher and one inhibition matcher.
  expected_matcher_count=2
  if [ "${expect_drill}" = "true" ]; then
    expected_matcher_count=3
    for marker in \
      'receiver: critical-drill-webhook' \
      'receiver: warning-drill-webhook' \
      'name: critical-drill-webhook' \
      'name: warning-drill-webhook' \
      'drill="true"' \
      'alert_family="alert-lifecycle-drill"' \
      'continue: true' \
      'group_wait: 1s' \
      'group_interval: 2s' \
      'send_resolved: true'; do
      grep -F -- "${marker}" <<<"${config_text}" >/dev/null || {
        echo "ERROR: active Alertmanager drill configuration is missing: ${marker}" >&2
        return 1
      }
    done

    [ "$(grep -Fc -- 'webhook_configs:' <<<"${config_text}" || true)" -eq 2 ] || {
      echo "ERROR: active Alertmanager configuration must contain exactly two drill webhook integrations." >&2
      return 1
    }
    [ "$(grep -Fc -- 'send_resolved: true' <<<"${config_text}" || true)" -eq 2 ] || {
      echo "ERROR: both drill webhook integrations must enable resolved delivery." >&2
      return 1
    }

    case "${url_mode}" in
      literal)
        url_line_count="$(grep -Ec -- '^[[:space:]]+(-[[:space:]]+)?url:[[:space:]]+' <<<"${config_text}" || true)"
        if [ "${url_line_count}" -ne 2 ]; then
          echo "ERROR: Alertmanager drill fixture must contain exactly two literal webhook URL lines; found ${url_line_count}." >&2
          return 1
        fi
        for marker in \
          'url: http://alert-lifecycle-drill-sink.observability.svc.cluster.local:8080/critical' \
          'url: http://alert-lifecycle-drill-sink.observability.svc.cluster.local:8080/warning'; do
          grep -F -- "${marker}" <<<"${config_text}" >/dev/null || {
            echo "ERROR: Alertmanager drill fixture is missing the exact internal URL: ${marker}" >&2
            return 1
          }
        done
        ;;
      redacted)
        # Alertmanager protects SecretURL values in /api/v2/status as exactly
        # `url: <secret>`; desired-state and literal fixtures remain exact.
        url_line_count="$(grep -Ec -- '^[[:space:]]+(-[[:space:]]+)?url:[[:space:]]+' <<<"${config_text}" || true)"
        redacted_url_count="$(grep -Ec -- '^[[:space:]]+(-[[:space:]]+)?url:[[:space:]]+<secret>[[:space:]]*$' <<<"${config_text}" || true)"
        if [ "${url_line_count}" -ne 2 ] || [ "${redacted_url_count}" -ne 2 ]; then
          echo "ERROR: active Alertmanager configuration must contain exactly two redacted drill webhook URL lines; found url_lines=${url_line_count}, redacted=${redacted_url_count}." >&2
          grep -En -- '^[[:space:]]+(-[[:space:]]+)?url:' <<<"${config_text}" >&2 || echo "  (none)" >&2
          return 1
        fi
        ;;
      *)
        echo "ERROR: unsupported Alertmanager drill URL validation mode: ${url_mode}" >&2
        return 1
        ;;
    esac
  elif grep -F -- 'webhook_configs:' <<<"${config_text}" >/dev/null; then
    echo "ERROR: webhook integrations are not allowed before the v0.11.5.2.0 drill successor." >&2
    return 1
  fi

  for severity in critical warning; do
    matcher_pattern="^[[:space:]]*-[[:space:]]+severity[[:space:]]*=[[:space:]]*\"${severity}\"[[:space:]]*$"
    matcher_count="$(grep -Ec -- "${matcher_pattern}" <<<"${config_text}" || true)"
    if [ "${matcher_count}" -ne "${expected_matcher_count}" ]; then
      echo "ERROR: active Alertmanager configuration must contain exactly ${expected_matcher_count} ${severity} severity matchers; found ${matcher_count}." >&2
      echo "Observed severity matcher lines:" >&2
      grep -En -- 'severity[[:space:]]*=' <<<"${config_text}" >&2 || echo "  (none)" >&2
      return 1
    fi
  done

  for external_receiver in \
    slack_configs email_configs pagerduty_configs sns_configs \
    opsgenie_configs victorops_configs wechat_configs telegram_configs \
    msteams_configs discord_configs; do
    if grep -F -- "${external_receiver}:" <<<"${config_text}" >/dev/null; then
      echo "ERROR: unexpected external receiver is active: ${external_receiver}" >&2
      return 1
    fi
  done
}

if [ -n "${ALERTMANAGER_CONFIG_FIXTURE}" ]; then
  [ -r "${ALERTMANAGER_CONFIG_FIXTURE}" ] || {
    echo "ERROR: Alertmanager configuration fixture is not readable: ${ALERTMANAGER_CONFIG_FIXTURE}" >&2
    exit 1
  }
  fixture_config="$(<"${ALERTMANAGER_CONFIG_FIXTURE}")"
  fixture_expect_drill=false
  fixture_url_mode="${ALERTMANAGER_CONFIG_FIXTURE_URL_MODE}"
  if grep -F -- 'name: critical-drill-webhook' <<<"${fixture_config}" >/dev/null; then
    fixture_expect_drill=true
  fi
  if [ "${fixture_url_mode}" = "auto" ]; then
    fixture_url_mode=literal
  fi
  assert_active_alertmanager_config "${fixture_config}" "${fixture_expect_drill}" "${fixture_url_mode}"
  echo "Alertmanager active-configuration fixture acceptance passed."
  exit 0
fi

for command_name in curl jq kubectl seq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

alertmanager_pid=""
prometheus_pid=""
alertmanager_log=""
prometheus_log=""

cleanup() {
  for pid in "${prometheus_pid}" "${alertmanager_pid}"; do
    if [ -n "${pid}" ]; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  for log_path in "${prometheus_log}" "${alertmanager_log}"; do
    if [ -n "${log_path}" ]; then
      rm -f -- "${log_path}"
    fi
  done
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
  local deadline=$((SECONDS + DISCOVERY_TIMEOUT_SECONDS))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      return 1
    fi
    sleep 1
  done
}

assert_application() {
  local sync health
  sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${MONITORING_APP}" -o jsonpath='{.status.sync.status}')"
  health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${MONITORING_APP}" -o jsonpath='{.status.health.status}')"
  [ "${sync}" = "Synced" ] || {
    echo "ERROR: Application/${MONITORING_APP} is ${sync:-unknown}, not Synced." >&2
    exit 1
  }
  [ "${health}" = "Healthy" ] || {
    echo "ERROR: Application/${MONITORING_APP} is ${health:-unknown}, not Healthy." >&2
    exit 1
  }
}

start_port_forward() {
  local service="$1"
  local remote_port="$2"
  local requested_port="$3"
  local variable_prefix="$4"
  local selected_port log_path pid

  selected_port="$(find_available_port "${requested_port}")" || {
    echo "ERROR: no local port is available from ${requested_port} through $((requested_port + 100))." >&2
    exit 1
  }
  log_path="$(mktemp)"
  kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward \
    "service/${service}" "${selected_port}:${remote_port}" >"${log_path}" 2>&1 &
  pid="$!"
  printf -v "${variable_prefix}_pid" '%s' "${pid}"
  printf -v "${variable_prefix}_log" '%s' "${log_path}"
  printf -v "${variable_prefix}_port" '%s' "${selected_port}"
}

echo "==> Checking the monitoring Application and Alertmanager runtime"
assert_application
kubectl -n "${OBSERVABILITY_NAMESPACE}" wait \
  --for=condition=Ready pod \
  -l "${ALERTMANAGER_POD_SELECTOR}" \
  --timeout="${TIMEOUT}"

service_type="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${ALERTMANAGER_SERVICE}" -o jsonpath='{.spec.type}')"
[ "${service_type}" = "ClusterIP" ] || {
  echo "ERROR: Service/${ALERTMANAGER_SERVICE} is ${service_type:-unknown}, not ClusterIP." >&2
  exit 1
}

start_port_forward \
  "${ALERTMANAGER_SERVICE}" 9093 "${ALERTMANAGER_LOCAL_PORT}" alertmanager
alertmanager_url="http://127.0.0.1:${alertmanager_port}"
if ! wait_http "${alertmanager_url}/-/ready"; then
  echo "ERROR: Alertmanager did not become ready through ${alertmanager_url}." >&2
  sed -n '1,80p' "${alertmanager_log}" >&2 || true
  exit 1
fi

status_payload="$(curl -fsS "${alertmanager_url}/api/v2/status")"
config_text="$(jq -er '.config.original' <<<"${status_payload}")"
expect_drill=false
if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.5.2.0-alert-lifecycle-drill.json" ]; then
  expect_drill=true
fi
assert_active_alertmanager_config "${config_text}" "${expect_drill}" redacted

echo "==> Checking Prometheus discovery of Alertmanager"
start_port_forward \
  "${PROMETHEUS_SERVICE}" 9090 "${PROMETHEUS_LOCAL_PORT}" prometheus
prometheus_url="http://127.0.0.1:${prometheus_port}"
if ! wait_http "${prometheus_url}/-/ready"; then
  echo "ERROR: Prometheus did not become ready through ${prometheus_url}." >&2
  sed -n '1,80p' "${prometheus_log}" >&2 || true
  exit 1
fi

deadline=$((SECONDS + DISCOVERY_TIMEOUT_SECONDS))
while true; do
  active_payload="$(curl -fsS "${prometheus_url}/api/v1/alertmanagers")"
  if jq -e '
    .status == "success" and
    (.data.activeAlertmanagers | length) >= 1
  ' <<<"${active_payload}" >/dev/null; then
    break
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "ERROR: Prometheus has no active Alertmanager endpoint." >&2
    jq . <<<"${active_payload}" >&2 || true
    exit 1
  fi
  sleep 2
done

deadline=$((SECONDS + DISCOVERY_TIMEOUT_SECONDS))
while true; do
  metric_payload="$(curl -fsS --get "${prometheus_url}/api/v1/query" \
    --data-urlencode 'query=alertmanager_build_info')"
  if jq -e '.status == "success" and (.data.result | length) >= 1' <<<"${metric_payload}" >/dev/null; then
    break
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "ERROR: Prometheus has not scraped alertmanager_build_info." >&2
    jq . <<<"${metric_payload}" >&2 || true
    exit 1
  fi
  sleep 2
done

if [ "${REQUIRE_NO_ALERT_RULES}" = "true" ]; then
  echo "==> Confirming the v0.11.5.0 no-alert-rule boundary"
  rules_payload="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrules -o json)"
  jq -e '[.items[].spec.groups[].rules[] | select(has("alert"))] | length == 0' \
    <<<"${rules_payload}" >/dev/null || {
      echo "ERROR: v0.11.5.0 found an alert rule before the v0.11.5.1 increment." >&2
      exit 1
    }
fi

if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.json" ]; then
  echo "v0.11.5.2.0.1 Alertmanager redacted webhook URL, runtime configuration, and Prometheus discovery acceptance passed."
else
  echo "v0.11.5.0 Alertmanager runtime, configuration, and Prometheus discovery acceptance passed."
fi

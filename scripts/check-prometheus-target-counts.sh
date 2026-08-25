#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${PROFILE:-local}"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19095}"
RULE_MATCH_TIMEOUT_SECONDS="${RULE_MATCH_TIMEOUT_SECONDS:-75}"
RULE_MATCH_RETRY_SECONDS="${RULE_MATCH_RETRY_SECONDS:-5}"
REQUIRE_ALL_TARGETS_UP="${REQUIRE_ALL_TARGETS_UP:-true}"
RECORDED_QUERY_FIXTURE="${RECORDED_QUERY_FIXTURE:-}"
DIRECT_QUERY_FIXTURE="${DIRECT_QUERY_FIXTURE:-}"

# shellcheck source=scripts/lib/observability-live.sh
source "${ROOT_DIR}/scripts/lib/observability-live.sh"

case "${PROFILE}" in
  local)
    monitoring_application="monitoring"
    views_application="observability-views"
    ;;
  aws)
    case "${AWS_ENVIRONMENT}" in
      aws-dev|aws-test|aws-prod) ;;
      *)
        echo "ERROR: AWS_ENVIRONMENT must be aws-dev, aws-test, or aws-prod." >&2
        exit 1
        ;;
    esac
    monitoring_application="monitoring-${AWS_ENVIRONMENT}"
    views_application="observability-views-${AWS_ENVIRONMENT}"
    ;;
  *)
    echo "ERROR: PROFILE must be local or aws, found ${PROFILE}." >&2
    exit 1
    ;;
esac

for command_name in curl jq seq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

normalize_vector() {
  jq -c '
    if .status != "success" or .data.resultType != "vector" then
      error("query did not return a successful vector")
    else
      [.data.result[] | {
        namespace: (.metric.namespace // ""),
        job: (.metric.job // ""),
        value: (.value[1] | tonumber)
      }]
      | sort_by(.namespace, .job)
    end
  '
}

assert_matching_vectors() {
  local recorded_payload="$1"
  local direct_payload="$2"
  local recorded_vector direct_vector series_count nonzero_count

  recorded_vector="$(normalize_vector <<<"${recorded_payload}")" || return 1
  direct_vector="$(normalize_vector <<<"${direct_payload}")" || return 1
  series_count="$(jq 'length' <<<"${direct_vector}")"
  [ "${series_count}" -gt 0 ] || {
    echo "ERROR: the direct target-down query returned no namespace/job series." >&2
    return 1
  }

  if [ "${recorded_vector}" != "${direct_vector}" ]; then
    echo "ERROR: recorded and direct Prometheus target-down vectors do not match." >&2
    echo "Recorded: ${recorded_vector}" >&2
    echo "Direct:   ${direct_vector}" >&2
    return 1
  fi

  if ! jq -e 'all(.[]; (.value >= 0) and (.value == (.value | floor)))' \
    <<<"${recorded_vector}" >/dev/null; then
    echo "ERROR: target-down counts must be non-negative integers." >&2
    return 1
  fi

  nonzero_count="$(jq '[.[] | select(.value > 0)] | length' <<<"${recorded_vector}")"
  if [ "${REQUIRE_ALL_TARGETS_UP}" = "true" ] && [ "${nonzero_count}" -ne 0 ]; then
    echo "ERROR: the clean baseline contains a down Prometheus target." >&2
    jq -c '.[] | select(.value > 0)' <<<"${recorded_vector}" >&2
    return 1
  fi

  echo "PASS: recorded target-down counts match the direct Boolean query for ${series_count} namespace/job series"
}

if [ -n "${RECORDED_QUERY_FIXTURE}" ] || [ -n "${DIRECT_QUERY_FIXTURE}" ]; then
  [ -n "${RECORDED_QUERY_FIXTURE}" ] && [ -n "${DIRECT_QUERY_FIXTURE}" ] || {
    echo "ERROR: both RECORDED_QUERY_FIXTURE and DIRECT_QUERY_FIXTURE are required." >&2
    exit 1
  }
  [ -r "${RECORDED_QUERY_FIXTURE}" ] && [ -r "${DIRECT_QUERY_FIXTURE}" ] || {
    echo "ERROR: target-count query fixture is not readable." >&2
    exit 1
  }
  assert_matching_vectors "$(<"${RECORDED_QUERY_FIXTURE}")" "$(<"${DIRECT_QUERY_FIXTURE}")"
  echo "v0.11.5.1.1 Prometheus target-down query fixture acceptance passed."
  exit 0
fi

command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: required command not found: kubectl" >&2
  exit 1
}

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

echo "==> Checking GitOps Applications and recording-rule ownership"
assert_application "${monitoring_application}"
assert_application "${views_application}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule operator-recording-rules >/dev/null

selected_prometheus_port="$(find_available_port "${PROMETHEUS_LOCAL_PORT}")" || {
  echo "ERROR: no Prometheus port is available from ${PROMETHEUS_LOCAL_PORT} through $((PROMETHEUS_LOCAL_PORT + 100))." >&2
  exit 1
}
prometheus_log="$(mktemp)"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" \
  "${selected_prometheus_port}:9090" >"${prometheus_log}" 2>&1 &
prometheus_pid="$!"
prometheus_url="http://127.0.0.1:${selected_prometheus_port}"

deadline=$((SECONDS + 30))
until curl -fsS "${prometheus_url}/-/ready" >/dev/null 2>&1; do
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "ERROR: timed out waiting for Prometheus readiness." >&2
    sed -n '1,80p' "${prometheus_log}" >&2 || true
    exit 1
  fi
  sleep 1
done

recorded_expression='platform:prometheus_targets_down:count'
direct_expression='sum by (namespace, job) (up == bool 0)'
deadline=$((SECONDS + RULE_MATCH_TIMEOUT_SECONDS))

echo "==> Comparing the recorded vector with the direct Boolean query"
while true; do
  recorded_payload="$(curl -fsS --get "${prometheus_url}/api/v1/query" \
    --data-urlencode "query=${recorded_expression}")"
  direct_payload="$(curl -fsS --get "${prometheus_url}/api/v1/query" \
    --data-urlencode "query=${direct_expression}")"
  if assert_matching_vectors "${recorded_payload}" "${direct_payload}"; then
    break
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "ERROR: target-down recording rule did not converge before the bounded timeout." >&2
    exit 1
  fi
  echo "INFO: waiting ${RULE_MATCH_RETRY_SECONDS}s for the next recording-rule evaluation" >&2
  sleep "${RULE_MATCH_RETRY_SECONDS}"
done

echo "v0.11.5.1.1 Prometheus target-down semantic and clean-baseline acceptance passed."

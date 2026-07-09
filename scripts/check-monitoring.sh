#!/usr/bin/env bash
set -euo pipefail

MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-9090}"
PROMETHEUS_BASE_URL="${PROMETHEUS_BASE_URL:-http://localhost:${PROMETHEUS_LOCAL_PORT}}"
QUERY="${QUERY:-demo_api_requests_total}"
TIMEOUT="${TIMEOUT:-180s}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl
require_cmd curl

if ! kubectl get namespace "$MONITORING_NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: namespace not found: $MONITORING_NAMESPACE" >&2
  exit 1
fi

echo "Checking Prometheus rollout..."
kubectl -n "$MONITORING_NAMESPACE" rollout status deployment/prometheus --timeout="$TIMEOUT"

echo "Checking Prometheus service..."
kubectl -n "$MONITORING_NAMESPACE" get service "$PROMETHEUS_SERVICE"

cat <<EOF_CHECK

Prometheus should be available through port-forward before HTTP checks.
Run this in another terminal if it is not already running:

  kubectl -n ${MONITORING_NAMESPACE} port-forward svc/${PROMETHEUS_SERVICE} ${PROMETHEUS_LOCAL_PORT}:9090

EOF_CHECK

echo "Checking Prometheus readiness endpoint..."
curl -fsS "${PROMETHEUS_BASE_URL}/-/ready" >/dev/null

echo "Querying Prometheus for demo-api metrics..."
RESPONSE="$(curl -fsS --get "${PROMETHEUS_BASE_URL}/api/v1/query" --data-urlencode "query=${QUERY}")"

if printf '%s' "$RESPONSE" | grep -q '"status":"success"' && printf '%s' "$RESPONSE" | grep -q 'demo_api_requests_total'; then
  echo "Prometheus query succeeded: ${QUERY}"
else
  echo "ERROR: Prometheus query did not return expected demo-api metric." >&2
  echo "$RESPONSE" >&2
  exit 1
fi

echo "Monitoring check completed."

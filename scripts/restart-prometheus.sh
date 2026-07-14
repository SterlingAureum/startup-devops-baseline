#!/usr/bin/env bash
set -euo pipefail

MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"

PF_PID=""
PF_LOG=""

cleanup() {
  if [ -n "${PF_PID:-}" ] && kill -0 "$PF_PID" >/dev/null 2>&1; then
    kill "$PF_PID" >/dev/null 2>&1 || true
    wait "$PF_PID" >/dev/null 2>&1 || true
  fi

  if [ -n "${PF_LOG:-}" ] && [ -f "$PF_LOG" ]; then
    rm -f "$PF_LOG"
  fi
}
trap cleanup EXIT

PF_LOG="$(mktemp)"

kubectl -n "${MONITORING_NAMESPACE}" port-forward "svc/${PROMETHEUS_SERVICE}" "${PROMETHEUS_LOCAL_PORT}:9090" >"${PF_LOG}" 2>&1 &
PF_PID="$!"

for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "Reloading Prometheus configuration..."
if curl -fsS -X POST "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/reload" >/dev/null; then
  echo "Prometheus reload requested successfully."
else
  echo "Prometheus reload failed. Falling back to deployment restart..."
  kubectl -n "${MONITORING_NAMESPACE}" rollout restart deployment/prometheus
  kubectl -n "${MONITORING_NAMESPACE}" rollout status deployment/prometheus --timeout=180s
fi

echo "Checking Prometheus targets..."
curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/targets" | grep "demo-api" || true

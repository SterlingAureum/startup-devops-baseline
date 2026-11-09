#!/usr/bin/env bash
set -Eeuo pipefail

MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-observability}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_POD_SELECTOR="${PROMETHEUS_POD_SELECTOR:-app.kubernetes.io/name=prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"
TIMEOUT="${TIMEOUT:-180s}"

for command in kubectl curl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Restarting the Operator-managed Prometheus Pod"
if ! kubectl -n "${MONITORING_NAMESPACE}" get pods \
  -l "${PROMETHEUS_POD_SELECTOR}" --no-headers | grep -q .; then
  echo "Prometheus Pod not found with selector: ${PROMETHEUS_POD_SELECTOR}" >&2
  exit 1
fi

kubectl -n "${MONITORING_NAMESPACE}" delete pod \
  -l "${PROMETHEUS_POD_SELECTOR}" \
  --wait=true

for _ in $(seq 1 30); do
  if kubectl -n "${MONITORING_NAMESPACE}" get pods \
    -l "${PROMETHEUS_POD_SELECTOR}" --no-headers | grep -q .; then
    break
  fi
  sleep 1
done

if ! kubectl -n "${MONITORING_NAMESPACE}" get pods \
  -l "${PROMETHEUS_POD_SELECTOR}" --no-headers | grep -q .; then
  echo "Prometheus replacement Pod was not created." >&2
  exit 1
fi

kubectl -n "${MONITORING_NAMESPACE}" wait \
  --for=condition=Ready pod \
  -l "${PROMETHEUS_POD_SELECTOR}" \
  --timeout="${TIMEOUT}"

PF_LOG="$(mktemp)"
PF_PID=""
cleanup() {
  if [[ -n "${PF_PID}" ]] && kill -0 "${PF_PID}" >/dev/null 2>&1; then
    kill "${PF_PID}" >/dev/null 2>&1 || true
    wait "${PF_PID}" >/dev/null 2>&1 || true
  fi
  rm -f -- "${PF_LOG}"
}
trap cleanup EXIT

kubectl -n "${MONITORING_NAMESPACE}" port-forward \
  "svc/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_LOCAL_PORT}:9090" >"${PF_LOG}" 2>&1 &
PF_PID="$!"

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready" >/dev/null 2>&1; then
    echo "Prometheus restart completed successfully."
    curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/targets" \
      | grep "demo-api" || true
    exit 0
  fi
  sleep 1
done

echo "Prometheus did not become ready through port-forward." >&2
sed -n '1,40p' "${PF_LOG}" >&2
exit 1

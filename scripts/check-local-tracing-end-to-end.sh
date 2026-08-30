#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-240}"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

for command_name in jq kubectl; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || fail "required command not found: ${command_name}"
done

context_name="$(kubectl config current-context 2>/dev/null || true)"
[ -n "${context_name}" ] || fail "kubectl has no current context"
echo "==> Using Kubernetes context ${context_name}"

wait_application() {
  local application_name="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local sync=""
  local health=""
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" \
      -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
    health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" \
      -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
    if [ "${sync}" = "Synced" ] && [ "${health}" = "Healthy" ]; then
      return 0
    fi
    sleep 2
  done
  fail "Application/${application_name} did not become Synced/Healthy; sync=${sync:-unknown} health=${health:-unknown}"
}

echo "==> Checking the declared local tracing Applications"
for application_name in \
  demo-api monitoring logging-loki logging-alloy \
  tracing-otel-collector tracing-tempo; do
  wait_application "${application_name}"
done

echo "==> Checking the stable demo-api Rollout"
kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o json \
  | jq -e '
      .status.phase == "Healthy"
      and .status.readyReplicas == .spec.replicas
      and .status.availableReplicas == .spec.replicas
      and .status.updatedReplicas == .spec.replicas
    ' >/dev/null \
  || fail "Rollout/${ROLLOUT_NAME} is not fully Healthy"

echo "==> Checking the private tracing and correlation Services"
for service_name in \
  observability-otel-collector observability-tempo observability-logs \
  observability-logs-gateway observability-metrics-grafana; do
  kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${service_name}" -o json \
    | jq -e '.spec.type == "ClusterIP" and .spec.clusterIP != "None"' >/dev/null \
    || fail "Service/${service_name} is not a private ClusterIP Service"
done

kubectl -n "${OBSERVABILITY_NAMESPACE}" get networkpolicy \
  observability-otel-collector-cluster-only \
  observability-tempo-cluster-only \
  observability-logs-cluster-only \
  grafana-cluster-only >/dev/null

kubectl get ingress --all-namespaces -o json \
  | jq -e '
      [
        .items[]?.spec.rules[]?.http.paths[]?.backend.service.name,
        .items[]?.spec.defaultBackend.service.name
        | select(. != null)
        | select(. == "observability-otel-collector" or . == "observability-tempo")
      ] | length == 0
    ' >/dev/null \
  || fail "Collector or Tempo is exposed through an Ingress"

echo "==> Real trace-log correlation acceptance run 1 of 2"
"${ROOT_DIR}/scripts/check-local-demo-api-trace-correlation.sh"

echo "==> Real trace-log correlation acceptance run 2 of 2"
"${ROOT_DIR}/scripts/check-local-demo-api-trace-correlation.sh"

echo "v0.11.6.2.3 local minimal tracing closure passed: private runtime, stable Rollout, and two independent real trace-log correlations."

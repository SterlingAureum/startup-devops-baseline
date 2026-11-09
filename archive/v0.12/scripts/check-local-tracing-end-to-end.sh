#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROLLOUT_NAME="${ROLLOUT_NAME:-demo-api}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
APP_CONTAINER="${APP_CONTAINER:-demo-api}"
NEUTRAL_IMAGE_TAG="${NEUTRAL_IMAGE_TAG:-sha-3e50802}"
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
rollout_json="$(kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o json)"
jq -e '
      .status.phase == "Healthy"
      and .status.readyReplicas == .spec.replicas
      and .status.availableReplicas == .spec.replicas
      and .status.updatedReplicas == .spec.replicas
    ' <<<"${rollout_json}" >/dev/null \
  || fail "Rollout/${ROLLOUT_NAME} is not fully Healthy"

echo "==> Checking the deployed demo-api artifact identity and tracing capability"
rollout_image="$(jq -r --arg container "${APP_CONTAINER}" \
  '[.spec.template.spec.containers[] | select(.name == $container)][0].image // empty' \
  <<<"${rollout_json}")"
[ -n "${rollout_image}" ] || fail "Rollout/${ROLLOUT_NAME} has no ${APP_CONTAINER} image"
case "${rollout_image}" in
  *:"${NEUTRAL_IMAGE_TAG}"|*:"${NEUTRAL_IMAGE_TAG}"@*)
    fail "Rollout/${ROLLOUT_NAME} still uses neutral replay image ${NEUTRAL_IMAGE_TAG}; build the exact current source under a unique local tag and redeploy it before tracing acceptance"
    ;;
esac

pods_json="$(kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o json)"
expected_replicas="$(jq -r '.spec.replicas' <<<"${rollout_json}")"
jq -e --argjson expected "${expected_replicas}" --arg container "${APP_CONTAINER}" '
      ([.items[]
        | select(.status.phase == "Running")
        | select(any(.status.containerStatuses[]?; .name == $container and .ready == true))]
       | length) == $expected
    ' <<<"${pods_json}" >/dev/null \
  || fail "the selected demo-api Pods do not match the fully ready Rollout replica count"

unique_image_ids="$(jq -r --arg container "${APP_CONTAINER}" \
  '[.items[]
    | select(.status.phase == "Running")
    | select(any(.status.containerStatuses[]?; .name == $container and .ready == true))
    | .status.containerStatuses[]
    | select(.name == $container)
    | .imageID] | unique | length' \
  <<<"${pods_json}")"
[ "${unique_image_ids}" = "1" ] \
  || fail "ready demo-api Pods do not use one identical runtime imageID"

while IFS= read -r pod_name; do
  kubectl -n "${APP_NAMESPACE}" exec "${pod_name}" -c "${APP_CONTAINER}" -- \
    python -c 'import inspect, os, src.logging_config, src.main, src.server, src.tracing; server=inspect.getsource(src.server.main); main=inspect.getsource(src.main.record_http_metrics); assert "configure_logging()" in server and "configure_tracing()" in server; assert "http_server_span" in main and "emit_log" in main; assert os.environ.get("TRACING_ENABLED", "").lower() == "true"; assert os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").startswith("http://observability-otel-collector.")' \
    >/dev/null \
    || fail "Pod/${pod_name} does not contain or run the accepted structured-logging and tracing implementation; rebuild the exact current source under a unique image tag and redeploy"
done < <(jq -r --arg container "${APP_CONTAINER}" '
  .items[]
  | select(.status.phase == "Running")
  | select(any(.status.containerStatuses[]?; .name == $container and .ready == true))
  | .metadata.name
' <<<"${pods_json}")

echo "PASS: deployed artifact is non-neutral, digest-consistent, and tracing-capable: ${rollout_image}"

echo "==> Reconfirming the stable demo-api Rollout after artifact inspection"
kubectl -n "${APP_NAMESPACE}" get rollout "${ROLLOUT_NAME}" -o json \
  | jq -e '
      .status.phase == "Healthy"
      and .status.readyReplicas == .spec.replicas
      and .status.availableReplicas == .spec.replicas
      and .status.updatedReplicas == .spec.replicas
    ' >/dev/null \
  || fail "Rollout/${ROLLOUT_NAME} changed health during artifact inspection"

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

echo "v0.11.6.2.3.1 local tracing closure passed: verified runtime artifact identity, private runtime, stable Rollout, and two independent real trace-log correlations."

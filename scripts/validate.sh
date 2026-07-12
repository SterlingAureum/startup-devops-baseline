#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
DEMO_APP_NAME="${DEMO_APP_NAME:-demo-api}"
INGRESS_APP_NAME="${INGRESS_APP_NAME:-ingress-nginx}"
INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-ingress-nginx}"
INGRESS_CONTROLLER_DEPLOYMENT="${INGRESS_CONTROLLER_DEPLOYMENT:-ingress-nginx-controller}"
INGRESS_HOST="${INGRESS_HOST:-demo-api.local}"
INGRESS_BASE_URL="${INGRESS_BASE_URL:-http://localhost}"
MONITORING_APP_NAME="${MONITORING_APP_NAME:-monitoring}"
MONITORING_NAMESPACE="${MONITORING_NAMESPACE:-monitoring}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-prometheus}"
PROMETHEUS_QUERY="${PROMETHEUS_QUERY:-demo_api_requests_total}"
PROMETHEUS_HTTP_MODE="${PROMETHEUS_HTTP_MODE:-port-forward}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19090}"
PROMETHEUS_BASE_URL="${PROMETHEUS_BASE_URL:-http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}}"
ARGO_ROLLOUTS_APP_NAME="${ARGO_ROLLOUTS_APP_NAME:-argo-rollouts}"
ARGO_ROLLOUTS_NAMESPACE="${ARGO_ROLLOUTS_NAMESPACE:-argo-rollouts}"
ARGO_ROLLOUTS_CONTROLLER_DEPLOYMENT="${ARGO_ROLLOUTS_CONTROLLER_DEPLOYMENT:-argo-rollouts}"
ROLLOUT_NAME="${ROLLOUT_NAME:-$DEMO_APP_NAME}"
STABLE_SERVICE_NAME="${STABLE_SERVICE_NAME:-demo-api-stable}"
CANARY_SERVICE_NAME="${CANARY_SERVICE_NAME:-demo-api-canary}"
TIMEOUT="${TIMEOUT:-180s}"
SKIP_PROMETHEUS_HTTP="${SKIP_PROMETHEUS_HTTP:-false}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
PROMETHEUS_PF_PID=""
PROMETHEUS_PF_LOG=""

info() { printf 'INFO: %s\n' "$*"; }
pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS: %s\n' "$*"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); printf 'WARN: %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL: %s\n' "$*" >&2; }

cleanup() {
  if [ -n "${PROMETHEUS_PF_PID:-}" ] && kill -0 "$PROMETHEUS_PF_PID" >/dev/null 2>&1; then
    kill "$PROMETHEUS_PF_PID" >/dev/null 2>&1 || true
    wait "$PROMETHEUS_PF_PID" >/dev/null 2>&1 || true
  fi

  if [ -n "${PROMETHEUS_PF_LOG:-}" ] && [ -f "$PROMETHEUS_PF_LOG" ]; then
    rm -f "$PROMETHEUS_PF_LOG"
  fi
}
trap cleanup EXIT

require_cmd() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "required command found: $cmd"
  else
    fail "required command not found: $cmd"
    exit 1
  fi
}

check_namespace() {
  local namespace="$1"
  if kubectl get namespace "$namespace" >/dev/null 2>&1; then
    pass "namespace exists: $namespace"
  else
    fail "namespace not found: $namespace"
    return 1
  fi
}

wait_pods_ready_by_label() {
  local namespace="$1"
  local selector="$2"
  local description="$3"

  if kubectl -n "$namespace" get pods -l "$selector" --no-headers 2>/dev/null | grep -q .; then
    if kubectl -n "$namespace" wait --for=condition=Ready pod -l "$selector" --timeout="$TIMEOUT" >/dev/null 2>&1; then
      pass "$description pods are Ready"
    else
      fail "$description pods are not Ready"
      kubectl -n "$namespace" get pods -l "$selector" || true
      return 1
    fi
  else
    fail "$description pods not found with selector: $selector"
    return 1
  fi
}

wait_deployment_ready() {
  local namespace="$1"
  local deployment="$2"
  local description="$3"

  if kubectl -n "$namespace" get deployment "$deployment" >/dev/null 2>&1; then
    if kubectl -n "$namespace" rollout status deployment "$deployment" --timeout="$TIMEOUT" >/dev/null 2>&1; then
      pass "$description deployment is rolled out"
    else
      fail "$description deployment is not rolled out"
      kubectl -n "$namespace" get deployment "$deployment" || true
      return 1
    fi
  else
    fail "$description deployment not found: $deployment"
    return 1
  fi
}

check_application() {
  local namespace="$1"
  local app_name="$2"

  if ! kubectl -n "$namespace" get application "$app_name" >/dev/null 2>&1; then
    fail "Argo CD application not found: $app_name"
    return 1
  fi

  local sync_status
  local health_status
  sync_status="$(kubectl -n "$namespace" get application "$app_name" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
  health_status="$(kubectl -n "$namespace" get application "$app_name" -o jsonpath='{.status.health.status}' 2>/dev/null || true)"

  if [ "$sync_status" = "Synced" ]; then
    pass "application sync status is Synced: $app_name"
  else
    fail "application sync status is not Synced: $app_name status=$sync_status"
    return 1
  fi

  if [ "$health_status" = "Healthy" ]; then
    pass "application health status is Healthy: $app_name"
  else
    fail "application health status is not Healthy: $app_name status=$health_status"
    return 1
  fi
}

check_application_if_exists() {
  local namespace="$1"
  local app_name="$2"
  local description="$3"

  if kubectl -n "$namespace" get application "$app_name" >/dev/null 2>&1; then
    check_application "$namespace" "$app_name"
  else
    warn "$description application not found: $app_name; skipping"
  fi
}

api_resource_exists() {
  local resource="$1"
  kubectl api-resources --no-headers 2>/dev/null | awk '{print $1}' | grep -qx "$resource"
}

rollout_exists() {
  local namespace="$1"
  local rollout="$2"
  kubectl -n "$namespace" get rollout "$rollout" >/dev/null 2>&1
}

get_rollout_phase() {
  local namespace="$1"
  local rollout="$2"
  kubectl -n "$namespace" get rollout "$rollout" -o jsonpath='{.status.phase}' 2>/dev/null || true
}

wait_rollout_or_deployment_ready() {
  local namespace="$1"
  local name="$2"
  local description="$3"

  if api_resource_exists "rollouts" && rollout_exists "$namespace" "$name"; then
    pass "$description Rollout exists: ${namespace}/${name}"

    if kubectl argo rollouts version >/dev/null 2>&1; then
      if kubectl argo rollouts status "$name" -n "$namespace" --timeout "$TIMEOUT" >/dev/null 2>&1; then
        pass "$description Rollout status is healthy"
        return 0
      fi

      fail "$description Rollout did not become healthy"
      kubectl argo rollouts get rollout "$name" -n "$namespace" || true
      return 1
    fi

    warn "kubectl argo rollouts plugin not found; using kubectl polling fallback"

    local timeout_seconds="${TIMEOUT%s}"
    if ! [[ "$timeout_seconds" =~ ^[0-9]+$ ]]; then
      timeout_seconds=180
    fi

    local elapsed=0
    local phase=""
    while [ "$elapsed" -lt "$timeout_seconds" ]; do
      phase="$(get_rollout_phase "$namespace" "$name")"
      if [ "$phase" = "Healthy" ]; then
        pass "$description Rollout phase is Healthy"
        return 0
      fi

      if [ "$phase" = "Degraded" ]; then
        fail "$description Rollout phase is Degraded"
        kubectl -n "$namespace" describe rollout "$name" || true
        return 1
      fi

      sleep 5
      elapsed=$((elapsed + 5))
    done

    fail "$description Rollout did not reach Healthy phase within ${TIMEOUT}; last phase=${phase:-unknown}"
    kubectl -n "$namespace" get rollout "$name" -o wide || true
    return 1
  fi

  warn "$description Rollout not found; falling back to Deployment check"
  wait_deployment_ready "$namespace" "$name" "$description"
}

check_service_exists() {
  local namespace="$1"
  local service_name="$2"
  local description="$3"

  if kubectl -n "$namespace" get service "$service_name" >/dev/null 2>&1; then
    pass "$description service exists: ${namespace}/${service_name}"
  else
    fail "$description service not found: ${namespace}/${service_name}"
    return 1
  fi
}

get_rollout_nginx_stable_ingress() {
  local namespace="$1"
  local rollout="$2"
  kubectl -n "$namespace" get rollout "$rollout" \
    -o jsonpath='{.spec.strategy.canary.trafficRouting.nginx.stableIngress}' 2>/dev/null || true
}

check_rollout_nginx_traffic_routing() {
  local namespace="$1"
  local rollout="$2"
  local expected_stable_ingress="$3"

  if ! api_resource_exists "rollouts" || ! rollout_exists "$namespace" "$rollout"; then
    warn "Rollout not found; skipping nginx traffic routing check"
    return 0
  fi

  local stable_ingress
  stable_ingress="$(get_rollout_nginx_stable_ingress "$namespace" "$rollout")"

  if [ "$stable_ingress" = "$expected_stable_ingress" ]; then
    pass "Rollout uses nginx traffic routing with stableIngress=${stable_ingress}"
    check_service_exists "$namespace" "$STABLE_SERVICE_NAME" "stable"
    check_service_exists "$namespace" "$CANARY_SERVICE_NAME" "canary"
  elif [ -z "$stable_ingress" ]; then
    warn "Rollout nginx traffic routing is not configured; checking legacy service instead"
    check_service_exists "$namespace" "$DEMO_APP_NAME" "demo-api"
  else
    fail "Rollout nginx traffic routing stableIngress mismatch: expected=${expected_stable_ingress} actual=${stable_ingress}"
    return 1
  fi
}

check_http_endpoint() {
  local path="$1"
  local expected_pattern="$2"
  local description="$3"

  local output
  if output="$(curl -fsS -H "Host: ${INGRESS_HOST}" "${INGRESS_BASE_URL}${path}" 2>/dev/null)"; then
    if printf '%s' "$output" | grep -q "$expected_pattern"; then
      pass "$description endpoint is reachable: $path"
    else
      fail "$description endpoint returned unexpected response: $path output=$output"
      return 1
    fi
  else
    fail "$description endpoint is not reachable: ${INGRESS_BASE_URL}${path} host=${INGRESS_HOST}"
    return 1
  fi
}

port_in_use() {
  local port="$1"

  if command -v ss >/dev/null 2>&1; then
    ss -ltn | awk '{print $4}' | grep -Eq "(^|:|\])${port}$"
    return $?
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi

  return 1
}

find_available_port() {
  local start_port="$1"
  local end_port=$((start_port + 100))
  local port

  for port in $(seq "$start_port" "$end_port"); do
    if ! port_in_use "$port"; then
      printf '%s\n' "$port"
      return 0
    fi
  done

  return 1
}

wait_for_url() {
  local url="$1"
  local attempts="${2:-30}"
  local i

  for i in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  return 1
}

start_prometheus_port_forward() {
  local local_port
  local_port="$(find_available_port "$PROMETHEUS_LOCAL_PORT")" || {
    warn "no available local port found for Prometheus port-forward starting from ${PROMETHEUS_LOCAL_PORT}"
    return 1
  }

  PROMETHEUS_LOCAL_PORT="$local_port"
  PROMETHEUS_BASE_URL="http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}"
  PROMETHEUS_PF_LOG="$(mktemp)"

  kubectl -n "$MONITORING_NAMESPACE" port-forward "svc/${PROMETHEUS_SERVICE}" "${PROMETHEUS_LOCAL_PORT}:9090" >"$PROMETHEUS_PF_LOG" 2>&1 &
  PROMETHEUS_PF_PID="$!"

  if wait_for_url "${PROMETHEUS_BASE_URL}/-/ready" 30; then
    pass "Prometheus port-forward is ready: ${PROMETHEUS_BASE_URL}"
    return 0
  fi

  warn "Prometheus port-forward did not become ready: ${PROMETHEUS_BASE_URL}"
  if [ -f "$PROMETHEUS_PF_LOG" ]; then
    warn "port-forward log: $(tr '\n' ' ' < "$PROMETHEUS_PF_LOG" | sed 's/[[:space:]]\+/ /g')"
  fi
  return 1
}

check_prometheus_http() {
  if [ "$SKIP_PROMETHEUS_HTTP" = "true" ] || [ "$PROMETHEUS_HTTP_MODE" = "skip" ]; then
    warn "skipping Prometheus HTTP checks"
    return 0
  fi

  if [ "$PROMETHEUS_HTTP_MODE" = "port-forward" ]; then
    if ! start_prometheus_port_forward; then
      warn "Prometheus HTTP checks skipped because port-forward failed"
      return 0
    fi
  elif [ "$PROMETHEUS_HTTP_MODE" = "external" ]; then
    warn "using external Prometheus URL: ${PROMETHEUS_BASE_URL}"
  else
    warn "unknown PROMETHEUS_HTTP_MODE=${PROMETHEUS_HTTP_MODE}; expected port-forward, external, or skip"
    return 0
  fi

  if curl -fsS "${PROMETHEUS_BASE_URL}/-/ready" >/dev/null 2>&1; then
    pass "Prometheus readiness endpoint is reachable"
  else
    warn "Prometheus readiness endpoint is not reachable at ${PROMETHEUS_BASE_URL}/-/ready"
    return 0
  fi

  local response
  if response="$(curl -fsS --get "${PROMETHEUS_BASE_URL}/api/v1/query" --data-urlencode "query=${PROMETHEUS_QUERY}" 2>/dev/null)"; then
    if printf '%s' "$response" | grep -q '"status":"success"' && printf '%s' "$response" | grep -q 'demo_api_requests_total'; then
      pass "Prometheus can query demo-api metrics: ${PROMETHEUS_QUERY}"
    else
      warn "Prometheus query succeeded but demo-api metric was not found yet: ${PROMETHEUS_QUERY}"
      warn "Generate demo-api traffic and wait for the next scrape interval."
    fi
  else
    warn "Prometheus query failed at ${PROMETHEUS_BASE_URL}/api/v1/query"
  fi
}

print_section() {
  printf '\n== %s ==\n' "$*"
}

print_section "Startup DevOps Baseline Validation"
info "Argo CD namespace: $ARGOCD_NAMESPACE"
info "Application namespace: $APP_NAMESPACE"
info "Ingress host: $INGRESS_HOST"
info "Ingress base URL: $INGRESS_BASE_URL"
info "Monitoring namespace: $MONITORING_NAMESPACE"
info "Prometheus HTTP mode: $PROMETHEUS_HTTP_MODE"
info "Prometheus local port start: $PROMETHEUS_LOCAL_PORT"
info "Argo Rollouts namespace: $ARGO_ROLLOUTS_NAMESPACE"
info "Timeout: $TIMEOUT"

print_section "Command checks"
require_cmd kubectl
require_cmd curl

print_section "Cluster access"
if kubectl cluster-info >/dev/null 2>&1; then
  pass "kubectl can access the cluster"
else
  fail "kubectl cannot access the cluster"
  exit 1
fi

if kubectl get nodes >/dev/null 2>&1; then
  pass "nodes can be listed"
  kubectl get nodes
else
  fail "failed to list nodes"
  exit 1
fi

print_section "kube-system checks"
check_namespace kube-system
wait_pods_ready_by_label kube-system "k8s-app=kube-proxy" "kube-proxy"
wait_pods_ready_by_label kube-system "k8s-app=kube-dns" "CoreDNS"
wait_pods_ready_by_label kube-system "app=kindnet" "kindnet"

print_section "Argo CD checks"
check_namespace "$ARGOCD_NAMESPACE"
wait_deployment_ready "$ARGOCD_NAMESPACE" argocd-server "argocd-server"
wait_deployment_ready "$ARGOCD_NAMESPACE" argocd-repo-server "argocd-repo-server"
wait_deployment_ready "$ARGOCD_NAMESPACE" argocd-redis "argocd-redis"
check_application "$ARGOCD_NAMESPACE" "$ROOT_APP_NAME"
check_application "$ARGOCD_NAMESPACE" "$DEMO_APP_NAME"
check_application "$ARGOCD_NAMESPACE" "$INGRESS_APP_NAME"
check_application "$ARGOCD_NAMESPACE" "$MONITORING_APP_NAME"
check_application_if_exists "$ARGOCD_NAMESPACE" "$ARGO_ROLLOUTS_APP_NAME" "Argo Rollouts"

print_section "Argo Rollouts controller checks"
if kubectl get namespace "$ARGO_ROLLOUTS_NAMESPACE" >/dev/null 2>&1; then
  pass "namespace exists: $ARGO_ROLLOUTS_NAMESPACE"
  if kubectl -n "$ARGO_ROLLOUTS_NAMESPACE" get deployment "$ARGO_ROLLOUTS_CONTROLLER_DEPLOYMENT" >/dev/null 2>&1; then
    wait_deployment_ready "$ARGO_ROLLOUTS_NAMESPACE" "$ARGO_ROLLOUTS_CONTROLLER_DEPLOYMENT" "argo-rollouts controller"
  else
    warn "argo-rollouts controller deployment not found; expected only before v0.3"
  fi
else
  warn "namespace not found: $ARGO_ROLLOUTS_NAMESPACE; expected only before v0.3"
fi

print_section "demo-api workload checks"
check_namespace "$APP_NAMESPACE"
wait_rollout_or_deployment_ready "$APP_NAMESPACE" "$ROLLOUT_NAME" "$DEMO_APP_NAME"

check_rollout_nginx_traffic_routing "$APP_NAMESPACE" "$ROLLOUT_NAME" "$DEMO_APP_NAME"

print_section "Ingress checks"
check_namespace "$INGRESS_NAMESPACE"
wait_deployment_ready "$INGRESS_NAMESPACE" "$INGRESS_CONTROLLER_DEPLOYMENT" "ingress-nginx controller"

if kubectl -n "$APP_NAMESPACE" get ingress "$DEMO_APP_NAME" >/dev/null 2>&1; then
  pass "ingress exists: ${APP_NAMESPACE}/${DEMO_APP_NAME}"
  kubectl -n "$APP_NAMESPACE" get ingress "$DEMO_APP_NAME"
else
  fail "ingress not found: ${APP_NAMESPACE}/${DEMO_APP_NAME}"
  exit 1
fi

print_section "HTTP checks through ingress"
check_http_endpoint "/health" '"status":"ok"' "health"
check_http_endpoint "/ready" '"status":"ready"' "readiness"
check_http_endpoint "/version" '"name":"demo-api"' "version"
check_http_endpoint "/metrics" "demo_api_requests_total" "metrics"

print_section "Monitoring checks"
check_namespace "$MONITORING_NAMESPACE"
wait_deployment_ready "$MONITORING_NAMESPACE" prometheus "Prometheus"

if kubectl -n "$MONITORING_NAMESPACE" get service "$PROMETHEUS_SERVICE" >/dev/null 2>&1; then
  pass "service exists: ${MONITORING_NAMESPACE}/${PROMETHEUS_SERVICE}"
else
  fail "service not found: ${MONITORING_NAMESPACE}/${PROMETHEUS_SERVICE}"
  exit 1
fi

check_prometheus_http

print_section "Summary"
printf 'PASS: %s\n' "$PASS_COUNT"
printf 'WARN: %s\n' "$WARN_COUNT"
printf 'FAIL: %s\n' "$FAIL_COUNT"

if [ "$FAIL_COUNT" -eq 0 ]; then
  echo "Validation completed successfully."
  exit 0
fi

echo "Validation completed with failures." >&2
exit 1

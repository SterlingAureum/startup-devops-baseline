#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
DEMO_APP_NAME="${DEMO_APP_NAME:-demo-api}"
INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-ingress-nginx}"
INGRESS_CONTROLLER_DEPLOYMENT="${INGRESS_CONTROLLER_DEPLOYMENT:-ingress-nginx-controller}"
INGRESS_HOST="${INGRESS_HOST:-demo-api.local}"
INGRESS_BASE_URL="${INGRESS_BASE_URL:-http://localhost}"
TIMEOUT="${TIMEOUT:-180s}"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

info() {
  printf 'INFO: %s\n' "$*"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf 'PASS: %s\n' "$*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf 'WARN: %s\n' "$*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf 'FAIL: %s\n' "$*" >&2
}

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

print_section() {
  printf '\n== %s ==\n' "$*"
}

print_section "Startup DevOps Baseline Validation"
info "Argo CD namespace: $ARGOCD_NAMESPACE"
info "Application namespace: $APP_NAMESPACE"
info "Ingress host: $INGRESS_HOST"
info "Ingress base URL: $INGRESS_BASE_URL"
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

print_section "demo-api workload checks"
check_namespace "$APP_NAMESPACE"
wait_deployment_ready "$APP_NAMESPACE" "$DEMO_APP_NAME" "$DEMO_APP_NAME"

if kubectl -n "$APP_NAMESPACE" get service "$DEMO_APP_NAME" >/dev/null 2>&1; then
  pass "service exists: ${APP_NAMESPACE}/${DEMO_APP_NAME}"
else
  fail "service not found: ${APP_NAMESPACE}/${DEMO_APP_NAME}"
  exit 1
fi

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

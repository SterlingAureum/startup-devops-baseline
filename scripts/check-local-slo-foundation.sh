#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-observability-metrics-grafana}"
GRAFANA_SECRET="${GRAFANA_SECRET:-observability-metrics-grafana}"
FEATURE_REVISION="${FEATURE_REVISION:-feature/v0.11-observability-sre-baseline}"
REPOSITORY_URL="${REPOSITORY_URL:-}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"
GRAFANA_DASHBOARD_FIXTURE="${GRAFANA_DASHBOARD_FIXTURE:-}"
EXPECTED_SLO_DASHBOARD_PANEL_COUNT="${EXPECTED_SLO_DASHBOARD_PANEL_COUNT:-}"
WORK_DIR="$(mktemp -d)"
APP_PF_PID=""
PROMETHEUS_PF_PID=""
GRAFANA_PF_PID=""
FIXTURE_MODE=false

if [ -z "${EXPECTED_SLO_DASHBOARD_PANEL_COUNT}" ]; then
  if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json" ]; then
    EXPECTED_SLO_DASHBOARD_PANEL_COUNT=6
  else
    EXPECTED_SLO_DASHBOARD_PANEL_COUNT=4
  fi
fi

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cleanup() {
  local status="$?"
  local pid
  if [ "${status}" -ne 0 ] && [ "${FIXTURE_MODE}" = false ]; then
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule \
      demo-api-slo-recording-rules -o yaml >&2 || true
    kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o wide >&2 || true
    for log_file in "${WORK_DIR}"/*-port-forward.log; do
      [ -s "${log_file}" ] && cat "${log_file}" >&2 || true
    done
  fi
  for pid in "${GRAFANA_PF_PID}" "${PROMETHEUS_PF_PID}" "${APP_PF_PID}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  rm -rf -- "${WORK_DIR}"
  exit "${status}"
}
trap cleanup EXIT

assert_slo_dashboard_payload() {
  local payload_file="$1"
  local actual_panel_count
  jq -e '.dashboard.uid == "startup-devops-demo-api-slo"' "${payload_file}" >/dev/null \
    || fail "Grafana SLO Dashboard UID is missing or unexpected"
  jq -e '.dashboard.editable == false' "${payload_file}" >/dev/null \
    || fail "Grafana SLO Dashboard is editable"
  actual_panel_count="$(jq -r '.dashboard.panels | if type == "array" then length else -1 end' "${payload_file}")"
  [ "${actual_panel_count}" = "${EXPECTED_SLO_DASHBOARD_PANEL_COUNT}" ] \
    || fail "Grafana SLO Dashboard panel count mismatch: expected ${EXPECTED_SLO_DASHBOARD_PANEL_COUNT}, found ${actual_panel_count}"
}

if [ -n "${GRAFANA_DASHBOARD_FIXTURE}" ]; then
  FIXTURE_MODE=true
  command -v jq >/dev/null 2>&1 || fail "required command not found: jq"
  [ -r "${GRAFANA_DASHBOARD_FIXTURE}" ] \
    || fail "Grafana Dashboard fixture is not readable: ${GRAFANA_DASHBOARD_FIXTURE}"
  assert_slo_dashboard_payload "${GRAFANA_DASHBOARD_FIXTURE}"
  echo "v0.11.7.1.2 Grafana SLO Dashboard API fixture acceptance passed."
  exit 0
fi

for command_name in awk base64 curl git jq kubectl python3 seq; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || fail "required command not found: ${command_name}"
done

if [ -z "${REPOSITORY_URL}" ]; then
  REPOSITORY_URL="$(git -C "${ROOT_DIR}" remote get-url origin)"
fi

print_revision_recovery() {
  local rollout_image=""
  local image_repository=""
  local image_tag=""
  local application_version=""
  echo "==> GitOps revision diagnostics" >&2
  kubectl -n "${ARGOCD_NAMESPACE}" get application \
    startup-devops-root namespace-guardrails demo-api observability-views \
    -o custom-columns='NAME:.metadata.name,TARGET:.spec.source.targetRevision,SYNC:.status.sync.status,HEALTH:.status.health.status,REVISION:.status.sync.revision' \
    >&2 || true
  rollout_image="$(kubectl -n "${APP_NAMESPACE}" get rollout demo-api \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="demo-api")].image}' 2>/dev/null || true)"
  application_version="$(kubectl -n "${APP_NAMESPACE}" get rollout demo-api \
    -o jsonpath='{.spec.template.spec.containers[?(@.name=="demo-api")].env[?(@.name=="APP_VERSION")].value}' 2>/dev/null || true)"
  if [ -n "${rollout_image}" ] && [[ "${rollout_image}" == *:* ]]; then
    image_repository="${rollout_image%:*}"
    image_tag="${rollout_image##*:}"
  fi
  if [ -n "${image_repository}" ] && [ -n "${image_tag}" ] && [ -n "${application_version}" ]; then
    cat >&2 <<EOF
Reuse the already accepted image while advancing the immutable feature Root:
  TARGET_REVISION=${FEATURE_REVISION} \\
  IMAGE_REPOSITORY=${image_repository} \\
  IMAGE_TAG=${image_tag} \\
  APPLICATION_VERSION=${application_version} \\
    ./scripts/deploy-local-feature-gitops.sh
EOF
  else
    echo "Unable to derive the current demo-api image parameters; inspect Rollout/demo-api before redeploying the feature Root." >&2
  fi
}

assert_revision_equals() {
  local actual="$1"
  local expected="$2"
  local description="$3"
  if [ "${actual}" != "${expected}" ]; then
    echo "ERROR: ${description}: expected ${expected}, found ${actual:-<empty>}" >&2
    print_revision_recovery
    exit 1
  fi
}

echo "==> Checking immutable feature Root and child revision alignment"
local_head="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
remote_head="$(git ls-remote "${REPOSITORY_URL}" "refs/heads/${FEATURE_REVISION}" \
  | awk 'NR == 1 {print $1}')"
[ -n "${remote_head}" ] \
  || fail "remote feature branch is unavailable: ${FEATURE_REVISION}"
assert_revision_equals "${local_head}" "${remote_head}" "local HEAD and remote feature HEAD"

for application_name in startup-devops-root namespace-guardrails demo-api observability-views; do
  target_revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" \
    -o jsonpath='{.spec.source.targetRevision}')"
  assert_revision_equals "${target_revision}" "${remote_head}" \
    "Application/${application_name} targetRevision"
  sync_revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" \
    -o jsonpath='{.status.sync.revision}')"
  assert_revision_equals "${sync_revision}" "${remote_head}" \
    "Application/${application_name} status revision"
done

root_child_revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application startup-devops-root \
  -o jsonpath='{.spec.source.helm.parameters[?(@.name=="git.targetRevision")].value}')"
assert_revision_equals "${root_child_revision}" "${remote_head}" \
  "Application/startup-devops-root git.targetRevision parameter"

free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

wait_http() {
  local url="$1"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    [ "${SECONDS}" -lt "${deadline}" ] || fail "timed out waiting for ${url}"
    sleep 1
  done
}

assert_application() {
  local name="$1"
  kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o json \
    | jq -e '.status.sync.status == "Synced" and .status.health.status == "Healthy"' \
      >/dev/null || fail "Application/${name} is not Synced and Healthy"
}

query_nonempty() {
  local expression="$1"
  local description="$2"
  local output="${WORK_DIR}/query-$(printf '%s' "${description}" | tr -cs '[:alnum:]' '-').json"
  curl -fsS --get "http://127.0.0.1:${prometheus_port}/api/v1/query" \
    --data-urlencode "query=${expression}" >"${output}"
  jq -e '.status == "success" and (.data.result | length) > 0' "${output}" >/dev/null \
    || fail "${description} returned no series: ${expression}"
}

query_ratio_range() {
  local expression="$1"
  local description="$2"
  local output="${WORK_DIR}/ratio-$(printf '%s' "${description}" | tr -cs '[:alnum:]' '-').json"
  curl -fsS --get "http://127.0.0.1:${prometheus_port}/api/v1/query" \
    --data-urlencode "query=${expression}" >"${output}"
  jq -e '
    .status == "success"
    and (.data.result | length) > 0
    and all(.data.result[]; (.value[1] | tonumber) >= 0 and (.value[1] | tonumber) <= 1)
  ' "${output}" >/dev/null || fail "${description} is absent or outside [0,1]"
}

echo "==> Checking GitOps ownership and SLO resources"
assert_application monitoring
assert_application observability-views
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule \
  demo-api-slo-recording-rules >/dev/null
kubectl -n "${OBSERVABILITY_NAMESPACE}" get configmap \
  observability-dashboard-slo-overview -o json \
  | jq -e '.metadata.labels.grafana_dashboard == "1"' >/dev/null \
  || fail "SLO Dashboard ConfigMap is not provisioned for Grafana"

echo "==> Generating bounded eligible GET /version traffic"
app_port="$(free_port)"
kubectl -n "${APP_NAMESPACE}" port-forward service/demo-api-stable \
  "${app_port}:80" >"${WORK_DIR}/app-port-forward.log" 2>&1 &
APP_PF_PID="$!"
wait_http "http://127.0.0.1:${app_port}/version"
for _ in $(seq 1 12); do
  curl -fsS "http://127.0.0.1:${app_port}/version" >/dev/null
done

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for scrape and SLO evaluation"
sleep "${RULE_WARMUP_SECONDS}"

prometheus_port="$(free_port)"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${PROMETHEUS_SERVICE}" \
  "${prometheus_port}:9090" >"${WORK_DIR}/prometheus-port-forward.log" 2>&1 &
PROMETHEUS_PF_PID="$!"
wait_http "http://127.0.0.1:${prometheus_port}/-/ready"

rules_payload="$(curl -fsS "http://127.0.0.1:${prometheus_port}/api/v1/rules?type=record")"
for rule_name in \
  demo_api:slo_http_requests:rate30d \
  demo_api:slo_http_5xx:rate30d \
  demo_api:slo_availability:ratio30d \
  demo_api:slo_availability_error_budget_remaining:ratio30d \
  demo_api:slo_latency_requests:rate30d \
  demo_api:slo_latency_good:rate30d \
  demo_api:slo_latency:ratio30d \
  demo_api:slo_latency_error_budget_remaining:ratio30d; do
  jq -e --arg name "${rule_name}" \
    '[.data.groups[].rules[] | select(.name == $name and .type == "recording")] | length == 1' \
    <<<"${rules_payload}" >/dev/null || fail "Prometheus did not load ${rule_name}"
done

query_nonempty 'demo_api:slo_http_requests:rate30d' "eligible request rate"
query_nonempty 'demo_api:slo_latency_requests:rate30d' "latency request rate"
query_ratio_range 'demo_api:slo_availability:ratio30d' "availability SLO"
query_ratio_range 'demo_api:slo_availability_error_budget_remaining:ratio30d' "availability budget"
query_ratio_range 'demo_api:slo_latency:ratio30d' "latency SLO"
query_ratio_range 'demo_api:slo_latency_error_budget_remaining:ratio30d' "latency budget"

echo "==> Checking the immutable SLO Dashboard through Grafana"
grafana_port="$(free_port)"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${GRAFANA_SERVICE}" \
  "${grafana_port}:80" >"${WORK_DIR}/grafana-port-forward.log" 2>&1 &
GRAFANA_PF_PID="$!"
wait_http "http://127.0.0.1:${grafana_port}/api/health"
admin_user="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" -o jsonpath='{.data.admin-user}' | base64 -d)"
admin_password="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" -o jsonpath='{.data.admin-password}' | base64 -d)"
grafana_dashboard_payload="${WORK_DIR}/grafana-slo-dashboard.json"
grafana_http_status="$(curl -sS -u "${admin_user}:${admin_password}" \
  -o "${grafana_dashboard_payload}" -w '%{http_code}' \
  "http://127.0.0.1:${grafana_port}/api/dashboards/uid/startup-devops-demo-api-slo")"
if [ "${grafana_http_status}" != "200" ]; then
  echo "Grafana response body:" >&2
  sed -n '1,120p' "${grafana_dashboard_payload}" >&2 || true
  fail "Grafana SLO Dashboard API returned HTTP ${grafana_http_status}"
fi
assert_slo_dashboard_payload "${grafana_dashboard_payload}"

echo "v0.11.7.0 local demo-api SLI, 30-day SLO formulas, error-budget rules, and Grafana Dashboard acceptance passed."

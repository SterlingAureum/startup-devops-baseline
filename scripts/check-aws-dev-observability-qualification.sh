#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_AWS_ACCOUNT_ID="${EXPECTED_AWS_ACCOUNT_ID:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
EXPECTED_CONTROL_PLANE_SHA="${EXPECTED_CONTROL_PLANE_SHA:-}"
EXPECTED_GIT_TARGET_REVISION="${EXPECTED_GIT_TARGET_REVISION:-main}"
EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION:-}"
MONITORING_CHART_VERSION="${MONITORING_CHART_VERSION:-88.5.0}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WORK_DIR="$(mktemp -d)"
KUBE_CONTEXT="aws-dev-unavailable"
PORT_FORWARD_PID=""

cleanup() {
  if [ -n "${PORT_FORWARD_PID}" ]; then
    kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
    wait "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in aws curl git jq kubectl python3; do
  command -v "${command}" >/dev/null 2>&1 || { echo "Required command not found: ${command}" >&2; exit 1; }
done

[[ "${EXPECTED_AWS_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]] || { echo "EXPECTED_AWS_ACCOUNT_ID must contain 12 digits." >&2; exit 1; }
[[ "${EXPECTED_CONTROL_PLANE_SHA}" =~ ^[0-9a-f]{40}$ ]] || { echo "EXPECTED_CONTROL_PLANE_SHA must be a full lowercase commit SHA." >&2; exit 1; }
[[ "${EXPECTED_GIT_TARGET_REVISION}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] \
  || { echo "EXPECTED_GIT_TARGET_REVISION contains unsupported characters." >&2; exit 1; }
case "${EXPECTED_GIT_TARGET_REVISION}" in
  HEAD|head|latest|Latest) echo "Moving alias is not an accepted Git target revision." >&2; exit 1 ;;
esac
[ -n "${EXPECTED_APPLICATION_VERSION}" ] || { echo "EXPECTED_APPLICATION_VERSION is required." >&2; exit 1; }

if [ -z "${OUTPUT_FILE}" ]; then
  OUTPUT_FILE="${ROOT_DIR}/artifacts/observability-qualification/aws-dev/${EXPECTED_CONTROL_PLANE_SHA}-$(date -u +%Y%m%dT%H%M%SZ).json"
fi

write_result() {
  local status="$1"
  local reason="$2"
  local facts_file="${3:-}"
  local arguments=(
    --status "${status}"
    --reason "${reason}"
    --started-at "${STARTED_AT}"
    --aws-account-id "${EXPECTED_AWS_ACCOUNT_ID}"
    --aws-region "${AWS_REGION}"
    --cluster-name "${CLUSTER_NAME}"
    --kube-context "${KUBE_CONTEXT}"
    --repository-commit "$(git -C "${ROOT_DIR}" rev-parse HEAD)"
    --target-revision "${EXPECTED_CONTROL_PLANE_SHA}"
    --application-version "${EXPECTED_APPLICATION_VERSION}"
    --output "${OUTPUT_FILE}"
  )
  [ -z "${facts_file}" ] || arguments+=(--runtime-facts "${facts_file}")
  "${ROOT_DIR}/scripts/write-environment-observability-qualification.py" "${arguments[@]}" >/dev/null
  echo "status=${status}"
  echo "reason=${reason}"
  echo "evidence=${OUTPUT_FILE}"
}

fail_with_evidence() {
  write_result failed "$1"
  exit 1
}

QUALIFICATION_ENVIRONMENT=aws-dev QUALIFICATION_ACTION=observe \
  "${ROOT_DIR}/scripts/check-environment-observability-qualification-policy.sh" >/dev/null

LOCAL_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
[ "${LOCAL_SHA}" = "${EXPECTED_CONTROL_PLANE_SHA}" ] || fail_with_evidence repository_commit_mismatch

CALLER_ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
  || fail_with_evidence aws_identity_unavailable
[ "${CALLER_ACCOUNT}" = "${EXPECTED_AWS_ACCOUNT_ID}" ] || fail_with_evidence aws_account_mismatch

set +e
aws eks describe-cluster --region "${AWS_REGION}" --name "${CLUSTER_NAME}" \
  >"${WORK_DIR}/cluster.json" 2>"${WORK_DIR}/cluster.err"
describe_status=$?
set -e
if ((describe_status != 0)); then
  if grep -Eq 'ResourceNotFoundException|No cluster found' "${WORK_DIR}/cluster.err"; then
    write_result waiting-runtime environment_absent
    exit 2
  fi
  fail_with_evidence eks_discovery_failed
fi
jq -e --arg name "${CLUSTER_NAME}" --arg region "${AWS_REGION}" '
  .cluster.name == $name and .cluster.status == "ACTIVE" and
  (.cluster.arn | contains(":" + $region + ":"))
' "${WORK_DIR}/cluster.json" >/dev/null || fail_with_evidence eks_identity_mismatch

export KUBECONFIG="${WORK_DIR}/kubeconfig"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}" --kubeconfig "${KUBECONFIG}" >/dev/null \
  || fail_with_evidence kubeconfig_failed
KUBE_CONTEXT="$(kubectl config current-context)"
kubectl --request-timeout=15s get --raw=/readyz >/dev/null 2>&1 || fail_with_evidence endpoint_unreachable

for check in \
  "get pods -n observability" \
  "get prometheusrules.monitoring.coreos.com -n observability" \
  "get applications.argoproj.io -n argocd"; do
  read -r -a args <<<"${check}"
  [ "$(kubectl auth can-i "${args[@]}")" = yes ] || fail_with_evidence rbac_read_missing
done
[ "$(kubectl auth can-i create pods/portforward -n observability)" = yes ] || fail_with_evidence rbac_portforward_missing
for denied in \
  "get secrets -n observability" \
  "create pods/exec -n observability" \
  "patch deployments.apps -n observability" \
  "delete pods -n observability"; do
  read -r -a args <<<"${denied}"
  [ "$(kubectl auth can-i "${args[@]}")" = no ] || fail_with_evidence rbac_boundary_failed
done

GIT_APPLICATIONS=(
  application-admission-policies-aws-dev
  data-platform-network-policy-aws-dev
  demo-api-aws-dev
  external-secrets-startup-apps
  namespace-guardrails-aws-dev
  observability-views-aws-dev
  postgresql-baseline
  runtime-qualification-rbac-aws-dev
  startup-apps-network-policy-aws-dev
)
for application in "${GIT_APPLICATIONS[@]}"; do
  kubectl -n argocd get application "${application}" -o json >"${WORK_DIR}/${application}.json" \
    || fail_with_evidence argocd_application_missing
  jq -e --arg source_revision "${EXPECTED_GIT_TARGET_REVISION}" --arg revision "${EXPECTED_CONTROL_PLANE_SHA}" '
    .spec.source.targetRevision == $source_revision and
    .status.sync.status == "Synced" and .status.health.status == "Healthy" and
    .status.sync.revision == $revision
  ' "${WORK_DIR}/${application}.json" >/dev/null || fail_with_evidence argocd_git_revision_mismatch
done
kubectl -n argocd get application monitoring-aws-dev -o json >"${WORK_DIR}/monitoring.json" \
  || fail_with_evidence monitoring_application_missing
jq -e --arg version "${MONITORING_CHART_VERSION}" '
  .spec.source.chart == "kube-prometheus-stack" and
  .spec.source.targetRevision == $version and
  .status.sync.status == "Synced" and .status.health.status == "Healthy"
' "${WORK_DIR}/monitoring.json" >/dev/null || fail_with_evidence monitoring_chart_mismatch

kubectl -n startup-apps get deployment demo-api -o json >"${WORK_DIR}/demo-api.json" \
  || fail_with_evidence demo_api_missing
jq -e --arg version "${EXPECTED_APPLICATION_VERSION}" '
  .metadata.annotations["platform.startup.dev/application-version"] == $version and
  .status.observedGeneration == .metadata.generation and
  .status.readyReplicas == .spec.replicas and
  .status.updatedReplicas == .spec.replicas and
  .status.availableReplicas == .spec.replicas
' "${WORK_DIR}/demo-api.json" >/dev/null || fail_with_evidence demo_api_identity_or_health_failed

kubectl -n observability get pods -o json >"${WORK_DIR}/observability-pods.json" \
  || fail_with_evidence monitoring_pods_unavailable
jq -e '
  [.items[] | select(.status.phase != "Succeeded") |
    ([.status.containerStatuses[]? | .ready] | length > 0 and all)] |
  length > 0 and all
' "${WORK_DIR}/observability-pods.json" >/dev/null || fail_with_evidence monitoring_workload_unhealthy

free_port() {
  python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

start_forward() {
  local service="$1" remote_port="$2" log_file="$3"
  FORWARD_PORT="$(free_port)"
  kubectl -n observability port-forward "service/${service}" "${FORWARD_PORT}:${remote_port}" >"${log_file}" 2>&1 &
  PORT_FORWARD_PID=$!
  for _ in $(seq 1 30); do
    kill -0 "${PORT_FORWARD_PID}" >/dev/null 2>&1 || return 1
    curl -fsS "http://127.0.0.1:${FORWARD_PORT}/-/ready" >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

start_forward observability-metrics-prometheus 9090 "${WORK_DIR}/prometheus-forward.log" \
  || fail_with_evidence prometheus_unreachable
PROMETHEUS_PORT="${FORWARD_PORT}"
curl -fsS "http://127.0.0.1:${PROMETHEUS_PORT}/api/v1/targets" >"${WORK_DIR}/targets.json" \
  || fail_with_evidence prometheus_targets_failed
jq -e '
  [.data.activeTargets[] | select(.labels.job == "demo-api" and .health == "up")] | length > 0
' "${WORK_DIR}/targets.json" >/dev/null || fail_with_evidence demo_api_target_not_up
curl -fsS "http://127.0.0.1:${PROMETHEUS_PORT}/api/v1/rules" >"${WORK_DIR}/rules.json" \
  || fail_with_evidence prometheus_rules_failed
for rule in \
  demo_api:slo_availability:ratio30d \
  demo_api:slo_latency:ratio30d \
  demo_api:slo_availability_burn_rate:ratio1h \
  demo_api:slo_latency_burn_rate:ratio1h \
  DemoApiAvailabilityErrorBudgetFastBurn \
  DemoApiLatencyErrorBudgetFastBurn \
  PrometheusTargetDown; do
  jq -e --arg rule "${rule}" '[.data.groups[].rules[] | select(.name == $rule)] | length == 1' \
    "${WORK_DIR}/rules.json" >/dev/null || fail_with_evidence prometheus_rule_inventory_failed
done
curl -fsS --get "http://127.0.0.1:${PROMETHEUS_PORT}/api/v1/query" \
  --data-urlencode 'query=demo_api:slo_http_requests:rate30d{deployment_environment_name="aws-dev"}' \
  >"${WORK_DIR}/slo-query.json" || fail_with_evidence slo_query_failed
SLO_STATUS="supported-not-verified"
if jq -e '.status == "success" and (.data.result | length > 0)' "${WORK_DIR}/slo-query.json" >/dev/null; then
  SLO_STATUS="supported-verified"
else
  jq -e '.status == "success"' "${WORK_DIR}/slo-query.json" >/dev/null || fail_with_evidence slo_query_failed
fi
kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
wait "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
PORT_FORWARD_PID=""

kubectl -n observability get configmaps -l grafana_dashboard=1 -o json >"${WORK_DIR}/dashboards.json" \
  || fail_with_evidence grafana_dashboard_discovery_failed
jq -e '[.items[].metadata.name] | sort == [
  "observability-dashboard-capacity-overview",
  "observability-dashboard-data-overview",
  "observability-dashboard-delivery-overview",
  "observability-dashboard-platform-overview",
  "observability-dashboard-service-overview",
  "observability-dashboard-slo-overview"
]' "${WORK_DIR}/dashboards.json" >/dev/null || fail_with_evidence grafana_dashboard_inventory_failed

start_forward observability-metrics-alertmanager 9093 "${WORK_DIR}/alertmanager-forward.log" \
  || fail_with_evidence alertmanager_unreachable
kill "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
wait "${PORT_FORWARD_PID}" >/dev/null 2>&1 || true
PORT_FORWARD_PID=""

if kubectl -n observability get deployment,statefulset,daemonset,service -o name | grep -Eiq '(loki|alloy|tempo|otel-collector|opentelemetry)'; then
  fail_with_evidence undeclared_logging_or_tracing_runtime
fi

jq -n --arg slo_status "${SLO_STATUS}" --arg git_target_revision "${EXPECTED_GIT_TARGET_REVISION}" '
{
  capabilities: {
    metrics: {status: "supported-verified", evidenceCheckIds: ["prometheus.ready", "prometheus.demo-api-target"]},
    dashboards: {status: "supported-verified", evidenceCheckIds: ["grafana.dashboard-configmaps"]},
    alerts: {status: "supported-verified", evidenceCheckIds: ["prometheus.rule-inventory", "alertmanager.ready"]},
    logs: {status: "not-deployed", evidenceCheckIds: ["logs.absent"]},
    traces: {status: "not-deployed", evidenceCheckIds: ["traces.absent"]},
    slo: {status: $slo_status, evidenceCheckIds: ["prometheus.rule-inventory", "slo.read-only-query"]},
    progressiveDeliveryTelemetry: {status: "not-applicable", evidenceCheckIds: ["demo-api.deployment"]}
  },
  checks: [
    {id: "aws.identity", outcome: "passed", observedValue: "exact-account-region", diagnostic: null},
    {id: "eks.cluster", outcome: "passed", observedValue: "ACTIVE", diagnostic: null},
    {id: "rbac.read-only", outcome: "passed", observedValue: "bounded-observe-and-portforward", diagnostic: null},
    {id: "argocd.git-revisions", outcome: "passed", observedValue: $git_target_revision, diagnostic: null},
    {id: "argocd.monitoring-chart", outcome: "passed", observedValue: "88.5.0", diagnostic: null},
    {id: "demo-api.deployment", outcome: "passed", observedValue: "ready-exact-version", diagnostic: null},
    {id: "monitoring.workloads", outcome: "passed", observedValue: "ready", diagnostic: null},
    {id: "prometheus.ready", outcome: "passed", observedValue: true, diagnostic: null},
    {id: "prometheus.demo-api-target", outcome: "passed", observedValue: "up", diagnostic: null},
    {id: "prometheus.rule-inventory", outcome: "passed", observedValue: "required-rules-present", diagnostic: null},
    {id: "slo.read-only-query", outcome: "passed", observedValue: $slo_status, diagnostic: null},
    {id: "grafana.dashboard-configmaps", outcome: "passed", observedValue: 6, diagnostic: null},
    {id: "alertmanager.ready", outcome: "passed", observedValue: true, diagnostic: null},
    {id: "logs.absent", outcome: "passed", observedValue: "not-deployed", diagnostic: null},
    {id: "traces.absent", outcome: "passed", observedValue: "not-deployed", diagnostic: null}
  ]
}' >"${WORK_DIR}/facts.json"

write_result qualified aws_dev_observability_qualified "${WORK_DIR}/facts.json"
echo "v0.11.8.1 aws-dev live observability qualification passed."

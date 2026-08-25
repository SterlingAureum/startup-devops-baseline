#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${PROFILE:-local}"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROLLOUTS_NAMESPACE="${ROLLOUTS_NAMESPACE:-argo-rollouts}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
CNPG_NAMESPACE="${CNPG_NAMESPACE:-cnpg-system}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19091}"
TRAFFIC_LOCAL_PORT="${TRAFFIC_LOCAL_PORT:-18081}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"
EXPECTED_ARGOCD_VERSION="${EXPECTED_ARGOCD_VERSION:-}"
EXPECTED_ROLLOUTS_VERSION="${EXPECTED_ROLLOUTS_VERSION:-v1.9.1}"
EXPECTED_CNPG_VERSION="${EXPECTED_CNPG_VERSION:-1.30.0}"

# shellcheck source=scripts/lib/observability-live.sh
source "${ROOT_DIR}/scripts/lib/observability-live.sh"

case "${PROFILE}" in
  local|aws) ;;
  *)
    echo "ERROR: PROFILE must be local or aws, found ${PROFILE}." >&2
    exit 1
    ;;
esac

for command_name in curl grep jq kubectl seq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

prometheus_pid=""
cleanup() {
  for pid in "${prometheus_pid}"; do
    if [ -n "${pid}" ]; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for ${url}" >&2
      exit 1
    fi
    sleep 1
  done
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

assert_image_version() {
  local workload_type="$1"
  local namespace="$2"
  local workload="$3"
  local expected="$4"
  local image
  image="$(kubectl -n "${namespace}" get "${workload_type}" "${workload}" \
    -o jsonpath='{.spec.template.spec.containers[0].image}')"
  case "${image}" in
    *:"${expected}"|*:"${expected}"@sha256:*) ;;
    *)
      echo "ERROR: ${namespace}/${workload} uses ${image:-<empty>}, expected ${expected}." >&2
      exit 1
      ;;
  esac
  echo "  ${namespace}/${workload}: ${image}"
}

assert_semver_image() {
  local workload_type="$1"
  local namespace="$2"
  local workload="$3"
  local expected="${4:-}"
  local image
  image="$(kubectl -n "${namespace}" get "${workload_type}" "${workload}" \
    -o jsonpath='{.spec.template.spec.containers[0].image}')"
  if [[ ! "${image}" =~ :v[0-9]+\.[0-9]+\.[0-9]+(@sha256:[[:xdigit:]]{64})?$ ]]; then
    echo "ERROR: ${namespace}/${workload} image is not semantic-versioned: ${image:-<empty>}." >&2
    exit 1
  fi
  if [ -n "${expected}" ]; then
    case "${image}" in
      *:"${expected}"|*:"${expected}"@sha256:*) ;;
      *)
        echo "ERROR: ${namespace}/${workload} uses ${image}, expected ${expected}." >&2
        exit 1
        ;;
    esac
  fi
  echo "  ${namespace}/${workload}: ${image}"
}

assert_target() {
  local payload="$1"
  local namespace="$2"
  local port_path="$3"
  local description="$4"
  jq -e --arg namespace "${namespace}" --arg portPath "${port_path}" '
    [.data.activeTargets[] |
      select(
        .health == "up" and
        (.scrapeUrl | contains($portPath)) and
        (
          .labels.namespace == $namespace or
          .discoveredLabels.__meta_kubernetes_namespace == $namespace
        )
      )
    ] | length > 0
  ' <<<"${payload}" >/dev/null || {
    echo "ERROR: no healthy ${description} target was found in namespace ${namespace} on ${port_path}." >&2
    exit 1
  }
}

assert_metric_name() {
  local payload="$1"
  local name="$2"
  jq -e --arg name "${name}" '.data | index($name) != null' <<<"${payload}" >/dev/null || {
    echo "ERROR: Prometheus did not discover raw metric ${name}." >&2
    exit 1
  }
}

query_nonempty() {
  local expression="$1"
  local description="$2"
  local payload
  payload="$(curl -fsS --get "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/query" \
    --data-urlencode "query=${expression}")"
  jq -e '.status == "success" and (.data.result | length) > 0' <<<"${payload}" >/dev/null || {
    echo "ERROR: ${description} returned no series: ${expression}" >&2
    exit 1
  }
}

if [ "${PROFILE}" = "local" ]; then
  monitoring_application="monitoring"
  views_application="observability-views"
else
  monitoring_application="monitoring-${AWS_ENVIRONMENT}"
  views_application="observability-views-${AWS_ENVIRONMENT}"
fi

echo "==> Checking controller versions"
assert_semver_image statefulset "${ARGOCD_NAMESPACE}" argocd-application-controller "${EXPECTED_ARGOCD_VERSION}"
assert_image_version deployment "${ROLLOUTS_NAMESPACE}" argo-rollouts "${EXPECTED_ROLLOUTS_VERSION}"
if [ "${PROFILE}" = "aws" ]; then
  assert_image_version deployment "${CNPG_NAMESPACE}" cnpg-cloudnative-pg "${EXPECTED_CNPG_VERSION}"
fi

echo "==> Checking Argo CD Applications and monitor resources"
assert_application "${monitoring_application}"
assert_application "${views_application}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" get servicemonitor argocd-application-controller >/dev/null
kubectl -n "${OBSERVABILITY_NAMESPACE}" get servicemonitor argo-rollouts-controller >/dev/null
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule operator-diagnostic-recording-rules >/dev/null
if [ "${PROFILE}" = "aws" ]; then
  kubectl -n "${OBSERVABILITY_NAMESPACE}" get podmonitor cloudnative-pg-operator >/dev/null
  kubectl -n "${OBSERVABILITY_NAMESPACE}" get podmonitor cloudnative-pg-cluster >/dev/null
fi

echo "==> Generating bounded demo-api telemetry"
observability_generate_demo_api_metrics \
  "${APP_NAMESPACE}" "${ARGOCD_NAMESPACE}" demo-api "${TRAFFIC_LOCAL_PORT}"

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for controller scrapes and rule evaluation"
sleep "${RULE_WARMUP_SECONDS}"

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_LOCAL_PORT}:9090" >/tmp/v0.11.4.1.0-prometheus-port-forward.log 2>&1 &
prometheus_pid="$!"
wait_http "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready"
observability_assert_prometheus_jobs_up \
  "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}" demo-api-stable demo-api-canary

echo "==> Checking active targets"
targets_payload="$(curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/targets?state=active")"
assert_target "${targets_payload}" "${ARGOCD_NAMESPACE}" ":8082/metrics" "Argo CD"
assert_target "${targets_payload}" "${ROLLOUTS_NAMESPACE}" ":8090/metrics" "Argo Rollouts"
if [ "${PROFILE}" = "aws" ]; then
  assert_target "${targets_payload}" "${CNPG_NAMESPACE}" ":8080/metrics" "CloudNativePG operator"
  assert_target "${targets_payload}" data-platform ":9187/metrics" "CloudNativePG instance"
fi

echo "==> Checking discovered raw metric names"
names_payload="$(curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/label/__name__/values")"
for metric_name in \
  argocd_app_info \
  rollout_info \
  rollout_info_replicas_desired \
  rollout_info_replicas_available \
  rollout_info_replicas_unavailable \
  rollout_reconcile_count \
  demo_api_dependency_checks_total \
  kube_deployment_spec_replicas \
  kube_deployment_status_replicas_available \
  kube_deployment_status_replicas_unavailable \
  kube_pod_container_status_restarts_total; do
  assert_metric_name "${names_payload}" "${metric_name}"
done
if [ "${PROFILE}" = "aws" ]; then
  for metric_name in \
    cnpg_collector_up \
    cnpg_collector_last_collection_error \
    cnpg_collector_nodes_used \
    cnpg_collector_manual_switchover_required; do
    assert_metric_name "${names_payload}" "${metric_name}"
  done
fi

echo "==> Checking loaded diagnostic recording rules"
rules_payload="$(curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/rules?type=record")"
for rule_name in \
  delivery:argocd_applications:count \
  delivery:argocd_applications_out_of_sync:count \
  delivery:argocd_applications_unhealthy:count \
  delivery:rollouts:count \
  delivery:rollouts_problem:count \
  delivery:rollout_desired_replicas:count \
  delivery:rollout_available_replicas:count \
  delivery:rollout_unavailable_replicas:count \
  delivery:rollout_ready_replicas:ratio \
  delivery:rollout_reconcile:rate5m \
  data:demo_api_dependency_checks:rate5m \
  data:postgresql_instances_up:min \
  data:postgresql_collection_errors:max \
  data:postgresql_nodes_used:max \
  data:postgresql_manual_switchover_required:max \
  platform:deployment_desired_replicas:count \
  platform:deployment_ready_replicas:ratio \
  platform:deployment_unavailable_replicas:count \
  platform:pod_container_restarts:increase15m \
  platform:prometheus_targets:count \
  platform:prometheus_targets_down:count; do
  jq -e --arg name "${rule_name}" \
    '[.data.groups[].rules[] | select(.name == $name and .type == "recording")] | length == 1' \
    <<<"${rules_payload}" >/dev/null || {
      echo "ERROR: Prometheus did not load recording rule ${rule_name} exactly once." >&2
      exit 1
    }
done

echo "==> Checking required rule results"
query_nonempty 'delivery:argocd_applications:count' "Argo CD application summary"
query_nonempty 'delivery:rollouts:count' "Rollout phase summary"
query_nonempty 'delivery:rollout_ready_replicas:ratio' "Rollout replica readiness"
query_nonempty 'data:demo_api_dependency_checks:rate5m' "demo-api dependency summary"
query_nonempty 'platform:deployment_desired_replicas:count' "Deployment desired replica summary"
query_nonempty 'platform:prometheus_targets:count' "Prometheus target summary"
if [ "${PROFILE}" = "aws" ]; then
  query_nonempty 'data:postgresql_instances_up:min' "CloudNativePG instance health"
  query_nonempty 'data:postgresql_collection_errors:max' "CloudNativePG collection health"
  query_nonempty 'data:postgresql_nodes_used:max' "CloudNativePG node distribution"
  query_nonempty 'data:postgresql_manual_switchover_required:max' "CloudNativePG switchover state"
fi

echo "v0.11.4.1.0 ${PROFILE} controller metric discovery and recording-rule acceptance passed."

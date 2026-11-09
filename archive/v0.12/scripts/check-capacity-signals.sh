#!/usr/bin/env bash
set -Eeuo pipefail

PROFILE="${PROFILE:-local}"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19093}"
RULE_WARMUP_SECONDS="${RULE_WARMUP_SECONDS:-45}"

case "${PROFILE}" in
  local|aws) ;;
  *)
    echo "ERROR: PROFILE must be local or aws, found ${PROFILE}." >&2
    exit 1
    ;;
esac

for command_name in curl jq kubectl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

prometheus_pid=""
prometheus_log="$(mktemp)"
cleanup() {
  if [ -n "${prometheus_pid}" ]; then
    kill "${prometheus_pid}" >/dev/null 2>&1 || true
    wait "${prometheus_pid}" >/dev/null 2>&1 || true
  fi
  rm -f -- "${prometheus_log}"
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for ${url}" >&2
      sed -n '1,80p' "${prometheus_log}" >&2 || true
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

assert_metric_name() {
  local payload="$1"
  local name="$2"
  jq -e --arg name "${name}" '.data | index($name) != null' <<<"${payload}" >/dev/null || {
    echo "ERROR: Prometheus did not discover source metric ${name}." >&2
    exit 1
  }
}

query_payload() {
  local expression="$1"
  curl -fsS --get "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/query" \
    --data-urlencode "query=${expression}"
}

assert_query_nonempty() {
  local expression="$1"
  local description="$2"
  local payload
  payload="$(query_payload "${expression}")"
  jq -e '.status == "success" and (.data.result | length) > 0' <<<"${payload}" >/dev/null || {
    echo "ERROR: ${description} returned no series: ${expression}" >&2
    jq . <<<"${payload}" >&2 || true
    exit 1
  }
  echo "PASS: ${description}"
}

assert_finite_query() {
  local expression="$1"
  local description="$2"
  local payload
  payload="$(query_payload "${expression}")"
  jq -e '
    .status == "success" and
    (.data.result | length) > 0 and
    all(.data.result[]; (.value[1] | test("^(NaN|[+-]Inf)$") | not))
  ' <<<"${payload}" >/dev/null || {
    echo "ERROR: ${description} is empty or non-finite: ${expression}" >&2
    jq . <<<"${payload}" >&2 || true
    exit 1
  }
  echo "PASS: ${description}"
}

assert_rule_loaded() {
  local payload="$1"
  local name="$2"
  jq -e --arg name "${name}" '
    [.data.groups[].rules[] | select(.name == $name and .health == "ok")] | length == 1
  ' <<<"${payload}" >/dev/null || {
    echo "ERROR: recording rule is missing, duplicated, or unhealthy: ${name}" >&2
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

echo "==> Checking GitOps Applications and capacity PrometheusRule"
assert_application "${monitoring_application}"
assert_application "${views_application}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule \
  capacity-efficiency-recording-rules >/dev/null

kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward "service/${PROMETHEUS_SERVICE}" \
  "${PROMETHEUS_LOCAL_PORT}:9090" >"${prometheus_log}" 2>&1 &
prometheus_pid="$!"
wait_http "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/-/ready"

echo "==> Checking capacity source metric names"
names_payload="$(curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/label/__name__/values")"
for metric_name in \
  kube_node_status_allocatable \
  kube_pod_status_phase \
  kube_pod_container_info \
  kube_pod_container_resource_requests \
  kube_pod_container_resource_limits \
  container_cpu_usage_seconds_total \
  container_memory_working_set_bytes; do
  assert_metric_name "${names_payload}" "${metric_name}"
done

echo "==> Checking representative capacity source series"
assert_query_nonempty 'kube_node_status_allocatable{resource="cpu",unit="core"}' "node CPU allocatable source"
assert_query_nonempty 'kube_node_status_allocatable{resource="memory",unit="byte"}' "node memory allocatable source"
assert_query_nonempty 'kube_node_status_allocatable{resource="pods",unit="integer"}' "node Pod allocatable source"
assert_query_nonempty 'kube_pod_status_phase{phase="Running"} == 1' "running Pod inventory source"
assert_query_nonempty 'kube_pod_container_info{container!=""}' "container inventory source"
assert_query_nonempty 'kube_pod_container_resource_requests{resource="cpu",unit="core"}' "CPU request source"
assert_query_nonempty 'kube_pod_container_resource_limits{resource="memory",unit="byte"}' "memory limit source"
assert_query_nonempty 'container_cpu_usage_seconds_total{namespace!="",container!="",container!="POD"}' "container CPU usage source"
assert_query_nonempty 'container_memory_working_set_bytes{namespace!="",container!="",container!="POD"}' "container memory source"

echo "==> Waiting ${RULE_WARMUP_SECONDS}s for capacity rule evaluation"
sleep "${RULE_WARMUP_SECONDS}"

echo "==> Checking loaded capacity and efficiency recording rules"
rules_payload="$(curl -fsS "http://127.0.0.1:${PROMETHEUS_LOCAL_PORT}/api/v1/rules?type=record")"
for rule_name in \
  capacity:node_cpu_allocatable_cores:sum \
  capacity:node_memory_allocatable_bytes:sum \
  capacity:node_pods_allocatable:sum \
  capacity:running_pods:count \
  capacity:running_pods_to_allocatable:ratio \
  capacity:cpu_requests_cores:sum \
  capacity:memory_requests_bytes:sum \
  capacity:cpu_limits_cores:sum \
  capacity:memory_limits_bytes:sum \
  capacity:cpu_requests_to_allocatable:ratio \
  capacity:memory_requests_to_allocatable:ratio \
  efficiency:namespace_cpu_requests_cores:sum \
  efficiency:namespace_memory_requests_bytes:sum \
  efficiency:namespace_cpu_usage_cores:rate5m \
  efficiency:namespace_memory_working_set_bytes:sum \
  efficiency:namespace_cpu_usage_to_requests:ratio \
  efficiency:namespace_memory_usage_to_requests:ratio \
  efficiency:namespace_active_containers:count \
  efficiency:namespace_containers_without_cpu_requests:count \
  efficiency:namespace_containers_without_memory_requests:count; do
  assert_rule_loaded "${rules_payload}" "${rule_name}"
done

echo "==> Checking cluster capacity rule results"
for rule_name in \
  capacity:node_cpu_allocatable_cores:sum \
  capacity:node_memory_allocatable_bytes:sum \
  capacity:node_pods_allocatable:sum \
  capacity:running_pods:count \
  capacity:cpu_requests_cores:sum \
  capacity:memory_requests_bytes:sum \
  capacity:cpu_limits_cores:sum \
  capacity:memory_limits_bytes:sum; do
  assert_query_nonempty "${rule_name}" "cluster capacity rule ${rule_name}"
done
assert_finite_query 'capacity:running_pods_to_allocatable:ratio' "Pod capacity ratio"
assert_finite_query 'capacity:cpu_requests_to_allocatable:ratio' "CPU request ratio"
assert_finite_query 'capacity:memory_requests_to_allocatable:ratio' "memory request ratio"

echo "==> Checking startup-apps efficiency and request coverage"
for rule_name in \
  efficiency:namespace_cpu_requests_cores:sum \
  efficiency:namespace_memory_requests_bytes:sum \
  efficiency:namespace_cpu_usage_cores:rate5m \
  efficiency:namespace_memory_working_set_bytes:sum \
  efficiency:namespace_active_containers:count \
  efficiency:namespace_containers_without_cpu_requests:count \
  efficiency:namespace_containers_without_memory_requests:count; do
  assert_query_nonempty "${rule_name}{namespace=\"${APP_NAMESPACE}\"}" \
    "startup-apps rule ${rule_name}"
done
assert_finite_query \
  "efficiency:namespace_cpu_usage_to_requests:ratio{namespace=\"${APP_NAMESPACE}\"}" \
  "startup-apps CPU usage-to-request ratio"
assert_finite_query \
  "efficiency:namespace_memory_usage_to_requests:ratio{namespace=\"${APP_NAMESPACE}\"}" \
  "startup-apps memory usage-to-request ratio"

echo "v0.11.4.2.0 capacity source, recording-rule, and request-coverage live acceptance passed."

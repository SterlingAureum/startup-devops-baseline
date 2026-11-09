#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${PROFILE:-local}"
CONFIRM_ALERT_DRILL="${CONFIRM_ALERT_DRILL:-false}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
MONITORING_APPLICATION="${MONITORING_APPLICATION:-monitoring}"
VIEWS_APPLICATION="${VIEWS_APPLICATION:-observability-views}"
PROMETHEUS_SERVICE="${PROMETHEUS_SERVICE:-observability-metrics-prometheus}"
ALERTMANAGER_SERVICE="${ALERTMANAGER_SERVICE:-observability-metrics-alertmanager}"
DEMO_API_WORKLOAD="${DEMO_API_WORKLOAD:-demo-api}"
DEMO_API_IMAGE="${DEMO_API_IMAGE:-}"
SINK_NAME="alert-lifecycle-drill-sink"
RULE_NAME="alert-lifecycle-drill"
PROMETHEUS_LOCAL_PORT="${PROMETHEUS_LOCAL_PORT:-19110}"
ALERTMANAGER_LOCAL_PORT="${ALERTMANAGER_LOCAL_PORT:-19113}"
DISCOVERY_TIMEOUT_SECONDS="${DISCOVERY_TIMEOUT_SECONDS:-180}"
RESOLUTION_TIMEOUT_SECONDS="${RESOLUTION_TIMEOUT_SECONDS:-180}"
RULE_REMOVAL_TIMEOUT_SECONDS="${RULE_REMOVAL_TIMEOUT_SECONDS:-120}"
INHIBITION_SETTLE_SECONDS="${INHIBITION_SETTLE_SECONDS:-10}"
POLL_SECONDS="${POLL_SECONDS:-2}"

if [ "${CONFIRM_ALERT_DRILL}" != "true" ]; then
  echo "ERROR: this script creates temporary firing alerts. Re-run with CONFIRM_ALERT_DRILL=true." >&2
  exit 1
fi

if [ "${PROFILE}" != "local" ]; then
  echo "ERROR: v0.11.5.2.0 live drill execution is local-only; AWS execution is deferred to v0.11.8." >&2
  exit 1
fi

for command_name in curl jq kubectl python3 seq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

drill_suffix="$(date -u +%Y%m%d%H%M%S)-$$"
drill_id="v011520-${drill_suffix}"
shared_component="alert-lifecycle-drill-${drill_suffix}"
prometheus_pid=""
prometheus_log=""
alertmanager_pid=""
alertmanager_log=""
resources_created="false"

stop_port_forward() {
  local pid="$1"
  local log_path="$2"
  if [ -n "${pid}" ]; then
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
  fi
  if [ -n "${log_path}" ]; then
    rm -f -- "${log_path}"
  fi
}

delete_drill_resources_best_effort() {
  kubectl -n "${OBSERVABILITY_NAMESPACE}" delete prometheusrule "${RULE_NAME}" \
    --ignore-not-found --wait=true >/dev/null 2>&1 || true
  kubectl -n "${OBSERVABILITY_NAMESPACE}" delete networkpolicy,service,deployment,configmap \
    -l platform.startup.dev/alert-lifecycle-drill=true \
    --ignore-not-found --wait=true >/dev/null 2>&1 || true
  resources_created="false"
}

delete_drill_resources_strict() {
  kubectl -n "${OBSERVABILITY_NAMESPACE}" delete prometheusrule "${RULE_NAME}" \
    --ignore-not-found --wait=true >/dev/null
  kubectl -n "${OBSERVABILITY_NAMESPACE}" delete networkpolicy,service,deployment,configmap \
    -l platform.startup.dev/alert-lifecycle-drill=true \
    --ignore-not-found --wait=true >/dev/null
  resources_created="false"
}

cleanup() {
  if [ "${resources_created}" = "true" ]; then
    delete_drill_resources_best_effort
  fi
  stop_port_forward "${alertmanager_pid}" "${alertmanager_log}"
  stop_port_forward "${prometheus_pid}" "${prometheus_log}"
}
trap cleanup EXIT

port_is_open() {
  local port="$1"
  (exec 3<>"/dev/tcp/127.0.0.1/${port}") >/dev/null 2>&1
}

find_available_port() {
  local start_port="$1"
  local port
  for port in $(seq "${start_port}" "$((start_port + 100))"); do
    if ! port_is_open "${port}"; then
      printf '%s\n' "${port}"
      return 0
    fi
  done
  return 1
}

wait_http() {
  local url="$1"
  local log_path="$2"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for ${url}." >&2
      sed -n '1,100p' "${log_path}" >&2 || true
      return 1
    fi
    sleep 1
  done
}

start_port_forward() {
  local service="$1"
  local remote_port="$2"
  local requested_port="$3"
  local prefix="$4"
  local selected_port log_path pid
  selected_port="$(find_available_port "${requested_port}")" || {
    echo "ERROR: no local port is available from ${requested_port} through $((requested_port + 100))." >&2
    exit 1
  }
  log_path="$(mktemp)"
  kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward \
    "service/${service}" "${selected_port}:${remote_port}" >"${log_path}" 2>&1 &
  pid="$!"
  printf -v "${prefix}_pid" '%s' "${pid}"
  printf -v "${prefix}_log" '%s' "${log_path}"
  printf -v "${prefix}_port" '%s' "${selected_port}"
}

assert_application() {
  local name="$1"
  local sync health
  sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o jsonpath='{.status.sync.status}')"
  health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o jsonpath='{.status.health.status}')"
  [ "${sync}" = "Synced" ] && [ "${health}" = "Healthy" ] || {
    echo "ERROR: Application/${name} must be Synced and Healthy; observed sync=${sync:-unknown}, health=${health:-unknown}." >&2
    exit 1
  }
}

assert_clean_formal_alerts() {
  local payload expected
  payload="$(curl -fsS "${prometheus_url}/api/v1/rules?type=alert")"
  expected='[
    "ArgoCDApplicationUnhealthy",
    "ArgoRolloutProblem",
    "DemoApiDependencySuccessRatioLowCritical",
    "DemoApiDependencySuccessRatioLowWarning",
    "DemoApiHttpSuccessRatioLowCritical",
    "DemoApiHttpSuccessRatioLowWarning",
    "KubernetesDeploymentUnavailable",
    "PostgreSQLCollectionFailed",
    "PrometheusTargetDown"
  ]'
  if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json" ]; then
    expected="$(jq -c '. + [
      "DemoApiAvailabilityErrorBudgetFastBurn",
      "DemoApiAvailabilityErrorBudgetSlowBurn",
      "DemoApiLatencyErrorBudgetFastBurn",
      "DemoApiLatencyErrorBudgetSlowBurn"
    ]' <<<"${expected}")"
  fi
  jq -e --argjson expected "${expected}" '
    ([.data.groups[].rules[] | select(.type == "alerting") | .name] | sort) ==
    ($expected | sort) and
    all(.data.groups[].rules[] | select(.type == "alerting"); .health == "ok" and .state == "inactive")
  ' <<<"${payload}" >/dev/null || {
    echo "ERROR: the repository-owned formal alerts must be healthy and inactive outside the drill." >&2
    jq '[.data.groups[].rules[] | select(.type == "alerting") | {name, health, state, lastError}]' <<<"${payload}" >&2
    exit 1
  }
}

assert_no_stale_resources() {
  local stale_count
  stale_count="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule,networkpolicy,service,deployment,configmap \
    -l platform.startup.dev/alert-lifecycle-drill=true -o name 2>/dev/null | wc -l | tr -d ' ')"
  [ "${stale_count}" -eq 0 ] || {
    echo "ERROR: stale alert lifecycle drill resources exist; delete them before starting." >&2
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get prometheusrule,networkpolicy,service,deployment,configmap \
      -l platform.startup.dev/alert-lifecycle-drill=true >&2 || true
    exit 1
  }
}

discover_demo_api_image() {
  # Reuse the currently deployed demo-api image; the repository does not add a drill-only image.
  if [ -n "${DEMO_API_IMAGE}" ]; then
    printf '%s\n' "${DEMO_API_IMAGE}"
    return
  fi
  local image=""
  image="$(kubectl -n "${APP_NAMESPACE}" get rollout "${DEMO_API_WORKLOAD}" \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)"
  if [ -z "${image}" ]; then
    image="$(kubectl -n "${APP_NAMESPACE}" get deployment "${DEMO_API_WORKLOAD}" \
      -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)"
  fi
  [ -n "${image}" ] || {
    echo "ERROR: could not derive a Python-capable demo-api image; set DEMO_API_IMAGE explicitly." >&2
    exit 1
  }
  printf '%s\n' "${image}"
}

create_sink() {
  local image="$1"
  kubectl -n "${OBSERVABILITY_NAMESPACE}" create configmap "${SINK_NAME}" \
    --from-file=alert-webhook-sink.py="${ROOT_DIR}/scripts/fixtures/alert-webhook-sink.py" \
    --dry-run=client -o yaml | kubectl label --local -f - \
      platform.startup.dev/alert-lifecycle-drill=true \
      app.kubernetes.io/name="${SINK_NAME}" -o yaml | kubectl apply -f - >/dev/null
  resources_created="true"

  kubectl apply -f - >/dev/null <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${SINK_NAME}
  namespace: ${OBSERVABILITY_NAMESPACE}
  labels:
    app.kubernetes.io/name: ${SINK_NAME}
    app.kubernetes.io/part-of: startup-devops-baseline
    platform.startup.dev/alert-lifecycle-drill: "true"
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ${SINK_NAME}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ${SINK_NAME}
        app.kubernetes.io/part-of: startup-devops-baseline
        platform.startup.dev/alert-lifecycle-drill: "true"
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: sink
          image: ${image}
          imagePullPolicy: IfNotPresent
          command: ["python3", "/opt/alert-drill/alert-webhook-sink.py"]
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 1
            periodSeconds: 2
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: 10m
              memory: 24Mi
            limits:
              cpu: 100m
              memory: 64Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: sink-source
              mountPath: /opt/alert-drill
              readOnly: true
      volumes:
        - name: sink-source
          configMap:
            name: ${SINK_NAME}
---
apiVersion: v1
kind: Service
metadata:
  name: ${SINK_NAME}
  namespace: ${OBSERVABILITY_NAMESPACE}
  labels:
    app.kubernetes.io/name: ${SINK_NAME}
    platform.startup.dev/alert-lifecycle-drill: "true"
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: ${SINK_NAME}
  ports:
    - name: http
      port: 8080
      targetPort: http
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ${SINK_NAME}
  namespace: ${OBSERVABILITY_NAMESPACE}
  labels:
    app.kubernetes.io/name: ${SINK_NAME}
    platform.startup.dev/alert-lifecycle-drill: "true"
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: ${SINK_NAME}
  policyTypes: ["Ingress", "Egress"]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - protocol: TCP
          port: 8080
  egress: []
YAML
  kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status deployment "${SINK_NAME}" --timeout=120s >/dev/null
}

sink_request() {
  local method="$1"
  local path="$2"
  kubectl -n "${OBSERVABILITY_NAMESPACE}" exec deployment/"${SINK_NAME}" -c sink -- \
    python3 -c 'import sys, urllib.request; method, path = sys.argv[1:3]; request = urllib.request.Request("http://127.0.0.1:8080" + path, method=method); print(urllib.request.urlopen(request, timeout=5).read().decode())' \
    "${method}" "${path}"
}

reset_sink() {
  sink_request POST /reset >/dev/null
}

apply_single_rule() {
  local alert_name="$1"
  local severity="$2"
  local component="$3"
  local expression="$4"
  kubectl apply -f - >/dev/null <<YAML
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ${RULE_NAME}
  namespace: ${OBSERVABILITY_NAMESPACE}
  labels:
    app.kubernetes.io/part-of: startup-devops-baseline
    platform.startup.dev/alert-lifecycle-drill: "true"
spec:
  groups:
    - name: alert-lifecycle-drill.v0.11.5.2.0
      interval: 5s
      rules:
        - alert: ${alert_name}
          expr: ${expression}
          for: 0s
          labels:
            severity: ${severity}
            environment: local
            cluster: startup-devops-local
            component: ${component}
            alert_family: alert-lifecycle-drill
            drill: "true"
            drill_id: ${drill_id}
          annotations:
            summary: Temporary ${severity} alert lifecycle drill
            description: Ephemeral v0.11.5.2.0 validation signal; the drill script must remove it.
YAML
}

apply_pair_rules() {
  local warning_component="$1"
  local critical_component="$2"
  local expression="$3"
  kubectl apply -f - >/dev/null <<YAML
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ${RULE_NAME}
  namespace: ${OBSERVABILITY_NAMESPACE}
  labels:
    app.kubernetes.io/part-of: startup-devops-baseline
    platform.startup.dev/alert-lifecycle-drill: "true"
spec:
  groups:
    - name: alert-lifecycle-drill.v0.11.5.2.0
      interval: 5s
      rules:
        - alert: AlertLifecycleDrillWarning
          expr: ${expression}
          for: 0s
          labels:
            severity: warning
            environment: local
            cluster: startup-devops-local
            component: ${warning_component}
            alert_family: alert-lifecycle-drill
            drill: "true"
            drill_id: ${drill_id}
          annotations:
            summary: Temporary warning alert lifecycle drill
            description: Ephemeral v0.11.5.2.0 validation signal; the drill script must remove it.
        - alert: AlertLifecycleDrillCritical
          expr: ${expression}
          for: 0s
          labels:
            severity: critical
            environment: local
            cluster: startup-devops-local
            component: ${critical_component}
            alert_family: alert-lifecycle-drill
            drill: "true"
            drill_id: ${drill_id}
          annotations:
            summary: Temporary critical alert lifecycle drill
            description: Ephemeral v0.11.5.2.0 validation signal; the drill script must remove it.
YAML
}

remove_rule() {
  kubectl -n "${OBSERVABILITY_NAMESPACE}" delete prometheusrule "${RULE_NAME}" \
    --ignore-not-found --wait=true >/dev/null
}

wait_prometheus_firing() {
  local alert_name="$1"
  local deadline=$((SECONDS + DISCOVERY_TIMEOUT_SECONDS))
  local payload
  while true; do
    payload="$(curl -fsS --get "${prometheus_url}/api/v1/query" \
      --data-urlencode "query=ALERTS{alertname=\"${alert_name}\",drill=\"true\",drill_id=\"${drill_id}\",alertstate=\"firing\"}")"
    if jq -e '.status == "success" and (.data.result | length) == 1' <<<"${payload}" >/dev/null; then
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: Prometheus did not report ${alert_name} firing." >&2
      jq . <<<"${payload}" >&2 || true
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

wait_prometheus_cleared() {
  local alert_name="$1"
  local deadline=$((SECONDS + RESOLUTION_TIMEOUT_SECONDS))
  local payload
  while true; do
    payload="$(curl -fsS --get "${prometheus_url}/api/v1/query" \
      --data-urlencode "query=ALERTS{alertname=\"${alert_name}\",drill=\"true\",drill_id=\"${drill_id}\"}")"
    if jq -e '.status == "success" and (.data.result | length) == 0' <<<"${payload}" >/dev/null; then
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: Prometheus did not clear ${alert_name} after the inactive expression was applied." >&2
      jq . <<<"${payload}" >&2 || true
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

wait_prometheus_drill_rules_removed() {
  local deadline=$((SECONDS + RULE_REMOVAL_TIMEOUT_SECONDS))
  local payload
  while true; do
    payload="$(curl -fsS "${prometheus_url}/api/v1/rules?type=alert")"
    if jq -e '
      [
        (.data.groups // [])[].rules[]?
        | select(
            .type == "alerting" and
            (.name == "AlertLifecycleDrillWarning" or .name == "AlertLifecycleDrillCritical")
          )
      ] | length == 0
    ' <<<"${payload}" >/dev/null; then
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: temporary alert lifecycle drill rules remained in the Prometheus inventory after Kubernetes deletion." >&2
      jq '[
        (.data.groups // [])[].rules[]?
        | select(
            .type == "alerting" and
            (.name == "AlertLifecycleDrillWarning" or .name == "AlertLifecycleDrillCritical")
          )
        | {name, health, state, lastError}
      ]' <<<"${payload}" >&2 || true
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

wait_alertmanager_state() {
  local alert_name="$1"
  local expected_state="$2"
  local require_inhibitor="$3"
  local drill_receiver="$4"
  local base_receiver="$5"
  local deadline=$((SECONDS + DISCOVERY_TIMEOUT_SECONDS))
  local payload
  while true; do
    payload="$(curl -fsS "${alertmanager_url}/api/v2/alerts")"
    if jq -e --arg name "${alert_name}" --arg drill_id "${drill_id}" \
      --arg state "${expected_state}" --arg require_inhibitor "${require_inhibitor}" \
      --arg drill_receiver "${drill_receiver}" --arg base_receiver "${base_receiver}" '
        any(.[];
          .labels.alertname == $name and
          .labels.drill_id == $drill_id and
          .status.state == $state and
          ([.receivers[].name] | index($drill_receiver)) != null and
          ([.receivers[].name] | index($base_receiver)) != null and
          ($require_inhibitor != "true" or (.status.inhibitedBy | length) > 0)
        )
      ' <<<"${payload}" >/dev/null; then
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: Alertmanager did not report ${alert_name} as ${expected_state}." >&2
      jq '[.[] | select(.labels.drill == "true") | {labels, status, receivers}]' <<<"${payload}" >&2 || true
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

wait_webhook_event() {
  local path="$1"
  local alert_name="$2"
  local status="$3"
  local timeout_seconds="${4:-${DISCOVERY_TIMEOUT_SECONDS}}"
  local deadline=$((SECONDS + timeout_seconds))
  local payload
  while true; do
    payload="$(sink_request GET /events)"
    if jq -e --arg path "${path}" --arg name "${alert_name}" \
      --arg status "${status}" --arg drill_id "${drill_id}" '
        any(.events[];
          .path == $path and
          .payload.status == $status and
          any(.payload.alerts[];
            .labels.alertname == $name and
            .labels.drill_id == $drill_id and
            .status == $status
          )
        )
      ' <<<"${payload}" >/dev/null; then
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: webhook did not receive ${status} for ${alert_name} on ${path}." >&2
      jq . <<<"${payload}" >&2 || true
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

assert_no_webhook_event() {
  local path="$1"
  local alert_name="$2"
  local status="$3"
  local payload
  payload="$(sink_request GET /events)"
  if jq -e --arg path "${path}" --arg name "${alert_name}" \
    --arg status "${status}" --arg drill_id "${drill_id}" '
      any(.events[];
        .path == $path and .payload.status == $status and
        any(.payload.alerts[];
          .labels.alertname == $name and .labels.drill_id == $drill_id and .status == $status
        )
      )
    ' <<<"${payload}" >/dev/null; then
    echo "ERROR: unexpected ${status} webhook for ${alert_name} on ${path}." >&2
    jq . <<<"${payload}" >&2 || true
    return 1
  fi
}

wait_no_drill_alerts() {
  local deadline=$((SECONDS + RESOLUTION_TIMEOUT_SECONDS))
  local prometheus_payload alertmanager_payload
  while true; do
    prometheus_payload="$(curl -fsS --get "${prometheus_url}/api/v1/query" \
      --data-urlencode "query=ALERTS{drill=\"true\",drill_id=\"${drill_id}\"}")"
    alertmanager_payload="$(curl -fsS "${alertmanager_url}/api/v2/alerts")"
    if jq -e '.status == "success" and (.data.result | length) == 0' <<<"${prometheus_payload}" >/dev/null &&
      jq -e --arg drill_id "${drill_id}" 'all(.[]; .labels.drill_id != $drill_id)' <<<"${alertmanager_payload}" >/dev/null; then
      return 0
    fi
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: drill alerts did not clear from Prometheus and Alertmanager." >&2
      jq . <<<"${prometheus_payload}" >&2 || true
      jq --arg drill_id "${drill_id}" \
        '[.[] | select(.labels.drill_id == $drill_id) | {labels, status}]' \
        <<<"${alertmanager_payload}" >&2 || true
      return 1
    fi
    sleep "${POLL_SECONDS}"
  done
}

assert_no_active_drill_alerts() {
  local payload
  payload="$(curl -fsS "${alertmanager_url}/api/v2/alerts")"
  if ! jq -e 'all(.[]; .labels.drill != "true")' <<<"${payload}" >/dev/null; then
    echo "ERROR: Alertmanager still contains an active drill alert from this or a previous run." >&2
    echo "Wait for the alert to resolve, confirm no temporary resources remain, and retry from preflight." >&2
    jq '[.[] | select(.labels.drill == "true") | {labels, status, receivers}]' <<<"${payload}" >&2 || true
    return 1
  fi
}

echo "==> Preflight: GitOps health, clean formal alerts, and zero stale drill resources"
assert_application "${MONITORING_APPLICATION}"
assert_application "${VIEWS_APPLICATION}"
assert_no_stale_resources

start_port_forward "${PROMETHEUS_SERVICE}" 9090 "${PROMETHEUS_LOCAL_PORT}" prometheus
prometheus_url="http://127.0.0.1:${prometheus_port}"
wait_http "${prometheus_url}/-/ready" "${prometheus_log}"
start_port_forward "${ALERTMANAGER_SERVICE}" 9093 "${ALERTMANAGER_LOCAL_PORT}" alertmanager
alertmanager_url="http://127.0.0.1:${alertmanager_port}"
wait_http "${alertmanager_url}/-/ready" "${alertmanager_log}"
assert_no_active_drill_alerts
assert_clean_formal_alerts

echo "==> Creating the temporary restricted in-cluster webhook sink"
sink_image="$(discover_demo_api_image)"
create_sink "${sink_image}"

echo "==> Phase 1: warning firing, routing, and resolved delivery"
reset_sink
apply_single_rule AlertLifecycleDrillWarning warning "${shared_component}" 'vector(1)'
wait_prometheus_firing AlertLifecycleDrillWarning
wait_alertmanager_state AlertLifecycleDrillWarning active false warning-drill-webhook warning-observation
wait_webhook_event /warning AlertLifecycleDrillWarning firing
apply_single_rule AlertLifecycleDrillWarning warning "${shared_component}" 'vector(0) == 1'
wait_prometheus_cleared AlertLifecycleDrillWarning
wait_webhook_event /warning AlertLifecycleDrillWarning resolved "${RESOLUTION_TIMEOUT_SECONDS}"
wait_no_drill_alerts
remove_rule
wait_prometheus_drill_rules_removed

echo "==> Phase 2: critical firing, routing, and resolved delivery"
reset_sink
apply_single_rule AlertLifecycleDrillCritical critical "${shared_component}" 'vector(1)'
wait_prometheus_firing AlertLifecycleDrillCritical
wait_alertmanager_state AlertLifecycleDrillCritical active false critical-drill-webhook critical-observation
wait_webhook_event /critical AlertLifecycleDrillCritical firing
apply_single_rule AlertLifecycleDrillCritical critical "${shared_component}" 'vector(0) == 1'
wait_prometheus_cleared AlertLifecycleDrillCritical
wait_webhook_event /critical AlertLifecycleDrillCritical resolved "${RESOLUTION_TIMEOUT_SECONDS}"
wait_no_drill_alerts
remove_rule
wait_prometheus_drill_rules_removed

echo "==> Phase 3: positive inhibition; critical inhibits an equal-scope warning"
reset_sink
apply_pair_rules "${shared_component}" "${shared_component}" 'vector(1)'
wait_prometheus_firing AlertLifecycleDrillWarning
wait_prometheus_firing AlertLifecycleDrillCritical
wait_alertmanager_state AlertLifecycleDrillCritical active false critical-drill-webhook critical-observation
wait_alertmanager_state AlertLifecycleDrillWarning suppressed true warning-drill-webhook warning-observation
wait_webhook_event /critical AlertLifecycleDrillCritical firing
sleep "${INHIBITION_SETTLE_SECONDS}"
assert_no_webhook_event /warning AlertLifecycleDrillWarning firing
apply_pair_rules "${shared_component}" "${shared_component}" 'vector(0) == 1'
wait_prometheus_cleared AlertLifecycleDrillWarning
wait_prometheus_cleared AlertLifecycleDrillCritical
wait_webhook_event /critical AlertLifecycleDrillCritical resolved "${RESOLUTION_TIMEOUT_SECONDS}"
wait_no_drill_alerts
remove_rule
wait_prometheus_drill_rules_removed

echo "==> Phase 4: unequal component labels prevent cross-scope inhibition"
reset_sink
apply_pair_rules "${shared_component}-warning" "${shared_component}-critical" 'vector(1)'
wait_prometheus_firing AlertLifecycleDrillWarning
wait_prometheus_firing AlertLifecycleDrillCritical
wait_alertmanager_state AlertLifecycleDrillWarning active false warning-drill-webhook warning-observation
wait_alertmanager_state AlertLifecycleDrillCritical active false critical-drill-webhook critical-observation
wait_webhook_event /warning AlertLifecycleDrillWarning firing
wait_webhook_event /critical AlertLifecycleDrillCritical firing
apply_pair_rules "${shared_component}-warning" "${shared_component}-critical" 'vector(0) == 1'
wait_prometheus_cleared AlertLifecycleDrillWarning
wait_prometheus_cleared AlertLifecycleDrillCritical
wait_webhook_event /warning AlertLifecycleDrillWarning resolved "${RESOLUTION_TIMEOUT_SECONDS}"
wait_webhook_event /critical AlertLifecycleDrillCritical resolved "${RESOLUTION_TIMEOUT_SECONDS}"
wait_no_drill_alerts
remove_rule
wait_prometheus_drill_rules_removed

echo "==> Cleanup: removing all temporary resources and rechecking the formal baseline"
delete_drill_resources_strict
wait_prometheus_drill_rules_removed
assert_no_stale_resources
assert_no_active_drill_alerts
assert_clean_formal_alerts

if [ -f "${ROOT_DIR}/delivery/contracts/v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.json" ]; then
  echo "v0.11.5.2.0.3 local firing, resolved delivery, strict cleanup, Prometheus rule-inventory convergence, and exact nine-alert baseline acceptance passed."
elif [ -f "${ROOT_DIR}/delivery/contracts/v0.11.5.2.0.2-alert-resolution-transition-repair.json" ]; then
  echo "v0.11.5.2.0.2 local firing, explicit inactive transition, routing, inhibition, resolved delivery, isolation, and zero-residual cleanup acceptance passed."
else
  echo "v0.11.5.2.0 local firing, routing, inhibition, resolved delivery, isolation, and zero-residual cleanup acceptance passed."
fi

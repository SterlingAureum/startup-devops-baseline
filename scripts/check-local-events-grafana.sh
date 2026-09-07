#!/usr/bin/env bash
set -Eeuo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
EVENTS_APP="${EVENTS_APP:-logging-alloy-events}"
EVENTS_DEPLOYMENT="${EVENTS_DEPLOYMENT:-observability-events-collector}"
EVENTS_SERVICE_ACCOUNT="${EVENTS_SERVICE_ACCOUNT:-observability-events-collector}"
EVENTS_PVC="${EVENTS_PVC:-observability-events-collector-storage}"
LOKI_GATEWAY_SERVICE="${LOKI_GATEWAY_SERVICE:-observability-logs-gateway}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-observability-metrics-grafana}"
GRAFANA_SECRET="${GRAFANA_SECRET:-observability-metrics-grafana}"
LOKI_LOCAL_PORT="${LOKI_LOCAL_PORT:-13100}"
GRAFANA_LOCAL_PORT="${GRAFANA_LOCAL_PORT:-13000}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
QUERY_TIMEOUT_SECONDS="${QUERY_TIMEOUT_SECONDS:-90}"
WORK_DIR="$(mktemp -d)"
LOKI_PF_PID=""
GRAFANA_PF_PID=""
EVENT_NAMES=()

cleanup() {
  local pid
  for pid in "${LOKI_PF_PID}" "${GRAFANA_PF_PID}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  if [ "${#EVENT_NAMES[@]}" -gt 0 ]; then
    kubectl -n "${APP_NAMESPACE}" delete event "${EVENT_NAMES[@]}" \
      --ignore-not-found --wait=false >/dev/null 2>&1 || true
  fi
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

for command_name in base64 curl jq kubectl python3; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || fail "required command not found: ${command_name}"
done

wait_application() {
  local name="$1"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  local sync=""
  local health=""

  until [ "${SECONDS}" -ge "${deadline}" ]; do
    if kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o json \
      >"${WORK_DIR}/${name}-application.json" 2>/dev/null; then
      sync="$(jq -r '.status.sync.status // ""' "${WORK_DIR}/${name}-application.json")"
      health="$(jq -r '.status.health.status // ""' "${WORK_DIR}/${name}-application.json")"
      if [ "${sync}" = "Synced" ] && [ "${health}" = "Healthy" ]; then
        echo "PASS: Application/${name} is Synced and Healthy."
        return 0
      fi
    fi
    sleep 3
  done

  kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o yaml >&2 || true
  fail "Application/${name} did not become Synced and Healthy; sync=${sync:-unknown} health=${health:-unknown}"
}

wait_http() {
  local url="$1"
  local log_file="$2"
  local deadline=$((SECONDS + 30))
  until curl -fsS "${url}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      sed -n '1,160p' "${log_file}" >&2 || true
      fail "endpoint did not become reachable: ${url}"
    fi
    sleep 1
  done
}

create_acceptance_event() {
  local name="$1"
  local marker="$2"
  local pod_name="$3"
  local pod_uid="$4"
  local timestamp
  timestamp="$(python3 -c '
from datetime import datetime, timezone
print(datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"))
')"

  kubectl create -f - >/dev/null <<YAML
apiVersion: events.k8s.io/v1
kind: Event
metadata:
  name: ${name}
  namespace: ${APP_NAMESPACE}
eventTime: ${timestamp}
action: LoggingAcceptance
reason: V011612Acceptance
regarding:
  apiVersion: v1
  kind: Pod
  name: ${pod_name}
  namespace: ${APP_NAMESPACE}
  uid: ${pod_uid}
reportingController: platform.startup.dev/logging-acceptance
reportingInstance: local
type: Normal
note: ${marker}
YAML
  EVENT_NAMES+=("${name}")
}

query_event_marker() {
  local start_ns="$1"
  local marker="$2"
  local logql
  printf -v logql '%s |= "%s"' \
    '{environment="local",cluster="startup-devops-local",namespace="startup-apps",application="kubernetes-events",container="events",severity="INFO"}' \
    "${marker}"
  curl -fsS --get "http://127.0.0.1:${LOKI_LOCAL_PORT}/loki/api/v1/query_range" \
    --data-urlencode "query=${logql}" \
    --data-urlencode "start=${start_ns}" \
    --data-urlencode 'direction=backward' \
    --data-urlencode 'limit=100'
}

event_marker_count() {
  local response_file="$1"
  local marker="$2"
  jq -r --arg marker "${marker}" \
    '[.data.result[].values[]?[1] | select(contains($marker))] | length' \
    "${response_file}"
}

wait_for_single_event() {
  local start_ns="$1"
  local marker="$2"
  local output="$3"
  local deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))

  until [ "${SECONDS}" -ge "${deadline}" ]; do
    if query_event_marker "${start_ns}" "${marker}" >"${output}" 2>/dev/null \
      && [ "$(event_marker_count "${output}" "${marker}")" = "1" ]; then
      return 0
    fi
    sleep 2
  done
  query_event_marker "${start_ns}" "${marker}" >"${output}" 2>/dev/null || true
  fail "Loki did not return exactly one copy of Kubernetes Event marker ${marker}."
}

delete_acceptance_events_strict() {
  local name

  [ "${#EVENT_NAMES[@]}" -gt 0 ] \
    || fail "strict Event cleanup was requested without a registered Event."
  kubectl -n "${APP_NAMESPACE}" delete event "${EVENT_NAMES[@]}" \
    --ignore-not-found --wait=true >/dev/null \
    || fail "temporary acceptance Events could not be deleted."
  for name in "${EVENT_NAMES[@]}"; do
    if kubectl -n "${APP_NAMESPACE}" get event "${name}" >/dev/null 2>&1; then
      fail "temporary acceptance Event still exists after deletion: ${name}"
    fi
  done
  EVENT_NAMES=()
}

echo "==> Waiting for the singleton Events Application and workload"
wait_application "${EVENTS_APP}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  "deployment/${EVENTS_DEPLOYMENT}" --timeout="${TIMEOUT_SECONDS}s"

echo "==> Checking singleton, non-root, durable-position, and network boundaries"
kubectl -n "${OBSERVABILITY_NAMESPACE}" get deployment "${EVENTS_DEPLOYMENT}" -o json \
  >"${WORK_DIR}/events-deployment.json"
jq -e --arg claim "${EVENTS_PVC}" '
  .spec.replicas == 1
  and .spec.template.spec.securityContext.runAsNonRoot == true
  and .spec.template.spec.securityContext.fsGroup == 473
  and ([.spec.template.spec.containers[] | select(.name == "alloy")] | length) == 1
  and (
    [.spec.template.spec.containers[] | select(.name == "alloy")][0]
    | .securityContext.runAsUser == 473
      and .securityContext.runAsGroup == 473
      and .securityContext.allowPrivilegeEscalation == false
      and .securityContext.readOnlyRootFilesystem == true
      and any(.volumeMounts[]?; .name == "alloy-storage" and .mountPath == "/var/lib/alloy")
  )
  and any(.spec.template.spec.volumes[]?; .name == "alloy-storage" and .persistentVolumeClaim.claimName == $claim)
' "${WORK_DIR}/events-deployment.json" >/dev/null \
  || fail "Events Alloy is not a one-replica, non-root Deployment with persistent positions."

[ "$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get pvc "${EVENTS_PVC}" -o jsonpath='{.status.phase}')" = "Bound" ] \
  || fail "Events Alloy position PVC is not Bound."
kubectl -n "${OBSERVABILITY_NAMESPACE}" get networkpolicy "${EVENTS_DEPLOYMENT}" >/dev/null
kubectl auth can-i --as "system:serviceaccount:${OBSERVABILITY_NAMESPACE}:${EVENTS_SERVICE_ACCOUNT}" \
  get events --all-namespaces | grep -qx yes \
  || fail "Events ServiceAccount cannot get Events."
kubectl auth can-i --as "system:serviceaccount:${OBSERVABILITY_NAMESPACE}:${EVENTS_SERVICE_ACCOUNT}" \
  list events --all-namespaces | grep -qx yes \
  || fail "Events ServiceAccount cannot list Events."
kubectl auth can-i --as "system:serviceaccount:${OBSERVABILITY_NAMESPACE}:${EVENTS_SERVICE_ACCOUNT}" \
  watch events --all-namespaces | grep -qx yes \
  || fail "Events ServiceAccount cannot watch Events."
for forbidden_resource in pods pods/log secrets configmaps; do
  [ "$(kubectl auth can-i --as "system:serviceaccount:${OBSERVABILITY_NAMESPACE}:${EVENTS_SERVICE_ACCOUNT}" \
    list "${forbidden_resource}" --all-namespaces)" = "no" ] \
    || fail "Events ServiceAccount can list forbidden resource ${forbidden_resource}."
done

echo "==> Starting private Loki and Grafana API tunnels"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward \
  "service/${LOKI_GATEWAY_SERVICE}" "${LOKI_LOCAL_PORT}:80" \
  >"${WORK_DIR}/loki-port-forward.log" 2>&1 &
LOKI_PF_PID="$!"
wait_http "http://127.0.0.1:${LOKI_LOCAL_PORT}/loki/api/v1/labels" \
  "${WORK_DIR}/loki-port-forward.log"

grafana_user="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" \
  -o jsonpath='{.data.admin-user}' | base64 --decode)"
grafana_password="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" \
  -o jsonpath='{.data.admin-password}' | base64 --decode)"
[ -n "${grafana_user}" ] && [ -n "${grafana_password}" ] \
  || fail "Grafana administrative credentials are unavailable."
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward \
  "service/${GRAFANA_SERVICE}" "${GRAFANA_LOCAL_PORT}:80" \
  >"${WORK_DIR}/grafana-port-forward.log" 2>&1 &
GRAFANA_PF_PID="$!"
wait_http "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/health" \
  "${WORK_DIR}/grafana-port-forward.log"

echo "==> Checking the Git-provisioned private Loki data source"
curl -fsS -u "${grafana_user}:${grafana_password}" \
  "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/datasources/uid/loki" \
  >"${WORK_DIR}/grafana-loki.json"
jq -e '
  .name == "Loki"
  and .uid == "loki"
  and .type == "loki"
  and .access == "proxy"
  and .url == "http://observability-logs-gateway.observability.svc.cluster.local"
  and .isDefault == false
  and .readOnly == true
' "${WORK_DIR}/grafana-loki.json" >/dev/null \
  || fail "Grafana Loki data source does not match the provisioned contract."
curl -fsS -u "${grafana_user}:${grafana_password}" \
  "http://127.0.0.1:${GRAFANA_LOCAL_PORT}/api/datasources/uid/loki/health" \
  >"${WORK_DIR}/grafana-loki-health.json"
jq -e '.status == "OK"' "${WORK_DIR}/grafana-loki-health.json" >/dev/null \
  || fail "Grafana could not reach Loki through the provisioned data source."

demo_pod="$(kubectl -n "${APP_NAMESPACE}" get pod -l app.kubernetes.io/name=demo-api -o json \
  | jq -r '[.items[] | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))] | first | .metadata.name // empty')"
[ -n "${demo_pod}" ] || fail "no Ready demo-api Pod was found for the Event reference."
demo_uid="$(kubectl -n "${APP_NAMESPACE}" get pod "${demo_pod}" -o jsonpath='{.metadata.uid}')"

start_ns="$(python3 -c 'import time; print(time.time_ns() - 5_000_000_000)')"
event_suffix="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
first_event="v011612-${event_suffix}-before"
first_marker="v011612-event-before-${event_suffix}"

echo "==> Creating and querying one deterministic Kubernetes Event"
create_acceptance_event "${first_event}" "${first_marker}" "${demo_pod}" "${demo_uid}"
wait_for_single_event "${start_ns}" "${first_marker}" "${WORK_DIR}/first-event.json"

echo "==> Checking the bounded Event-stream indexed-label inventory"
curl -fsS --get "http://127.0.0.1:${LOKI_LOCAL_PORT}/loki/api/v1/series" \
  --data-urlencode 'match[]={environment="local",cluster="startup-devops-local",namespace="startup-apps",application="kubernetes-events",container="events",severity="INFO"}' \
  --data-urlencode "start=${start_ns}" >"${WORK_DIR}/event-series.json"
python3 - "${WORK_DIR}/event-series.json" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text())
if payload.get("status") != "success":
    raise SystemExit("Loki Series API did not return success")
series = payload.get("data", [])
if not series:
    raise SystemExit("Loki Series API returned no Kubernetes Event stream")
observed = {label for stream in series for label in stream}
expected = {"environment", "cluster", "namespace", "application", "container", "severity"}
if observed != expected:
    raise SystemExit(f"Unexpected Event-stream indexed Loki labels: {sorted(observed)}")
print("Kubernetes Event streams preserve the exact six-label Loki contract.")
PY

echo "==> Restarting the singleton collector and rejecting Event replay"
sleep 5
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout restart "deployment/${EVENTS_DEPLOYMENT}" >/dev/null
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  "deployment/${EVENTS_DEPLOYMENT}" --timeout="${TIMEOUT_SECONDS}s"
sleep 10
query_event_marker "${start_ns}" "${first_marker}" >"${WORK_DIR}/post-restart-first-event.json"
[ "$(event_marker_count "${WORK_DIR}/post-restart-first-event.json" "${first_marker}")" = "1" ] \
  || fail "The Events collector replayed a previously accepted Event after restart."

second_event="v011612-${event_suffix}-after"
second_marker="v011612-event-after-${event_suffix}"
create_acceptance_event "${second_event}" "${second_marker}" "${demo_pod}" "${demo_uid}"
wait_for_single_event "${start_ns}" "${second_marker}" "${WORK_DIR}/second-event.json"

echo "==> Strictly deleting temporary Kubernetes Events"
delete_acceptance_events_strict

echo "==> Proving accepted Event history remains queryable after source cleanup"
query_event_marker "${start_ns}" "${first_marker}" >"${WORK_DIR}/post-cleanup-first-event.json"
[ "$(event_marker_count "${WORK_DIR}/post-cleanup-first-event.json" "${first_marker}")" = "1" ] \
  || fail "The first accepted Event history changed after Kubernetes source cleanup."
query_event_marker "${start_ns}" "${second_marker}" >"${WORK_DIR}/post-cleanup-second-event.json"
[ "$(event_marker_count "${WORK_DIR}/post-cleanup-second-event.json" "${second_marker}")" = "1" ] \
  || fail "The second accepted Event history changed after Kubernetes source cleanup."

echo "v0.11.6.1.2 singleton Kubernetes Events and Grafana Loki data-source acceptance passed."

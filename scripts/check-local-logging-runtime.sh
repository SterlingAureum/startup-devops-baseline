#!/usr/bin/env bash
set -Eeuo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
LOKI_APP="${LOKI_APP:-logging-loki}"
ALLOY_APP="${ALLOY_APP:-logging-alloy}"
LOKI_STATEFULSET="${LOKI_STATEFULSET:-observability-logs}"
LOKI_GATEWAY_DEPLOYMENT="${LOKI_GATEWAY_DEPLOYMENT:-observability-logs-gateway}"
LOKI_GATEWAY_SERVICE="${LOKI_GATEWAY_SERVICE:-observability-logs-gateway}"
ALLOY_DAEMONSET="${ALLOY_DAEMONSET:-observability-logs-collector}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
APP_CONTAINER="${APP_CONTAINER:-demo-api}"
LOKI_LOCAL_PORT="${LOKI_LOCAL_PORT:-13100}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
QUERY_TIMEOUT_SECONDS="${QUERY_TIMEOUT_SECONDS:-90}"
WORK_DIR="$(mktemp -d)"
LOKI_PF_PID=""

cleanup() {
  if [ -n "${LOKI_PF_PID}" ] && kill -0 "${LOKI_PF_PID}" >/dev/null 2>&1; then
    kill "${LOKI_PF_PID}" >/dev/null 2>&1 || true
    wait "${LOKI_PF_PID}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

for command_name in curl jq kubectl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "required command not found: ${command_name}"
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

select_ready_demo_pod() {
  kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o json \
    | jq -r '
      [
        .items[]
        | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
      ]
      | sort_by(.metadata.creationTimestamp)
      | last
      | .metadata.name // empty
    '
}

query_loki() {
  local start_ns="$1"
  curl -fsS --get "http://127.0.0.1:${LOKI_LOCAL_PORT}/loki/api/v1/query_range" \
    --data-urlencode 'query={environment="local",cluster="startup-devops-local",namespace="startup-apps",application="demo-api",container="demo-api",severity="INFO"}' \
    --data-urlencode "start=${start_ns}" \
    --data-urlencode 'direction=backward' \
    --data-urlencode 'limit=1000'
}

result_contains_pod_request() {
  local response_file="$1"
  local pod_name="$2"
  local release_id="$3"
  jq -e --arg pod "${pod_name}" --arg release "${release_id}" '
    [
      .data.result[].values[]?[1]
      | fromjson?
      | select(
          .["kubernetes.pod.name"] == $pod
          and .["platform.release.id"] == $release
          and .message == "http_request_completed"
          and .["http.route"] == "/version"
          and .["http.response.status_code"] == 200
        )
    ]
    | length > 0
  ' "${response_file}" >/dev/null
}

echo "==> Waiting for logging Applications"
wait_application "${LOKI_APP}"
wait_application "${ALLOY_APP}"

echo "==> Waiting for Loki and Alloy workloads"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  "statefulset/${LOKI_STATEFULSET}" --timeout="${TIMEOUT_SECONDS}s"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  "deployment/${LOKI_GATEWAY_DEPLOYMENT}" --timeout="${TIMEOUT_SECONDS}s"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status \
  "daemonset/${ALLOY_DAEMONSET}" --timeout="${TIMEOUT_SECONDS}s"

echo "==> Checking private services and NetworkPolicies"
[ "$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${LOKI_GATEWAY_SERVICE}" -o jsonpath='{.spec.type}')" = "ClusterIP" ] \
  || fail "Loki gateway Service is not ClusterIP."
kubectl -n "${OBSERVABILITY_NAMESPACE}" get networkpolicy observability-logs-cluster-only >/dev/null
kubectl -n "${OBSERVABILITY_NAMESPACE}" get networkpolicy observability-logs-collector >/dev/null
kubectl -n "${OBSERVABILITY_NAMESPACE}" get ingress -o json \
  | jq -e '[.items[] | select(.metadata.name | startswith("observability-logs"))] | length == 0' >/dev/null \
  || fail "A logging Ingress is present."
kubectl -n "${OBSERVABILITY_NAMESPACE}" get service -o json \
  | jq -e '[.items[] | select(.metadata.name | startswith("observability-logs")) | .spec.type] | all(. == "ClusterIP")' >/dev/null \
  || fail "A logging Service is publicly exposed."

echo "==> Selecting a Ready demo-api Pod and generating one bounded request"
old_pod="$(select_ready_demo_pod)"
[ -n "${old_pod}" ] || fail "no Ready demo-api Pod was found."
kubectl -n "${APP_NAMESPACE}" get pod "${old_pod}" -o json >"${WORK_DIR}/old-pod.json"
release_id="$(jq -r '.metadata.annotations["platform.startup.dev/release-id"] // empty' "${WORK_DIR}/old-pod.json")"
[ -n "${release_id}" ] || fail "the selected demo-api Pod lacks the canonical release ID annotation."
start_ns="$(python3 -c 'import time; print(time.time_ns() - 600_000_000_000)')"
kubectl -n "${APP_NAMESPACE}" exec "${old_pod}" -c "${APP_CONTAINER}" -- \
  python -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8080/version", timeout=5).read()' \
  >/dev/null

echo "==> Starting a private Loki API tunnel"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward \
  "service/${LOKI_GATEWAY_SERVICE}" "${LOKI_LOCAL_PORT}:80" \
  >"${WORK_DIR}/loki-port-forward.log" 2>&1 &
LOKI_PF_PID="$!"

deadline=$((SECONDS + 30))
until curl -fsS "http://127.0.0.1:${LOKI_LOCAL_PORT}/loki/api/v1/labels" >/dev/null 2>&1; do
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    cat "${WORK_DIR}/loki-port-forward.log" >&2 || true
    fail "Loki API did not become reachable through the private tunnel."
  fi
  sleep 1
done

echo "==> Waiting for the structured demo-api log in Loki"
deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))
until [ "${SECONDS}" -ge "${deadline}" ]; do
  if query_loki "${start_ns}" >"${WORK_DIR}/query.json" 2>/dev/null \
    && result_contains_pod_request "${WORK_DIR}/query.json" "${old_pod}" "${release_id}"; then
    break
  fi
  sleep 2
done
result_contains_pod_request "${WORK_DIR}/query.json" "${old_pod}" "${release_id}" \
  || fail "Loki did not return the expected structured demo-api request log."

echo "==> Checking the bounded Loki indexed-label inventory"
curl -fsS --get "http://127.0.0.1:${LOKI_LOCAL_PORT}/loki/api/v1/labels" \
  --data-urlencode "start=${start_ns}" >"${WORK_DIR}/labels.json"
python3 - "${WORK_DIR}/labels.json" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text())
if payload.get("status") != "success":
    raise SystemExit("Loki label API did not return success")
observed = set(payload.get("data", []))
allowed = {"environment", "cluster", "namespace", "application", "container", "severity"}
required = {"environment", "cluster", "namespace", "application", "container", "severity"}
unexpected = sorted(observed - allowed)
missing = sorted(required - observed)
if unexpected:
    raise SystemExit(f"Unexpected indexed Loki labels: {', '.join(unexpected)}")
if missing:
    raise SystemExit(f"Required indexed Loki labels were not observed: {', '.join(missing)}")
print("Indexed Loki labels are exactly bounded by the v0.11.6 contract.")
PY

echo "==> Replacing the source Pod and proving the old log remains queryable"
kubectl -n "${APP_NAMESPACE}" delete pod "${old_pod}" --wait=true >/dev/null
deadline=$((SECONDS + TIMEOUT_SECONDS))
new_pod=""
until [ "${SECONDS}" -ge "${deadline}" ]; do
  new_pod="$(select_ready_demo_pod)"
  if [ -n "${new_pod}" ] && [ "${new_pod}" != "${old_pod}" ]; then
    break
  fi
  sleep 3
done
[ -n "${new_pod}" ] && [ "${new_pod}" != "${old_pod}" ] \
  || fail "a replacement Ready demo-api Pod did not appear."

query_loki "${start_ns}" >"${WORK_DIR}/post-replacement-query.json"
result_contains_pod_request "${WORK_DIR}/post-replacement-query.json" "${old_pod}" "${release_id}" \
  || fail "the pre-replacement demo-api log disappeared after replacing its source Pod."

echo "v0.11.6.1.1 local Loki Monolithic and Alloy Pod-log runtime acceptance passed."

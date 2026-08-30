#!/usr/bin/env bash
set -Eeuo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
APP_CONTAINER="${APP_CONTAINER:-demo-api}"
DEMO_APP="${DEMO_APP:-demo-api}"
MONITORING_APP="${MONITORING_APP:-monitoring}"
LOKI_APP="${LOKI_APP:-logging-loki}"
COLLECTOR_APP="${COLLECTOR_APP:-tracing-otel-collector}"
TEMPO_APP="${TEMPO_APP:-tracing-tempo}"
LOKI_GATEWAY_SERVICE="${LOKI_GATEWAY_SERVICE:-observability-logs-gateway}"
LOKI_SERVICE="${LOKI_SERVICE:-observability-logs}"
TEMPO_SERVICE="${TEMPO_SERVICE:-observability-tempo}"
GRAFANA_SERVICE="${GRAFANA_SERVICE:-observability-metrics-grafana}"
GRAFANA_SECRET="${GRAFANA_SECRET:-observability-metrics-grafana}"
QUERY_TIMEOUT_SECONDS="${QUERY_TIMEOUT_SECONDS:-90}"
APPLICATION_TIMEOUT_SECONDS="${APPLICATION_TIMEOUT_SECONDS:-240}"
WORK_DIR="$(mktemp -d)"
LOKI_PF_PID=""
TEMPO_PF_PID=""
GRAFANA_PF_PID=""
LOKI_DIRECT_PF_PID=""

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

cleanup() {
  local status="$?"
  local pid
  if [ "${status}" -ne 0 ]; then
    echo "==> v0.11.6.2.2 failure diagnostics" >&2
    kubectl -n "${ARGOCD_NAMESPACE}" get application \
      "${DEMO_APP}" "${MONITORING_APP}" "${LOKI_APP}" "${COLLECTOR_APP}" "${TEMPO_APP}" \
      -o wide >&2 || true
    kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o wide >&2 || true
    kubectl -n "${APP_NAMESPACE}" logs -l "${APP_SELECTOR}" -c "${APP_CONTAINER}" \
      --since=10m --tail=200 >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get pods -o wide >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" logs deployment/observability-otel-collector \
      --tail=100 >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" logs deployment/observability-tempo \
      --tail=100 >&2 || true
    echo "==> Loki gateway failure boundary" >&2
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get service \
      "${LOKI_GATEWAY_SERVICE}" "${LOKI_SERVICE}" -o wide >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get endpoints \
      "${LOKI_GATEWAY_SERVICE}" "${LOKI_SERVICE}" -o wide >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get endpointslice \
      -l 'kubernetes.io/service-name in (observability-logs-gateway,observability-logs)' \
      -o wide >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get networkpolicy \
      observability-logs-cluster-only -o yaml >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" logs \
      deployment/observability-logs-gateway --all-containers --tail=100 >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" logs \
      statefulset/observability-logs --all-containers --tail=100 >&2 || true
    loki_direct_port="$(free_port 2>/dev/null || true)"
    if [ -n "${loki_direct_port}" ]; then
      kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${LOKI_SERVICE}" \
        "${loki_direct_port}:3100" >"${WORK_DIR}/loki-direct-port-forward.log" 2>&1 &
      LOKI_DIRECT_PF_PID="$!"
      sleep 2
      curl -sS --max-time 5 -D "${WORK_DIR}/loki-direct-headers.txt" \
        -o "${WORK_DIR}/loki-direct-body.txt" \
        "http://127.0.0.1:${loki_direct_port}/loki/api/v1/labels" || true
      echo "==> Direct Loki API response" >&2
      [ -s "${WORK_DIR}/loki-direct-headers.txt" ] \
        && cat "${WORK_DIR}/loki-direct-headers.txt" >&2 || true
      [ -s "${WORK_DIR}/loki-direct-body.txt" ] \
        && sed -n '1,80p' "${WORK_DIR}/loki-direct-body.txt" >&2 || true
    fi
    for log_file in "${WORK_DIR}"/*-port-forward.log; do
      [ -s "${log_file}" ] && cat "${log_file}" >&2 || true
    done
  fi
  for pid in "${LOKI_PF_PID}" "${TEMPO_PF_PID}" "${GRAFANA_PF_PID}" "${LOKI_DIRECT_PF_PID}"; do
    if [ -n "${pid}" ] && kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
      wait "${pid}" >/dev/null 2>&1 || true
    fi
  done
  rm -rf -- "${WORK_DIR}"
  exit "${status}"
}
trap cleanup EXIT

for command_name in base64 curl jq kubectl python3; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || fail "required command not found: ${command_name}"
done

wait_application() {
  local name="$1"
  local deadline=$((SECONDS + APPLICATION_TIMEOUT_SECONDS))
  local sync=""
  local health=""
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" \
      -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
    health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" \
      -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
    if [ "${sync}" = "Synced" ] && [ "${health}" = "Healthy" ]; then
      return 0
    fi
    sleep 2
  done
  fail "Application/${name} did not become Synced/Healthy; sync=${sync:-unknown} health=${health:-unknown}"
}

free_port() {
  python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

wait_http() {
  local url="$1"
  local log_file="$2"
  local deadline=$((SECONDS + 30))
  local response_body="${WORK_DIR}/http-response-$(printf '%s' "${url}" | tr -cs '[:alnum:]' '-').txt"
  local response_headers="${response_body%.txt}-headers.txt"
  local http_status="000"
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    http_status="$(curl -sS --max-time 5 -D "${response_headers}" \
      -o "${response_body}" -w '%{http_code}' "${url}" 2>/dev/null || true)"
    case "${http_status}" in
      2??) return 0 ;;
    esac
    sleep 1
  done
  [ -s "${log_file}" ] && cat "${log_file}" >&2 || true
  echo "last HTTP status: ${http_status:-000}" >&2
  [ -s "${response_headers}" ] && cat "${response_headers}" >&2 || true
  [ -s "${response_body}" ] && sed -n '1,80p' "${response_body}" >&2 || true
  fail "endpoint did not return HTTP 2xx: ${url}"
}

echo "==> Waiting for the real local tracing path"
for application in "${DEMO_APP}" "${MONITORING_APP}" "${LOKI_APP}" "${COLLECTOR_APP}" "${TEMPO_APP}"; do
  wait_application "${application}"
done

kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o json >"${WORK_DIR}/demo-pods.json"
demo_pod="$(jq -r '[.items[] | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))] | sort_by(.metadata.creationTimestamp) | last | .metadata.name // empty' "${WORK_DIR}/demo-pods.json")"
[ -n "${demo_pod}" ] || fail "no Ready demo-api Pod was found"

echo "==> Checking the local-only exporter and private network boundary"
kubectl -n "${APP_NAMESPACE}" get pod "${demo_pod}" -o json >"${WORK_DIR}/demo-pod.json"
jq -e --arg container "${APP_CONTAINER}" '
  [.spec.containers[] | select(.name == $container)][0].env
  | map({key: .name, value: (.value // "")}) | from_entries
  | .TRACING_ENABLED == "true"
    and .OTEL_EXPORTER_OTLP_TRACES_ENDPOINT == "http://observability-otel-collector.observability.svc.cluster.local:4318/v1/traces"
    and .OTEL_EXPORTER_OTLP_PROTOCOL == "http/protobuf"
    and .OTEL_EXPORTER_OTLP_TRACES_TIMEOUT == "5"
' "${WORK_DIR}/demo-pod.json" >/dev/null \
  || fail "demo-api does not carry the accepted local OTLP exporter settings"

[ "$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${TEMPO_SERVICE}" -o jsonpath='{.spec.type}')" = "ClusterIP" ] \
  || fail "Tempo is not private ClusterIP"
kubectl -n "${OBSERVABILITY_NAMESPACE}" get networkpolicy grafana-cluster-only \
  observability-otel-collector-cluster-only observability-tempo-cluster-only >/dev/null

loki_port="$(free_port)"
tempo_port="$(free_port)"
grafana_port="$(free_port)"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${LOKI_GATEWAY_SERVICE}" \
  "${loki_port}:80" >"${WORK_DIR}/loki-port-forward.log" 2>&1 &
LOKI_PF_PID="$!"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${TEMPO_SERVICE}" \
  "${tempo_port}:3200" >"${WORK_DIR}/tempo-port-forward.log" 2>&1 &
TEMPO_PF_PID="$!"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${GRAFANA_SERVICE}" \
  "${grafana_port}:80" >"${WORK_DIR}/grafana-port-forward.log" 2>&1 &
GRAFANA_PF_PID="$!"
wait_http "http://127.0.0.1:${loki_port}/loki/api/v1/labels" "${WORK_DIR}/loki-port-forward.log"
wait_http "http://127.0.0.1:${tempo_port}/ready" "${WORK_DIR}/tempo-port-forward.log"
wait_http "http://127.0.0.1:${grafana_port}/api/health" "${WORK_DIR}/grafana-port-forward.log"

echo "==> Checking the provisioned Loki-to-Tempo correlation contract"
grafana_user="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" -o jsonpath='{.data.admin-user}' | base64 --decode)"
grafana_password="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get secret "${GRAFANA_SECRET}" -o jsonpath='{.data.admin-password}' | base64 --decode)"
[ -n "${grafana_user}" ] && [ -n "${grafana_password}" ] || fail "Grafana credentials are unavailable"

curl -fsS -u "${grafana_user}:${grafana_password}" \
  "http://127.0.0.1:${grafana_port}/api/datasources/uid/loki" >"${WORK_DIR}/grafana-loki.json"
curl -fsS -u "${grafana_user}:${grafana_password}" \
  "http://127.0.0.1:${grafana_port}/api/datasources/uid/tempo" >"${WORK_DIR}/grafana-tempo.json"
jq -e '
  .uid == "loki" and .type == "loki" and .readOnly == true
  and any(.jsonData.derivedFields[]?;
    .name == "TraceID"
    and .datasourceUid == "tempo"
    and .matcherRegex == "\"trace_id\":\"([0-9a-f]{32})\"")
' "${WORK_DIR}/grafana-loki.json" >/dev/null \
  || fail "Grafana Loki data source does not expose the accepted TraceID derived field"
jq -e '
  .name == "Tempo" and .uid == "tempo" and .type == "tempo"
  and .access == "proxy"
  and .url == "http://observability-tempo.observability.svc.cluster.local:3200"
  and .isDefault == false and .readOnly == true
' "${WORK_DIR}/grafana-tempo.json" >/dev/null \
  || fail "Grafana Tempo data source does not match the private provisioned contract"
for uid in loki tempo; do
  curl -fsS -u "${grafana_user}:${grafana_password}" \
    "http://127.0.0.1:${grafana_port}/api/datasources/uid/${uid}/health" \
    >"${WORK_DIR}/grafana-${uid}-health.json"
  jq -e '.status == "OK"' "${WORK_DIR}/grafana-${uid}-health.json" >/dev/null \
    || fail "Grafana data source health failed: ${uid}"
done

trace_id="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
parent_span_id="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
start_ns="$(python3 -c 'import time; print(time.time_ns() - 5_000_000_000)')"

echo "==> Sending one real W3C-correlated GET /version request"
kubectl -n "${APP_NAMESPACE}" exec "${demo_pod}" -c "${APP_CONTAINER}" -- \
  python -c 'import sys, urllib.request; trace_id, parent_id = sys.argv[1:3]; request=urllib.request.Request("http://demo-api-stable.startup-apps.svc.cluster.local/version", headers={"traceparent": f"00-{trace_id}-{parent_id}-01"}); response=urllib.request.urlopen(request, timeout=10); body=response.read(); status=response.status; response.close(); print(status); raise SystemExit(0 if status == 200 and body else 1)' \
  "${trace_id}" "${parent_span_id}" | grep -qx '200'

query_loki() {
  local output="$1"
  local logql
  printf -v logql '%s |= "\\"trace_id\\":\\"%s\\""' \
    '{environment="local",cluster="startup-devops-local",namespace="startup-apps",application="demo-api",container="demo-api"}' \
    "${trace_id}"
  curl -fsS --get "http://127.0.0.1:${loki_port}/loki/api/v1/query_range" \
    --data-urlencode "query=${logql}" --data-urlencode "start=${start_ns}" \
    --data-urlencode 'direction=backward' --data-urlencode 'limit=20' >"${output}"
}

echo "==> Waiting for the correlated JSON log in Loki"
deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  if query_loki "${WORK_DIR}/loki-trace.json" 2>/dev/null \
    && jq -e '[.data.result[].values[]?[1] | fromjson | select(.trace_id == $trace)] | length == 1' \
      --arg trace "${trace_id}" "${WORK_DIR}/loki-trace.json" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
query_loki "${WORK_DIR}/loki-trace.json" || fail "Loki trace correlation query failed"
span_id="$(jq -r --arg trace "${trace_id}" '[.data.result[].values[]?[1] | fromjson | select(.trace_id == $trace)] | first | .span_id // empty' "${WORK_DIR}/loki-trace.json")"
[[ "${span_id}" =~ ^[0-9a-f]{16}$ ]] || fail "Loki did not return one valid correlated span_id"
jq -e 'all(.data.result[]; (.stream | has("trace_id") | not) and (.stream | has("span_id") | not))' \
  "${WORK_DIR}/loki-trace.json" >/dev/null \
  || fail "trace_id or span_id entered the Loki indexed label set"

echo "==> Querying the same real trace from Tempo"
deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))
while [ "${SECONDS}" -lt "${deadline}" ]; do
  if curl -fsS -H 'Accept: application/json' \
    "http://127.0.0.1:${tempo_port}/api/v2/traces/${trace_id}" \
    >"${WORK_DIR}/tempo-trace.json" 2>/dev/null \
    && python3 - "${WORK_DIR}/tempo-trace.json" "${span_id}" <<'PY'
import json
from pathlib import Path
import sys

value = json.loads(Path(sys.argv[1]).read_text())
encoded = json.dumps(value, sort_keys=True)
for marker in (
    sys.argv[2], "demo-api", "GET /version", "http.request.method",
    "http.route", "/version", "http.response.status_code",
):
    if marker not in encoded:
        raise SystemExit(1)
PY
  then
    break
  fi
  sleep 2
done
python3 - "${WORK_DIR}/tempo-trace.json" "${span_id}" <<'PY'
import json
from pathlib import Path
import sys

value = json.loads(Path(sys.argv[1]).read_text())
encoded = json.dumps(value, sort_keys=True)
required = (
    sys.argv[2], "demo-api", "GET /version", "http.request.method",
    "http.route", "/version", "http.response.status_code",
)
missing = [marker for marker in required if marker not in encoded]
if missing:
    raise SystemExit(f"Tempo real trace markers missing: {missing}")
PY

echo "v0.11.6.2.2 real HTTP trace, Loki JSON correlation, bounded labels, Tempo query, and Grafana derived-field acceptance passed."

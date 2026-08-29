#!/usr/bin/env bash
set -Eeuo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
APP_CONTAINER="${APP_CONTAINER:-demo-api}"
COLLECTOR_APP="${COLLECTOR_APP:-tracing-otel-collector}"
TEMPO_APP="${TEMPO_APP:-tracing-tempo}"
COLLECTOR_DEPLOYMENT="${COLLECTOR_DEPLOYMENT:-observability-otel-collector}"
COLLECTOR_SERVICE="${COLLECTOR_SERVICE:-observability-otel-collector}"
COLLECTOR_SELECTOR="${COLLECTOR_SELECTOR:-app.kubernetes.io/instance=observability-otel-collector}"
TEMPO_DEPLOYMENT="${TEMPO_DEPLOYMENT:-observability-tempo}"
TEMPO_SERVICE="${TEMPO_SERVICE:-observability-tempo}"
TIMEOUT="${TIMEOUT:-180s}"
QUERY_TIMEOUT_SECONDS="${QUERY_TIMEOUT_SECONDS:-90}"
WORK_DIR="$(mktemp -d)"
TEMPO_PF_PID=""
TEMPO_PF_LOG="${WORK_DIR}/tempo-port-forward.log"

diagnostics() {
  local status="$?"
  if [ "${status}" -ne 0 ]; then
    echo "==> v0.11.6.2.1 failure diagnostics" >&2
    kubectl -n "${ARGOCD_NAMESPACE}" get application "${TEMPO_APP}" "${COLLECTOR_APP}" -o wide >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" get deployment,pod,service,networkpolicy -l app.kubernetes.io/part-of=startup-devops-baseline -o wide >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" logs deployment/"${COLLECTOR_DEPLOYMENT}" --tail=100 >&2 || true
    kubectl -n "${OBSERVABILITY_NAMESPACE}" logs deployment/"${TEMPO_DEPLOYMENT}" --tail=100 >&2 || true
    if [ -s "${TEMPO_PF_LOG}" ]; then
      cat "${TEMPO_PF_LOG}" >&2
    fi
  fi
  if [ -n "${TEMPO_PF_PID}" ] && kill -0 "${TEMPO_PF_PID}" >/dev/null 2>&1; then
    kill "${TEMPO_PF_PID}" >/dev/null 2>&1 || true
    wait "${TEMPO_PF_PID}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${WORK_DIR}"
  exit "${status}"
}
trap diagnostics EXIT

for command_name in curl jq kubectl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

wait_application() {
  local name="$1"
  local deadline=$((SECONDS + 180))
  while [ "${SECONDS}" -lt "${deadline}" ]; do
    local sync health
    sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o jsonpath='{.status.sync.status}' 2>/dev/null || true)"
    health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" -o jsonpath='{.status.health.status}' 2>/dev/null || true)"
    if [ "${sync}" = "Synced" ] && [ "${health}" = "Healthy" ]; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: Application ${name} did not become Synced/Healthy." >&2
  return 1
}

echo "==> Waiting for private tracing Applications and workloads"
wait_application "${TEMPO_APP}"
wait_application "${COLLECTOR_APP}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status deployment/"${TEMPO_DEPLOYMENT}" --timeout="${TIMEOUT}"
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status deployment/"${COLLECTOR_DEPLOYMENT}" --timeout="${TIMEOUT}"

for service in "${TEMPO_SERVICE}" "${COLLECTOR_SERVICE}"; do
  service_type="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${service}" -o jsonpath='{.spec.type}')"
  [ "${service_type}" = "ClusterIP" ] || {
    echo "ERROR: ${service} is not private ClusterIP: ${service_type}" >&2
    exit 1
  }
done

python3 - \
  "$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${COLLECTOR_SERVICE}" -o json)" \
  "$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get service "${TEMPO_SERVICE}" -o json)" <<'PY'
import json
import sys

collector = json.loads(sys.argv[1])
tempo = json.loads(sys.argv[2])
collector_ports = {item["port"] for item in collector["spec"].get("ports", [])}
tempo_ports = {item["port"] for item in tempo["spec"].get("ports", [])}
if collector_ports != {4318}:
    raise SystemExit(f"Collector Service port set changed: {sorted(collector_ports)}")
if tempo_ports != {3200, 4318}:
    raise SystemExit(f"Tempo Service port set changed: {sorted(tempo_ports)}")
PY

echo "==> Selecting a Ready demo-api Pod and proving export remains disabled"
kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o json >"${WORK_DIR}/demo-pods.json"
demo_pod="$(jq -r '[.items[] | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))] | sort_by(.metadata.creationTimestamp) | last | .metadata.name // empty' "${WORK_DIR}/demo-pods.json")"
[ -n "${demo_pod}" ] || {
  echo "ERROR: no Ready demo-api Pod found." >&2
  exit 1
}
tracing_enabled="$(kubectl -n "${APP_NAMESPACE}" get pod "${demo_pod}" -o json | jq -r --arg container "${APP_CONTAINER}" '.spec.containers[] | select(.name == $container) | [.env[]? | select(.name == "TRACING_ENABLED") | .value] | first // empty')"
[ "${tracing_enabled}" = "false" ] || {
  echo "ERROR: demo-api export is not disabled: TRACING_ENABLED=${tracing_enabled}" >&2
  exit 1
}

trace_id="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
span_id="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
python3 - "${trace_id}" "${span_id}" >"${WORK_DIR}/trace.json" <<'PY'
import base64
import json
import sys
import time

trace_id, span_id = sys.argv[1:]
start = time.time_ns()
payload = {
    "resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": "v0.11.6.2.1-acceptance"}},
            {"key": "deployment.environment.name", "value": {"stringValue": "local"}},
        ]},
        "scopeSpans": [{
            "scope": {"name": "startup-devops-baseline.acceptance", "version": "v0.11.6.2.1"},
            "spans": [{
                "traceId": base64.b64encode(bytes.fromhex(trace_id)).decode(),
                "spanId": base64.b64encode(bytes.fromhex(span_id)).decode(),
                "name": "v0.11.6.2.1.synthetic.collector-tempo",
                "kind": 1,
                "startTimeUnixNano": str(start),
                "endTimeUnixNano": str(start + 1_000_000),
                "attributes": [{"key": "test.run_id", "value": {"stringValue": trace_id}}],
                "status": {"code": 1},
            }],
        }],
    }],
}
print(json.dumps(payload, separators=(",", ":")))
PY

echo "==> Sending one synthetic OTLP trace through the Collector"
kubectl -n "${APP_NAMESPACE}" exec -i "${demo_pod}" -c "${APP_CONTAINER}" -- \
  python -c 'import sys, urllib.request; data=sys.stdin.buffer.read(); request=urllib.request.Request("http://observability-otel-collector.observability.svc.cluster.local:4318/v1/traces", data=data, headers={"Content-Type":"application/json"}, method="POST"); response=urllib.request.urlopen(request, timeout=10); print(response.status); response.close()' \
  <"${WORK_DIR}/trace.json" | grep -qx '200'

tempo_local_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
kubectl -n "${OBSERVABILITY_NAMESPACE}" port-forward service/"${TEMPO_SERVICE}" "${tempo_local_port}:3200" \
  >"${TEMPO_PF_LOG}" 2>&1 &
TEMPO_PF_PID="$!"

tempo_url="http://127.0.0.1:${tempo_local_port}"
deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))
until curl -fsS "${tempo_url}/ready" >/dev/null 2>&1; do
  [ "${SECONDS}" -lt "${deadline}" ] || {
    echo "ERROR: Tempo port-forward did not become ready." >&2
    exit 1
  }
  sleep 1
done

query_trace() {
  local output="$1"
  local query_deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))
  while [ "${SECONDS}" -lt "${query_deadline}" ]; do
    if curl -fsS -H 'Accept: application/json' "${tempo_url}/api/v2/traces/${trace_id}" >"${output}" 2>/dev/null; then
      python3 - "${output}" "${trace_id}" <<'PY' && return 0
import json
from pathlib import Path
import sys

value = json.loads(Path(sys.argv[1]).read_text())
encoded = json.dumps(value, sort_keys=True)
for marker in (
    "v0.11.6.2.1.synthetic.collector-tempo",
    "v0.11.6.2.1-acceptance",
    sys.argv[2],
):
    if marker not in encoded:
        raise SystemExit(1)
PY
    fi
    sleep 2
  done
  return 1
}

echo "==> Querying the accepted trace from Tempo"
query_trace "${WORK_DIR}/trace-before-replacement.json" || {
  echo "ERROR: synthetic trace was not queryable from Tempo." >&2
  exit 1
}

echo "==> Replacing the Collector Pod and preserving Tempo-owned history"
collector_pod="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get pods -l "${COLLECTOR_SELECTOR}" -o json | jq -r '[.items[] | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))] | first | .metadata.name // empty')"
[ -n "${collector_pod}" ] || {
  echo "ERROR: no Ready Collector Pod found." >&2
  exit 1
}
kubectl -n "${OBSERVABILITY_NAMESPACE}" delete pod "${collector_pod}" --wait=true
kubectl -n "${OBSERVABILITY_NAMESPACE}" rollout status deployment/"${COLLECTOR_DEPLOYMENT}" --timeout="${TIMEOUT}"
replacement_pod="$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get pods -l "${COLLECTOR_SELECTOR}" -o json | jq -r '[.items[] | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))] | first | .metadata.name // empty')"
[ -n "${replacement_pod}" ] && [ "${replacement_pod}" != "${collector_pod}" ] || {
  echo "ERROR: Collector Pod replacement was not observed." >&2
  exit 1
}

query_trace "${WORK_DIR}/trace-after-replacement.json" || {
  echo "ERROR: accepted trace disappeared after Collector Pod replacement." >&2
  exit 1
}

echo "v0.11.6.2.1 private Collector-to-Tempo synthetic trace, disabled application export, and Collector replacement history acceptance passed."

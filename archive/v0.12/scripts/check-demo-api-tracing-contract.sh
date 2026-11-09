#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
APP_CONTAINER="${APP_CONTAINER:-demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command_name in jq kubectl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

[ -n "${IMAGE_TAG}" ] || {
  echo "ERROR: IMAGE_TAG must identify the unique v0.11.6.2.0 image." >&2
  exit 1
}

echo "==> Selecting the newest Ready demo-api Pod"
kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o json \
  >"${WORK_DIR}/pods.json"
pod_name="$({
  jq -r '
    [
      .items[]
      | select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    ]
    | sort_by(.metadata.creationTimestamp)
    | last
    | .metadata.name // empty
  ' "${WORK_DIR}/pods.json"
})"
[ -n "${pod_name}" ] || {
  echo "ERROR: no Ready demo-api Pod was found." >&2
  kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o wide >&2
  exit 1
}

kubectl -n "${APP_NAMESPACE}" get pod "${pod_name}" -o json \
  >"${WORK_DIR}/pod.json"

echo "==> Proving the unique image and disabled-by-default OTLP boundary"
python3 - "${WORK_DIR}/pod.json" "${APP_CONTAINER}" "${IMAGE_TAG}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


pod = json.loads(Path(sys.argv[1]).read_text())
container_name = sys.argv[2]
image_tag = sys.argv[3]
containers = {
    container["name"]: container
    for container in pod.get("spec", {}).get("containers", [])
}
if container_name not in containers:
    raise SystemExit(f"Container {container_name!r} was not found")
container = containers[container_name]
image = container.get("image", "")
if not (image.endswith(f":{image_tag}") or f":{image_tag}@sha256:" in image):
    raise SystemExit(f"Pod image {image!r} does not use IMAGE_TAG={image_tag!r}")

environment = {
    item["name"]: item.get("value")
    for item in container.get("env", [])
    if "name" in item and "value" in item
}
expected = {
    "TRACING_ENABLED": "false",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT": "5",
}
for name, value in expected.items():
    if environment.get(name) != value:
        raise SystemExit(
            f"Pod environment mismatch for {name}: "
            f"expected {value!r}, observed {environment.get(name)!r}"
        )
endpoint = environment.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
if endpoint != (
    "http://observability-otel-collector.observability.svc.cluster.local:4318/"
    "v1/traces"
):
    raise SystemExit("Pod does not carry the bounded future Collector endpoint")
PY

echo "==> Proving the rebuilt image contains the exact SDK contract without enabling it"
kubectl -n "${APP_NAMESPACE}" exec -i "${pod_name}" -c "${APP_CONTAINER}" -- \
  python - <<'PY'
from importlib.metadata import version
from src import tracing


expected = {
    "opentelemetry-api": "1.44.0",
    "opentelemetry-sdk": "1.44.0",
    "opentelemetry-exporter-otlp-proto-http": "1.44.0",
}
observed = {name: version(name) for name in expected}
if observed != expected:
    raise SystemExit(f"OpenTelemetry dependency mismatch: {observed!r}")
if tracing.tracing_enabled():
    raise SystemExit("Tracing unexpectedly enabled in the v0.11.6.2.0 checkpoint")
if tracing.configure_tracing() is not None:
    raise SystemExit("Disabled tracing created a provider")
if tracing._CONFIGURED_PROVIDER is not None:
    raise SystemExit("Disabled tracing retained a configured provider")
print("Exact OpenTelemetry dependencies are present and export remains disabled.")
PY

echo "==> Re-running the accepted structured logging contract"
APP_NAMESPACE="${APP_NAMESPACE}" \
APP_SELECTOR="${APP_SELECTOR}" \
APP_CONTAINER="${APP_CONTAINER}" \
  "${ROOT_DIR}/scripts/check-demo-api-structured-logs.sh"

echo "==> Proving disabled tracing does not emit fabricated correlation identifiers"
kubectl -n "${APP_NAMESPACE}" logs "${pod_name}" -c "${APP_CONTAINER}" --since=5m \
  >"${WORK_DIR}/demo-api.log"
python3 - "${WORK_DIR}/demo-api.log" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


records = []
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip():
        continue
    value = json.loads(line)
    if value.get("message") == "http_request_completed":
        records.append(value)
if not records:
    raise SystemExit("No structured request record was available")
for record in records:
    if "trace_id" in record or "span_id" in record:
        raise SystemExit("Disabled tracing emitted a fabricated correlation identifier")
print(f"Validated {len(records)} request records without fabricated trace fields.")
PY

echo "v0.11.6.2.0 demo-api OpenTelemetry tracing contract acceptance passed with OTLP export disabled."

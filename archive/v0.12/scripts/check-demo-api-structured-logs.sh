#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
APP_SELECTOR="${APP_SELECTOR:-app.kubernetes.io/name=demo-api}"
APP_CONTAINER="${APP_CONTAINER:-demo-api}"
LOG_LOOKBACK="${LOG_LOOKBACK:-5m}"
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

echo "==> Selecting the newest Ready demo-api Pod"
kubectl -n "${APP_NAMESPACE}" get pods -l "${APP_SELECTOR}" -o json \
  >"${WORK_DIR}/pods.json"
pod_name="$({
  jq -r '
    [
      .items[]
      | select(
          any(
            .status.conditions[]?;
            .type == "Ready" and .status == "True"
          )
        )
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

echo "==> Generating bounded and deliberately sensitive-looking requests"
kubectl -n "${APP_NAMESPACE}" exec "${pod_name}" -c "${APP_CONTAINER}" -- \
  python -c 'from urllib.request import urlopen; urlopen("http://127.0.0.1:8080/version?token=v011610-sensitive-query", timeout=5).read()' \
  >/dev/null
kubectl -n "${APP_NAMESPACE}" exec "${pod_name}" -c "${APP_CONTAINER}" -- \
  python -c 'from urllib.error import HTTPError; from urllib.request import urlopen; exec("try:\n urlopen(\"http://127.0.0.1:8080/customer/v011610-sensitive-path?authorization=v011610-sensitive-header\", timeout=5).read()\nexcept HTTPError:\n pass")' \
  >/dev/null

echo "==> Waiting for structured request records"
deadline=$((SECONDS + 30))
while true; do
  kubectl -n "${APP_NAMESPACE}" logs "${pod_name}" \
    -c "${APP_CONTAINER}" --since="${LOG_LOOKBACK}" \
    >"${WORK_DIR}/demo-api.log"
  if grep -F 'http_request_completed' "${WORK_DIR}/demo-api.log" >/dev/null; then
    break
  fi
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "ERROR: timed out waiting for a structured request record." >&2
    cat "${WORK_DIR}/demo-api.log" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Validating JSON Lines, release identity, noise, and sensitive-data boundaries"
python3 - "${WORK_DIR}/pod.json" "${WORK_DIR}/demo-api.log" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


pod = json.loads(Path(sys.argv[1]).read_text())
log_text = Path(sys.argv[2]).read_text()
lines = [line for line in log_text.splitlines() if line.strip()]
if not lines:
    raise SystemExit("No demo-api log lines were returned")

records: list[dict[str, Any]] = []
for number, line in enumerate(lines, start=1):
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise SystemExit(f"Log line {number} is not one JSON object: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"Log line {number} is not a JSON object")
    records.append(value)

required = {
    "timestamp",
    "severity",
    "message",
    "service.name",
    "service.version",
    "deployment.environment.name",
    "platform.release.id",
    "platform.source.commit",
    "container.image.digest",
}
for number, record in enumerate(records, start=1):
    missing = sorted(required - record.keys())
    if missing:
        raise SystemExit(f"Log line {number} lacks required fields: {', '.join(missing)}")
    if record["severity"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise SystemExit(f"Log line {number} has an unbounded severity")
    if not str(record["timestamp"]).endswith("Z"):
        raise SystemExit(f"Log line {number} does not use a UTC RFC3339 timestamp")

annotations = pod.get("metadata", {}).get("annotations", {})
expected = {
    "service.version": annotations.get("platform.startup.dev/application-version"),
    "deployment.environment.name": annotations.get("platform.startup.dev/environment"),
    "platform.release.id": annotations.get("platform.startup.dev/release-id"),
    "platform.source.commit": annotations.get("platform.startup.dev/source-commit"),
    "container.image.digest": annotations.get("platform.startup.dev/image-digest"),
}
if any(value in (None, "") for value in expected.values()):
    raise SystemExit("The selected Pod lacks one or more canonical delivery annotations")

for number, record in enumerate(records, start=1):
    if record.get("service.name") != "demo-api":
        raise SystemExit(f"Log line {number} has the wrong service.name")
    for field, value in expected.items():
        if record.get(field) != value:
            raise SystemExit(
                f"Log line {number} identity mismatch for {field}: "
                f"expected {value!r}, observed {record.get(field)!r}"
            )

request_records = [
    record for record in records
    if record.get("message") == "http_request_completed"
]
if not any(
    record.get("http.route") == "/version"
    and record.get("http.response.status_code") == 200
    and record.get("outcome") == "success"
    for record in request_records
):
    raise SystemExit("No successful bounded /version request record was found")
if not any(
    record.get("http.route") == "__unmatched__"
    and record.get("http.response.status_code") == 404
    and record.get("outcome") == "failure"
    for record in request_records
):
    raise SystemExit("No bounded unmatched-route failure record was found")

for record in request_records:
    if (
        record.get("http.route") in {"/health", "/ready", "/metrics"}
        and int(record.get("http.response.status_code", 500)) < 400
    ):
        raise SystemExit("A successful probe or metrics request produced log noise")

for marker in (
    "v011610-sensitive-query",
    "v011610-sensitive-path",
    "v011610-sensitive-header",
):
    if marker in log_text:
        raise SystemExit(f"Sensitive-looking raw request content reached logs: {marker}")

print(f"Validated {len(records)} JSON log records from Pod/{pod['metadata']['name']}.")
PY

echo "v0.11.6.1.0 demo-api structured JSON logging runtime acceptance passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 -m py_compile "${ROOT_DIR}/scripts/generate-synthetic-otlp-trace.py"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Callable


root = Path(sys.argv[1])


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read(relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    return path.read_text()


def load_json(relative: str) -> dict[str, Any]:
    try:
        value = json.loads(read(relative))
    except json.JSONDecodeError as error:
        raise ContractError(f"Invalid JSON in {relative}: {error}") from error
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.11.6.2.1.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.2.1.1", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.2.1", "Bad predecessor")

    incident = value.get("incident", {})
    require(incident.get("failedStage") == "synthetic-otlp-http-ingest", "Wrong failed stage")
    require(incident.get("observedHttpStatus") == 400, "Wrong observed status")
    for key in (
        "tempoApplicationHealthy", "collectorApplicationHealthy",
        "collectorReceiverListening", "networkPathReachedCollector",
    ):
        require(incident.get(key) is True, f"Incident evidence removed: {key}")
    require(incident.get("runtimeResourceDefect") is False, "Runtime defect incorrectly claimed")
    require(
        incident.get("rootCause")
        == "trace-and-span-identifiers-used-base64-instead-of-otlp-json-hex",
        "Root cause changed",
    )

    protocol = value.get("protocol", {})
    require(protocol == {
        "contentType": "application/json",
        "traceIdEncoding": "hexadecimal",
        "traceIdCharacters": 32,
        "spanIdEncoding": "hexadecimal",
        "spanIdCharacters": 16,
        "zeroIdentifiersAllowed": False,
        "identifierFieldCase": "lowerCamelCase",
        "enumEncoding": "integer",
        "timestampEncoding": "decimal-string",
    }, "OTLP/JSON protocol contract changed")

    repair = value.get("repair", {})
    require(
        repair.get("dedicatedPayloadGenerator")
        == "scripts/generate-synthetic-otlp-trace.py",
        "Payload generator changed",
    )
    for key in (
        "base64IdentifiersRemoved", "httpErrorStatusPrinted",
        "httpErrorBodyPrinted", "transportFailurePrinted",
        "tempoAndCollectorDiagnosticsExplicit", "collectorReplacementProofPreserved",
    ):
        require(repair.get(key) is True, f"Repair requirement disabled: {key}")
    require(repair.get("httpErrorBodyLimitBytes") == 4096, "HTTP error body limit changed")

    unchanged = value.get("unchanged", {})
    require(
        (
            unchanged.get("localPlatformChart"),
            unchanged.get("localPlatformApplicationVersion"),
            unchanged.get("collectorChart"),
            unchanged.get("collectorApplicationVersion"),
            unchanged.get("tempoChart"),
            unchanged.get("tempoApplicationVersion"),
        ) == ("0.7.0", "v0.11.6.2.1", "0.172.0", "0.159.0", "0.1.0", "3.0.3"),
        "Runtime version boundary changed",
    )
    version_keys = {
        "localPlatformChart", "localPlatformApplicationVersion", "collectorChart",
        "collectorApplicationVersion", "tempoChart", "tempoApplicationVersion",
    }
    for key, item in unchanged.items():
        if key not in version_keys:
            require(item is False, f"Unchanged boundary expanded: {key}")

    acceptance = value.get("acceptance", {})
    require(
        acceptance.get("offlineValidator")
        == "scripts/validate-v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.sh",
        "Offline validator changed",
    )
    require(acceptance.get("liveEntrypoint") == "scripts/check-local-tracing-runtime.sh", "Live entrypoint changed")
    for key in (
        "validHexPayloadTestRequired", "invalidIdentifierTestsRequired",
        "base64RegressionTestRequired", "httpErrorVisibilityTestRequired",
        "explicitRuntimeDiagnosticsTestRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("consecutiveLiveRunsRequired") == 2, "Two-run proof removed")
    require(acceptance.get("runtimeRedeployRequired") is False, "Unnecessary redeploy required")
    require(acceptance.get("imageRebuildRequired") is False, "Unnecessary image rebuild required")
    require(value.get("nextIncrement", {}).get("version") == "v0.11.6.2.2", "Next increment changed")


contract_path = "delivery/contracts/v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Repair document missing")
require(
    (root / "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json").is_file(),
    "Predecessor contract missing",
)

generator_path = root / contract["repair"]["dedicatedPayloadGenerator"]
spec = importlib.util.spec_from_file_location("synthetic_otlp_trace", generator_path)
require(spec is not None and spec.loader is not None, "Cannot load payload generator")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

trace_id = "0123456789abcdef0123456789abcdef"
span_id = "fedcba9876543210"
payload = generator.build_payload(
    trace_id,
    span_id,
    start_time_unix_nano=1_750_000_000_000_000_000,
)
span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
require(span["traceId"] == trace_id, "Trace ID is not direct hexadecimal")
require(span["spanId"] == span_id, "Span ID is not direct hexadecimal")
require(isinstance(span["kind"], int), "Span kind is not an integer enum")
require(isinstance(span["startTimeUnixNano"], str), "Start timestamp is not a decimal string")
require(isinstance(span["endTimeUnixNano"], str), "End timestamp is not a decimal string")
encoded_payload = json.dumps(payload)
require("ASNFZ4mrze8BI0VniavN7w==" not in encoded_payload, "Base64 trace ID returned")
require("/ty6mHZUMhA=" not in encoded_payload, "Base64 span ID returned")

for name, bad_trace, bad_span in (
    ("Base64 trace ID", "ASNFZ4mrze8BI0VniavN7w==", span_id),
    ("short trace ID", "0123456789abcdef", span_id),
    ("non-hex trace ID", "g" * 32, span_id),
    ("zero trace ID", "0" * 32, span_id),
    ("Base64 span ID", trace_id, "/ty6mHZUMhA="),
    ("short span ID", trace_id, "01234567"),
    ("zero span ID", trace_id, "0" * 16),
):
    try:
        generator.build_payload(bad_trace, bad_span, start_time_unix_nano=1)
    except ValueError:
        continue
    raise ContractError(f"Invalid identifier accepted: {name}")

generator_source = read("scripts/generate-synthetic-otlp-trace.py")
for marker in (
    '"traceId": normalized_trace_id',
    '"spanId": normalized_span_id',
    'TRACE_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")',
    'SPAN_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{16}$")',
    'if int(value, 16) == 0:',
):
    require(marker in generator_source, f"Generator boundary missing: {marker}")
for forbidden in ("import base64", "b64encode", "bytes.fromhex"):
    require(forbidden not in generator_source, f"Base64 regression found: {forbidden}")

live = read("scripts/check-local-tracing-runtime.sh")
for marker in (
    'scripts/generate-synthetic-otlp-trace.py',
    'except urllib.error.HTTPError as error:',
    'error.read(4096)',
    'OTLP HTTP request failed: status=',
    'OTLP HTTP request failed before a response:',
    'get deployment "${TEMPO_DEPLOYMENT}" "${COLLECTOR_DEPLOYMENT}"',
    'get pods -l "${TEMPO_SELECTOR}"',
    'get pods -l "${COLLECTOR_SELECTOR}"',
    'get service "${TEMPO_SERVICE}" "${COLLECTOR_SERVICE}"',
    'get networkpolicy "${TEMPO_SERVICE}-cluster-only" "${COLLECTOR_SERVICE}-cluster-only"',
    'v0.11.6.2.1.1 hex-encoded OTLP/JSON trace',
):
    require(marker in live, f"Live repair marker missing: {marker}")
for forbidden in ("import base64", "b64encode", "bytes.fromhex"):
    require(forbidden not in live, f"Live Base64 regression found: {forbidden}")

predecessor_validator = read("scripts/validate-v0.11.6.2.1-private-local-otel-collector-tempo-runtime.sh")
for marker in (
    "v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.json",
    "Synthetic OTLP/JSON repair successor coverage passed",
):
    require(marker in predecessor_validator, f"Predecessor successor coverage missing: {marker}")

correlation_successor = (
    root / "delivery/contracts/v0.11.6.2.2-real-demo-api-trace-log-correlation.json"
).is_file()
closure_successor = (
    root / "delivery/contracts/v0.11.6.2.3-local-minimal-tracing-closure.json"
).is_file()
platform_chart = read("clusters/local/platform/Chart.yaml")
expected_platform = (
    ("version: 0.8.0", 'appVersion: "v0.11.6.2.2"')
    if correlation_successor
    else ("version: 0.7.0", 'appVersion: "v0.11.6.2.1"')
)
require(all(marker in platform_chart for marker in expected_platform), "Platform version changed")
collector_values = read("clusters/local/platform/files/tracing/otel-collector-values.yaml")
require('tag: "0.159.0"' in collector_values, "Collector version changed")
tempo_chart = read("platform/tracing/tempo/Chart.yaml")
require("version: 0.1.0" in tempo_chart and 'appVersion: "3.0.3"' in tempo_chart, "Tempo version changed")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.sh"),
    ("CHANGELOG.md", "## v0.11.6.2.1.1"),
    ("README.md", "v0.11.6.2.3-local-minimal-tracing-closure" if closure_successor else ("v0.11.6.2.2-real-demo-api-trace-log-correlation" if correlation_successor else "v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair")),
    ("docs/ROADMAP.md", "v0.11.6.2.1.1"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.2.3" if closure_successor else ("active v0.11.6.2.2" if correlation_successor else "active v0.11.6.2.1.1")),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.2.1.1 repairs"),
    ("docs/V0.11.6.2.1_PRIVATE_LOCAL_OTEL_COLLECTOR_TEMPO_RUNTIME.md", "Repair v0.11.6.2.1.1"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/generate-synthetic-otlp-trace.py @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("Base64 trace IDs", lambda value: value["protocol"].update(traceIdEncoding="base64")),
    ("Base64 span IDs", lambda value: value["protocol"].update(spanIdEncoding="base64")),
    ("zero identifiers", lambda value: value["protocol"].update(zeroIdentifiersAllowed=True)),
    ("hidden status", lambda value: value["repair"].update(httpErrorStatusPrinted=False)),
    ("hidden body", lambda value: value["repair"].update(httpErrorBodyPrinted=False)),
    ("unbounded body", lambda value: value["repair"].update(httpErrorBodyLimitBytes=0)),
    ("incomplete diagnostics", lambda value: value["repair"].update(tempoAndCollectorDiagnosticsExplicit=False)),
    ("runtime defect overclaim", lambda value: value["incident"].update(runtimeResourceDefect=True)),
    ("runtime redeploy", lambda value: value["acceptance"].update(runtimeRedeployRequired=True)),
    ("image rebuild", lambda value: value["acceptance"].update(imageRebuildRequired=True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.2.1.1 valid hexadecimal OTLP/JSON identifiers and bounded diagnostic contracts passed.")
print("v0.11.6.2.1.1 Base64, malformed, zero, hidden-error, incomplete-diagnostic, redeploy, and rebuild mutations were rejected.")
PY

bash -n "${ROOT_DIR}/scripts/check-local-tracing-runtime.sh"

echo "v0.11.6.2.1.1 synthetic OTLP/JSON encoding and diagnostics repair validation passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command_name in bash helm python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 -m py_compile \
  "${ROOT_DIR}/apps/demo-api/src/runtime_identity.py" \
  "${ROOT_DIR}/apps/demo-api/src/tracing.py" \
  "${ROOT_DIR}/apps/demo-api/src/logging_config.py" \
  "${ROOT_DIR}/apps/demo-api/src/database.py" \
  "${ROOT_DIR}/apps/demo-api/src/main.py" \
  "${ROOT_DIR}/apps/demo-api/src/server.py" \
  "${ROOT_DIR}/apps/demo-api/tests/test_tracing.py"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
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
    require(value.get("schemaVersion") == "v0.11.6.2.0", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.2.0", "Bad version")
    require(
        value.get("status") == "offline-implemented-local-image-rebuild-required",
        "Bad status",
    )
    require(value.get("predecessor") == "v0.11.6.1.3", "Bad predecessor")

    scope = value.get("scope", {})
    require(scope.get("environment") == "local", "Environment boundary changed")
    for key in (
        "applicationCodeChanged",
        "applicationImageSourceChanged",
        "helmRuntimeConfigurationChanged",
        "w3cTraceContextImplemented",
        "httpServerSpanImplemented",
        "postgresqlClientSpanImplemented",
        "logTraceCorrelationImplemented",
    ):
        require(scope.get(key) is True, f"Required tracing scope disabled: {key}")
    for key in (
        "collectorImplemented",
        "tempoImplemented",
        "grafanaTraceDatasourceImplemented",
        "operatorAutoInstrumentationImplemented",
    ):
        require(scope.get(key) is False, f"Scope expanded: {key}")

    require(value.get("dependencies") == {
        "opentelemetry-api": "1.44.0",
        "opentelemetry-sdk": "1.44.0",
        "opentelemetry-exporter-otlp-proto-http": "1.44.0",
    }, "OpenTelemetry dependency versions changed")

    runtime = value.get("runtime", {})
    require(runtime.get("enabledByDefault") is False, "Tracing enabled by default")
    require(runtime.get("enableVariable") == "TRACING_ENABLED", "Enable switch changed")
    require(runtime.get("protocol") == "http/protobuf", "OTLP protocol changed")
    require(runtime.get("defaultTimeoutSeconds") == 5, "Default timeout changed")
    require(runtime.get("maximumTimeoutSeconds") == 30, "Maximum timeout changed")
    for key in (
        "exporterCreatedWhenDisabled",
        "backgroundProcessorCreatedWhenDisabled",
        "networkAttemptWhenDisabled",
        "samplingConfiguredInApplication",
        "baggagePropagationAccepted",
    ):
        require(runtime.get(key) is False, f"Disabled or propagation boundary expanded: {key}")
    require(runtime.get("collectorOwnsSamplingNextIncrement") is True, "Collector sampling boundary removed")

    path = value.get("tracePath", {})
    require(
        path.get("shape") == "http-request-to-demo-api-server-span-to-postgresql-client-span",
        "Trace path changed",
    )
    require((path.get("httpSpanKind"), path.get("databaseSpanKind")) == ("SERVER", "CLIENT"), "Span kinds changed")
    require(path.get("suppressedPaths") == ["/health", "/ready", "/metrics"], "Probe suppression changed")
    require(path.get("readinessDatabaseSpanEnabled") is False, "Readiness tracing noise enabled")
    require(path.get("localLivePostgresqlRequired") is False, "Local PostgreSQL was invented")
    require(path.get("awsPostgresqlQualificationDeferredTo") == "v0.11.8", "AWS qualification boundary changed")

    identity = value.get("identity", {})
    require(identity.get("sharedSource") == "apps/demo-api/src/runtime_identity.py", "Identity source changed")
    require(identity.get("resourceAttributes") == [
        "service.name",
        "service.version",
        "deployment.environment.name",
        "platform.release.id",
        "platform.source.commit",
        "container.image.digest",
    ], "Trace resource identity changed")
    require(identity.get("logCorrelationFields") == ["trace_id", "span_id"], "Log correlation fields changed")
    require(identity.get("invalidContextFieldsOmitted") is True, "Invalid identifiers may be logged")

    security = value.get("security", {})
    require(security.get("httpAttributeAllowlist") == [
        "http.request.method",
        "http.route",
        "http.response.status_code",
    ], "HTTP attribute allowlist changed")
    require(security.get("databaseAttributeAllowlist") == [
        "db.system.name",
        "db.operation.name",
    ], "Database attribute allowlist changed")
    for key, item in security.items():
        if key not in {"httpAttributeAllowlist", "databaseAttributeAllowlist"}:
            require(item is False, f"Sensitive tracing behavior enabled: {key}")

    acceptance = value.get("acceptance", {})
    require(
        acceptance.get("offlineValidator")
        == "scripts/validate-v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.sh",
        "Offline validator changed",
    )
    require(
        acceptance.get("liveEntrypoint") == "scripts/check-demo-api-tracing-contract.sh",
        "Live entrypoint changed",
    )
    for key in (
        "unitTestsRequired",
        "deploymentAndRolloutRenderRequired",
        "uniqueImageRebuildRequired",
        "tracingDisabledLiveRequired",
        "structuredLoggingRegressionRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    for key in ("localCollectorRequired", "localTraceQueryRequired"):
        require(acceptance.get(key) is False, f"Premature live requirement enabled: {key}")

    unchanged = value.get("unchanged", {})
    require(
        (
            unchanged.get("localPlatformChart"),
            unchanged.get("localPlatformApplicationVersion"),
            unchanged.get("lokiChart"),
            unchanged.get("lokiApplicationVersion"),
            unchanged.get("alloyChart"),
            unchanged.get("alloyApplicationVersion"),
        ) == ("0.6.0", "v0.11.6.1.2", "18.11.3", "3.7.6", "1.11.0", "1.18.0"),
        "Existing runtime version boundary changed",
    )
    version_keys = {
        "localPlatformChart",
        "localPlatformApplicationVersion",
        "lokiChart",
        "lokiApplicationVersion",
        "alloyChart",
        "alloyApplicationVersion",
    }
    for key, item in unchanged.items():
        if key not in version_keys:
            require(item is False, f"Unchanged boundary expanded: {key}")

    operations = value.get("operations", {})
    for key in ("imageRebuildRequired", "uniqueImageTagRequired", "localDemoApiRedeployRequired"):
        require(operations.get(key) is True, f"Required operation disabled: {key}")
    for key in (
        "loggingRuntimeRedeployRequired",
        "collectorDeploymentRequired",
        "tempoDeploymentRequired",
        "databaseEnablementRequired",
    ):
        require(operations.get(key) is False, f"Unnecessary operation enabled: {key}")
    require(value.get("nextIncrement", {}).get("version") == "v0.11.6.2.1", "Next increment changed")


contract_path = "delivery/contracts/v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require(
    (root / "delivery/contracts/v0.11.6.1.3-local-logging-end-to-end-closure.json").is_file(),
    "Missing predecessor contract",
)

requirements = read("apps/demo-api/requirements.txt").splitlines()
for dependency, version in contract["dependencies"].items():
    require(f"{dependency}=={version}" in requirements, f"Dependency pin missing: {dependency}")
for forbidden in (
    "opentelemetry-instrumentation-fastapi",
    "opentelemetry-instrumentation-psycopg",
    "tempo",
    "jaeger",
    "xray",
):
    require(not any(forbidden in line.lower() for line in requirements), f"Forbidden dependency found: {forbidden}")

tracing = read("apps/demo-api/src/tracing.py")
for marker in (
    "TraceContextTextMapPropagator",
    "SpanKind.SERVER",
    "SpanKind.CLIENT",
    "record_exception=False",
    "set_status_on_exception=False",
    "BatchSpanProcessor",
    "OTLPSpanExporter",
    "FORBIDDEN_AMBIENT_EXPORTER_CREDENTIALS",
    "Resource(attributes=runtime_identity())",
    "if not tracing_enabled():",
    "QUIET_HTTP_PATHS",
    "DATABASE_SPAN_NAMES",
):
    require(marker in tracing, f"Tracing implementation marker missing: {marker}")
for forbidden in (
    "TraceIdRatioBased",
    "db.statement",
    "request.url",
    "url.query",
    "authorization",
    "cookie",
    "record_exception(",
):
    require(forbidden.lower() not in tracing.lower(), f"Forbidden tracing behavior found: {forbidden}")

main = read("apps/demo-api/src/main.py")
require("with http_server_span(" in main, "HTTP server span is not active around the request")
require("finish_http_server_span(" in main, "HTTP span finalization missing")
require("database_health(traced=traced)" in main, "Readiness trace control missing")
require("_observed_database_health(traced=False)" in main, "Readiness span noise is not suppressed")

database = read("apps/demo-api/src/database.py")
for marker in (
    'database_client_span("health", enabled=traced)',
    'database_client_span("marker.write")',
    'database_client_span("marker.read")',
):
    require(marker in database, f"Database tracing marker missing: {marker}")

logging_config = read("apps/demo-api/src/logging_config.py")
for marker in (
    "runtime_identity()",
    'payload["trace_id"]',
    'payload["span_id"]',
    "span_context.is_valid",
):
    require(marker in logging_config, f"Log correlation marker missing: {marker}")
require("def _runtime_identity" not in logging_config, "Duplicate release identity source remains")

server = read("apps/demo-api/src/server.py")
require(server.find("configure_logging()") < server.find("configure_tracing()") < server.find("uvicorn.run("), "Startup ordering changed")

tests = read("apps/demo-api/tests/test_tracing.py")
for marker in (
    "test_disabled_tracing_creates_no_span",
    "test_disabled_configuration_creates_no_exporter_or_provider",
    "test_unsafe_export_endpoint_is_rejected_before_exporter_creation",
    "test_ambient_exporter_credentials_are_rejected",
    "test_w3c_parent_server_database_and_log_correlation",
    "test_probe_and_metrics_paths_do_not_create_success_spans",
    "test_server_and_database_failures_set_error_without_exception_data",
    "test_log_ids_are_omitted_without_an_active_span",
    "test_resource_reuses_canonical_release_identity",
):
    require(marker in tests, f"Tracing unit-test boundary missing: {marker}")

closure_validator = read("scripts/validate-v0.11.6.1.3-local-logging-end-to-end-closure.sh")
for marker in (
    "v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.json",
    "Tracing successor skips closure",
    "v0.11.6.2.0 application tracing successor coverage passed",
):
    require(marker in closure_validator, f"Closure successor coverage missing: {marker}")

chart = read("apps/demo-api/helm/Chart.yaml")
slo_rollout_successor = (root / "delivery/contracts/v0.11.7.2-slo-aware-argo-rollouts-analysis.json").is_file()
slo_analysis_repair_successor = (root / "delivery/contracts/v0.11.7.2.1-slo-analysis-promql-live-race-repair.json").is_file()
canary_endpoint_repair_successor = (root / "delivery/contracts/v0.11.7.2.2-canary-endpoint-identity-scrape-window-repair.json").is_file()
require(("version: 0.8.2" if canary_endpoint_repair_successor else ("version: 0.8.1" if slo_analysis_repair_successor else ("version: 0.8.0" if slo_rollout_successor else "version: 0.7.0"))) in chart and 'appVersion: "0.5.0"' in chart, "demo-api Chart identity not advanced")
values = read("apps/demo-api/helm/values.yaml")
for marker in (
    "tracing:",
    "enabled: false",
    "protocol: http/protobuf",
    "timeoutSeconds: 5",
    "observability-otel-collector.observability.svc.cluster.local:4318/v1/traces",
):
    require(marker in values, f"Helm tracing default missing: {marker}")
for template in (
    "apps/demo-api/helm/templates/deployment.yaml",
    "apps/demo-api/helm/templates/rollout.yaml",
):
    content = read(template)
    for variable in (
        "TRACING_ENABLED",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
        "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT",
    ):
        require(content.count(f"- name: {variable}") == 1, f"{variable} is not exact in {template}")

runtime_successor = (
    root / "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json"
).is_file()
correlation_successor = (
    root / "delivery/contracts/v0.11.6.2.2-real-demo-api-trace-log-correlation.json"
).is_file()
closure_successor = (
    root / "delivery/contracts/v0.11.6.2.3-local-minimal-tracing-closure.json"
).is_file()

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.sh"),
    ("CHANGELOG.md", "## v0.11.6.2.0"),
    ("README.md", "v0.11.6.2.0-demo-api-opentelemetry-tracing-contract"),
    ("apps/demo-api/README.md", "v0.11.6.2.0 tracing contract"),
    ("docs/ROADMAP.md", "v0.11.6.2.0"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.2.3" if closure_successor else ("active v0.11.6.2.2" if correlation_successor else ("active v0.11.6.2.1" if runtime_successor else "active v0.11.6.2.0"))),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.2.0 implements"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/check-demo-api-tracing-contract.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("enabled by default", lambda value: value["runtime"].__setitem__("enabledByDefault", True)),
    ("exporter while disabled", lambda value: value["runtime"].__setitem__("exporterCreatedWhenDisabled", True)),
    ("application sampling", lambda value: value["runtime"].__setitem__("samplingConfiguredInApplication", True)),
    ("baggage acceptance", lambda value: value["runtime"].__setitem__("baggagePropagationAccepted", True)),
    ("raw SQL", lambda value: value["security"].__setitem__("rawSqlCaptured", True)),
    ("exception text", lambda value: value["security"].__setitem__("exceptionMessageCaptured", True)),
    ("ambient exporter credentials", lambda value: value["security"].__setitem__("ambientExporterCredentialsAccepted", True)),
    ("premature Tempo", lambda value: value["scope"].__setitem__("tempoImplemented", True)),
    ("fake local PostgreSQL", lambda value: value["tracePath"].__setitem__("localLivePostgresqlRequired", True)),
    ("skip image rebuild", lambda value: value["operations"].__setitem__("imageRebuildRequired", False)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.2.0 W3C propagation, bounded spans, shared identity, disabled export, and security contracts passed.")
print("v0.11.6.2.0 default export, app sampling, baggage, sensitive spans, premature Tempo, fake database, and stale image mutations were rejected.")
PY

echo "==> Rendering Deployment and Rollout tracing configuration"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  >"${WORK_DIR}/rollout.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --set rollout.enabled=false \
  >"${WORK_DIR}/deployment.yaml"

python3 - "${WORK_DIR}/rollout.yaml" "${WORK_DIR}/deployment.yaml" <<'PY'
from pathlib import Path
import sys


for manifest_path in sys.argv[1:]:
    manifest = Path(manifest_path).read_text()
    for name, value in (
        ("TRACING_ENABLED", '"false"'),
        ("OTEL_EXPORTER_OTLP_PROTOCOL", '"http/protobuf"'),
        ("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT", '"5"'),
    ):
        marker = f"- name: {name}\n              value: {value}"
        if manifest.count(marker) != 1:
            raise SystemExit(f"{name} does not render exactly once with {value} in {manifest_path}")
    if manifest.count("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") != 1:
        raise SystemExit(f"OTLP traces endpoint does not render exactly once in {manifest_path}")
    for forbidden in ("kind: OpenTelemetryCollector", "kind: Instrumentation", "tempo"):
        if forbidden.lower() in manifest.lower():
            raise SystemExit(f"Premature tracing runtime found in {manifest_path}: {forbidden}")
PY

bash -n "${ROOT_DIR}/scripts/check-demo-api-tracing-contract.sh"

echo "v0.11.6.2.0 demo-api OpenTelemetry tracing contract validation passed."

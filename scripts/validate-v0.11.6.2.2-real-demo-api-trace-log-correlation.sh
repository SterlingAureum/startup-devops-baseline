#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

for command_name in bash helm python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

echo "==> Validating the v0.11.6.2.2 contract and scope boundary"
python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
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


contract_path = "delivery/contracts/v0.11.6.2.2-real-demo-api-trace-log-correlation.json"
contract = json.loads(read(contract_path))
closure_successor = (root / "delivery/contracts/v0.11.6.2.3-local-minimal-tracing-closure.json").is_file()


def validate(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.11.6.2.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.2.2", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-acceptance-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.2.1.1", "Bad predecessor")

    scope = value.get("scope", {})
    require(scope.get("environment") == "local", "Environment expanded")
    for key in (
        "applicationExportEnabled", "grafanaTempoDatasourceImplemented",
        "lokiTraceDerivedFieldImplemented", "realHttpTraceClaimed",
    ):
        require(scope.get(key) is True, f"Required scope missing: {key}")
    for key in (
        "applicationCodeChanged", "applicationImageChanged",
        "postgresqlLiveTraceClaimed", "awsRuntimeChanged",
    ):
        require(scope.get(key) is False, f"Scope expanded: {key}")

    require(value.get("versions") == {
        "localPlatformChart": "0.8.0",
        "localPlatformApplicationVersion": "v0.11.6.2.2",
        "demoApiChart": "0.7.0",
        "demoApiApplicationVersion": "0.5.0",
        "opentelemetrySdk": "1.44.0",
        "collectorApplicationVersion": "0.159.0",
        "tempoApplicationVersion": "3.0.3",
    }, "Runtime identity changed")

    export = value.get("applicationExport", {})
    require(export.get("enableVariable") == "TRACING_ENABLED", "Enable variable changed")
    require(export.get("enabledValue") == "true", "Local export not enabled")
    require(export.get("protocol") == "http/protobuf", "Protocol expanded")
    require(export.get("endpoint") == "http://observability-otel-collector.observability.svc.cluster.local:4318/v1/traces", "Endpoint changed")
    require(export.get("timeoutSeconds") == 5, "Timeout changed")
    for key in ("localOverrideOnly", "baseChartDefaultEnabled"):
        expected = key == "localOverrideOnly"
        require(export.get(key) is expected, f"Export boundary changed: {key}")
    require(export.get("externalCredentialsAdded") is False, "External credentials added")

    correlation = value.get("correlation", {})
    require(correlation.get("requestRoute") == "/version", "Acceptance route changed")
    require((correlation.get("traceIdCharacters"), correlation.get("spanIdCharacters")) == (32, 16), "Identifier width changed")
    require((correlation.get("lokiDatasourceUid"), correlation.get("tempoDatasourceUid")) == ("loki", "tempo"), "Data source UID changed")
    require(correlation.get("derivedFieldName") == "TraceID", "Derived field changed")
    for key in ("traceIdIndexedAsLokiLabel", "spanIdIndexedAsLokiLabel"):
        require(correlation.get(key) is False, f"High-cardinality label enabled: {key}")

    grafana = value.get("grafana", {})
    require(grafana.get("tempoUrl") == "http://observability-tempo.observability.svc.cluster.local:3200", "Tempo URL changed")
    require(grafana.get("access") == "proxy", "Grafana access changed")
    require(grafana.get("networkPolicyTempoPort") == 3200, "Grafana Tempo port changed")
    for key in ("defaultDatasource", "editable", "dedicatedTracingDashboardAdded"):
        require(grafana.get(key) is False, f"Grafana scope expanded: {key}")

    acceptance = value.get("acceptance", {})
    require(acceptance.get("offlineValidator") == "scripts/validate-v0.11.6.2.2-real-demo-api-trace-log-correlation.sh", "Offline validator changed")
    require(acceptance.get("liveEntrypoint") == "scripts/check-local-demo-api-trace-correlation.sh", "Live checker changed")
    for key in (
        "realHttpRequestRequired", "lokiCorrelationQueryRequired",
        "tempoTraceQueryRequired", "grafanaDatasourceHealthRequired",
        "highCardinalityLabelRejectionRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("consecutiveRunsRequired") == 2, "Two-run proof removed")

    require(all(value.get("deferred", {}).values()), "A deferred complex tracing feature was enabled")
    operations = value.get("operations", {})
    require(operations.get("localPlatformReconciliationRequired") is True, "Reconciliation requirement removed")
    for key in (
        "imageRebuildRequired", "applicationCodeChangeRequired",
        "loggingRuntimeRedeployRequired", "databaseEnablementRequired",
    ):
        require(operations.get(key) is False, f"Unnecessary operation enabled: {key}")
    require(value.get("nextIncrement", {}).get("version") == "v0.11.6.2.3", "Next increment changed")


validate(contract)
require((root / contract["designDocument"]).is_file(), "Design document missing")
for predecessor in (
    "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json",
    "delivery/contracts/v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.json",
):
    require((root / predecessor).is_file(), f"Predecessor missing: {predecessor}")

platform_chart = read("clusters/local/platform/Chart.yaml")
require("version: 0.8.0" in platform_chart and 'appVersion: "v0.11.6.2.2"' in platform_chart, "Local platform identity changed")
demo_chart = read("apps/demo-api/helm/Chart.yaml")
require("version: 0.7.0" in demo_chart and 'appVersion: "0.5.0"' in demo_chart, "demo-api Chart changed")
demo_values = read("apps/demo-api/helm/values.yaml")
require(re.search(r"tracing:\s+enabled: false", demo_values), "Base demo-api tracing default was enabled")

local_values = read("clusters/local/platform/values.yaml")
for marker in (
    "tracing:", "enabled: true",
    "http://observability-otel-collector.observability.svc.cluster.local:4318/v1/traces",
    "protocol: http/protobuf", "timeoutSeconds: 5",
):
    require(marker in local_values, f"Local tracing value missing: {marker}")

demo_application = read("clusters/local/platform/templates/demo-api.yaml")
for marker in (
    "telemetry.tracing.enabled", "telemetry.tracing.endpoint",
    "telemetry.tracing.protocol", "telemetry.tracing.timeoutSeconds",
):
    require(marker in demo_application, f"demo-api Application parameter missing: {marker}")

monitoring = read("clusters/local/platform/templates/monitoring.yaml")
for marker in (
    "name: Tempo", "uid: tempo", "type: tempo",
    "http://observability-tempo.observability.svc.cluster.local:3200",
    "name: TraceID", "datasourceUid: tempo",
    'matcherRegex: \'"trace_id":"([0-9a-f]{32})"\'',
    "url: '$${__value.raw}'", "port: 3200",
):
    require(marker in monitoring, f"Grafana correlation marker missing: {marker}")

alloy = read("clusters/local/platform/files/logging/alloy-values.yaml")
require('values = ["environment", "cluster", "namespace", "application", "container", "severity"]' in alloy, "Six-label Loki contract changed")
label_section = alloy.split('stage.label_keep {', 1)[1].split('}', 1)[0]
for forbidden in ("trace_id", "span_id"):
    require(forbidden not in label_section, f"High-cardinality Loki label added: {forbidden}")

live = read("scripts/check-local-demo-api-trace-correlation.sh")
for marker in (
    "TRACING_ENABLED", "traceparent", "demo-api-stable.startup-apps.svc.cluster.local/version",
    "loki/api/v1/query_range", "api/v2/traces/${trace_id}",
    "api/datasources/uid/tempo", "api/datasources/uid/${uid}/health",
    'has("trace_id")', 'has("span_id")',
    "v0.11.6.2.2 real HTTP trace",
    "last HTTP status:", "Direct Loki API response",
    "observability-logs-cluster-only", "get endpointslice",
    "deployment/observability-logs-gateway", "statefulset/observability-logs",
):
    require(marker in live, f"Live acceptance marker missing: {marker}")
for forbidden in ("/db/health", "service_graph", "spanmetrics", "tail_sampling", "xray"):
    require(forbidden not in live.lower(), f"Live scope expanded: {forbidden}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.2.2-real-demo-api-trace-log-correlation.sh"),
    ("CHANGELOG.md", "## v0.11.6.2.2"),
    ("README.md", "v0.11.6.2.3-local-minimal-tracing-closure" if closure_successor else "v0.11.6.2.2-real-demo-api-trace-log-correlation"),
    ("docs/ROADMAP.md", "v0.11.6.2.2"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.2.3" if closure_successor else "active v0.11.6.2.2"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.2.2 joins"),
    ("docs/V0.11.6.2.2_REAL_DEMO_API_TRACE_LOG_CORRELATION.md", "kubectl argo rollouts status demo-api"),
    ("docs/V0.11.6.2.2_REAL_DEMO_API_TRACE_LOG_CORRELATION.md", "direct response is diagnostic only"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/check-local-demo-api-trace-correlation.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
    ("AWS expansion", lambda value: value["scope"].update(awsRuntimeChanged=True)),
    ("image rebuild", lambda value: value["operations"].update(imageRebuildRequired=True)),
    ("base default", lambda value: value["applicationExport"].update(baseChartDefaultEnabled=True)),
    ("credential", lambda value: value["applicationExport"].update(externalCredentialsAdded=True)),
    ("trace label", lambda value: value["correlation"].update(traceIdIndexedAsLokiLabel=True)),
    ("default Tempo", lambda value: value["grafana"].update(defaultDatasource=True)),
    ("service graph", lambda value: value["deferred"].update(serviceGraph=False)),
    ("one run", lambda value: value["acceptance"].update(consecutiveRunsRequired=1)),
)
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except ContractError:
        continue
    raise ContractError(f"Forbidden mutation accepted: {name}")

print("v0.11.6.2.2 local export, real trace, Loki correlation, Grafana, and operation contracts passed.")
print("v0.11.6.2.2 AWS, image, default, credential, indexed-ID, dashboard, complex tracing, and one-run mutations were rejected.")
PY

echo "==> Rendering the local App-of-Apps and base demo-api Chart"
helm template startup-devops-local-platform "${ROOT_DIR}/clusters/local/platform" \
  >"${WORK_DIR}/local-platform.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  >"${WORK_DIR}/demo-api.yaml"

python3 - "${WORK_DIR}/local-platform.yaml" "${WORK_DIR}/demo-api.yaml" <<'PY'
from pathlib import Path
import sys

platform = Path(sys.argv[1]).read_text()
demo = Path(sys.argv[2]).read_text()
for marker in (
    "name: telemetry.tracing.enabled\n          value: \"true\"",
    "name: telemetry.tracing.endpoint",
    "name: Tempo",
    "uid: tempo",
    "datasourceUid: tempo",
    "port: 3200",
):
    if marker not in platform:
        raise SystemExit(f"Rendered local platform marker missing: {marker}")
if 'name: TRACING_ENABLED\n              value: "false"' not in demo:
    raise SystemExit("Base demo-api Chart no longer renders tracing disabled")
PY

bash -n "${ROOT_DIR}/scripts/check-local-demo-api-trace-correlation.sh"
echo "v0.11.6.2.2 real demo-api trace and log correlation validation passed."

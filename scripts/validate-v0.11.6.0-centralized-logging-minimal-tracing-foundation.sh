#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable


root = Path(sys.argv[1])


class ContractError(ValueError):
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


EXPECTED_ENVIRONMENTS = ["local", "aws-dev", "aws-test", "aws-prod"]
EXPECTED_IDENTITY = [
    "service.name",
    "service.version",
    "deployment.environment.name",
    "platform.release.id",
    "platform.source.commit",
    "container.image.digest",
]
EXPECTED_REQUIRED_LOG_FIELDS = [
    "timestamp",
    "severity",
    "message",
    *EXPECTED_IDENTITY,
]
EXPECTED_BOUNDED_LABELS = [
    "environment",
    "cluster",
    "namespace",
    "application",
    "container",
    "severity",
]
EXPECTED_PLAN = [
    ("v0.11.6.1", "structured-demo-api-logs-alloy-loki-and-kubernetes-events"),
    ("v0.11.6.2", "opentelemetry-sdk-collector-and-minimal-tempo-path"),
    ("v0.11.6.3", "grafana-metric-log-trace-release-correlation-and-local-acceptance"),
    ("v0.11.6.4", "clean-replay-diagnostics-and-v0.11.6-closure"),
]


def validate_contract(contract: dict[str, Any], check_files: bool = True) -> None:
    require(contract.get("schemaVersion") == "v0.11.6.0", "Bad schemaVersion")
    require(contract.get("version") == "v0.11.6.0", "Bad version")
    require(contract.get("status") == "design-foundation-runtime-deferred", "Bad status")
    require(contract.get("predecessor") == "v0.11.5.2.0.3", "Bad predecessor")
    if check_files:
        require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
        require((root / "delivery/contracts/v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.json").is_file(), "Missing predecessor contract")

    accepted = contract.get("v0115Acceptance", {})
    require(accepted.get("scope") == "local", "v0.11.5 acceptance scope changed")
    require(accepted.get("formalAlertCount") == 9, "Formal alert count changed")
    for key in (
        "alertmanagerRuntimeAccepted",
        "formalAlertsHealthyAndInactive",
        "warningAndCriticalLifecycleAccepted",
        "routingAccepted",
        "positiveAndNegativeInhibitionAccepted",
        "resolvedDeliveryAccepted",
        "zeroKubernetesResidualAccepted",
        "zeroPrometheusRuleInventoryResidualAccepted",
        "externalProviderDeliveryDeferred",
    ):
        require(accepted.get(key) is True, f"v0.11.5 acceptance evidence omitted: {key}")
    require(accepted.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS alert acceptance moved")

    scope = contract.get("scope", {})
    require(scope.get("centralizedLoggingBoundary") == "per-environment", "Logging became cross-environment")
    require(scope.get("minimalTracingBoundary") == "http-demo-api-postgresql", "Trace scope changed")
    for key in (
        "runtimeImplemented",
        "applicationCodeChanged",
        "kubernetesResourcesAdded",
        "helmDependenciesAdded",
        "containerImagesAdded",
        "liveClaimAdded",
    ):
        require(scope.get(key) is False, f"Design-only scope expanded: {key}")

    components = contract.get("components", {})
    require(components.get("applicationLogging", {}).get("source") == "stdout-stderr", "Application log source changed")
    require(components.get("applicationLogging", {}).get("format") == "json-lines", "Application log format changed")
    require(components.get("applicationLogging", {}).get("fileLogging") is False, "Application file logging enabled")
    require(components.get("applicationLogging", {}).get("loggingSidecarRequired") is False, "Logging sidecar required")
    require(components.get("logCollector", {}).get("component") == "grafana-alloy", "Log collector changed")
    require(components.get("logCollector", {}).get("includeKubernetesEvents") is True, "Kubernetes Events omitted")
    require(components.get("logBackend", {}).get("component") == "loki", "Log backend changed")
    require(components.get("logBackend", {}).get("crossEnvironmentBackend") is False, "Shared log backend enabled")
    require(components.get("traceCollector", {}).get("component") == "upstream-opentelemetry-collector", "Trace collector changed")
    require(components.get("traceCollector", {}).get("protocol") == "otlp", "Trace protocol changed")
    require(components.get("traceCollector", {}).get("samplingOwnedOutsideApplication") is True, "Application owns sampling")
    require(components.get("traceBackend", {}).get("component") == "tempo", "Trace backend changed")
    require(components.get("traceBackend", {}).get("applicationBackendCoupling") is False, "Application coupled to Tempo")
    require(components.get("visualization", {}).get("component") == "grafana", "Visualization component changed")

    isolation = contract.get("environmentIsolation", {})
    require(isolation.get("environments") == EXPECTED_ENVIRONMENTS, "Environment order changed")
    for key in (
        "separateRuntimePerEnvironment",
        "separateStoragePerEnvironment",
        "separateRetentionPerEnvironment",
        "separateCredentialsPerEnvironment",
        "futureAggregationWithoutApplicationContractChange",
    ):
        require(isolation.get(key) is True, f"Environment isolation weakened: {key}")
    for key in (
        "crossEnvironmentQueryRequired",
        "globalSharedLokiRequired",
        "globalSharedTempoRequired",
    ):
        require(isolation.get(key) is False, f"Global backend entered scope: {key}")

    profiles = contract.get("environmentProfiles", [])
    require([item.get("environment") for item in profiles] == EXPECTED_ENVIRONMENTS, "Environment profiles changed")
    require(all(item.get("productionClaim") is False for item in profiles[:-1]), "Non-production profile claims production")
    require(profiles[-1].get("profile") == "production-parity", "Production profile weakened")
    require(profiles[-1].get("productionClaim") == "requires-live-v0.11-acceptance", "Production evidence requirement removed")

    log_schema = contract.get("logSchema", {})
    require(log_schema.get("requiredFields") == EXPECTED_REQUIRED_LOG_FIELDS, "Required log schema changed")
    require(log_schema.get("conditionalCorrelationFields") == ["trace_id", "span_id"], "Log correlation fields changed")
    forbidden = log_schema.get("forbiddenFields", [])
    for field in (
        "http.request.body",
        "http.request.header.authorization",
        "http.request.header.cookie",
        "db.query.parameter",
        "db.statement.raw",
        "enduser.id",
        "raw.url.query",
        "credential",
        "secret",
    ):
        require(field in forbidden, f"Sensitive log field no longer forbidden: {field}")

    labels = contract.get("lokiLabelPolicy", {})
    require(labels.get("allowedBoundedLabels") == EXPECTED_BOUNDED_LABELS, "Loki label allowlist changed")
    require(labels.get("boundedCardinalityRequired") is True, "Loki cardinality guard disabled")
    structured_only = labels.get("structuredFieldsNotIndexedLabels", [])
    for field in (
        "trace_id",
        "span_id",
        "platform.release.id",
        "platform.source.commit",
        "container.image.digest",
        "pod.uid",
        "pod.ip",
        "request.id",
        "enduser.id",
        "raw.url",
    ):
        require(field in structured_only, f"High-cardinality field may become a label: {field}")
        require(field not in labels.get("allowedBoundedLabels", []), f"High-cardinality field indexed: {field}")

    tracing = contract.get("tracing", {})
    require(tracing.get("scope") == "minimal-extensible-foundation", "Trace scope expanded")
    require(tracing.get("initialPath") == "http-request-to-demo-api-server-span-to-postgresql-client-span", "Initial trace path changed")
    require(tracing.get("propagation") == "w3c-trace-context", "Propagation changed")
    require(tracing.get("exportProtocol") == "otlp", "Export protocol changed")
    for key in (
        "applicationUsesOpenTelemetryApi",
        "samplingConfiguredInCollector",
        "serverSpanRequired",
        "postgresqlClientSpanRequired",
        "traceAndSpanIdsInLogs",
    ):
        require(tracing.get(key) is True, f"Trace foundation weakened: {key}")
    for key in (
        "applicationCallsBackendSpecificApi",
        "secretsInSpanAttributes",
        "rawSqlParametersInSpanAttributes",
        "fullDistributedTracingPlatformRequired",
    ):
        require(tracing.get(key) is False, f"Trace boundary expanded: {key}")

    correlation = contract.get("correlation", {})
    require(correlation.get("requiredDimensions") == EXPECTED_IDENTITY, "Correlation identity changed")
    require(correlation.get("metricToLog") == "release-and-service-identity", "Metric-to-log boundary changed")
    require(correlation.get("logToTrace") == "trace_id", "Log-to-trace boundary changed")
    require(correlation.get("traceToLog") == "trace_id-and-span_id", "Trace-to-log boundary changed")
    require(correlation.get("crossEnvironmentIdentity") == "same-release-fields-not-shared-backend", "Cross-environment identity changed")
    require(correlation.get("acceptanceIncrement") == "v0.11.6.3", "Correlation acceptance moved")

    plan = contract.get("implementationPlan", [])
    require([(item.get("increment"), item.get("outcome")) for item in plan] == EXPECTED_PLAN, "Implementation plan changed")

    runtime = contract.get("runtimeRequirementsForLaterIncrements", {})
    require(runtime and all(value is True for value in runtime.values()), "A later runtime requirement was disabled")

    deferred = contract.get("deferred", [])
    for capability in (
        "cross-cluster-log-aggregation",
        "cross-cluster-trace-aggregation",
        "multi-tenant-observability-backend",
        "distributed-ha-loki",
        "distributed-ha-tempo",
        "long-term-object-storage",
        "tail-sampling",
        "service-graph",
        "messaging-tracing",
        "model-inference-tracing",
        "gpu-telemetry",
        "aiops-automation",
    ):
        require(capability in deferred, f"Deferred capability entered scope: {capability}")

    require(all(value is False for value in contract.get("boundaries", {}).values()), "Design-only boundary expanded")

    acceptance = contract.get("acceptance", {})
    if check_files:
        require((root / acceptance.get("offlineValidator", "")).is_file(), "Missing offline validator")
    require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
    for key in ("localClusterExecutionRequired", "monitoringRedeployRequired", "imageRebuildRequired"):
        require(acceptance.get(key) is False, f"Design-only acceptance requires runtime action: {key}")
    require(acceptance.get("loggingRuntimeDeferredTo") == "v0.11.6.1", "Logging runtime moved")
    require(acceptance.get("tracingRuntimeDeferredTo") == "v0.11.6.2", "Tracing runtime moved")
    require(acceptance.get("localCorrelationAcceptanceDeferredTo") == "v0.11.6.3", "Correlation acceptance moved")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS execution moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Clean-room closure moved")


contract_path = "delivery/contracts/v0.11.6.0-centralized-logging-minimal-tracing-foundation.json"
contract = load_json(contract_path)
validate_contract(contract)

# The v0.11.0 design contract remains a historical snapshot; progress is
# recorded by successor contracts rather than rewriting its original plan.
foundation = load_json("delivery/contracts/v0.11-observability-sre-foundation.json")
increments = {item.get("id"): item for item in foundation.get("increments", [])}
require(increments.get("v0.11.5", {}).get("status") == "planned", "Historical v0.11.0 alerting plan was rewritten")
require(increments.get("v0.11.6", {}).get("status") == "planned", "Historical v0.11.0 logging plan was rewritten")

local_chart = read("clusters/local/platform/Chart.yaml")
logging_runtime_successor = (root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file()
events_runtime_successor = (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file()
tracing_runtime_successor = (root / "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json").is_file()
require(
    ("version: 0.7.0" if tracing_runtime_successor else ("version: 0.6.0" if events_runtime_successor else ("version: 0.5.0" if logging_runtime_successor else "version: 0.4.1"))) in local_chart
    and ('appVersion: "v0.11.6.2.1"' if tracing_runtime_successor else ('appVersion: "v0.11.6.1.2"' if events_runtime_successor else ('appVersion: "v0.11.6.1.1"' if logging_runtime_successor else 'appVersion: "v0.11.5.2.0"'))) in local_chart,
    "Local platform runtime changed",
)
views_chart = read("platform/observability/helm/Chart.yaml")
require("version: 0.4.1" in views_chart and 'appVersion: "v0.11.5.1.1"' in views_chart, "Observability views runtime changed")

# Before a v0.11.6.1 successor exists, the design foundation must not silently
# deploy a logging or tracing runtime.
successor_exists = any((root / "delivery/contracts").glob("v0.11.6.1*.json"))
if not successor_exists:
    runtime_pattern = re.compile(r"(?i)\b(grafana-alloy|opentelemetry-collector|loki|tempo)\b")
    for base in ("clusters", "platform", "apps"):
        for path in (root / base).rglob("*.yaml"):
            require(not runtime_pattern.search(path.read_text()), f"Design-only increment contains runtime declaration: {path.relative_to(root)}")
        for path in (root / base).rglob("*.yml"):
            require(not runtime_pattern.search(path.read_text()), f"Design-only increment contains runtime declaration: {path.relative_to(root)}")

design = read("docs/V0.11.6.0_CENTRALIZED_LOGGING_MINIMAL_TRACING_FOUNDATION.md")
for marker in (
    "Centralized logging means one queryable log path inside each environment",
    "Grafana Alloy",
    "OpenTelemetry Collector",
    "structured metadata, not indexed",
    "HTTP request",
    "v0.11.6.1",
    "v0.11.6.2",
    "v0.11.6.3",
    "v0.11.6.4",
    "No observability service receives a public endpoint by default",
):
    require(marker in design, f"Design document lacks marker: {marker}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.0-centralized-logging-minimal-tracing-foundation.sh"),
    ("README.md", "v0.11.6.0-centralized-logging-minimal-tracing-foundation"),
    ("docs/ROADMAP.md", "v0.11.6.0"),
    ("docs/OBSERVABILITY.md", "environment-local Loki"),
    ("docs/V0.11.5.2.0.3_PROMETHEUS_RULE_CLEANUP_SYNCHRONIZATION_REPAIR.md", "accepted locally"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.0"),
    ("CHANGELOG.md", "## v0.11.6.0"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.6.0-centralized-logging-minimal-tracing-foundation.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("shared Loki", lambda value: value["environmentIsolation"].__setitem__("globalSharedLokiRequired", True)),
    ("shared Tempo", lambda value: value["environmentIsolation"].__setitem__("globalSharedTempoRequired", True)),
    ("indexed trace ID", lambda value: value["lokiLabelPolicy"]["allowedBoundedLabels"].append("trace_id")),
    ("backend-coupled application", lambda value: value["tracing"].__setitem__("applicationCallsBackendSpecificApi", True)),
    ("application-owned sampling", lambda value: value["tracing"].__setitem__("samplingConfiguredInCollector", False)),
    ("authorization logging", lambda value: value["logSchema"]["forbiddenFields"].remove("http.request.header.authorization")),
    ("public endpoint", lambda value: value["boundaries"].__setitem__("publicEndpointAdded", True)),
    ("premature runtime claim", lambda value: value["scope"].__setitem__("runtimeImplemented", True)),
    ("AI infrastructure scope", lambda value: value["boundaries"].__setitem__("aiInfrastructureScopeAdded", True)),
    ("AIOps implementation", lambda value: value["boundaries"].__setitem__("aiopsImplementationAdded", True)),
]

for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.0 per-environment logging, bounded JSON and Loki labels, vendor-neutral minimal tracing, correlation, cost, and security contracts passed.")
print("v0.11.6.0 shared-backend, indexed-trace, backend-coupling, sensitive-data, public-endpoint, runtime-claim, AI-infra, and AIOps mutations were rejected.")
PY

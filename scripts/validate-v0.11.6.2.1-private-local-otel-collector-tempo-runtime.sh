#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
OTEL_COLLECTOR_CHART_DIR="${OTEL_COLLECTOR_CHART_DIR:-}"

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

echo "==> Validating the runtime contract and repository boundary"
python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


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


def validate(value: dict) -> None:
    require(value.get("schemaVersion") == "v0.11.6.2.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.2.1", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-acceptance-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.2.0", "Bad predecessor")

    scope = value.get("scope", {})
    require(scope.get("environment") == "local", "Environment expanded")
    require(scope.get("collectorImplemented") is True, "Collector missing")
    require(scope.get("tempoImplemented") is True, "Tempo missing")
    for key in (
        "applicationCodeChanged", "applicationImageChanged", "applicationExportEnabled",
        "grafanaTraceDatasourceImplemented", "postgresqlLiveTraceClaimed", "awsRuntimeChanged",
    ):
        require(scope.get(key) is False, f"Scope expanded: {key}")

    require(value.get("versions") == {
        "localPlatformChart": "0.7.0",
        "localPlatformApplicationVersion": "v0.11.6.2.1",
        "collectorChart": "0.172.0",
        "collectorApplicationVersion": "0.159.0",
        "tempoChart": "0.1.0",
        "tempoApplicationVersion": "3.0.3",
        "deprecatedExternalTempoChartUsed": False,
    }, "Pinned runtime versions changed")

    topology = value.get("topology", {})
    require(topology.get("namespace") == "observability", "Tracing namespace changed")
    require(topology.get("applications") == [
        {"name": "tracing-tempo", "syncWave": 7},
        {"name": "tracing-otel-collector", "syncWave": 8},
    ], "Application order changed")
    require(topology.get("collectorOtlpHttpPort") == 4318, "Collector port changed")
    require((topology.get("tempoHttpPort"), topology.get("tempoOtlpHttpPort")) == (3200, 4318), "Tempo ports changed")
    require(topology.get("publicEndpointAdded") is False, "Public endpoint added")

    collector = value.get("collector", {})
    require((collector.get("mode"), collector.get("replicas")) == ("deployment", 1), "Collector topology changed")
    require(collector.get("receiverProtocols") == ["otlp-http"], "Collector receiver set changed")
    require(collector.get("processors") == ["memory_limiter", "batch"], "Collector processors changed")
    require(collector.get("exporters") == ["otlp_http/tempo"], "Collector exporter changed")
    require(collector.get("pipelines") == ["traces"], "Collector pipeline set changed")
    for key in (
        "samplingConfigured", "logsPipelineConfigured", "metricsPipelineConfigured",
        "jaegerReceiverConfigured", "zipkinReceiverConfigured", "kubernetesRbacRequired",
    ):
        require(collector.get(key) is False, f"Collector boundary expanded: {key}")

    tempo = value.get("tempo", {})
    require((tempo.get("deploymentMode"), tempo.get("replicas"), tempo.get("target")) == ("monolithic", 1, "all"), "Tempo topology changed")
    require((tempo.get("backend"), tempo.get("storage"), tempo.get("retention")) == ("local-filesystem", "bounded-emptyDir", "24h"), "Tempo storage changed")
    require(tempo.get("repoOwnedMinimalChart") is True, "Repository-owned Tempo Chart removed")
    for key in ("multitenancyEnabled", "kafkaRequired", "metricsGeneratorEnabled"):
        require(tempo.get(key) is False, f"Tempo boundary expanded: {key}")

    security = value.get("security", {})
    for key in ("clusterIpOnly", "readOnlyRootFilesystems", "allCapabilitiesDropped", "networkPoliciesRequired"):
        require(security.get(key) is True, f"Security control disabled: {key}")
    for key in (
        "ingressCreated", "loadBalancerCreated", "hostNetworkUsed", "hostPathUsed",
        "privilegedUsed", "serviceAccountTokensMounted", "externalCredentialsAdded",
    ):
        require(security.get(key) is False, f"Unsafe runtime behavior enabled: {key}")

    acceptance = value.get("acceptance", {})
    require(acceptance.get("offlineValidator") == "scripts/validate-v0.11.6.2.1-private-local-otel-collector-tempo-runtime.sh", "Offline validator changed")
    require(acceptance.get("liveEntrypoint") == "scripts/check-local-tracing-runtime.sh", "Live checker changed")
    for key in (
        "helmRenderRequired", "syntheticOtlpTraceRequired", "tempoTraceQueryRequired",
        "collectorPodReplacementHistoryRequired", "applicationExportDisabledRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("consecutiveRunsRequired") == 2, "Two-run acceptance removed")

    operations = value.get("operations", {})
    require(operations.get("localPlatformReconciliationRequired") is True, "Reconciliation requirement removed")
    for key in ("imageRebuildRequired", "applicationCodeChangeRequired", "loggingRuntimeRedeployRequired", "databaseEnablementRequired"):
        require(operations.get(key) is False, f"Unnecessary operation enabled: {key}")
    require(value.get("nextIncrement", {}).get("version") == "v0.11.6.2.2", "Next increment changed")


contract_path = "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json"
contract = json.loads(read(contract_path))
validate(contract)
require((root / contract["designDocument"]).is_file(), "Design document missing")
require((root / "delivery/contracts/v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.json").is_file(), "Predecessor contract missing")

platform_chart = read("clusters/local/platform/Chart.yaml")
require("version: 0.7.0" in platform_chart and 'appVersion: "v0.11.6.2.1"' in platform_chart, "Local platform identity changed")
platform_values = read("clusters/local/platform/values.yaml")
for marker in (
    "otelCollector:", "https://open-telemetry.github.io/opentelemetry-helm-charts", "version: 0.172.0",
):
    require(marker in platform_values, f"Collector pin missing: {marker}")
require("tempo:" not in platform_values, "Deprecated external Tempo Chart input returned")

tempo_chart = read("platform/tracing/tempo/Chart.yaml")
require("version: 0.1.0" in tempo_chart and 'appVersion: "3.0.3"' in tempo_chart, "Tempo Chart identity changed")
tempo_config = read("platform/tracing/tempo/templates/configmap.yaml")
for marker in (
    "multitenancy_enabled: false", "backend_worker:", "block_retention: {{ .Values.retention }}",
    "backend: local", "path: /data/tempo/wal", "path: /data/tempo/blocks",
    "reporting_enabled: false",
):
    require(marker in tempo_config, f"Tempo configuration marker missing: {marker}")
for forbidden in ("compactor:", "kafka:", "metrics_generator:", "s3:", "minio"):
    require(forbidden not in tempo_config.lower(), f"Forbidden Tempo component found: {forbidden}")

collector_values = read("clusters/local/platform/files/tracing/otel-collector-values.yaml")
for marker in (
    "mode: deployment", "replicaCount: 1", "tag: \"0.159.0\"", "alternateConfig:",
    "otlp_http/tempo:", "memory_limiter:", "batch:", "pipelines:", "traces:",
    "automountServiceAccountToken: false", "clusterRole:", "create: false",
):
    require(marker in collector_values, f"Collector marker missing: {marker}")
for forbidden in ("tail_sampling", "k8sattributes", "kind: ingress", "type: loadbalancer", "privileged: true", "hostpath:"):
    require(forbidden not in collector_values.lower(), f"Forbidden Collector behavior found: {forbidden}")

for relative, name, wave in (
    ("clusters/local/platform/templates/tracing-tempo.yaml", "tracing-tempo", "7"),
    ("clusters/local/platform/templates/tracing-otel-collector.yaml", "tracing-otel-collector", "8"),
):
    application = read(relative)
    require(f"name: {name}" in application, f"Application name missing: {name}")
    require(f'sync-wave: "{wave}"' in application, f"Application wave changed: {name}")
    require("CreateNamespace=true" in application, f"Namespace creation option missing: {name}")

tempo_app = read("clusters/local/platform/templates/tracing-tempo.yaml")
require("path: platform/tracing/tempo" in tempo_app and ".Values.git.targetRevision" in tempo_app, "Tempo is not repository revision unified")
require("chart: tempo" not in tempo_app, "Deprecated external Tempo Chart used")
collector_app = read("clusters/local/platform/templates/tracing-otel-collector.yaml")
require("chart: opentelemetry-collector" in collector_app and ".Values.externalCharts.otelCollector.version" in collector_app, "Collector Chart pin missing")

demo_app = read("clusters/local/platform/templates/demo-api.yaml")
require("group: \"\"" not in demo_app, "Reconciliation repair regressed: empty group field returned")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.2.1-private-local-otel-collector-tempo-runtime.sh"),
    ("CHANGELOG.md", "## v0.11.6.2.1"),
    ("README.md", "v0.11.6.2.1-private-local-otel-collector-tempo-runtime"),
    ("docs/ROADMAP.md", "v0.11.6.2.1"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.2.1"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.2.1 implements"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/platform/tracing/tempo/ @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/check-local-tracing-runtime.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

repair_contract = root / "delivery/contracts/v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.json"
if repair_contract.is_file():
    repair_live = read("scripts/check-local-tracing-runtime.sh")
    repair_generator = read("scripts/generate-synthetic-otlp-trace.py")
    for marker in (
        '"traceId": normalized_trace_id',
        '"spanId": normalized_span_id',
        "OTLP HTTP request failed: status=",
        "get pods -l \"${TEMPO_SELECTOR}\"",
        "get pods -l \"${COLLECTOR_SELECTOR}\"",
    ):
        require(marker in repair_live or marker in repair_generator, f"Repair successor marker missing: {marker}")
    for forbidden in ("import base64", "b64encode", "bytes.fromhex"):
        require(forbidden not in repair_live and forbidden not in repair_generator, f"Repair successor regressed: {forbidden}")
    print("Synthetic OTLP/JSON repair successor coverage passed.")

mutations = (
    ("application export", lambda item: item["scope"].update(applicationExportEnabled=True)),
    ("Grafana expansion", lambda item: item["scope"].update(grafanaTraceDatasourceImplemented=True)),
    ("sampling", lambda item: item["collector"].update(samplingConfigured=True)),
    ("logs pipeline", lambda item: item["collector"].update(logsPipelineConfigured=True)),
    ("Kafka", lambda item: item["tempo"].update(kafkaRequired=True)),
    ("durability overclaim", lambda item: item["tempo"].update(storage="durable-object-storage")),
    ("deprecated Tempo Chart", lambda item: item["versions"].update(deprecatedExternalTempoChartUsed=True)),
    ("public endpoint", lambda item: item["security"].update(loadBalancerCreated=True)),
    ("service-account token", lambda item: item["security"].update(serviceAccountTokensMounted=True)),
    ("skip history proof", lambda item: item["acceptance"].update(collectorPodReplacementHistoryRequired=False)),
    ("image rebuild", lambda item: item["operations"].update(imageRebuildRequired=True)),
)
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {name}")

print("v0.11.6.2.1 contract, versions, private topology, security, and reconciliation predecessor checks passed.")
print("v0.11.6.2.1 export, Grafana, sampling, Kafka, durability, deprecated Chart, public, token, and stale acceptance mutations were rejected.")
PY

echo "==> Linting and rendering the repository-owned Tempo Chart"
helm lint "${ROOT_DIR}/platform/tracing/tempo" >/dev/null
helm template observability-tempo "${ROOT_DIR}/platform/tracing/tempo" \
  --namespace observability >"${WORK_DIR}/tempo.yaml"

echo "==> Linting and rendering the local platform Chart"
helm lint "${ROOT_DIR}/clusters/local/platform" >/dev/null
helm template local-platform "${ROOT_DIR}/clusters/local/platform" \
  >"${WORK_DIR}/platform-stable.yaml"
helm template local-platform "${ROOT_DIR}/clusters/local/platform" \
  --set-string git.targetRevision=0123456789abcdef0123456789abcdef01234567 \
  >"${WORK_DIR}/platform-feature.yaml"

echo "==> Resolving and rendering the pinned OpenTelemetry Collector Chart"
if [ -n "${OTEL_COLLECTOR_CHART_DIR}" ]; then
  [ -d "${OTEL_COLLECTOR_CHART_DIR}" ] || {
    echo "OTEL_COLLECTOR_CHART_DIR is not a directory: ${OTEL_COLLECTOR_CHART_DIR}" >&2
    exit 1
  }
  collector_chart="${OTEL_COLLECTOR_CHART_DIR}"
  collector_version="$(helm show chart "${collector_chart}" | sed -n 's/^version: //p')"
  collector_repo_args=()
else
  collector_chart="opentelemetry-collector"
  collector_version="$(helm show chart "${collector_chart}" \
    --repo https://open-telemetry.github.io/opentelemetry-helm-charts \
    --version 0.172.0 | sed -n 's/^version: //p')"
  collector_repo_args=(--repo https://open-telemetry.github.io/opentelemetry-helm-charts --version 0.172.0)
fi
[ "${collector_version}" = "0.172.0" ] || {
  echo "Pinned Collector Chart 0.172.0 was not resolved." >&2
  exit 1
}
helm template observability-otel-collector "${collector_chart}" \
  "${collector_repo_args[@]}" \
  --namespace observability \
  -f "${ROOT_DIR}/clusters/local/platform/files/tracing/otel-collector-values.yaml" \
  >"${WORK_DIR}/collector.yaml"

python3 - \
  "${WORK_DIR}/tempo.yaml" \
  "${WORK_DIR}/collector.yaml" \
  "${WORK_DIR}/platform-stable.yaml" \
  "${WORK_DIR}/platform-feature.yaml" <<'PY'
from pathlib import Path
import re
import sys


tempo, collector, stable, feature = (Path(path).read_text() for path in sys.argv[1:])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def kinds(text: str) -> list[str]:
    return re.findall(r"^kind: (\S+)$", text, re.MULTILINE)


require(sorted(kinds(tempo)) == sorted(["NetworkPolicy", "ServiceAccount", "ConfigMap", "Service", "Deployment"]), "Tempo resource set changed")
require("image: \"grafana/tempo:3.0.3\"" in tempo, "Tempo image pin changed")
require("replicas: 1" in tempo and "- -target=all" in tempo, "Tempo is not one monolithic replica")
require("type: ClusterIP" in tempo and "emptyDir:" in tempo, "Tempo local service/storage changed")
require("automountServiceAccountToken: false" in tempo, "Tempo token mounted")
for forbidden in ("kind: Ingress", "type: LoadBalancer", "hostPath:", "privileged: true", "kind: StatefulSet"):
    require(forbidden not in tempo, f"Forbidden Tempo render found: {forbidden}")

require(sorted(kinds(collector)) == sorted(["NetworkPolicy", "ServiceAccount", "ConfigMap", "Service", "Deployment"]), "Collector resource set changed")
require("opentelemetry-collector-k8s:0.159.0" in collector, "Collector image pin changed")
require("replicas: 1" in collector and "type: ClusterIP" in collector, "Collector private topology changed")
require("automountServiceAccountToken: false" in collector, "Collector token mounted")
require(re.search(r"pipelines:\s*\n\s+traces:", collector) is not None, "Collector traces pipeline missing")
for forbidden in ("kind: ClusterRole", "kind: Ingress", "type: LoadBalancer", "hostPath:", "hostPort:", "privileged: true", "tail_sampling", "jaeger:", "zipkin:"):
    require(forbidden not in collector, f"Forbidden Collector render found: {forbidden}")

for text, revision in ((stable, "HEAD"), (feature, "0123456789abcdef0123456789abcdef01234567")):
    names = set(re.findall(r"^  name: ([^\s]+)$", text, re.MULTILINE))
    require({"tracing-tempo", "tracing-otel-collector"}.issubset(names), "Tracing Applications missing")
    tempo_document = next(part for part in re.split(r"^---\s*$", text, flags=re.MULTILINE) if "name: tracing-tempo" in part)
    require(f"targetRevision: {revision}" in tempo_document or f'targetRevision: "{revision}"' in tempo_document, "Tempo repository revision is not unified")
    collector_document = next(part for part in re.split(r"^---\s*$", text, flags=re.MULTILINE) if "name: tracing-otel-collector" in part)
    require('targetRevision: "0.172.0"' in collector_document, "Collector external version changed")

print("Tempo, Collector, and stable/feature platform Helm renders passed.")
PY

bash -n "${ROOT_DIR}/scripts/check-local-tracing-runtime.sh"

echo "v0.11.6.2.1 private local OTel Collector and Tempo runtime validation passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command_name in helm python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

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


EXPECTED_LABELS = [
    "environment",
    "cluster",
    "namespace",
    "application",
    "container",
    "severity",
]
EXPECTED_FORBIDDEN_LABELS = [
    "service_name",
    "pod",
    "pod_name",
    "pod_uid",
    "image",
    "image_digest",
    "release_id",
    "source_commit",
    "request_id",
    "trace_id",
    "span_id",
]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.11.6.1.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.1", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.1.0", "Bad predecessor")

    scope = value.get("scope", {})
    for key in ("lokiImplemented", "alloyPodLogsImplemented"):
        require(scope.get(key) is True, f"Required scope disabled: {key}")
    for key in (
        "applicationCodeChanged",
        "applicationImageChanged",
        "kubernetesEventsImplemented",
        "grafanaLokiDatasourceImplemented",
        "tracingImplemented",
    ):
        require(scope.get(key) is False, f"Scope expanded prematurely: {key}")

    applications = value.get("applications", [])
    require(len(applications) == 2, "Logging Application set changed")
    require(
        [(item.get("name"), item.get("syncWave")) for item in applications]
        == [("logging-loki", 7), ("logging-alloy", 8)],
        "Logging Application order changed",
    )
    require(
        applications[0].get("repository") == "https://grafana-community.github.io/helm-charts"
        and applications[0].get("chartVersion") == "18.11.3"
        and applications[0].get("applicationVersion") == "3.7.6",
        "Loki version pin changed",
    )
    require(
        applications[1].get("repository") == "https://grafana.github.io/helm-charts"
        and applications[1].get("chartVersion") == "1.11.0"
        and applications[1].get("applicationVersion") == "1.18.0",
        "Alloy version pin changed",
    )

    loki = value.get("loki", {})
    require(loki.get("deploymentMode") == "Monolithic", "Loki mode changed")
    require((loki.get("replicas"), loki.get("replicationFactor")) == (1, 1), "Loki singleton changed")
    require((loki.get("indexStore"), loki.get("objectStore"), loki.get("schema")) == ("tsdb", "filesystem", "v13"), "Loki storage schema changed")
    require((loki.get("persistence"), loki.get("storageCapacity"), loki.get("retention")) == ("emptyDir", "2Gi", "24h"), "Local storage profile changed")
    for key in (
        "authenticationEnabled",
        "publicIngress",
        "minioEnabled",
        "canaryEnabled",
        "chunksCacheEnabled",
        "resultsCacheEnabled",
        "automaticServiceNameDiscoveryEnabled",
    ):
        require(loki.get(key) is False, f"Loki boundary expanded: {key}")
    require(loki.get("gatewayEnabled") is True and loki.get("gatewayServiceType") == "ClusterIP", "Private Loki gateway changed")

    alloy = value.get("alloy", {})
    require(alloy.get("controller") == "DaemonSet", "Alloy controller changed")
    require(alloy.get("collectionMethod") == "kubernetes-api", "Alloy collection method changed")
    require(alloy.get("nodeLocalDiscovery") is True, "Node-local discovery disabled")
    for key in ("hostPathRequired", "privilegedRequired", "hostNetwork", "hostPID", "serviceEnabled", "publicIngress", "configurationReloadSidecarEnabled"):
        require(alloy.get(key) is False, f"Alloy boundary expanded: {key}")
    for key in ("serviceAccountTokenRequired", "nonJsonLinesPreserved", "podIdentityAsStructuredMetadata", "networkPolicyEnabled"):
        require(alloy.get(key) is True, f"Alloy requirement disabled: {key}")
    require(alloy.get("rbacResources") == ["namespaces", "pods", "pods/log"], "Alloy RBAC scope changed")
    require(alloy.get("kubernetesApiServiceCidr") == "10.96.0.1/32", "Local Kubernetes API egress changed")

    labels = value.get("labels", {})
    require(labels.get("allowedIndexed") == EXPECTED_LABELS, "Indexed label contract changed")
    require(labels.get("forbiddenIndexed") == EXPECTED_FORBIDDEN_LABELS, "Forbidden label contract changed")
    require(labels.get("static") == {"environment": "local", "cluster": "startup-devops-local"}, "Static label identity changed")

    versions = value.get("versions", {})
    require((versions.get("localPlatformChartPrevious"), versions.get("localPlatformChart"), versions.get("localPlatformApp")) == ("0.4.1", "0.5.0", "v0.11.6.1.1"), "Local platform version transition changed")
    require((versions.get("demoApiChart"), versions.get("demoApiApp")) == ("0.6.0", "0.4.0"), "demo-api changed")
    require((versions.get("observabilityViewsChart"), versions.get("observabilityViewsApp")) == ("0.4.1", "v0.11.5.1.1"), "Observability views changed")
    require(all(item is False for item in value.get("unchanged", {}).values()), "Unchanged boundary expanded")

    acceptance = value.get("acceptance", {})
    for key in (
        "completeQualityGateRequired",
        "localGitOpsRedeployRequired",
        "lokiQueryRequired",
        "indexedLabelInventoryRequired",
        "oldPodLogSurvivesDemoApiReplacementRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    for key in ("imageRebuildRequired", "demoApiRedeployRequired"):
        require(acceptance.get(key) is False, f"Unnecessary application action required: {key}")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")


contract_path = "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.6.1.0-structured-demo-api-logging-runtime.json").is_file(), "Missing predecessor contract")
require(
    (root / "delivery/contracts/v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.json").is_file(),
    "Missing application-scoped live-acceptance repair contract",
)

chart = read("clusters/local/platform/Chart.yaml")
require("version: 0.5.0" in chart and 'appVersion: "v0.11.6.1.1"' in chart, "Local platform Chart not advanced")
values = read("clusters/local/platform/values.yaml")
for marker in (
    "repoURL: https://grafana-community.github.io/helm-charts",
    "version: 18.11.3",
    "repoURL: https://grafana.github.io/helm-charts",
    "version: 1.11.0",
):
    require(marker in values, f"External Chart pin missing: {marker}")

loki_app = read("clusters/local/platform/templates/logging-loki.yaml")
alloy_app = read("clusters/local/platform/templates/logging-alloy.yaml")
for text, markers in (
    (loki_app, ("name: logging-loki", 'sync-wave: "7"', "chart: loki", "releaseName: observability-logs", 'files/logging/loki-values.yaml', "CreateNamespace=true", "ServerSideApply=true")),
    (alloy_app, ("name: logging-alloy", 'sync-wave: "8"', "chart: alloy", "releaseName: observability-logs-collector", 'files/logging/alloy-values.yaml', "CreateNamespace=true", "ServerSideApply=true")),
):
    for marker in markers:
        require(marker in text, f"Logging Application marker missing: {marker}")

loki_values = read("clusters/local/platform/files/logging/loki-values.yaml")
for marker in (
    "deploymentMode: Monolithic",
    "replication_factor: 1",
    "store: tsdb",
    "object_store: filesystem",
    "schema: v13",
    "type: filesystem",
    "retention_enabled: true",
    "delete_request_store: filesystem",
    "retention_period: 24h",
    "max_query_lookback: 24h",
    "discover_service_name: []",
    "sizeLimit: 2Gi",
    "sidecar:\n  rules:\n    enabled: false",
    "name: observability-logs-cluster-only",
):
    require(marker in loki_values, f"Loki values marker missing: {marker}")
for marker in ("minio:\n  enabled: false", "lokiCanary:\n  enabled: false", "chunksCache:\n  enabled: false", "resultsCache:\n  enabled: false", "ingress:\n    enabled: false"):
    require(marker in loki_values, f"Loki local reduction missing: {marker}")
require(loki_values.count("replicas: 1") == 2, "Only Loki and gateway may have one replica")
require(loki_values.count("replicas: 0") == 13, "Non-monolithic Loki replica zeroing changed")
for forbidden in ("type: LoadBalancer", "type: NodePort", "object_store: s3", "ignoreMinioDeprecation: true"):
    require(forbidden not in loki_values, f"Forbidden Loki value found: {forbidden}")

alloy_values = read("clusters/local/platform/files/logging/alloy-values.yaml")
for marker in (
    "type: daemonset",
    'names = ["startup-apps"]',
    'field = "spec.nodeName=" + coalesce(sys.env("HOSTNAME"), constants.hostname)',
    'loki.source.kubernetes "pod_logs"',
    "drop_malformed = false",
    "stage.structured_metadata",
    "stage.label_keep",
    'values = ["environment", "cluster", "namespace", "application", "container", "severity"]',
    'environment = "local"',
    'cluster     = "startup-devops-local"',
    "observability-logs-gateway.observability.svc.cluster.local/loki/api/v1/push",
    "readOnlyRootFilesystem: true",
    "runAsNonRoot: true",
    "runAsUser: 473",
    "runAsGroup: 473",
    "fsGroup: 473",
    "automountServiceAccountToken: true",
    "pods/log",
    "networkPolicy:\n  enabled: true",
    "cidr: 10.96.0.1/32",
):
    require(marker in alloy_values, f"Alloy values marker missing: {marker}")
for forbidden in ("hostPath:", "privileged: true", "cidr: 0.0.0.0/0", "loki.source.kubernetes_events", "tempo", "otlp", "service_name"):
    require(forbidden not in alloy_values, f"Premature or unsafe Alloy value found: {forbidden}")

rbac_start = alloy_values.find("\nrbac:\n")
rbac_end = alloy_values.find("\nserviceAccount:\n", rbac_start)
require(rbac_start >= 0 and rbac_end > rbac_start, "Could not isolate Alloy RBAC values")
rbac_values = alloy_values[rbac_start:rbac_end]
require("rules: []" not in rbac_values, "Alloy Chart cannot render an empty RBAC rule list")
require("clusterRules: []" not in rbac_values, "Alloy Chart cannot render an empty clusterRules list")
require(rbac_values.count("    - apiGroups:") == 2, "Alloy least-privilege RBAC must use two non-empty rule lists")
require(
    {item.strip() for item in re.findall(r"(?m)^\s{8}- (namespaces|pods|pods/log)$", rbac_values)}
    == {"namespaces", "pods", "pods/log"},
    "Alloy RBAC resource inventory changed",
)

live = read("scripts/check-local-logging-runtime.sh")
for marker in (
    "wait_application",
    "statefulset/${LOKI_STATEFULSET}",
    "daemonset/${ALLOY_DAEMONSET}",
    "/loki/api/v1/query_range",
    "/loki/api/v1/series",
    "query_fsnotify_errors",
    '.stream.pod_name == $pod',
    '(.stream.pod_uid // "") != ""',
    "Unexpected indexed Loki labels",
    "delete pod",
    "pre-replacement demo-api log disappeared",
):
    require(marker in live, f"Live checker marker missing: {marker}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.1-local-loki-alloy-pod-logs.sh"),
    ("scripts/validate.sh", "wait_application_ready"),
    ("scripts/validate.sh", "Alloy Pod-log collector"),
    ("README.md", "v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair"),
    ("docs/ROADMAP.md", "v0.11.6.1.1 - local Loki Monolithic and node-local Alloy Pod-log"),
    ("docs/OBSERVABILITY.md", "check-local-logging-runtime.sh"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.1.1"),
    ("CHANGELOG.md", "## v0.11.6.1.1"),
    (".github/CODEOWNERS", "/scripts/check-local-logging-runtime.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("distributed Loki", lambda value: value["loki"].__setitem__("deploymentMode", "Distributed")),
    ("high-cardinality label", lambda value: value["labels"]["allowedIndexed"].append("pod")),
    ("duplicate event collector", lambda value: value["scope"].__setitem__("kubernetesEventsImplemented", True)),
    ("host filesystem", lambda value: value["alloy"].__setitem__("hostPathRequired", True)),
    ("public gateway", lambda value: value["loki"].__setitem__("gatewayServiceType", "LoadBalancer")),
    ("premature tracing", lambda value: value["scope"].__setitem__("tracingImplemented", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.1.1 local Loki, Alloy, label-cardinality, storage, and security contracts passed.")
print("v0.11.6.1.1 distributed, high-cardinality, duplicate-event, host-path, public, and tracing mutations were rejected.")
PY

echo "==> Rendering the local App-of-Apps Chart"
helm lint "${ROOT_DIR}/clusters/local/platform"
helm template startup-devops-root "${ROOT_DIR}/clusters/local/platform" \
  >"${WORK_DIR}/local-platform.yaml"

python3 - "${WORK_DIR}/local-platform.yaml" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text()
applications = re.findall(r"(?m)^kind: Application\nmetadata:\n  name: (\S+)$", text)
required = {"logging-loki", "logging-alloy"}
missing = sorted(required - set(applications))
if missing:
    raise SystemExit(f"Rendered local platform lacks logging Applications: {', '.join(missing)}")
if text.count("name: logging-loki") != 1 or text.count("name: logging-alloy") != 1:
    raise SystemExit("Rendered logging Application cardinality changed")
PY

echo "==> Rendering pinned Loki and Alloy Charts"
helm template observability-logs loki \
  --repo https://grafana-community.github.io/helm-charts \
  --version 18.11.3 \
  --namespace observability \
  --values "${ROOT_DIR}/clusters/local/platform/files/logging/loki-values.yaml" \
  >"${WORK_DIR}/loki.yaml"
helm template observability-logs-collector alloy \
  --repo https://grafana.github.io/helm-charts \
  --version 1.11.0 \
  --namespace observability \
  --values "${ROOT_DIR}/clusters/local/platform/files/logging/alloy-values.yaml" \
  >"${WORK_DIR}/alloy.yaml"

python3 - "${WORK_DIR}/loki.yaml" "${WORK_DIR}/alloy.yaml" <<'PY'
from pathlib import Path
import re
import sys

loki = Path(sys.argv[1]).read_text()
alloy = Path(sys.argv[2]).read_text()

def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def normalized_yaml_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def resource_document(rendered: str, expected_kind: str, expected_name: str) -> str:
    for document in re.split(r"(?m)^---\s*$", rendered):
        kind_match = re.search(
            r"(?m)^kind:[ \t]*(?P<value>[^#\n]+?)[ \t]*(?:#.*)?$",
            document,
        )
        metadata_match = re.search(
            r"(?m)^metadata:[ \t]*(?:#.*)?\n(?P<body>(?:^[ \t]+[^\n]*(?:\n|$))*)",
            document,
        )
        if kind_match is None or metadata_match is None:
            continue
        name_match = re.search(
            r"(?m)^  name:[ \t]*(?P<value>[^#\n]+?)[ \t]*(?:#.*)?$",
            metadata_match.group("body"),
        )
        if name_match is None:
            continue
        if (
            normalized_yaml_scalar(kind_match.group("value")) == expected_kind
            and normalized_yaml_scalar(name_match.group("value")) == expected_name
        ):
            return document
    return ""


for name_literal in (
    "observability-logs",
    '"observability-logs"',
    "'observability-logs'",
):
    fixture = f"kind: StatefulSet\nmetadata:\n  labels:\n    test: fixture\n  name: {name_literal}\nspec: {{}}\n"
    require(
        resource_document(fixture, "StatefulSet", "observability-logs") == fixture,
        f"Manifest name normalization rejected: {name_literal}",
    )


statefulset = resource_document(loki, "StatefulSet", "observability-logs")
require(statefulset, "Rendered Loki StatefulSet missing")
gateway = resource_document(loki, "Deployment", "observability-logs-gateway")
require(gateway, "Rendered Loki gateway Deployment missing")
require("name: observability-logs-cluster-only" in loki, "Rendered Loki NetworkPolicy missing")
require("name: loki-sc-rules" not in statefulset, "Rendered Loki StatefulSet contains the unused rules sidecar")
require("automountServiceAccountToken: false" in statefulset, "Rendered Loki StatefulSet may mount a ServiceAccount token")
require("kind: Ingress" not in loki, "Rendered Loki contains an Ingress")
require("type: LoadBalancer" not in loki and "type: NodePort" not in loki, "Rendered Loki contains a public Service")
for forbidden in ("chunks-cache", "results-cache", "loki-canary", "minio"):
    require(forbidden not in loki.lower(), f"Rendered Loki contains disabled component: {forbidden}")

daemonset = resource_document(alloy, "DaemonSet", "observability-logs-collector")
require(daemonset, "Rendered Alloy DaemonSet missing")
require('names = ["startup-apps"]' in alloy, "Rendered Alloy discovery is not application-scoped")
require("kind: NetworkPolicy" in alloy, "Rendered Alloy NetworkPolicy missing")
require("kind: Ingress" not in alloy and "kind: Service\n" not in alloy, "Rendered Alloy exposes a service or Ingress")
require("hostPath:" not in alloy and "privileged: true" not in alloy, "Rendered Alloy requires host privileges")
for marker in (
    "readOnlyRootFilesystem: true",
    "allowPrivilegeEscalation: false",
    "runAsNonRoot: true",
    "runAsUser: 473",
    "runAsGroup: 473",
    "fsGroup: 473",
):
    require(marker in daemonset, f"Rendered Alloy security context missing: {marker}")

cluster_role = resource_document(alloy, "ClusterRole", "observability-logs-collector")
require(cluster_role, "Rendered Alloy ClusterRole missing")


def normalized_yaml_list_item(raw: str) -> str:
    match = re.fullmatch(
        r"[ \t]*-[ \t]+(?P<value>[^#\n]+?)[ \t]*(?:#.*)?",
        raw,
    )
    require(match is not None, f"Invalid rendered YAML list item: {raw!r}")
    return normalized_yaml_scalar(match.group("value"))


for fixture, expected in (
    ("        - namespaces", "namespaces"),
    ('  - "pods"', "pods"),
    ("    - 'pods/log'  # read-only subresource", "pods/log"),
):
    require(
        normalized_yaml_list_item(fixture) == expected,
        f"Rendered YAML list normalization rejected: {fixture!r}",
    )


resource_blocks = re.findall(r"(?ms)^\s+resources:\n((?:\s+- [^\n]+\n)+)", cluster_role)
rendered_resources = {
    normalized_yaml_list_item(line)
    for block in resource_blocks
    for line in block.splitlines()
    if line.strip()
}
require(
    rendered_resources == {"namespaces", "pods", "pods/log"},
    f"Rendered Alloy RBAC resources changed: {sorted(rendered_resources)}",
)
print("Pinned Loki and Alloy external Charts rendered with private, bounded runtime resources.")
PY

echo "v0.11.6.1.1 local Loki Monolithic and Alloy Pod-log offline validation passed."

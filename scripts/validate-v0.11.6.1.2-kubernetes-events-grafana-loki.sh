#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

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
EXPECTED_FORBIDDEN = [
    "job",
    "instance",
    "event_name",
    "event_uid",
    "reason",
    "involved_object_name",
    "involved_object_uid",
    "pod",
    "pod_uid",
    "trace_id",
    "span_id",
]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.11.6.1.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.2", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.1.1.5", "Bad predecessor")

    scope = value.get("scope", {})
    for key in ("kubernetesEventsImplemented", "grafanaLokiDatasourceImplemented"):
        require(scope.get(key) is True, f"Required scope disabled: {key}")
    for key in (
        "podLogPipelineChanged",
        "applicationCodeChanged",
        "applicationImageChanged",
        "tracingImplemented",
    ):
        require(scope.get(key) is False, f"Scope expanded: {key}")

    application = value.get("application", {})
    require(
        (
            application.get("name"),
            application.get("syncWave"),
            application.get("chart"),
            application.get("repository"),
            application.get("chartVersion"),
            application.get("applicationVersion"),
            application.get("releaseName"),
        )
        == (
            "logging-alloy-events",
            9,
            "alloy",
            "https://grafana.github.io/helm-charts",
            "1.11.0",
            "1.18.0",
            "observability-events-collector",
        ),
        "Events Application identity changed",
    )

    collector = value.get("eventsCollector", {})
    require((collector.get("controller"), collector.get("replicas")) == ("Deployment", 1), "Events singleton changed")
    require(collector.get("collectionScope") == "all-namespaces", "Event collection scope changed")
    require(collector.get("collectionMethod") == "kubernetes-api", "Event collection method changed")
    require(collector.get("component") == "loki.source.kubernetes_events", "Event component changed")
    require(collector.get("logFormat") == "json", "Event log format changed")
    require(collector.get("clustered") is False, "Unexpected Alloy clustering")
    require(collector.get("positionsPersistent") is True, "Persistent Event positions disabled")
    require(
        (
            collector.get("positionsClaim"),
            collector.get("positionsCapacity"),
            collector.get("positionsPath"),
        )
        == ("observability-events-collector-storage", "256Mi", "/var/lib/alloy"),
        "Event position storage changed",
    )
    require(collector.get("rbacResources") == ["events"], "Events RBAC expanded")
    require(collector.get("rbacVerbs") == ["get", "list", "watch"], "Events RBAC verbs changed")
    for key in ("hostPathRequired", "privilegedRequired", "hostNetwork", "hostPID", "publicService"):
        require(collector.get(key) is False, f"Unsafe collector boundary: {key}")
    for key in ("serviceAccountTokenRequired", "networkPolicyEnabled"):
        require(collector.get(key) is True, f"Collector requirement disabled: {key}")
    require(collector.get("kubernetesApiServiceCidr") == "10.96.0.1/32", "Kubernetes API egress changed")

    labels = value.get("labels", {})
    require(labels.get("allowedIndexed") == EXPECTED_LABELS, "Indexed Event labels changed")
    require(labels.get("forbiddenIndexed") == EXPECTED_FORBIDDEN, "Forbidden Event labels changed")
    require(
        labels.get("static")
        == {
            "environment": "local",
            "cluster": "startup-devops-local",
            "application": "kubernetes-events",
            "container": "events",
            "severity": "INFO",
        },
        "Static Event labels changed",
    )

    grafana = value.get("grafana", {})
    require(grafana.get("managedBy") == "kube-prometheus-stack", "Grafana owner changed")
    require(
        (
            grafana.get("datasourceName"),
            grafana.get("datasourceUid"),
            grafana.get("datasourceType"),
            grafana.get("access"),
            grafana.get("url"),
        )
        == (
            "Loki",
            "loki",
            "loki",
            "proxy",
            "http://observability-logs-gateway.observability.svc.cluster.local",
        ),
        "Grafana Loki data source changed",
    )
    for key in ("defaultDatasource", "editable", "publicIngress"):
        require(grafana.get(key) is False, f"Unsafe Grafana setting: {key}")
    require((grafana.get("maxLines"), grafana.get("timeoutSeconds")) == (1000, 60), "Grafana Loki query bounds changed")
    require((grafana.get("serviceType"), grafana.get("networkPolicyPort")) == ("ClusterIP", 8080), "Grafana network boundary changed")

    versions = value.get("versions", {})
    require(
        (
            versions.get("localPlatformChartPrevious"),
            versions.get("localPlatformChart"),
            versions.get("localPlatformApp"),
        )
        == ("0.5.0", "0.6.0", "v0.11.6.1.2"),
        "Local platform version transition changed",
    )
    require((versions.get("lokiChart"), versions.get("lokiApplicationVersion")) == ("18.11.3", "3.7.6"), "Loki version changed")
    require((versions.get("alloyChart"), versions.get("alloyApplicationVersion")) == ("1.11.0", "1.18.0"), "Alloy version changed")
    require((versions.get("demoApiChart"), versions.get("demoApiApplicationVersion")) == ("0.6.0", "0.4.0"), "demo-api version changed")
    require(all(item is False for item in value.get("unchanged", {}).values()), "Unchanged boundary expanded")

    acceptance = value.get("acceptance", {})
    for key in (
        "completeQualityGateRequired",
        "localGitOpsRedeployRequired",
        "singletonCollectorRequired",
        "persistentPositionRestartCheckRequired",
        "eventQueryRequired",
        "eventIndexedLabelInventoryRequired",
        "grafanaDatasourceHealthRequired",
        "podLogRegressionRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("imageRebuildRequired") is False, "Unnecessary image rebuild required")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Closure boundary moved")


contract_path = "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.json").is_file(), "Missing predecessor repair contract")

chart = read("clusters/local/platform/Chart.yaml")
tracing_successor = (root / "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json").is_file()
require(
    ("version: 0.7.0" if tracing_successor else "version: 0.6.0") in chart
    and ('appVersion: "v0.11.6.2.1"' if tracing_successor else 'appVersion: "v0.11.6.1.2"') in chart,
    "Local platform Chart not advanced",
)

sync_wave_repair = (
    root
    / "delivery/contracts/v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.json"
).is_file()
expected_events_wave = "8" if sync_wave_repair else "9"
application = read("clusters/local/platform/templates/logging-alloy-events.yaml")
for marker in (
    "name: logging-alloy-events",
    f'sync-wave: "{expected_events_wave}"',
    "chart: alloy",
    "releaseName: observability-events-collector",
    'files/logging/alloy-events-values.yaml',
    "CreateNamespace=true",
    "ServerSideApply=true",
):
    require(marker in application, f"Events Application marker missing: {marker}")

storage = read("clusters/local/platform/templates/logging-alloy-events-storage.yaml")
for marker in (
    "kind: PersistentVolumeClaim",
    "name: observability-events-collector-storage",
    "namespace: observability",
    'sync-wave: "8"',
    "- ReadWriteOnce",
    "storage: 256Mi",
):
    require(marker in storage, f"Event position storage marker missing: {marker}")
if sync_wave_repair:
    require(
        'sync-wave: "8"' in application and 'sync-wave: "8"' in storage,
        "WaitForFirstConsumer PVC and Events Application are separated across sync waves",
    )

events = read("clusters/local/platform/files/logging/alloy-events-values.yaml")
for marker in (
    "fullnameOverride: observability-events-collector",
    "storagePath: /var/lib/alloy",
    'mountPath: /var/lib/alloy',
    'loki.source.kubernetes_events "cluster_events"',
    'log_format = "json"',
    'application = "kubernetes-events"',
    'container   = "events"',
    'severity    = "INFO"',
    'values = ["environment", "cluster", "namespace", "application", "container", "severity"]',
    "type: deployment",
    "replicas: 1",
    "claimName: observability-events-collector-storage",
    "runAsUser: 473",
    "runAsGroup: 473",
    "automountServiceAccountToken: true",
    "cidr: 10.96.0.1/32",
    "observability-logs-gateway.observability.svc.cluster.local/loki/api/v1/push",
):
    require(marker in events, f"Events Alloy marker missing: {marker}")
for forbidden in (
    "type: daemonset",
    "hostPath:",
    "privileged: true",
    "cidr: 0.0.0.0/0",
    "loki.source.kubernetes \"pod_logs\"",
    "discovery.kubernetes",
    "tempo",
    "otlp",
):
    require(forbidden not in events, f"Unsafe or premature Events Alloy value: {forbidden}")

rbac_start = events.find("\nrbac:\n")
rbac_end = events.find("\nserviceAccount:\n", rbac_start)
require(rbac_start >= 0 and rbac_end > rbac_start, "Could not isolate Events RBAC")
rbac = events[rbac_start:rbac_end]
require("rules: []" not in rbac and "clusterRules: []" not in rbac, "Empty Alloy RBAC list found")
require(set(re.findall(r"(?m)^\s{8}- (events)$", rbac)) == {"events"}, "Events RBAC resources expanded")
require(set(re.findall(r"(?m)^\s{8}- (get|list|watch)$", rbac)) == {"get", "list", "watch"}, "Events RBAC verbs changed")

monitoring = read("clusters/local/platform/templates/monitoring.yaml")
for marker in (
    "additionalDataSources:",
    "- name: Loki",
    "uid: loki",
    "type: loki",
    "access: proxy",
    "url: http://observability-logs-gateway.observability.svc.cluster.local",
    "isDefault: false",
    "editable: false",
    "maxLines: 1000",
    "timeout: 60",
    "port: 8080",
):
    require(marker in monitoring, f"Grafana Loki provisioning marker missing: {marker}")
require(monitoring.count("- name: Loki") == 1, "Grafana Loki data source cardinality changed")
require("isDefault: true" not in monitoring, "Loki replaced Prometheus as the default data source")
for forbidden in ("kind: Ingress", "type: LoadBalancer", "type: NodePort"):
    require(forbidden not in monitoring, f"Public monitoring exposure found: {forbidden}")
grafana_policy_start = monitoring.find("name: grafana-cluster-only")
grafana_policy_end = monitoring.find("\n  destination:\n", grafana_policy_start)
require(grafana_policy_start >= 0 and grafana_policy_end > grafana_policy_start, "Could not isolate Grafana NetworkPolicy")
grafana_policy = monitoring[grafana_policy_start:grafana_policy_end]
require("port: 8080" in grafana_policy, "Grafana NetworkPolicy lacks private Loki access")

live = read("scripts/check-local-events-grafana.sh")
for marker in (
    "logging-alloy-events",
    "observability-events-collector-storage",
    "kubectl auth can-i",
    "events.k8s.io/v1",
    "/loki/api/v1/query_range",
    "/loki/api/v1/series",
    "/api/datasources/uid/loki",
    "/api/datasources/uid/loki/health",
    "rollout restart",
    "replayed a previously accepted Event",
):
    require(marker in live, f"Live checker marker missing: {marker}")
microtime_repair = (
    root
    / "delivery/contracts/v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.json"
).is_file()
if microtime_repair:
    for marker in (
        "from datetime import datetime, timezone",
        'isoformat(timespec="microseconds")',
        '.replace("+00:00", "Z")',
    ):
        require(marker in live, f"Event MicroTime repair marker missing: {marker}")
    require("%N" not in live, "Nanosecond Event timestamp regression found")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.2-kubernetes-events-grafana-loki.sh"),
    ("scripts/validate.sh", "Alloy Kubernetes Event collector"),
    ("README.md", "v0.11.6.1.2"),
    ("docs/ROADMAP.md", "v0.11.6.1.2 - singleton Kubernetes Event collection"),
    ("docs/OBSERVABILITY.md", "check-local-events-grafana.sh"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.1.2"),
    ("CHANGELOG.md", "## v0.11.6.1.2"),
    (".github/CODEOWNERS", "/scripts/check-local-events-grafana.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("duplicate collector", lambda value: value["eventsCollector"].__setitem__("replicas", 2)),
    ("volatile positions", lambda value: value["eventsCollector"].__setitem__("positionsPersistent", False)),
    ("RBAC expansion", lambda value: value["eventsCollector"]["rbacResources"].append("secrets")),
    ("high-cardinality label", lambda value: value["labels"]["allowedIndexed"].append("event_uid")),
    ("public Grafana", lambda value: value["grafana"].__setitem__("publicIngress", True)),
    ("default Loki", lambda value: value["grafana"].__setitem__("defaultDatasource", True)),
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

print("v0.11.6.1.2 singleton Events, durable positions, bounded labels, and Grafana Loki contracts passed.")
print("v0.11.6.1.2 duplicate, volatile, RBAC, high-cardinality, public, default, and tracing mutations were rejected.")
if sync_wave_repair:
    print("v0.11.6.1.2.1 same-wave WaitForFirstConsumer successor coverage passed.")
if microtime_repair:
    print("v0.11.6.1.2.2 six-digit Event MicroTime successor coverage passed.")
PY

command -v helm >/dev/null 2>&1 || {
  echo "Required command not found: helm" >&2
  exit 1
}

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
required = {"logging-loki", "logging-alloy", "logging-alloy-events"}
missing = sorted(required - set(applications))
if missing:
    raise SystemExit(f"Rendered local platform lacks logging Applications: {', '.join(missing)}")
for name in required:
    if applications.count(name) != 1:
        raise SystemExit(f"Rendered logging Application cardinality changed: {name}")
if text.count("name: observability-events-collector-storage") != 1:
    raise SystemExit("Rendered Event position PVC cardinality changed")
PY

echo "==> Rendering pinned singleton Events Alloy Chart"
helm template observability-events-collector alloy \
  --repo https://grafana.github.io/helm-charts \
  --version 1.11.0 \
  --namespace observability \
  --values "${ROOT_DIR}/clusters/local/platform/files/logging/alloy-events-values.yaml" \
  >"${WORK_DIR}/alloy-events.yaml"

python3 - "${WORK_DIR}/alloy-events.yaml" <<'PY'
from pathlib import Path
import re
import sys

rendered = Path(sys.argv[1]).read_text()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def resource_document(expected_kind: str, expected_name: str) -> str:
    for document in re.split(r"(?m)^---\s*$", rendered):
        kind = re.search(r"(?m)^kind:\s*([^#\n]+)", document)
        metadata = re.search(r"(?m)^metadata:\s*\n(?P<body>(?:^\s+[^\n]*(?:\n|$))*)", document)
        if kind is None or metadata is None:
            continue
        name = re.search(r"(?m)^  name:\s*([^#\n]+)", metadata.group("body"))
        if name is not None and scalar(kind.group(1)) == expected_kind and scalar(name.group(1)) == expected_name:
            return document
    return ""


deployment = resource_document("Deployment", "observability-events-collector")
require(deployment, "Rendered Events Alloy Deployment missing")
require("replicas: 1" in deployment, "Rendered Events Alloy is not singleton")
require("claimName: observability-events-collector-storage" in deployment, "Rendered Events positions are not persistent")
for marker in (
    "runAsNonRoot: true",
    "runAsUser: 473",
    "runAsGroup: 473",
    "readOnlyRootFilesystem: true",
    "allowPrivilegeEscalation: false",
    "mountPath: /var/lib/alloy",
):
    require(marker in deployment, f"Rendered Events security/storage marker missing: {marker}")
require("kind: DaemonSet" not in rendered, "Events collector rendered as a DaemonSet")
require("kind: Ingress" not in rendered, "Events collector rendered an Ingress")
require("hostPath:" not in rendered and "privileged: true" not in rendered, "Unsafe Events workload rendered")

cluster_role = resource_document("ClusterRole", "observability-events-collector")
require(cluster_role, "Rendered Events Alloy ClusterRole missing")
resources = set(re.findall(r"(?m)^\s+- (events|pods|pods/log|secrets|configmaps)$", cluster_role))
verbs = set(re.findall(r"(?m)^\s+- (get|list|watch|create|update|patch|delete)$", cluster_role))
require(resources == {"events"}, f"Rendered Events RBAC resources expanded: {sorted(resources)}")
require(verbs == {"get", "list", "watch"}, f"Rendered Events RBAC verbs changed: {sorted(verbs)}")
require("name: observability-events-collector" in rendered and "kind: NetworkPolicy" in rendered, "Rendered Events NetworkPolicy missing")

print("Pinned Alloy Chart renders one non-root Event Deployment with durable positions and exact read-only Event RBAC.")
PY

echo "v0.11.6.1.2 Kubernetes Events and Grafana Loki integration validation passed."

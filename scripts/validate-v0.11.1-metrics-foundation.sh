#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Validating v0.11.1 metrics foundation"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any


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
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON in {relative}: {exc}") from exc
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


EXPECTED_PROFILES = {
    "local": {
        "retention": "6h",
        "retentionSize": "2GiB",
        "storage": "emptyDir",
        "replicas": 1,
        "productionClaim": False,
    },
    "aws-dev": {
        "retention": "24h",
        "retentionSize": "8GiB",
        "storageClass": "gp3-observability",
        "storage": "10Gi",
        "replicas": 1,
        "productionClaim": False,
    },
    "aws-test": {
        "retention": "48h",
        "retentionSize": "8GiB",
        "storageClass": "gp3-observability",
        "storage": "10Gi",
        "replicas": 1,
        "productionClaim": False,
    },
    "aws-prod": {
        "retention": "7d",
        "retentionSize": "16GiB",
        "storageClass": "gp3-observability",
        "storage": "20Gi",
        "replicas": 1,
        "productionClaim": "requires-live-v0.11-acceptance",
    },
}


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schemaVersion") == "v0.11.1", "Bad schemaVersion")
    require(contract.get("version") == "v0.11.1", "Bad version")
    require(contract.get("status") == "offline-implemented", "Bad status")
    require(contract.get("liveAcceptanceClaimed") is False, "Live acceptance is claimed")

    for field in ("foundationContract", "designDocument"):
        value = contract.get(field)
        require(isinstance(value, str) and (root / value).is_file(), f"Missing {field}")

    chart = contract.get("chart")
    require(isinstance(chart, dict), "Missing chart contract")
    require(
        chart == {
            "repository": "https://prometheus-community.github.io/helm-charts",
            "name": "kube-prometheus-stack",
            "version": "88.5.0",
            "releaseName": "observability-metrics",
            "namespace": "observability",
            "floatingVersionAllowed": False,
        },
        "Chart identity or pin changed",
    )

    enabled = contract.get("enabledComponents")
    disabled = contract.get("disabledComponents")
    require(isinstance(enabled, list), "Missing enabledComponents")
    require(isinstance(disabled, list), "Missing disabledComponents")
    for component in (
        "prometheus-operator", "prometheus", "kube-state-metrics",
        "node-exporter", "prometheus-operator-crds",
    ):
        require(component in enabled, f"Required component disabled: {component}")
    for component in (
        "grafana", "alertmanager", "default-alert-rules", "loki",
        "grafana-alloy", "tempo", "opentelemetry-collector", "thanos",
        "remote-write",
    ):
        require(component in disabled, f"Deferred component entered v0.11.1: {component}")

    require(contract.get("profiles") == EXPECTED_PROFILES, "Environment profiles changed")

    placement = contract.get("placement")
    require(isinstance(placement, dict), "Missing placement")
    require(
        placement.get("awsControlPlaneComponentsNodeSelector") == {"workload": "system"},
        "AWS metrics control plane is not on system nodes",
    )
    require(placement.get("nodeExporterToleratesAllWorkerTaints") is True, "node-exporter coverage weakened")
    require(placement.get("dedicatedObservabilityNodePoolRequired") is False, "Unexpected dedicated NodePool")

    compatibility = contract.get("applicationCompatibility")
    require(isinstance(compatibility, dict), "Missing application compatibility")
    require(compatibility.get("jobLabelSource") == "__meta_kubernetes_service_name", "Job compatibility changed")
    require(compatibility.get("requiredJobs") == ["demo-api", "demo-api-stable", "demo-api-canary"], "Job set changed")
    require(
        compatibility.get("legacyCanaryQuery") == 'sum(up{job="demo-api-canary"})',
        "Legacy Canary query changed",
    )

    security = contract.get("security")
    require(isinstance(security, dict), "Missing security contract")
    require(security.get("prometheusServiceType") == "ClusterIP", "Prometheus is not cluster-only")
    for field in ("publicIngress", "loadBalancer", "nodePort", "adminApiEnabled"):
        require(security.get(field) is False, f"Unsafe endpoint enabled: {field}")
    for field in ("networkPolicy", "startupAppsScrapeIngressExplicit", "scrapeLimitsRequired"):
        require(security.get(field) is True, f"Required protection disabled: {field}")

    storage = contract.get("awsStorage")
    require(isinstance(storage, dict), "Missing AWS storage contract")
    require(storage.get("provisioner") == "ebs.csi.aws.com", "Unexpected storage provisioner")
    require(storage.get("type") == "gp3", "Unexpected AWS volume type")
    require(storage.get("encrypted") is True, "AWS metrics volume is not encrypted")
    require(storage.get("reclaimPolicy") == "Delete", "Disposable volume is not deleted")
    require(storage.get("coveredByResidualCostAudit") is True, "Metrics volume is outside cleanup audit")

    migration = contract.get("migration")
    require(isinstance(migration, dict), "Missing migration contract")
    require(migration.get("legacyPathRetainedAsHistoricalMaterial") is True, "Legacy history removed")
    require(migration.get("legacyPathReferencedByActiveArgoApplication") is False, "Legacy Prometheus remains active")
    require(migration.get("acceptedBecauseLocalHasNoProductionClaim") is True, "Local cutover claims production")

    automation = contract.get("automationBoundary")
    require(isinstance(automation, dict), "Missing automation boundary")
    for field in (
        "releaseOrchestratorChanged", "automaticEnvironmentCreation",
        "automaticPullRequestMerge", "automaticProductionRolloutProgression",
        "automaticRollback",
    ):
        require(automation.get(field) is False, f"Automation boundary expanded: {field}")
    require(automation.get("productionApprovalPreserved") is True, "Production approval removed")


def require_markers(relative: str, markers: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in markers:
        require(marker in text, f"{relative}: missing marker {marker!r}")
    return text


def validate_repository() -> None:
    local = require_markers(
        "clusters/local/platform/templates/monitoring.yaml",
        (
            ".Values.externalCharts.monitoring.repoURL",
            "chart: kube-prometheus-stack",
            ".Values.externalCharts.monitoring.version",
            "releaseName: observability-metrics",
            "namespace: observability",
            "retention: 6h",
            "retentionSize: 2GiB",
            "emptyDir:",
            "name: prometheus-cluster-only",
            "type: ClusterIP",
            "enableAdminAPI: false",
        ),
    )
    require_markers(
        "clusters/local/platform/values.yaml",
        ("monitoring:", "version: 88.5.0"),
    )
    aws = require_markers(
        "clusters/aws/base/platform/monitoring.yaml",
        (
            "name: monitoring-aws-dev",
            "targetRevision: 88.5.0",
            "retention: 24h",
            "retentionSize: 8GiB",
            "workload: system",
            "operator: Exists",
            "storageClassName: gp3-observability",
            "storage: 10Gi",
            "provisioner: ebs.csi.aws.com",
            "encrypted: \"true\"",
            "tagSpecification_1: Project=startup-devops-baseline",
            "tagSpecification_2: Environment=dev",
            "tagSpecification_3: Component=observability-prometheus",
            "reclaimPolicy: Delete",
            "volumeBindingMode: WaitForFirstConsumer",
        ),
    )

    grafana_successor = (root / "delivery/contracts/v0.11.4.0-grafana-recording-rules.json").is_file()
    for text, label in ((local, "local"), (aws, "AWS")):
        for marker in ("kind: Ingress", "type: LoadBalancer", "type: NodePort"):
            require(marker not in text, f"{label} metrics stack exposes {marker}")
        require(re.search(r"(?ms)defaultRules:\n\s+create: false", text) is not None, f"{label}: default rules enabled")
        require(re.search(r"(?ms)alertmanager:\n\s+enabled: false", text) is not None, f"{label}: Alertmanager enabled")
        if grafana_successor:
            require(re.search(r"(?ms)grafana:\n\s+enabled: true", text) is not None, f"{label}: v0.11.4 Grafana successor missing")
            require("defaultDashboardsEnabled: false" in text, f"{label}: uncontrolled default dashboards enabled")
        else:
            require(re.search(r"(?ms)grafana:\n\s+enabled: false", text) is not None, f"{label}: Grafana enabled before v0.11.4")

    successor_monitor = root / "apps/demo-api/helm/templates/servicemonitor.yaml"
    if successor_monitor.is_file():
        for text, label in ((local, "local"), (aws, "AWS")):
            require("demo-api-compatibility" not in text, f"{label}: transitional application monitor remains")
            require("additionalServiceMonitors:" not in text, f"{label}: application telemetry remains platform-owned")
        require_markers(
            "apps/demo-api/helm/templates/servicemonitor.yaml",
            (
                "kind: ServiceMonitor",
                "- __meta_kubernetes_service_name",
                "targetLabel: job",
                "- __meta_kubernetes_pod_annotation_platform_startup_dev_release_id",
            ),
        )
    else:
        for marker in ("name: demo-api-compatibility", "- __meta_kubernetes_service_name", "targetLabel: job"):
            require(marker in local, f"local: missing transitional compatibility marker {marker!r}")

    base = require_markers(
        "clusters/aws/base/platform/kustomization.yaml",
        ("- monitoring.yaml",),
    )
    require(base.count("- monitoring.yaml") == 1, "AWS monitoring Application declared more than once")

    require_markers(
        "clusters/aws/overlays/test/kustomization.yaml",
        (
            "value: monitoring-aws-test",
            "value: 48h",
            "value: aws-test",
            "value: startup-devops-baseline-test",
            "value: Environment=test",
        ),
    )
    require_markers(
        "clusters/aws/overlays/prod/kustomization.yaml",
        (
            "value: monitoring-aws-prod",
            "value: 7d",
            "value: 16GiB",
            "value: 20Gi",
            "value: aws-prod",
            "value: startup-devops-baseline-prod",
            "value: Environment=prod",
        ),
    )

    require_markers(
        "clusters/aws/base/security/network-policies/startup-apps/policies.yaml",
        (
            "name: allow-observability-to-demo-api",
            "kubernetes.io/metadata.name: observability",
            "app.kubernetes.io/name: prometheus",
            "port: 8080",
        ),
    )

    endpoint = "http://observability-metrics-prometheus.observability.svc.cluster.local:9090"
    for relative in (
        "apps/demo-api/helm/values.yaml",
        "apps/demo-api/helm/templates/analysis-template.yaml",
        "apps/demo-api/helm/values-v0.3.3-analysis-snippet.yaml",
        "scripts/enable-demo-api-analysis.sh",
    ):
        require(endpoint in read(relative), f"{relative}: new Prometheus endpoint missing")

    active_cluster_yaml = "\n".join(
        path.read_text() for path in sorted((root / "clusters").rglob("*.yaml"))
    )
    require(
        "path: platform/monitoring/prometheus" not in active_cluster_yaml,
        "Active Argo CD declaration still references legacy Prometheus",
    )

    check_script = require_markers(
        "scripts/check-monitoring.sh",
        (
            "MONITORING_NAMESPACE=\"${MONITORING_NAMESPACE:-observability}\"",
            "PROMETHEUS_SERVICE=\"${PROMETHEUS_SERVICE:-observability-metrics-prometheus}\"",
            "--for=condition=Ready pod",
            "(.data.result | length) > 0",
        ),
    )
    require("deployment/prometheus" not in check_script, "Monitoring check still assumes legacy Deployment")

    require_markers(
        "docs/V0.11.1_METRICS_FOUNDATION.md",
        ("88.5.0", "Local Live Validation", "AWS Validation Boundary"),
    )


contract = load_json("delivery/contracts/v0.11.1-metrics-foundation.json")
validate_contract(contract)
validate_repository()

negative_cases: list[tuple[str, Any]] = [
    ("floating chart version", lambda value: value["chart"].update(version="*")),
    ("live evidence claim", lambda value: value.update(liveAcceptanceClaimed=True)),
    ("public Prometheus", lambda value: value["security"].update(publicIngress=True)),
    ("automatic merge", lambda value: value["automationBoundary"].update(automaticPullRequestMerge=True)),
    ("unbounded production storage", lambda value: value["profiles"]["aws-prod"].update(storage="100Gi")),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Negative case was accepted: {name}")

print("v0.11.1 metrics foundation validation passed.")
PY

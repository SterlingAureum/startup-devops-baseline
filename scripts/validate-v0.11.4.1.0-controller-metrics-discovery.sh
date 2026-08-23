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


def markers(relative: str, required: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in required:
        require(marker in text, f"{relative}: missing marker {marker}")
    return text


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.4.1.0", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.1.0", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    versions = value.get("componentVersions", {})
    require(versions.get("argoCD", {}).get("installationBoundaryChanged") is False, "Argo CD install boundary changed")
    require(versions.get("argoCD", {}).get("runtimeSemverImageRequired") is True, "Argo CD version is not observed")
    require(versions.get("argoCD", {}).get("exactVersionOverride") == "EXPECTED_ARGOCD_VERSION", "Wrong Argo CD override")
    require(versions.get("argoCD", {}).get("requiredMetric") == "argocd_app_info", "Wrong Argo CD metric")
    require(versions.get("argoRollouts", {}).get("chartVersion") == "2.41.1", "Wrong Rollouts Chart")
    require(versions.get("argoRollouts", {}).get("applicationVersion") == "v1.9.1", "Wrong Rollouts app")
    require(versions.get("cloudNativePG", {}).get("chartVersion") == "0.29.0", "Wrong CNPG Chart")
    require(versions.get("cloudNativePG", {}).get("applicationVersion") == "1.30.0", "Wrong CNPG app")
    require(versions.get("cloudNativePG", {}).get("awsOnly") is True, "CNPG local boundary changed")
    require(versions.get("kubePrometheusStack", {}).get("chartVersion") == "88.5.0", "Wrong monitoring Chart")

    monitors = value.get("monitors", {})
    require(len(monitors.get("local", [])) == 2, "Local monitor set changed")
    require(len(monitors.get("awsAdditional", [])) == 2, "AWS monitor set changed")
    require(monitors.get("cloudNativePGMetricLabel") == "cnpg_cluster", "CNPG identity label changed")
    require(monitors.get("kubernetesClusterExternalLabelPreserved") is True, "Cluster identity collision accepted")
    require(monitors.get("scrapeInterval") == "30s", "Scrape interval changed")

    rules = value.get("recordingRules", {})
    require(len(rules.get("names", [])) == 21, "Recording-rule set changed")
    require(rules.get("alertRulesAdded") is False, "Alert rule added")
    require(rules.get("missingDataCoercedToHealthyZero") is False, "Missing data hidden")
    require(rules.get("dashboardAdded") is False, "Dashboard added early")

    require(all(value.get("discovery", {}).values()), "Live discovery check disabled")
    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Boundary expanded")
    acceptance = value.get("acceptance", {})
    require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
    require(acceptance.get("localLiveDiscoveryRequired") is True, "Local discovery optional")
    require(acceptance.get("cloudNativePGLiveEvidenceDeferredTo") == "v0.11.8", "AWS evidence moved")
    require(acceptance.get("dashboardsDeferredTo") == "v0.11.4.1.1", "Dashboard boundary changed")


contract = json.loads(read("delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json"))
validate_contract(contract)

markers(
    "platform/observability/helm/Chart.yaml",
    ("name: startup-devops-observability-views", "version: 0.2.0", 'appVersion: "v0.11.4.1.0"'),
)
values = markers(
    "platform/observability/helm/values.yaml",
    (
        "controllerMonitors:",
        "scrapeInterval: 30s",
        "argoCD:",
        "argoRollouts:",
        "cloudNativePG:",
        "enabled: false",
        "clusterName: postgresql-baseline",
    ),
)
require("feature/" not in values, "Feature revision committed to observability values")

monitor_text = markers(
    "platform/observability/helm/templates/controller-monitors.yaml",
    (
        "kind: ServiceMonitor",
        "name: argocd-application-controller",
        "app.kubernetes.io/name: argocd-metrics",
        "name: argo-rollouts-controller",
        "app.kubernetes.io/component: rollouts-controller",
        "kind: PodMonitor",
        "name: cloudnative-pg-operator",
        "name: cloudnative-pg-cluster",
        "cnpg.io/cluster:",
        "port: metrics",
        "targetLabel: cnpg_cluster",
        "action: labeldrop",
    ),
)
require(monitor_text.count("kind: ServiceMonitor") == 2, "ServiceMonitor set changed")
require(monitor_text.count("kind: PodMonitor") == 2, "PodMonitor set changed")
require("port: 9187" not in monitor_text, "PodMonitor bypasses the named metrics port")

rule_text = markers(
    "platform/observability/helm/templates/operator-recording-rules.yaml",
    (
        "kind: PrometheusRule",
        "delivery.operator.v0.11.4.1.0",
        "data.operator.v0.11.4.1.0",
        "platform.operator.v0.11.4.1.0",
        "argocd_app_info",
        "rollout_info",
        "cnpg_collector_up",
        "kube_deployment_spec_replicas",
    ),
)
found_rules = re.findall(r"^\s*- record:\s*(\S+)\s*$", rule_text, re.MULTILINE)
require(found_rules == contract["recordingRules"]["names"], "Recording-rule names or ordering changed")
require(re.search(r"^\s*- alert:", rule_text, re.MULTILINE) is None, "Alert rule added")
require("or vector(0)" not in rule_text, "Missing data is coerced to zero")
for forbidden in ("pod_uid", "trace_id", "request_id", "raw_url"):
    require(forbidden not in rule_text, f"Unbounded dimension retained: {forbidden}")

local_rollouts = markers(
    "clusters/local/platform/templates/argo-rollouts.yaml",
    ("chart: argo-rollouts", "controller:", "metrics:", "enabled: true", "dashboard:", "enabled: false"),
)
aws_rollouts = markers(
    "clusters/aws/base/platform/argo-rollouts.yaml",
    ("chart: argo-rollouts", "targetRevision: 2.41.1", "controller:", "metrics:", "enabled: true", "dashboard:"),
)
require("serviceMonitor:\n          enabled: true" not in local_rollouts + aws_rollouts, "External Chart owns ServiceMonitor")
markers("clusters/local/platform/values.yaml", ("version: 2.41.1", "version: 88.5.0"))
markers("clusters/local/platform/Chart.yaml", ("version: 0.3.0", 'appVersion: "v0.11.4.1.0"'))
markers(
    "clusters/aws/base/platform/observability-views.yaml",
    ("controllerMonitors.cloudNativePG.enabled", 'value: "true"'),
)

markers(
    "scripts/install-argocd.sh",
    ("argoproj/argo-cd/stable/manifests/install.yaml",),
)
markers(
    "scripts/bootstrap-eks-argocd.sh",
    ('ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"',),
)

live = markers(
    "scripts/check-controller-metrics.sh",
    (
        "PROFILE=",
        "EXPECTED_ARGOCD_VERSION",
        "assert_semver_image",
        "EXPECTED_ROLLOUTS_VERSION",
        "EXPECTED_CNPG_VERSION",
        "/api/v1/targets?state=active",
        "/api/v1/label/__name__/values",
        "/api/v1/rules?type=record",
        "PROFILE must be local or aws",
    ),
)
for rule_name in contract["recordingRules"]["names"]:
    require(rule_name in live, f"Live validator does not check {rule_name}")

historical = markers(
    "scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh",
    (
        "v0.11.4.1.0-controller-metrics-discovery.json",
        'expected_rollouts_version = "2.41.1" if controller_metrics_successor else "2.41.0"',
    ),
)
require('"version: 0.3.0" if controller_metrics_successor' in historical, "Platform Chart successor missing")
markers(
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    ("v0.11.4.1.0-controller-metrics-discovery.json", "controller_metrics_successor"),
)

markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.1.0 controller metrics discovery", "validate-v0.11.4.1.0-controller-metrics-discovery.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json @SterlingAureum",
        "/scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh @SterlingAureum",
        "/scripts/check-controller-metrics.sh @SterlingAureum",
        "/docs/V0.11.4.1.0_CONTROLLER_METRICS_DISCOVERY.md @SterlingAureum",
    ),
)

dashboard_paths = sorted((root / "platform/observability/helm/dashboards").glob("*.json"))
require([path.name for path in dashboard_paths] == ["service-overview.json"], "Dashboard added before v0.11.4.1.1")

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("unobserved Argo CD", lambda value: value["componentVersions"]["argoCD"].update(runtimeSemverImageRequired=False)),
    ("old Rollouts", lambda value: value["componentVersions"]["argoRollouts"].update(chartVersion="2.41.0")),
    ("local CNPG", lambda value: value["componentVersions"]["cloudNativePG"].update(awsOnly=False)),
    ("label collision", lambda value: value["monitors"].update(kubernetesClusterExternalLabelPreserved=False)),
    ("missing-data zero", lambda value: value["recordingRules"].update(missingDataCoercedToHealthyZero=True)),
    ("early Dashboard", lambda value: value["recordingRules"].update(dashboardAdded=True)),
    ("alert rule", lambda value: value["boundaries"].update(alertRulesAdded=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.4.1.0 controller versions, discovery, monitors, rules, and boundaries passed.")
PY

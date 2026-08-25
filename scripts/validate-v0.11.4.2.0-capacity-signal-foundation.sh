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
        return json.loads(read(relative))
    except json.JSONDecodeError as error:
        raise ContractError(f"Invalid JSON: {relative}: {error}") from error


def markers(relative: str, required: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in required:
        require(marker in text, f"{relative}: missing marker {marker}")
    return text


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.4.2.0", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.2.0", "Bad version")
    require(value.get("predecessor") == "v0.11.4.1.1", "Bad predecessor")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    chart = value.get("chart", {})
    require(chart.get("previousVersion") == "0.2.2", "Wrong predecessor Chart")
    require(chart.get("version") == "0.3.0", "Wrong capacity Chart")
    require(chart.get("applicationVersion") == "v0.11.4.2.0", "Wrong application version")

    sources = value.get("sourceMetrics", {})
    require(sources.get("ownership") == "existing-kube-prometheus-stack-core-targets", "Source ownership changed")
    require(len(sources.get("names", [])) == 7, "Source metric set changed")
    for name in ("newMonitorAdded", "newExporterAdded", "kubePrometheusStackChanged"):
        require(sources.get(name) is False, f"Source boundary expanded: {name}")

    rules = value.get("recordingRules", {})
    require(rules.get("resource") == "PrometheusRule/capacity-efficiency-recording-rules", "Wrong rule resource")
    require(rules.get("evaluationInterval") == "30s", "Rule interval changed")
    require(rules.get("groups") == [
        "capacity.foundation.v0.11.4.2.0",
        "efficiency.foundation.v0.11.4.2.0",
    ], "Rule groups changed")
    require(len(rules.get("names", [])) == 20, "Capacity rule count changed")

    semantics = value.get("semantics", {})
    require(semantics.get("activePodPhases") == ["Pending", "Running"], "Active phases changed")
    for name in (
        "requestsAndLimitsAreContainerReservationProxies",
        "namespaceUsageRatioRequiresPositiveRequest",
        "missingRequestZeroAnchoredToActiveContainers",
        "globalVectorZeroForbidden",
        "noSourceProducesNoData",
    ):
        require(semantics.get(name) is True, f"Semantics weakened: {name}")
    for name in ("schedulerExactFitClaimed", "currencyCostClaimed"):
        require(semantics.get(name) is False, f"Unsupported claim enabled: {name}")
    require(semantics.get("cpuUsageWindow") == "5m", "CPU window changed")
    require(semantics.get("memoryUsageType") == "working-set", "Memory usage changed")

    live = value.get("liveDiscovery", {})
    require(live.get("profiles") == ["local", "aws"], "Live profiles changed")
    require(live.get("awsFormalEvidenceDeferredTo") == "v0.11.8", "AWS evidence moved")
    for name, flag in live.items():
        if name not in {"script", "profiles", "awsFormalEvidenceDeferredTo"}:
            require(flag is True, f"Live check disabled: {name}")

    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Boundary expanded")

    acceptance = value.get("acceptance", {})
    require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
    require(acceptance.get("localLiveDiscoveryRequired") is True, "Local live check optional")
    require(acceptance.get("operatorDashboardRegressionRequired") is True, "Dashboard regression optional")
    require(acceptance.get("capacityDashboardDeferredTo") == "v0.11.4.2.1", "Dashboard boundary changed")
    require(acceptance.get("cleanLocalReplayDeferredTo") == "v0.11.4.2-final", "Clean replay boundary changed")


contract = load_json("delivery/contracts/v0.11.4.2.0-capacity-signal-foundation.json")
validate_contract(contract)
capacity_dashboard_successor = (root / "delivery/contracts/v0.11.4.2.1-capacity-efficiency-dashboard.json").is_file()

expected_views_chart_version = "version: 0.3.1" if capacity_dashboard_successor else "version: 0.3.0"
expected_views_app_version = (
    'appVersion: "v0.11.4.2.1"' if capacity_dashboard_successor else 'appVersion: "v0.11.4.2.0"'
)

markers(
    "platform/observability/helm/Chart.yaml",
    ("name: startup-devops-observability-views", expected_views_chart_version, expected_views_app_version),
)

rules_path = contract["recordingRules"]["path"]
rules = markers(
    rules_path,
    (
        "kind: PrometheusRule",
        "name: capacity-efficiency-recording-rules",
        "capacity.foundation.v0.11.4.2.0",
        "efficiency.foundation.v0.11.4.2.0",
        'phase=~"Pending|Running"',
        "0 * count by (namespace)",
        "and on (namespace)",
    ),
)
found_rules = re.findall(r"^\s*- record:\s*(\S+)\s*$", rules, re.MULTILINE)
require(found_rules == contract["recordingRules"]["names"], "Capacity rule ordering or names changed")
found_groups = re.findall(r"^\s*- name:\s*([^\s]+)\s*$", rules, re.MULTILINE)
require(found_groups == contract["recordingRules"]["groups"], "Capacity group names changed")
for source_name in contract["sourceMetrics"]["names"]:
    require(source_name in rules, f"Recording rules do not use source: {source_name}")
require("or vector(0)" not in rules, "Global missing-data zero fallback added")
require(re.search(r"^\s*- alert:", rules, re.MULTILINE) is None, "Capacity increment added an alert")
require(rules.count("0 * count by (namespace)") >= 4, "Namespace zero anchors changed")
require(rules.count("efficiency:namespace_cpu_requests_cores:sum > 0") == 1, "CPU ratio request guard changed")
require(rules.count("efficiency:namespace_memory_requests_bytes:sum > 0") == 1, "Memory ratio request guard changed")

operator_contract = load_json("delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json")
operator_rules = read("platform/observability/helm/templates/operator-recording-rules.yaml")
found_operator_rules = re.findall(r"^\s*- record:\s*(\S+)\s*$", operator_rules, re.MULTILINE)
require(found_operator_rules == operator_contract["recordingRules"]["names"], "Existing operator rules changed")

service_rules = read("platform/observability/helm/templates/recording-rules.yaml")
require(service_rules.count("        - record:") == 9, "Existing service rules changed")
require("or vector(0)" not in service_rules + operator_rules, "Existing no-data boundary changed")

expected_dashboards = {
    "data-overview.json": ("startup-devops-data-overview", 6),
    "delivery-overview.json": ("startup-devops-delivery-overview", 8),
    "platform-overview.json": ("startup-devops-platform-overview", 6),
    "service-overview.json": ("startup-devops-service-overview", 5),
}
if capacity_dashboard_successor:
    expected_dashboards["capacity-overview.json"] = ("startup-devops-capacity-overview", 12)
dashboard_dir = root / "platform/observability/helm/dashboards"
require(set(path.name for path in dashboard_dir.glob("*.json")) == set(expected_dashboards), "Dashboard set changed")
for filename, (uid, panel_count) in expected_dashboards.items():
    dashboard = load_json(f"platform/observability/helm/dashboards/{filename}")
    require(dashboard.get("uid") == uid, f"Dashboard UID changed: {filename}")
    require(len(dashboard.get("panels", [])) == panel_count, f"Dashboard panels changed: {filename}")
    text = json.dumps(dashboard)
    if filename == "capacity-overview.json":
        pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)+")
        used_rules = set(pattern.findall(text))
        require(used_rules == set(contract["recordingRules"]["names"]), "Capacity Dashboard rule set changed")
    else:
        require("capacity:" not in text and "efficiency:" not in text, f"Existing Dashboard consumed capacity rules: {filename}")

live = markers(
    "scripts/check-capacity-signals.sh",
    (
        "PROFILE must be local or aws",
        "capacity-efficiency-recording-rules",
        "/api/v1/label/__name__/values",
        "/api/v1/rules?type=record",
        "startup-apps efficiency and request coverage",
        "is empty or non-finite",
        "v0.11.4.2.0 capacity source, recording-rule, and request-coverage live acceptance passed.",
    ),
)
for source_name in contract["sourceMetrics"]["names"]:
    require(source_name in live, f"Live check misses source metric: {source_name}")
for rule_name in contract["recordingRules"]["names"]:
    require(rule_name in live, f"Live check misses recording rule: {rule_name}")

historical_v040 = markers(
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    (
        "v0.11.4.2.0-capacity-signal-foundation.json",
        'expected_views_chart_version = "version: 0.3.0"',
        'expected_views_app_version = \'appVersion: "v0.11.4.2.0"\'',
    ),
)
require("capacity_signal_successor" in historical_v040, "v0.11.4.0 successor branch missing")
historical_v0410 = markers(
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    (
        "v0.11.4.2.0-capacity-signal-foundation.json",
        'expected_views_chart_version = "version: 0.3.0"',
        'expected_views_app_version = \'appVersion: "v0.11.4.2.0"\'',
    ),
)
require("capacity_signal_successor" in historical_v0410, "v0.11.4.1.0 successor branch missing")
historical_ratio = markers(
    "scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh",
    (
        "v0.11.4.2.0-capacity-signal-foundation.json",
        'expected_views_chart_version = "version: 0.3.0"',
        'expected_views_app_version = \'appVersion: "v0.11.4.2.0"\'',
    ),
)
require("capacity_signal_successor" in historical_ratio, "v0.11.4.1.0.2 successor branch missing")
historical_dashboards = markers(
    "scripts/validate-v0.11.4.1.1-operator-dashboards.sh",
    (
        "v0.11.4.2.0-capacity-signal-foundation.json",
        'expected_views_chart_version = "version: 0.3.0"',
        'expected_views_app_version = \'appVersion: "v0.11.4.2.0"\'',
    ),
)
require("capacity_signal_successor" in historical_dashboards, "v0.11.4.1.1 successor branch missing")

markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.2.0 capacity signal foundation", "validate-v0.11.4.2.0-capacity-signal-foundation.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/delivery/contracts/v0.11.4.2.0-capacity-signal-foundation.json @SterlingAureum",
        "/scripts/validate-v0.11.4.2.0-capacity-signal-foundation.sh @SterlingAureum",
        "/scripts/check-capacity-signals.sh @SterlingAureum",
        "/docs/V0.11.4.2.0_CAPACITY_SIGNAL_FOUNDATION.md @SterlingAureum",
    ),
)

for monitoring_path in (
    "clusters/local/platform/templates/monitoring.yaml",
    "clusters/aws/base/platform/monitoring.yaml",
):
    monitoring = read(monitoring_path)
    require("capacity-efficiency-recording-rules" not in monitoring, f"Monitoring ownership changed: {monitoring_path}")
    require("kubecost" not in monitoring.lower(), f"Kubecost added: {monitoring_path}")

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("global zero", lambda value: value["semantics"].update(globalVectorZeroForbidden=False)),
    ("scheduler claim", lambda value: value["semantics"].update(schedulerExactFitClaimed=True)),
    ("currency claim", lambda value: value["semantics"].update(currencyCostClaimed=True)),
    ("new exporter", lambda value: value["sourceMetrics"].update(newExporterAdded=True)),
    ("Dashboard", lambda value: value["boundaries"].update(dashboardAdded=True)),
    ("autoscaling", lambda value: value["boundaries"].update(automaticScalingAdded=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.4.2.0 capacity source ownership, recording rules, semantics, and boundaries passed.")
PY

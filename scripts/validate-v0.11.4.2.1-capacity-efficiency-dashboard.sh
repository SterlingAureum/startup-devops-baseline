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
    require(value.get("schemaVersion") == "v0.11.4.2.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.2.1", "Bad version")
    require(value.get("predecessor") == "v0.11.4.2.0", "Bad predecessor")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    chart = value.get("chart", {})
    require(chart.get("previousVersion") == "0.3.0", "Wrong predecessor Chart")
    require(chart.get("version") == "0.3.1", "Wrong Dashboard Chart")
    require(chart.get("applicationVersion") == "v0.11.4.2.1", "Wrong application version")
    require(chart.get("dashboardConfigMapsExpected") == 5, "Dashboard ConfigMap count changed")

    dashboard = value.get("dashboard", {})
    require(dashboard.get("uid") == "startup-devops-capacity-overview", "Dashboard UID changed")
    require(dashboard.get("title") == "Startup DevOps / Capacity & Efficiency Overview", "Dashboard title changed")
    require(dashboard.get("panelCount") == 12, "Dashboard panel count changed")
    require(dashboard.get("variables") == ["namespace"], "Dashboard variables changed")
    require(len(dashboard.get("preservedDashboardUids", [])) == 4, "Preserved Dashboard set changed")
    require(len(dashboard.get("acceptedRules", [])) == 20, "Accepted rule set changed")
    require(dashboard.get("allAcceptedRulesConsumed") is True, "Rule consumption is incomplete")

    policy = value.get("dashboardPolicy", {})
    require(policy.get("editable") is False, "Dashboard UI drift accepted")
    require(policy.get("datasourceUid") == "prometheus", "Datasource UID changed")
    require(policy.get("refresh") == "30s", "Refresh changed")
    require(policy.get("defaultTimeRange") == "now-1h", "Time range changed")
    for name in (
        "recordingRulesOnly",
        "rawMetricsForbidden",
        "globalVectorZeroForbidden",
        "schedulerExactFitClaimForbidden",
        "currencyCostClaimForbidden",
        "missingSourceRemainsNoData",
    ):
        require(policy.get(name) is True, f"Dashboard policy disabled: {name}")

    live = value.get("liveAcceptance", {})
    require(live.get("profiles") == ["local", "aws"], "Live profiles changed")
    require(live.get("awsFormalEvidenceDeferredTo") == "v0.11.8", "AWS evidence moved")
    for name, flag in live.items():
        if name not in {"script", "profiles", "awsFormalEvidenceDeferredTo"}:
            require(flag is True, f"Live check disabled: {name}")

    boundaries = value.get("boundaries", {})
    require(boundaries.get("dashboardOnlyIncrement") is True, "Dashboard-only boundary missing")
    for name, flag in boundaries.items():
        if name != "dashboardOnlyIncrement":
            require(flag is False, f"Boundary expanded: {name}")

    acceptance = value.get("acceptance", {})
    require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
    require(acceptance.get("localLiveDashboardAcceptanceRequired") is True, "Local live check optional")
    require(acceptance.get("capacitySignalRegressionRequired") is True, "Capacity regression optional")
    require(acceptance.get("operatorDashboardRegressionRequired") is True, "Operator regression optional")
    require(acceptance.get("cleanLocalReplayRequiredAfterAcceptance") is True, "Clean replay optional")


def dashboard_queries(dashboard: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            expression = target.get("expr")
            if expression:
                queries.append(expression)
    for variable in dashboard.get("templating", {}).get("list", []):
        definition = variable.get("definition")
        if definition:
            queries.append(definition)
    return queries


def recording_rule_names(queries: list[str]) -> set[str]:
    pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)+")
    return {name for query in queries for name in pattern.findall(query)}


contract = load_json("delivery/contracts/v0.11.4.2.1-capacity-efficiency-dashboard.json")
validate_contract(contract)
semantic_repair_successor = (root / "delivery/contracts/v0.11.5.1.1-prometheus-target-down-semantics-repair.json").is_file()
actionable_alerts_successor = (root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file()

if semantic_repair_successor:
    expected_views_chart_version = "version: 0.4.1"
    expected_views_app_version = 'appVersion: "v0.11.5.1.1"'
elif actionable_alerts_successor:
    expected_views_chart_version = "version: 0.4.0"
    expected_views_app_version = 'appVersion: "v0.11.5.1"'
else:
    expected_views_chart_version = "version: 0.3.1"
    expected_views_app_version = 'appVersion: "v0.11.4.2.1"'

markers(
    "platform/observability/helm/Chart.yaml",
    ("name: startup-devops-observability-views", expected_views_chart_version, expected_views_app_version),
)

expected_dashboards = {
    "capacity-overview.json": ("startup-devops-capacity-overview", 12),
    "data-overview.json": ("startup-devops-data-overview", 6),
    "delivery-overview.json": ("startup-devops-delivery-overview", 8),
    "platform-overview.json": ("startup-devops-platform-overview", 6),
    "service-overview.json": ("startup-devops-service-overview", 5),
}
dashboard_dir = root / "platform/observability/helm/dashboards"
require(set(path.name for path in dashboard_dir.glob("*.json")) == set(expected_dashboards), "Dashboard file set changed")
uids: list[str] = []
for filename, (uid, panel_count) in expected_dashboards.items():
    dashboard = load_json(f"platform/observability/helm/dashboards/{filename}")
    uids.append(dashboard.get("uid", ""))
    require(dashboard.get("uid") == uid, f"Dashboard UID changed: {filename}")
    require(dashboard.get("editable") is False, f"Dashboard is editable: {filename}")
    require(len(dashboard.get("panels", [])) == panel_count, f"Dashboard panels changed: {filename}")
require(len(uids) == len(set(uids)), "Dashboard UID collision")

capacity_dashboard = load_json(contract["dashboard"]["file"])
require(capacity_dashboard.get("title") == contract["dashboard"]["title"], "Capacity title changed")
require(capacity_dashboard.get("schemaVersion", 0) >= 39, "Capacity schema too old")
require(capacity_dashboard.get("refresh") == "30s", "Capacity refresh changed")
require(capacity_dashboard.get("time", {}).get("from") == "now-1h", "Capacity time range changed")
require([item.get("name") for item in capacity_dashboard.get("templating", {}).get("list", [])] == ["namespace"], "Namespace variable changed")
require("capacity" in capacity_dashboard.get("tags", []), "Capacity tag missing")
require("efficiency" in capacity_dashboard.get("tags", []), "Efficiency tag missing")

panel_ids = [panel.get("id") for panel in capacity_dashboard.get("panels", [])]
require(len(panel_ids) == len(set(panel_ids)), "Duplicate capacity panel ID")
for panel in capacity_dashboard.get("panels", []):
    require(panel.get("datasource", {}).get("uid") == "prometheus", f"Panel datasource changed: {panel.get('title')}")
    require(bool(panel.get("description")), f"Panel interpretation missing: {panel.get('title')}")
    grid = panel.get("gridPos", {})
    require(grid.get("w", 0) > 0 and grid.get("x", 0) + grid.get("w", 0) <= 24, f"Invalid panel grid: {panel.get('title')}")

queries = dashboard_queries(capacity_dashboard)
require(queries, "Capacity Dashboard has no queries")
require(all("or vector(0)" not in query for query in queries), "Dashboard added a global zero fallback")
source_contract = load_json("delivery/contracts/v0.11.4.2.0-capacity-signal-foundation.json")
for raw_name in source_contract["sourceMetrics"]["names"]:
    require(all(raw_name not in query for query in queries), f"Dashboard queries raw metric: {raw_name}")
used_rules = recording_rule_names(queries)
require(used_rules == set(contract["dashboard"]["acceptedRules"]), f"Capacity query rule set changed: {sorted(used_rules)}")

require(contract["dashboard"]["acceptedRules"] == source_contract["recordingRules"]["names"], "Dashboard does not use the exact accepted rule order")
rule_source = read(source_contract["recordingRules"]["path"])
found_rules = re.findall(r"^\s*- record:\s*(\S+)\s*$", rule_source, re.MULTILINE)
require(found_rules == source_contract["recordingRules"]["names"], "Accepted capacity rules changed")
require("or vector(0)" not in rule_source, "Capacity source gained global zero")

description_text = " ".join(panel.get("description", "") for panel in capacity_dashboard["panels"])
for marker in ("not exact scheduler headroom", "not currency cost", "remains no-data"):
    require(marker in description_text, f"Dashboard interpretation marker missing: {marker}")

template = markers(
    "platform/observability/helm/templates/dashboard-configmaps.yaml",
    ('.Files.Glob "dashboards/*.json"', '.Files.Get $path', "dashboardLabelValue"),
)
require("kubectl" not in template, "Dashboard provisioning bypasses GitOps")

live = markers(
    "scripts/check-capacity-dashboard.sh",
    (
        "PROFILE must be local or aws",
        "observability-dashboard-capacity-overview",
        "capacity-efficiency-recording-rules",
        "startup-devops-capacity-overview 12",
        "/api/dashboards/uid/",
        ".dashboard.editable == false",
        "Capacity Dashboard variable or tags changed.",
        "v0.11.4.2.1 Capacity and Resource Efficiency Dashboard live acceptance passed.",
    ),
)
for rule_name in (
    "capacity:node_cpu_allocatable_cores:sum",
    "capacity:node_memory_allocatable_bytes:sum",
    "capacity:running_pods_to_allocatable:ratio",
    "capacity:cpu_requests_to_allocatable:ratio",
    "capacity:memory_requests_to_allocatable:ratio",
    "efficiency:namespace_cpu_usage_to_requests:ratio",
    "efficiency:namespace_memory_usage_to_requests:ratio",
    "efficiency:namespace_containers_without_cpu_requests:count",
    "efficiency:namespace_containers_without_memory_requests:count",
):
    require(rule_name in live, f"Live check misses representative Dashboard rule: {rule_name}")

historical_files = (
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    "scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh",
)
for historical_file in historical_files:
    historical = markers(
        historical_file,
        (
            "v0.11.4.2.1-capacity-efficiency-dashboard.json",
            'expected_views_chart_version = "version: 0.3.1"',
            'expected_views_app_version = \'appVersion: "v0.11.4.2.1"\'',
        ),
    )
    require("capacity_dashboard_successor" in historical, f"Successor branch missing: {historical_file}")

historical_operator = markers(
    "scripts/validate-v0.11.4.1.1-operator-dashboards.sh",
    (
        "v0.11.4.2.1-capacity-efficiency-dashboard.json",
        'expected_views_chart_version = "version: 0.3.1"',
        'expected_views_app_version = \'appVersion: "v0.11.4.2.1"\'',
        'expected_files.insert(0, "capacity-overview.json")',
    ),
)
require("capacity_dashboard_successor" in historical_operator, "Operator Dashboard successor branch missing")

historical_capacity = markers(
    "scripts/validate-v0.11.4.2.0-capacity-signal-foundation.sh",
    (
        "v0.11.4.2.1-capacity-efficiency-dashboard.json",
        'expected_views_chart_version = "version: 0.3.1"',
        'expected_dashboards["capacity-overview.json"]',
        "Capacity Dashboard rule set changed",
    ),
)
require("capacity_dashboard_successor" in historical_capacity, "Capacity signal successor branch missing")

markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.2.1 Capacity and Resource Efficiency Dashboard", "validate-v0.11.4.2.1-capacity-efficiency-dashboard.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/delivery/contracts/v0.11.4.2.1-capacity-efficiency-dashboard.json @SterlingAureum",
        "/scripts/validate-v0.11.4.2.1-capacity-efficiency-dashboard.sh @SterlingAureum",
        "/scripts/check-capacity-dashboard.sh @SterlingAureum",
        "/docs/V0.11.4.2.1_CAPACITY_EFFICIENCY_DASHBOARD.md @SterlingAureum",
    ),
)

for monitoring_path in (
    "clusters/local/platform/templates/monitoring.yaml",
    "clusters/aws/base/platform/monitoring.yaml",
):
    monitoring = read(monitoring_path)
    require("revisionHistoryLimit" not in monitoring, f"Grafana Deployment changed: {monitoring_path}")
    require("kubecost" not in monitoring.lower(), f"Kubecost added: {monitoring_path}")

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("editable Dashboard", lambda value: value["dashboardPolicy"].update(editable=True)),
    ("raw metrics", lambda value: value["dashboardPolicy"].update(rawMetricsForbidden=False)),
    ("global zero", lambda value: value["dashboardPolicy"].update(globalVectorZeroForbidden=False)),
    ("scheduler claim", lambda value: value["dashboardPolicy"].update(schedulerExactFitClaimForbidden=False)),
    ("currency claim", lambda value: value["dashboardPolicy"].update(currencyCostClaimForbidden=False)),
    ("recording rule", lambda value: value["boundaries"].update(recordingRuleChanged=True)),
    ("autoscaling", lambda value: value["boundaries"].update(autoscalingAdded=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.4.2.1 immutable rule-backed Capacity and Resource Efficiency Dashboard passed.")
PY

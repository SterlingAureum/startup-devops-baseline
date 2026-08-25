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
    require(value.get("schemaVersion") == "v0.11.4.1.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.1.1", "Bad version")
    require(value.get("predecessor") == "v0.11.4.1.0.2", "Bad predecessor")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    chart = value.get("chart", {})
    require(chart.get("previousVersion") == "0.2.1", "Wrong predecessor Chart")
    require(chart.get("version") == "0.2.2", "Wrong Dashboard Chart")
    require(chart.get("applicationVersion") == "v0.11.4.1.1", "Wrong application version")
    require(chart.get("dashboardConfigMapsExpected") == 4, "Dashboard ConfigMap count changed")

    dashboards = value.get("dashboards", {})
    require(set(dashboards) == {"service", "delivery", "data", "platform"}, "Dashboard domains changed")
    require(dashboards.get("service", {}).get("preserved") is True, "Service Dashboard replaced")
    require(dashboards.get("delivery", {}).get("panelCount") == 8, "Delivery panel count changed")
    require(dashboards.get("data", {}).get("panelCount") == 6, "Data panel count changed")
    require(dashboards.get("platform", {}).get("panelCount") == 6, "Platform panel count changed")
    require(dashboards.get("data", {}).get("localCloudNativePGDataRequired") is False, "Local CNPG data forced")
    require(dashboards.get("data", {}).get("cloudNativePGLiveEvidenceDeferredTo") == "v0.11.8", "CNPG evidence moved")

    policy = value.get("dashboardPolicy", {})
    require(policy.get("editable") is False, "Dashboard UI drift accepted")
    require(policy.get("datasourceUid") == "prometheus", "Datasource UID changed")
    require(policy.get("refresh") == "30s", "Refresh changed")
    require(policy.get("defaultTimeRange") == "now-1h", "Time range changed")
    for name in ("recordingRulesOnly", "rawMetricsForbidden", "globalVectorZeroForbidden", "localCloudNativePGNoDataAllowed"):
        require(policy.get(name) is True, f"Dashboard policy disabled: {name}")

    live = value.get("liveAcceptance", {})
    require(live.get("profiles") == ["local", "aws"], "Live profiles changed")
    require(all(flag is True for name, flag in live.items() if name not in {"script", "profiles"}), "Live check disabled")

    boundaries = value.get("boundaries", {})
    require(boundaries.get("dashboardOnlyIncrement") is True, "Dashboard-only boundary missing")
    for name, flag in boundaries.items():
        if name != "dashboardOnlyIncrement":
            require(flag is False, f"Boundary expanded: {name}")

    acceptance = value.get("acceptance", {})
    require(acceptance.get("completeQualityGateRequired") is True, "Quality gate optional")
    require(acceptance.get("localLiveDashboardAcceptanceRequired") is True, "Local live check optional")
    require(acceptance.get("controllerMetricRegressionRequired") is True, "Controller regression optional")
    require(acceptance.get("capacityViewsDeferredTo") == "v0.11.4.2", "Capacity boundary changed")


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


contract = load_json("delivery/contracts/v0.11.4.1.1-operator-dashboards.json")
validate_contract(contract)
capacity_signal_successor = (root / "delivery/contracts/v0.11.4.2.0-capacity-signal-foundation.json").is_file()
capacity_dashboard_successor = (root / "delivery/contracts/v0.11.4.2.1-capacity-efficiency-dashboard.json").is_file()
actionable_alerts_successor = (root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file()

if actionable_alerts_successor:
    expected_views_chart_version = "version: 0.4.0"
    expected_views_app_version = 'appVersion: "v0.11.5.1"'
elif capacity_dashboard_successor:
    expected_views_chart_version = "version: 0.3.1"
    expected_views_app_version = 'appVersion: "v0.11.4.2.1"'
elif capacity_signal_successor:
    expected_views_chart_version = "version: 0.3.0"
    expected_views_app_version = 'appVersion: "v0.11.4.2.0"'
else:
    expected_views_chart_version = "version: 0.2.2"
    expected_views_app_version = 'appVersion: "v0.11.4.1.1"'

markers(
    "platform/observability/helm/Chart.yaml",
    ("name: startup-devops-observability-views", expected_views_chart_version, expected_views_app_version),
)

dashboard_dir = root / "platform/observability/helm/dashboards"
expected_files = [
    "data-overview.json",
    "delivery-overview.json",
    "platform-overview.json",
    "service-overview.json",
]
if capacity_dashboard_successor:
    expected_files.insert(0, "capacity-overview.json")
require(sorted(path.name for path in dashboard_dir.glob("*.json")) == expected_files, "Dashboard file set changed")

loaded_dashboards: dict[str, dict[str, Any]] = {}
for domain, spec in contract["dashboards"].items():
    dashboard = load_json(spec["file"])
    loaded_dashboards[domain] = dashboard
    require(dashboard.get("uid") == spec["uid"], f"{domain}: UID changed")
    require(dashboard.get("editable") is False, f"{domain}: Dashboard is editable")
    require(dashboard.get("schemaVersion", 0) >= 39, f"{domain}: schema too old")
    require(dashboard.get("refresh") == "30s", f"{domain}: refresh changed")
    require(dashboard.get("time", {}).get("from") == "now-1h", f"{domain}: time range changed")
    if domain == "service":
        continue
    require(dashboard.get("title") == spec["title"], f"{domain}: title changed")
    require(len(dashboard.get("panels", [])) == spec["panelCount"], f"{domain}: panel count changed")
    require(
        [item.get("name") for item in dashboard.get("templating", {}).get("list", [])] == spec["variables"],
        f"{domain}: variable set changed",
    )
    panel_ids = [panel.get("id") for panel in dashboard.get("panels", [])]
    require(len(panel_ids) == len(set(panel_ids)), f"{domain}: duplicate panel ID")
    for panel in dashboard.get("panels", []):
        require(panel.get("datasource", {}).get("uid") == "prometheus", f"{domain}: datasource changed")
        grid = panel.get("gridPos", {})
        require(grid.get("w", 0) > 0 and grid.get("x", 0) + grid.get("w", 0) <= 24, f"{domain}: invalid grid")
    queries = dashboard_queries(dashboard)
    require(queries, f"{domain}: no queries")
    require(all("or vector(0)" not in query for query in queries), f"{domain}: global zero fallback added")
    used_rules = recording_rule_names(queries)
    require(used_rules == set(spec["rules"]), f"{domain}: query rule set changed: {sorted(used_rules)}")

uids = [dashboard.get("uid") for dashboard in loaded_dashboards.values()]
require(len(uids) == len(set(uids)), "Dashboard UID collision")

data_dashboard = loaded_dashboards["data"]
cnpg_panels = [panel for panel in data_dashboard["panels"] if "AWS Profile" in panel.get("title", "")]
require(len(cnpg_panels) == 4, "Conditional CNPG panel set changed")
for panel in cnpg_panels:
    description = panel.get("description", "")
    require("AWS profiles" in description and "No data is expected" in description, "CNPG no-data boundary missing")

configmap_template = markers(
    "platform/observability/helm/templates/dashboard-configmaps.yaml",
    ('.Files.Glob "dashboards/*.json"', '.Files.Get $path', "dashboardLabelValue"),
)
require("kubectl" not in configmap_template, "Dashboard provisioning bypasses GitOps")

predecessor = load_json("delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json")
accepted_operator_rules = predecessor.get("recordingRules", {}).get("names", [])
dashboard_operator_rules = []
for domain in ("delivery", "data", "platform"):
    dashboard_operator_rules.extend(contract["dashboards"][domain]["rules"])
require(dashboard_operator_rules == accepted_operator_rules, "Dashboards do not consume the exact accepted 21 rules")

operator_rules_source = read("platform/observability/helm/templates/operator-recording-rules.yaml")
found_operator_rules = re.findall(r"^\s*- record:\s*(\S+)\s*$", operator_rules_source, re.MULTILINE)
require(found_operator_rules == accepted_operator_rules, "Operator recording rules changed")

live = markers(
    "scripts/check-operator-dashboards.sh",
    (
        "PROFILE must be local or aws",
        "observability-dashboard-delivery-overview",
        "observability-dashboard-data-overview",
        "observability-dashboard-platform-overview",
        "local CloudNativePG data is optional",
        "/api/dashboards/uid/",
        ".dashboard.editable == false",
        "v0.11.4.1.1 operator Dashboard provisioning and rule-backed live acceptance passed.",
    ),
)
for rule_name in contract["dashboards"]["data"]["localRequiredRules"]:
    require(rule_name in live, f"Live check misses local Data rule: {rule_name}")

historical_v040 = markers(
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    (
        "v0.11.4.1.1-operator-dashboards.json",
        'expected_views_chart_version = "version: 0.2.2"',
        'expected_views_app_version = \'appVersion: "v0.11.4.1.1"\'',
    ),
)
require("operator_dashboards_successor" in historical_v040, "v0.11.4.0 successor branch missing")
historical_v0410 = markers(
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    (
        "v0.11.4.1.1-operator-dashboards.json",
        'expected_views_chart_version = "version: 0.2.2"',
        "expected_dashboard_names",
        '"delivery-overview.json"',
    ),
)
require("operator_dashboards_successor" in historical_v0410, "v0.11.4.1.0 successor branch missing")
markers(
    "scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh",
    (
        "v0.11.4.1.1-operator-dashboards.json",
        'expected_views_chart_version = "version: 0.2.2"',
        'expected_views_app_version = \'appVersion: "v0.11.4.1.1"\'',
    ),
)

markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.1.1 operator Dashboards", "validate-v0.11.4.1.1-operator-dashboards.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/delivery/contracts/v0.11.4.1.1-operator-dashboards.json @SterlingAureum",
        "/scripts/validate-v0.11.4.1.1-operator-dashboards.sh @SterlingAureum",
        "/scripts/check-operator-dashboards.sh @SterlingAureum",
        "/docs/V0.11.4.1.1_OPERATOR_DASHBOARDS.md @SterlingAureum",
    ),
)

for monitoring_path in (
    "clusters/local/platform/templates/monitoring.yaml",
    "clusters/aws/base/platform/monitoring.yaml",
):
    monitoring = read(monitoring_path)
    require("revisionHistoryLimit" not in monitoring, f"Grafana Deployment changed: {monitoring_path}")

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("editable Dashboard", lambda value: value["dashboardPolicy"].update(editable=True)),
    ("raw metrics", lambda value: value["dashboardPolicy"].update(rawMetricsForbidden=False)),
    ("global zero", lambda value: value["dashboardPolicy"].update(globalVectorZeroForbidden=False)),
    ("local CNPG required", lambda value: value["dashboards"]["data"].update(localCloudNativePGDataRequired=True)),
    ("alerting", lambda value: value["boundaries"].update(alertingAdded=True)),
    ("capacity view", lambda value: value["boundaries"].update(capacityOrCostViewAdded=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.4.1.1 immutable rule-backed Delivery, Data, and Platform Dashboards passed.")
PY

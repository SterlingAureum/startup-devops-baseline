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
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON in {relative}: {exc}") from exc
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


def markers(relative: str, expected: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in expected:
        require(marker in text, f"{relative}: missing marker {marker!r}")
    return text


expected_rules = [
    "demo_api:http_requests:rate5m",
    "demo_api:http_errors:rate5m",
    "demo_api:http_success_ratio:rate5m",
    "demo_api:http_request_duration_seconds:p50_5m",
    "demo_api:http_request_duration_seconds:p95_5m",
    "demo_api:http_request_duration_seconds:p99_5m",
    "demo_api:dependency_checks:rate5m",
    "demo_api:dependency_success_ratio:rate5m",
    "demo_api:dependency_check_duration_seconds:p95_5m",
]


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.4.0", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.0", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    source = value.get("sourceModel", {})
    require(source.get("viewsChart") == "platform/observability/helm", "Wrong views Chart")
    require(source.get("viewsChartVersion") == "0.1.0", "Wrong views Chart version")
    require(source.get("localPlatformChartVersion") == "0.2.0", "Wrong local platform Chart version")
    require(
        source.get("sameRepositoryApplications")
        == ["startup-devops-root", "namespace-guardrails", "demo-api", "observability-views"],
        "Same-repository Application set changed",
    )
    require(source.get("featureRevisionInheritedFromRoot") is True, "Feature revision inheritance disabled")
    require(source.get("stableLocalRevision") == "HEAD", "Stable local revision changed")
    require(source.get("stableAwsRevision") == "main", "Stable AWS revision changed")

    grafana = value.get("grafana", {})
    require(grafana.get("managedBy") == "kube-prometheus-stack", "Unexpected Grafana owner")
    require(grafana.get("enabledProfiles") == ["local", "aws-dev", "aws-test", "aws-prod"], "Grafana profiles changed")
    require(grafana.get("datasourceUid") == "prometheus", "Datasource UID changed")
    require(grafana.get("defaultDashboardsEnabled") is False, "Default dashboards enabled")
    require(grafana.get("gitProvisionedDashboards") is True, "Git dashboard provisioning disabled")
    for key in ("anonymousAccess", "publicIngress", "persistenceRequired", "plaintextAdminCredentialCommitted"):
        require(grafana.get(key) is False, f"Unsafe Grafana setting: {key}")
    require(grafana.get("serviceType") == "ClusterIP", "Grafana service exposed")
    require(grafana.get("awsSystemPlacement") is True, "AWS system placement missing")

    dashboard = value.get("dashboard", {})
    require(dashboard.get("uid") == "startup-devops-service-overview", "Dashboard UID changed")
    require(dashboard.get("editable") is False, "Dashboard is UI-editable")
    require(dashboard.get("variables") == ["environment", "release"], "Dashboard variables changed")
    require(len(dashboard.get("panels", [])) == 5, "Dashboard panel set changed")

    rules = value.get("recordingRules", {})
    require(rules.get("evaluationInterval") == "30s", "Rule interval changed")
    require(rules.get("names") == expected_rules, "Recording rule set changed")
    for key in ("alertRulesAdded", "missingDataCoercedToHealthyZero", "podIdentityUsedForAggregation", "rawUrlUsedForAggregation"):
        require(rules.get(key) is False, f"Recording-rule boundary expanded: {key}")

    security = value.get("securityAndCost", {})
    require(security.get("grafanaNetworkPolicy") is True, "Grafana NetworkPolicy missing")
    require(security.get("resourceRequestsAndLimits") is True, "Grafana resources unbounded")
    for key in ("awsGrafanaPersistence", "kubecostAdded", "awsBillingIntegrationAdded", "realCurrencyCostClaimed"):
        require(security.get(key) is False, f"Cost/storage boundary expanded: {key}")

    require(all(flag is False for flag in value.get("boundaries", {}).values()), "Version boundary expanded")
    acceptance = value.get("acceptance", {})
    require(acceptance.get("completeQualityGateRequired") is True, "Complete quality gate is optional")
    require(acceptance.get("localLiveReplayRequiredBeforeTag") is True, "Local live replay is optional")
    require(acceptance.get("awsLiveEvidenceDeferredTo") == "v0.11.8", "AWS evidence boundary changed")


contract = load_json("delivery/contracts/v0.11.4.0-grafana-recording-rules.json")
validate_contract(contract)
controller_metrics_successor = (root / "delivery/contracts/v0.11.4.1.0-controller-metrics-discovery.json").is_file()
ratio_no_series_successor = (root / "delivery/contracts/v0.11.4.1.0.2-ratio-no-series-repair.json").is_file()
operator_dashboards_successor = (root / "delivery/contracts/v0.11.4.1.1-operator-dashboards.json").is_file()
capacity_signal_successor = (root / "delivery/contracts/v0.11.4.2.0-capacity-signal-foundation.json").is_file()
capacity_dashboard_successor = (root / "delivery/contracts/v0.11.4.2.1-capacity-efficiency-dashboard.json").is_file()

if capacity_dashboard_successor:
    expected_views_chart_version = "version: 0.3.1"
    expected_views_app_version = 'appVersion: "v0.11.4.2.1"'
elif capacity_signal_successor:
    expected_views_chart_version = "version: 0.3.0"
    expected_views_app_version = 'appVersion: "v0.11.4.2.0"'
elif operator_dashboards_successor:
    expected_views_chart_version = "version: 0.2.2"
    expected_views_app_version = 'appVersion: "v0.11.4.1.1"'
elif ratio_no_series_successor:
    expected_views_chart_version = "version: 0.2.1"
    expected_views_app_version = 'appVersion: "v0.11.4.1.0.2"'
elif controller_metrics_successor:
    expected_views_chart_version = "version: 0.2.0"
    expected_views_app_version = 'appVersion: "v0.11.4.1.0"'
else:
    expected_views_chart_version = "version: 0.1.0"
    expected_views_app_version = 'appVersion: "v0.11.4.0"'

chart = markers(
    "platform/observability/helm/Chart.yaml",
    (
        "name: startup-devops-observability-views",
        expected_views_chart_version,
        expected_views_app_version,
    ),
)
values = markers(
    "platform/observability/helm/values.yaml",
    ("dashboardLabel: grafana_dashboard", "datasourceUid: prometheus", "evaluationInterval: 30s"),
)
require("feature/" not in chart + values, "Feature revision committed to observability Chart")

rule_text = markers(
    "platform/observability/helm/templates/recording-rules.yaml",
    ("kind: PrometheusRule", "demo-api.operator.v0.11.4.0", 'job=~"demo-api|demo-api-stable|demo-api-canary"'),
)
found_rules = re.findall(r"^\s*- record:\s*(\S+)\s*$", rule_text, re.MULTILINE)
require(found_rules == expected_rules, "Rendered source rule ordering or names changed")
require(re.search(r"^\s*- alert:", rule_text, re.MULTILINE) is None, "v0.11.4.0 added an alert rule")
require("or vector(0)" not in rule_text, "Missing data is coerced to a healthy zero")
for forbidden in ("raw_url", "request_id", "trace_id", "pod_uid", "container_id"):
    require(forbidden not in rule_text, f"Unbounded recording-rule dimension: {forbidden}")

dashboard = load_json("platform/observability/helm/dashboards/service-overview.json")
require(dashboard.get("uid") == "startup-devops-service-overview", "Dashboard UID mismatch")
require(dashboard.get("title") == "Startup DevOps / Service Overview", "Dashboard title mismatch")
require(dashboard.get("editable") is False, "Dashboard permits UI drift")
require(dashboard.get("schemaVersion", 0) >= 39, "Dashboard schema is too old")
panels = dashboard.get("panels", [])
require([panel.get("title") for panel in panels] == contract["dashboard"]["panels"], "Dashboard panels changed")
for panel in panels:
    datasource = panel.get("datasource", {})
    require(datasource.get("uid") == "prometheus", f"Panel datasource drift: {panel.get('title')}")
    for target in panel.get("targets", []):
        require("demo_api:" in target.get("expr", ""), f"Panel bypasses recording rules: {panel.get('title')}")
variables = dashboard.get("templating", {}).get("list", [])
require([value.get("name") for value in variables] == ["environment", "release"], "Dashboard variable set changed")

markers(
    "platform/observability/helm/templates/dashboard-configmaps.yaml",
    ('.Files.Glob "dashboards/*.json"', ".Files.Get $path", "dashboardLabelValue"),
)

local_app = markers(
    "clusters/local/platform/templates/observability-views.yaml",
    ("name: observability-views", ".Values.git.repoURL", ".Values.git.targetRevision", "path: platform/observability/helm", "sync-wave: \"6\""),
)
aws_app = markers(
    "clusters/aws/base/platform/observability-views.yaml",
    ("name: observability-views-aws-dev", "targetRevision: main", "path: platform/observability/helm", "value: aws-dev"),
)
require("feature/" not in local_app + aws_app, "Feature revision committed to an observability Application")

markers(
    "clusters/local/platform/Chart.yaml",
    (
        "version: 0.3.0" if controller_metrics_successor else "version: 0.2.0",
        'appVersion: "v0.11.4.1.0"' if controller_metrics_successor else 'appVersion: "v0.11.4.0"',
    ),
)
markers("clusters/aws/base/platform/kustomization.yaml", ("- observability-views.yaml",))
for relative, name, environment, cluster in (
    ("clusters/aws/overlays/test/kustomization.yaml", "observability-views-aws-test", "aws-test", "startup-devops-baseline-test"),
    ("clusters/aws/overlays/prod/kustomization.yaml", "observability-views-aws-prod", "aws-prod", "startup-devops-baseline-prod"),
):
    markers(relative, (name, environment, cluster))

for relative, label, aws in (
    ("clusters/local/platform/templates/monitoring.yaml", "local", False),
    ("clusters/aws/base/platform/monitoring.yaml", "AWS", True),
):
    text = markers(
        relative,
        (
            "grafana:",
            "enabled: true",
            "defaultDashboardsEnabled: false",
            "type: ClusterIP",
            "persistence:",
            "label: grafana_dashboard",
            "searchNamespace: observability",
            "uid: prometheus",
            "allow_sign_up: false",
            "name: grafana-cluster-only",
            "port: 3000",
            "cpu: 100m",
            "memory: 128Mi",
            "cpu: 500m",
            "memory: 512Mi",
        ),
    )
    require(re.search(r"(?ms)alertmanager:\n\s+enabled: false", text) is not None, f"{label}: Alertmanager enabled")
    require(re.search(r"(?ms)auth\.anonymous:\n\s+enabled: false", text) is not None, f"{label}: anonymous Grafana access enabled")
    for forbidden in ("kind: Ingress", "type: LoadBalancer", "type: NodePort", "adminPassword:"):
        require(forbidden not in text, f"{label}: forbidden Grafana exposure or credential: {forbidden}")
    if aws:
        require(re.search(r"(?ms)grafana:.*?nodeSelector:\n\s+workload: system", text) is not None, "AWS Grafana system placement missing")

for relative in ("scripts/deploy-local-feature-gitops.sh", "scripts/restore-local-gitops-baseline.sh"):
    markers(relative, ("OBSERVABILITY_VIEWS_APP_NAME", 'assert_revision "${OBSERVABILITY_VIEWS_APP_NAME}"' if "restore" in relative else '"${OBSERVABILITY_VIEWS_APP_NAME}"'))

markers(
    "scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh",
    (
        "v0.11.4.0-grafana-recording-rules.json",
        'expected_names.add("observability-views")',
        'same_repository_names.append("observability-views")',
        "for name in same_repository_names:",
    ),
)

markers(
    "scripts/validate-active-gitops-revisions.sh",
    ("clusters/aws/base/platform/observability-views.yaml", "clusters/local/platform/templates/observability-views.yaml", "+ 3"),
)
markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.0 Grafana and recording rules", "validate-v0.11.4.0-grafana-recording-rules.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/platform/observability/ @SterlingAureum",
        "/delivery/contracts/v0.11.4.0-grafana-recording-rules.json @SterlingAureum",
        "/scripts/validate-v0.11.4.0-grafana-recording-rules.sh @SterlingAureum",
        "/docs/V0.11.4.0_GRAFANA_RECORDING_RULES.md @SterlingAureum",
    ),
)

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("public Grafana", lambda value: value["grafana"].update(publicIngress=True)),
    ("mutable dashboard", lambda value: value["dashboard"].update(editable=True)),
    ("alert rule", lambda value: value["recordingRules"].update(alertRulesAdded=True)),
    ("missing-data zero", lambda value: value["recordingRules"].update(missingDataCoercedToHealthyZero=True)),
    ("billing claim", lambda value: value["securityAndCost"].update(realCurrencyCostClaimed=True)),
    ("production expansion", lambda value: value["boundaries"].update(productionAutomationChanged=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.4.0 Grafana, recording-rule, revision, security, and boundary validation passed.")
PY

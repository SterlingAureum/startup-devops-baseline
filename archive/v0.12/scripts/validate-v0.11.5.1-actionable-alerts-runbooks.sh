#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

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
    except json.JSONDecodeError as error:
        raise ContractError(f"Invalid JSON in {relative}: {error}") from error
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


contract_path = "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.1", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.1", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.0.1", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.0.1-matcher-normalization-repair.json").is_file(), "Missing predecessor contract")

chart_contract = contract.get("chart", {})
require(chart_contract.get("previousVersion") == "0.3.1", "Wrong predecessor Chart version")
require(chart_contract.get("version") == "0.4.0", "Wrong Chart version")
require(chart_contract.get("applicationVersion") == "v0.11.5.1", "Wrong application version")
semantic_repair_successor = (root / "delivery/contracts/v0.11.5.1.1-prometheus-target-down-semantics-repair.json").is_file()
alert_lifecycle_drill_successor = (root / "delivery/contracts/v0.11.5.2.0-alert-lifecycle-drill.json").is_file()
slo_foundation_successor = (root / "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json").is_file()
burn_rate_successor = (root / "delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json").is_file()
chart = read("platform/observability/helm/Chart.yaml")
chart_markers = (
    "name: startup-devops-observability-views",
    "version: 0.6.0" if burn_rate_successor else ("version: 0.5.0" if slo_foundation_successor else ("version: 0.4.1" if semantic_repair_successor else "version: 0.4.0")),
    'appVersion: "v0.11.7.1"' if burn_rate_successor else ('appVersion: "v0.11.7.0"' if slo_foundation_successor else ('appVersion: "v0.11.5.1.1"' if semantic_repair_successor else 'appVersion: "v0.11.5.1"')),
)
for marker in chart_markers:
    require(marker in chart, f"Chart is missing: {marker}")

policy = contract.get("policy", {})
require(policy.get("alertCount") == 8, "Alert count changed")
require(policy.get("warningCount") == 2, "Warning count changed")
require(policy.get("criticalCount") == 6, "Critical count changed")
require(policy.get("recordingRulesOnly") is True, "Raw metric alerts allowed")
require(policy.get("cleanBaselineMustBeInactive") is True, "Clean inactive state optional")
require(policy.get("externalNotificationConfigured") is False, "External notification configured early")
require(policy.get("defaultRulesEnabled") is False, "Default rules enabled")
require(policy.get("requiredLabels") == ["severity", "environment", "cluster", "component", "alert_family"], "Required labels changed")
require(policy.get("requiredAnnotations") == ["summary", "description", "runbook_url"], "Required annotations changed")
require(policy.get("inhibitionEqualLabels") == ["environment", "cluster", "component", "alert_family"], "Inhibition equality changed")

expected_alerts = {
    "DemoApiHttpSuccessRatioLowWarning": ("warning", "demo-api", "demo-api-http-reliability", "<0.99", "10m"),
    "DemoApiHttpSuccessRatioLowCritical": ("critical", "demo-api", "demo-api-http-reliability", "<0.95", "5m"),
    "DemoApiDependencySuccessRatioLowWarning": ("warning", "demo-api-dependency", "demo-api-dependency-reliability", "<0.99", "10m"),
    "DemoApiDependencySuccessRatioLowCritical": ("critical", "demo-api-dependency", "demo-api-dependency-reliability", "<0.90", "5m"),
    "ArgoRolloutProblem": ("critical", "argo-rollouts", "rollout-health", ">0", "5m"),
    "ArgoCDApplicationUnhealthy": ("critical", "argocd", "gitops-application-health", ">0", "10m"),
    "KubernetesDeploymentUnavailable": ("critical", "kubernetes-workload", "deployment-availability", ">0", "10m"),
    "PostgreSQLCollectionFailed": ("critical", "cloudnative-pg", "postgresql-collection-health", ">0", "5m"),
}
successor_alert = {
    "PrometheusTargetDown": ("critical", "prometheus", "monitoring-target-health", ">0", "10m"),
}
alerts = contract.get("alerts", [])
require(len(alerts) == 8, "Contract must contain exactly eight alerts")
require({alert.get("name") for alert in alerts} == set(expected_alerts), "Contract alert inventory changed")
require(sum(alert.get("severity") == "warning" for alert in alerts) == 2, "Contract warning cardinality changed")
require(sum(alert.get("severity") == "critical" for alert in alerts) == 6, "Contract critical cardinality changed")

runbook_names: set[str] = set()
for alert in alerts:
    name = alert["name"]
    severity, component, family, threshold, duration = expected_alerts[name]
    require(
        (alert.get("severity"), alert.get("component"), alert.get("alertFamily"), alert.get("threshold"), alert.get("for"))
        == (severity, component, family, threshold, duration),
        f"Alert policy changed: {name}",
    )
    source_rules = alert.get("sourceRules", [])
    require(source_rules and all(":" in rule for rule in source_rules), f"Alert does not use recording rules: {name}")
    runbook = alert.get("runbook", "")
    require(runbook.startswith("docs/runbooks/alerts/") and runbook.endswith(".md"), f"Bad Runbook path: {name}")
    require(runbook not in runbook_names, f"Runbook reused by multiple alerts: {runbook}")
    runbook_names.add(runbook)
    runbook_text = read(runbook)
    require(runbook_text.startswith(f"# {name}\n"), f"Runbook heading changed: {name}")
    for marker in ("## Meaning", "## Impact", "## First response", "## Diagnosis and recovery"):
        require(marker in runbook_text, f"Runbook section missing for {name}: {marker}")
    for forbidden in ("kubectl delete", "kubectl patch", "kubectl rollout restart", "kubectl scale"):
        require(forbidden not in runbook_text, f"Runbook contains unapproved direct mutation for {name}: {forbidden}")

template_path = chart_contract.get("ruleTemplate", "")
template = read(template_path)
require("kind: PrometheusRule" in template, "Alert template is not a PrometheusRule")
require("name: actionable-alerts" in template, "PrometheusRule name changed")
blocks = re.split(r"(?m)^\s*- alert:\s*", template)[1:]
runtime_expected_alerts = expected_alerts | (successor_alert if semantic_repair_successor else {})
require(len(blocks) == len(runtime_expected_alerts), "Rendered template source has the wrong successor-aware alert count")
template_names: list[str] = []
recording_name_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)+")
contract_by_name = {alert["name"]: alert for alert in alerts}
if semantic_repair_successor:
    contract_by_name["PrometheusTargetDown"] = {
        "severity": "critical",
        "component": "prometheus",
        "alertFamily": "monitoring-target-health",
        "sourceRules": ["platform:prometheus_targets_down:count"],
        "runbook": "docs/runbooks/alerts/prometheus-target-down.md",
    }
for block in blocks:
    name, _, body = block.partition("\n")
    name = name.strip()
    template_names.append(name)
    require(name in runtime_expected_alerts, f"Unexpected alert in template: {name}")
    alert = contract_by_name[name]
    for marker in (
        f"severity: {alert['severity']}",
        'environment: {{ .Values.environment | quote }}',
        'cluster: {{ .Values.cluster | quote }}',
        f"component: {alert['component']}",
        f"alert_family: {alert['alertFamily']}",
        "summary:",
        "description:",
        "runbook_url:",
        Path(alert["runbook"]).name,
    ):
        require(marker in body, f"Alert template metadata missing for {name}: {marker}")
    found_sources = set(recording_name_pattern.findall(body))
    require(found_sources == set(alert["sourceRules"]), f"Alert source rules changed for {name}: {sorted(found_sources)}")

require(set(template_names) == set(runtime_expected_alerts), "Template alert inventory changed")
for forbidden_raw in (
    "demo_api_http_requests_total",
    "demo_api_dependency_checks_total",
    "argocd_app_info",
    "rollout_info",
    "cnpg_collector_",
    "kube_",
    "up{",
    "or vector(0)",
):
    require(forbidden_raw not in template, f"Alert template bypasses accepted recording rules: {forbidden_raw}")

values = read("platform/observability/helm/values.yaml")
for marker in (
    "warningThreshold: 0.99",
    "criticalThreshold: 0.95",
    "criticalThreshold: 0.90",
    "warningFor: 10m",
    "criticalFor: 5m",
    "argoRolloutProblemFor: 5m",
    "argoCDApplicationUnhealthyFor: 10m",
    "kubernetesDeploymentUnavailableFor: 10m",
    "postgresqlCollectionFailedFor: 5m",
):
    require(marker in values, f"Alert value missing: {marker}")
if semantic_repair_successor:
    require("prometheusTargetDownFor: 10m" in values, "Prometheus target-down duration missing")

all_template_alerts = []
for path in (root / "platform/observability/helm/templates").glob("*.yaml"):
    all_template_alerts.extend(re.findall(r"(?m)^\s*- alert:\s*(\S+)\s*$", path.read_text()))
burn_rate_alerts = []
if burn_rate_successor:
    burn_rate_alerts = json.loads(read("delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json"))["alerts"]["names"]
expected_runtime_alerts = template_names + burn_rate_alerts
require(
    len(all_template_alerts) == len(expected_runtime_alerts),
    "Successor-aware alert cardinality changed",
)
require(
    len(all_template_alerts) == len(set(all_template_alerts)),
    "Duplicate alert name exists",
)
require(
    set(all_template_alerts) == set(expected_runtime_alerts),
    "Alert rule exists outside the successor-aware bounded inventory",
)

for relative in ("clusters/local/platform/templates/monitoring.yaml", "clusters/aws/base/platform/monitoring.yaml"):
    monitoring = read(relative)
    require(re.search(r"(?ms)defaultRules:\n\s+create: false", monitoring) is not None, f"Default rules enabled: {relative}")
    for marker in ('severity = "critical"', 'severity = "warning"', "- environment", "- cluster", "- component", "- alert_family"):
        require(marker in monitoring, f"Alertmanager inhibition contract changed in {relative}: {marker}")
    if alert_lifecycle_drill_successor:
        require(monitoring.count("webhook_configs:") == 2, f"Drill webhook count changed in {relative}")
        require(monitoring.count("alert-lifecycle-drill-sink.observability.svc.cluster.local:8080") == 2, f"Internal drill URL changed in {relative}")
    else:
        require("webhook_configs:" not in monitoring, f"Webhook receiver added before drill successor in {relative}")
    for external in ("slack_configs:", "email_configs:", "pagerduty_configs:", "sns_configs:"):
        require(external not in monitoring, f"External receiver added early in {relative}: {external}")

require(all(value is False for value in contract.get("boundaries", {}).values()), "Version boundary expanded")
acceptance = contract.get("acceptance", {})
require((root / acceptance.get("offlineValidator", "")).is_file(), "Missing offline validator")
require((root / acceptance.get("liveValidator", "")).is_file(), "Missing live validator")
require(acceptance.get("profiles") == ["local", "aws"], "Live profiles changed")
require(acceptance.get("completeQualityGateRequired") is True, "Complete quality gate is optional")
require(acceptance.get("localLiveAcceptanceRequired") is True, "Local live acceptance is optional")
require(acceptance.get("cleanBaselineAllInactiveRequired") is True, "Inactive baseline is optional")
require(acceptance.get("alertmanagerRegressionRequired") is True, "Alertmanager regression is optional")
require(acceptance.get("formalFiringRoutingInhibitionResolutionDrillDeferredTo") == "v0.11.5.2", "Drill boundary moved")
require(acceptance.get("formalAwsEvidenceDeferredTo") == "v0.11.8", "AWS evidence boundary moved")

for relative in (
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    "scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh",
    "scripts/validate-v0.11.4.1.1-operator-dashboards.sh",
    "scripts/validate-v0.11.4.2.0-capacity-signal-foundation.sh",
    "scripts/validate-v0.11.4.2.1-capacity-efficiency-dashboard.sh",
    "scripts/validate-v0.11.4.2.2-replay-diagnostics-repair.sh",
    "scripts/validate-v0.11.5.0-alertmanager-foundation.sh",
):
    text = read(relative)
    require("v0.11.5.1-actionable-alerts-runbooks.json" in text, f"Historical validator is not successor-aware: {relative}")
    require("v0.11.5.1" in text and "0.4.0" in text, f"Historical Chart successor missing: {relative}")

if semantic_repair_successor:
    for relative in (
        "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
        "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
        "scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh",
        "scripts/validate-v0.11.4.1.1-operator-dashboards.sh",
        "scripts/validate-v0.11.4.2.0-capacity-signal-foundation.sh",
        "scripts/validate-v0.11.4.2.1-capacity-efficiency-dashboard.sh",
        "scripts/validate-v0.11.4.2.2-replay-diagnostics-repair.sh",
        "scripts/validate-v0.11.5.0-alertmanager-foundation.sh",
    ):
        text = read(relative)
        require("v0.11.5.1.1-prometheus-target-down-semantics-repair.json" in text, f"Historical validator lacks semantic-repair successor: {relative}")
        require("v0.11.5.1.1" in text and "0.4.1" in text, f"Historical semantic-repair Chart successor missing: {relative}")

for relative, marker in (
    ("scripts/check-actionable-alerts.sh", "clean inactive-state acceptance passed"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.1-actionable-alerts-runbooks.sh"),
    ("docs/V0.11.5.1_ACTIONABLE_ALERTS_RUNBOOKS.md", "## Alert inventory"),
    ("docs/ROADMAP.md", "v0.11.5.1"),
    ("README.md", "v0.11.5.1-actionable-alerts-runbooks"),
    ("CHANGELOG.md", "## v0.11.5.1"),
    (".github/CODEOWNERS", "/scripts/check-actionable-alerts.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Required integration marker missing: {relative}: {marker}")

print("v0.11.5.1 exact alert inventory, recording-rule sources, inhibition labels, Runbooks, and boundaries passed.")
PY

fixture_dir="$(mktemp -d)"
trap 'rm -rf -- "${fixture_dir}"' EXIT

python3 - "${fixture_dir}" "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


fixture_dir = Path(sys.argv[1])
root = Path(sys.argv[2])
names = [
    "DemoApiHttpSuccessRatioLowWarning",
    "DemoApiHttpSuccessRatioLowCritical",
    "DemoApiDependencySuccessRatioLowWarning",
    "DemoApiDependencySuccessRatioLowCritical",
    "ArgoRolloutProblem",
    "ArgoCDApplicationUnhealthy",
    "KubernetesDeploymentUnavailable",
    "PrometheusTargetDown",
    "PostgreSQLCollectionFailed",
]
warning_names = {
    "DemoApiHttpSuccessRatioLowWarning",
    "DemoApiDependencySuccessRatioLowWarning",
}
if (root / "delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json").is_file():
    names.extend([
        "DemoApiAvailabilityErrorBudgetFastBurn",
        "DemoApiAvailabilityErrorBudgetSlowBurn",
        "DemoApiLatencyErrorBudgetFastBurn",
        "DemoApiLatencyErrorBudgetSlowBurn",
    ])
    warning_names.update({"DemoApiAvailabilityErrorBudgetSlowBurn", "DemoApiLatencyErrorBudgetSlowBurn"})
rules = []
for name in names:
    rules.append({
        "type": "alerting",
        "name": name,
        "health": "ok",
        "state": "inactive",
        "labels": {
            "severity": "warning" if name in warning_names else "critical",
            "environment": "local",
            "cluster": "startup-devops-local",
            "component": "fixture-component",
            "alert_family": "fixture-family",
        },
        "annotations": {
            "summary": "fixture summary",
            "description": "fixture description",
            "runbook_url": f"https://github.com/SterlingAureum/startup-devops-baseline/blob/main/docs/runbooks/alerts/{name}.md",
        },
    })

valid = {"status": "success", "data": {"groups": [{"rules": rules}]}}
pending = deepcopy(valid)
pending["data"]["groups"][0]["rules"][0]["state"] = "pending"
missing = deepcopy(valid)
missing["data"]["groups"][0]["rules"].pop()

for name, payload in (("valid", valid), ("pending", pending), ("missing", missing)):
    (fixture_dir / f"{name}.json").write_text(json.dumps(payload))
PY

ALERT_RULES_FIXTURE="${fixture_dir}/valid.json" \
  "${ROOT_DIR}/scripts/check-actionable-alerts.sh" >/dev/null

for invalid_fixture in pending missing; do
  if ALERT_RULES_FIXTURE="${fixture_dir}/${invalid_fixture}.json" \
    "${ROOT_DIR}/scripts/check-actionable-alerts.sh" >"${fixture_dir}/${invalid_fixture}.log" 2>&1; then
    echo "ERROR: ${invalid_fixture} alert API fixture unexpectedly passed." >&2
    exit 1
  fi
  grep -F -- 'actionable alert inventory, metadata, health, or clean-baseline state is invalid' \
    "${fixture_dir}/${invalid_fixture}.log" >/dev/null || {
      echo "ERROR: ${invalid_fixture} alert API diagnostic changed." >&2
      cat "${fixture_dir}/${invalid_fixture}.log" >&2
      exit 1
    }
done

echo "v0.11.5.1 alert API fixture acceptance and negative clean-state regressions passed."

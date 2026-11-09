#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
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


def require_in_order(text: str, markers: list[str], context: str) -> None:
    offset = 0
    for marker in markers:
        position = text.find(marker, offset)
        require(position >= 0, f"{context}: missing or out-of-order marker: {marker}")
        offset = position + len(marker)


def phase(text: str, number: int, next_number: int | None) -> str:
    start_marker = f'echo "==> Phase {number}:'
    start = text.find(start_marker)
    require(start >= 0, f"Missing phase {number}")
    if next_number is None:
        end = text.find('echo "==> Cleanup:', start)
    else:
        end = text.find(f'echo "==> Phase {next_number}:', start)
    require(end > start, f"Missing end boundary for phase {number}")
    return text[start:end]


contract_path = "delivery/contracts/v0.11.5.2.0.2-alert-resolution-transition-repair.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.2.0.2", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.2.0.2", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.2.0.1", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.2.0.1-alertmanager-webhook-url-redaction-repair.json").is_file(), "Missing predecessor contract")

incident = contract.get("incident", {})
for key in ("warningFiringObserved", "warningDrillReceiverObserved", "warningWebhookFiringObserved", "resolutionTransitionDefect"):
    require(incident.get(key) is True, f"Incident evidence omitted: {key}")
for key in ("resolvedWebhookObserved", "networkPathDefect", "alertmanagerRouteDefect"):
    require(incident.get(key) is False, f"Incident evidence changed: {key}")
require(incident.get("failedSequence") == [
    "apply-firing-rule",
    "observe-firing",
    "delete-prometheus-rule",
    "wait-for-resolved",
], "Failed sequence changed")

repair = contract.get("repair", {})
require(repair.get("firingExpression") == "vector(1)", "Firing expression changed")
require(repair.get("inactiveExpression") == "vector(0) == 1", "Inactive expression is not empty-vector")
require(repair.get("numericZeroAloneAllowed") is False, "Numeric zero alone was permitted")
for key in (
    "samePrometheusRuleRetainedThroughResolution",
    "sameAlertNameAndLabelsRetainedThroughResolution",
    "prometheusClearRequiredBeforeWebhookResolved",
    "webhookResolvedRequiredBeforeRuleDeletion",
    "ruleDeletionIsCleanupOnly",
    "preflightRejectsAnyActiveDrillAlert",
    "finalStateRejectsAnyActiveDrillAlert",
    "allLifecyclePhasesRepaired",
):
    require(repair.get(key) is True, f"Repair requirement disabled: {key}")

require(contract.get("phases") == {
    "warning": "explicit-inactive-then-resolved-then-delete",
    "critical": "explicit-inactive-then-resolved-then-delete",
    "positiveInhibition": "explicit-inactive-critical-resolved-then-delete",
    "negativeIsolation": "explicit-inactive-both-resolved-then-delete",
}, "Lifecycle phase contract changed")

unchanged = contract.get("unchanged", {})
require(unchanged.get("localPlatformChartVersion") == "0.4.1", "Local platform Chart changed")
require(unchanged.get("localPlatformApplicationVersion") == "v0.11.5.2.0", "Local platform appVersion changed")
require(unchanged.get("observabilityChartVersion") == "0.4.1", "Observability Chart changed")
require(unchanged.get("observabilityApplicationVersion") == "v0.11.5.1.1", "Observability appVersion changed")
require(unchanged.get("formalAlertCount") == 9, "Formal alert inventory changed")
for name, value in unchanged.items():
    if name not in {
        "localPlatformChartVersion",
        "localPlatformApplicationVersion",
        "observabilityChartVersion",
        "observabilityApplicationVersion",
        "formalAlertCount",
    }:
        require(value is False, f"Runtime boundary expanded: {name}")
require(all(value is False for value in contract.get("boundaries", {}).values()), "Repair boundary expanded")

acceptance = contract.get("acceptance", {})
for key in ("offlineValidator", "liveValidator"):
    require((root / acceptance.get(key, "")).is_file(), f"Missing acceptance script: {key}")
for key in ("completeQualityGateRequired", "localLiveRerunRequired", "previousActiveDrillAlertMustClear", "zeroResidualRequired"):
    require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
for key in ("monitoringRedeployBeforeRerun", "imageRebuildBeforeRerun"):
    require(acceptance.get(key) is False, f"Unnecessary runtime action required: {key}")
require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")

local_chart = read("clusters/local/platform/Chart.yaml")
logging_runtime_successor = (root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file()
events_runtime_successor = (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file()
tracing_runtime_successor = (root / "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json").is_file()
require(
    ("version: 0.8.0" if tracing_runtime_successor else ("version: 0.6.0" if events_runtime_successor else ("version: 0.5.0" if logging_runtime_successor else "version: 0.4.1"))) in local_chart
    and ('appVersion: "v0.11.6.2.2"' if tracing_runtime_successor else ('appVersion: "v0.11.6.1.2"' if events_runtime_successor else ('appVersion: "v0.11.6.1.1"' if logging_runtime_successor else 'appVersion: "v0.11.5.2.0"'))) in local_chart,
    "Local platform Chart changed",
)
views_chart = read("platform/observability/helm/Chart.yaml")
slo_foundation_successor = (root / "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json").is_file()
burn_rate_successor = (root / "delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json").is_file()
expected_views = ("version: 0.6.0", 'appVersion: "v0.11.7.1"') if burn_rate_successor else (("version: 0.5.0", 'appVersion: "v0.11.7.0"') if slo_foundation_successor else ("version: 0.4.1", 'appVersion: "v0.11.5.1.1"'))
require(all(marker in views_chart for marker in expected_views), "Observability Chart changed")

live = read("scripts/check-alert-lifecycle-drill.sh")
for marker in (
    "wait_prometheus_cleared()",
    "assert_no_active_drill_alerts()",
    'all(.[]; .labels.drill != "true")',
    "vector(1)",
    "vector(0) == 1",
    "v0.11.5.2.0.2-alert-resolution-transition-repair.json",
    "explicit inactive transition",
):
    require(marker in live, f"Live drill lacks repair marker: {marker}")
require(live.count("assert_no_active_drill_alerts") == 3, "Global stale-alert check must run at preflight and final state")
require("'vector(0)'" not in live and '"vector(0)"' not in live, "Numeric zero alone is still used")

phase_1 = phase(live, 1, 2)
phase_2 = phase(live, 2, 3)
phase_3 = phase(live, 3, 4)
phase_4 = phase(live, 4, None)
require_in_order(phase_1, [
    "apply_single_rule AlertLifecycleDrillWarning warning",
    "'vector(0) == 1'",
    "wait_prometheus_cleared AlertLifecycleDrillWarning",
    "wait_webhook_event /warning AlertLifecycleDrillWarning resolved",
    "wait_no_drill_alerts",
    "remove_rule",
], "Phase 1")
require_in_order(phase_2, [
    "apply_single_rule AlertLifecycleDrillCritical critical",
    "'vector(0) == 1'",
    "wait_prometheus_cleared AlertLifecycleDrillCritical",
    "wait_webhook_event /critical AlertLifecycleDrillCritical resolved",
    "wait_no_drill_alerts",
    "remove_rule",
], "Phase 2")
require_in_order(phase_3, [
    "apply_pair_rules",
    "'vector(0) == 1'",
    "wait_prometheus_cleared AlertLifecycleDrillWarning",
    "wait_prometheus_cleared AlertLifecycleDrillCritical",
    "wait_webhook_event /critical AlertLifecycleDrillCritical resolved",
    "wait_no_drill_alerts",
    "remove_rule",
], "Phase 3")
require_in_order(phase_4, [
    "apply_pair_rules",
    "'vector(0) == 1'",
    "wait_prometheus_cleared AlertLifecycleDrillWarning",
    "wait_prometheus_cleared AlertLifecycleDrillCritical",
    "wait_webhook_event /warning AlertLifecycleDrillWarning resolved",
    "wait_webhook_event /critical AlertLifecycleDrillCritical resolved",
    "wait_no_drill_alerts",
    "remove_rule",
], "Phase 4")

# Prove that the ordering validator rejects the original delete-before-resolved
# regression instead of merely accepting the current source text.
bad_order = phase_1.replace(
    "wait_webhook_event /warning AlertLifecycleDrillWarning resolved \"${RESOLUTION_TIMEOUT_SECONDS}\"\nwait_no_drill_alerts\nremove_rule",
    "remove_rule\nwait_webhook_event /warning AlertLifecycleDrillWarning resolved \"${RESOLUTION_TIMEOUT_SECONDS}\"\nwait_no_drill_alerts",
    1,
)
try:
    require_in_order(bad_order, [
        "wait_prometheus_cleared AlertLifecycleDrillWarning",
        "wait_webhook_event /warning AlertLifecycleDrillWarning resolved",
        "wait_no_drill_alerts",
        "remove_rule",
    ], "delete-before-resolved mutation")
except ContractError:
    pass
else:
    raise ContractError("Delete-before-resolved mutation was accepted")

bad_expression = live.replace("'vector(0) == 1'", "'vector(0)'", 1)
try:
    require("'vector(0)'" not in bad_expression, "Numeric-zero-only mutation")
except ContractError:
    pass
else:
    raise ContractError("Numeric-zero-only mutation was accepted")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.2.0.2-alert-resolution-transition-repair.sh"),
    ("README.md", "v0.11.5.2.0.2-alert-resolution-transition-repair"),
    ("docs/ROADMAP.md", "v0.11.5.2.0.2"),
    ("docs/OBSERVABILITY.md", "vector(0) == 1"),
    ("docs/V0.11.5.2.0_ALERT_LIFECYCLE_DRILL.md", "v0.11.5.2.0.2"),
    ("docs/V0.11.5.2.0.1_ALERTMANAGER_WEBHOOK_URL_REDACTION_REPAIR.md", "v0.11.5.2.0.2"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.5.2.0.2"),
    ("CHANGELOG.md", "## v0.11.5.2.0.2"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.5.2.0.2-alert-resolution-transition-repair.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}")

print("v0.11.5.2.0.2 explicit inactive transition, resolved-before-delete ordering, stale-run protection, and unchanged runtime boundaries passed.")
print("v0.11.5.2.0.2 delete-before-resolved and numeric-zero-only mutations were rejected.")
PY

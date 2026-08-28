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


def function_body(text: str, name: str, next_name: str) -> str:
    start = text.find(f"{name}() {{")
    end = text.find(f"{next_name}() {{", start)
    require(start >= 0 and end > start, f"Could not isolate function: {name}")
    return text[start:end]


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


contract_path = "delivery/contracts/v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.2.0.3", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.2.0.3", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.2.0.2", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.2.0.2-alert-resolution-transition-repair.json").is_file(), "Missing predecessor contract")

incident = contract.get("incident", {})
for key in (
    "allFourLifecyclePhasesCompleted",
    "temporaryRulesHealthy",
    "temporaryRulesInactive",
    "formalRulesHealthy",
    "formalRulesInactive",
    "cleanupSynchronizationDefect",
):
    require(incident.get(key) is True, f"Incident evidence omitted: {key}")
for key in (
    "kubernetesDeletionConfirmedByIncidentOutput",
    "prometheusInventoryConvergenceConfirmed",
    "lifecycleTransitionDefect",
):
    require(incident.get(key) is False, f"Incident evidence overstated: {key}")
require((incident.get("observedFormalAlertCount"), incident.get("observedTemporaryAlertCount"), incident.get("observedPrometheusInventoryCount")) == (9, 2, 11), "Observed inventory changed")

repair = contract.get("repair", {})
for key in (
    "kubernetesDeletionAndPrometheusReloadSeparated",
    "strictFinalKubernetesDeletion",
    "exitTrapCleanupRemainsBestEffort",
    "prometheusInventoryAbsenceRequiredAfterEachPhase",
    "prometheusInventoryAbsenceRequiredBeforeFormalBaseline",
    "boundedPolling",
    "timeoutDiagnosticsRequired",
    "formalBaselineCheckedOnlyAfterConvergence",
):
    require(repair.get(key) is True, f"Repair requirement disabled: {key}")
require(repair.get("temporaryAlertNamesChecked") == ["AlertLifecycleDrillWarning", "AlertLifecycleDrillCritical"], "Temporary inventory scope changed")
require(repair.get("ruleRemovalTimeoutSeconds") == 120, "Rule-removal timeout changed")

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
for key in (
    "completeQualityGateRequired",
    "localLiveRerunRequired",
    "zeroKubernetesResidualRequired",
    "zeroPrometheusRuleInventoryResidualRequired",
    "exactFormalAlertInventoryRequired",
):
    require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
for key in ("monitoringRedeployBeforeRerun", "imageRebuildBeforeRerun"):
    require(acceptance.get(key) is False, f"Unnecessary runtime action required: {key}")
require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")

local_chart = read("clusters/local/platform/Chart.yaml")
logging_runtime_successor = (root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file()
events_runtime_successor = (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file()
require(
    ("version: 0.6.0" if events_runtime_successor else ("version: 0.5.0" if logging_runtime_successor else "version: 0.4.1")) in local_chart
    and ('appVersion: "v0.11.6.1.2"' if events_runtime_successor else ('appVersion: "v0.11.6.1.1"' if logging_runtime_successor else 'appVersion: "v0.11.5.2.0"')) in local_chart,
    "Local platform Chart changed",
)
views_chart = read("platform/observability/helm/Chart.yaml")
require("version: 0.4.1" in views_chart and 'appVersion: "v0.11.5.1.1"' in views_chart, "Observability Chart changed")

live = read("scripts/check-alert-lifecycle-drill.sh")
for marker in (
    'RULE_REMOVAL_TIMEOUT_SECONDS="${RULE_REMOVAL_TIMEOUT_SECONDS:-120}"',
    "delete_drill_resources_best_effort()",
    "delete_drill_resources_strict()",
    "wait_prometheus_drill_rules_removed()",
    "/api/v1/rules?type=alert",
    "temporary alert lifecycle drill rules remained in the Prometheus inventory",
    "v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.json",
    "Prometheus rule-inventory convergence",
):
    require(marker in live, f"Live drill lacks cleanup repair marker: {marker}")

best_effort = function_body(live, "delete_drill_resources_best_effort", "delete_drill_resources_strict")
strict = function_body(live, "delete_drill_resources_strict", "cleanup")
cleanup = function_body(live, "cleanup", "port_is_open")
require(best_effort.count("|| true") == 2, "EXIT cleanup is not explicitly best-effort")
require("|| true" not in strict and strict.count("kubectl") == 2, "Final Kubernetes cleanup is not strict")
require("delete_drill_resources_best_effort" in cleanup, "EXIT trap does not use best-effort cleanup")
require(live.count("wait_prometheus_drill_rules_removed") == 6, "Prometheus inventory wait must run after four phases and final cleanup")

for number, next_number in ((1, 2), (2, 3), (3, 4), (4, None)):
    require_in_order(phase(live, number, next_number), [
        "remove_rule",
        "wait_prometheus_drill_rules_removed",
    ], f"Phase {number} cleanup")

cleanup_start = live.find('echo "==> Cleanup:')
require(cleanup_start >= 0, "Final cleanup section missing")
final_cleanup = live[cleanup_start:]
require_in_order(final_cleanup, [
    "delete_drill_resources_strict",
    "wait_prometheus_drill_rules_removed",
    "assert_no_stale_resources",
    "assert_no_active_drill_alerts",
    "assert_clean_formal_alerts",
], "Final cleanup")

# Negative mutation: the original race asserted the formal baseline before the
# Prometheus rule inventory converged.
bad_order = final_cleanup.replace(
    "delete_drill_resources_strict\nwait_prometheus_drill_rules_removed\nassert_no_stale_resources\nassert_no_active_drill_alerts\nassert_clean_formal_alerts",
    "delete_drill_resources_strict\nassert_clean_formal_alerts\nassert_no_stale_resources\nassert_no_active_drill_alerts\nwait_prometheus_drill_rules_removed",
    1,
)
try:
    require_in_order(bad_order, [
        "delete_drill_resources_strict",
        "wait_prometheus_drill_rules_removed",
        "assert_no_stale_resources",
        "assert_no_active_drill_alerts",
        "assert_clean_formal_alerts",
    ], "pre-convergence formal-baseline mutation")
except ContractError:
    pass
else:
    raise ContractError("Pre-convergence formal-baseline mutation was accepted")

# Negative mutation: ordinary final cleanup must not use the trap's
# best-effort deletion path.
bad_cleanup = final_cleanup.replace("delete_drill_resources_strict", "delete_drill_resources_best_effort", 1)
try:
    require("delete_drill_resources_strict" in bad_cleanup, "best-effort final-cleanup mutation")
except ContractError:
    pass
else:
    raise ContractError("Best-effort final-cleanup mutation was accepted")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.sh"),
    ("README.md", "v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair"),
    ("docs/ROADMAP.md", "v0.11.5.2.0.3"),
    ("docs/OBSERVABILITY.md", "rule inventory convergence"),
    ("docs/V0.11.5.2.0_ALERT_LIFECYCLE_DRILL.md", "v0.11.5.2.0.3"),
    ("docs/V0.11.5.2.0.2_ALERT_RESOLUTION_TRANSITION_REPAIR.md", "v0.11.5.2.0.3"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.5.2.0.3"),
    ("CHANGELOG.md", "## v0.11.5.2.0.3"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.5.2.0.3-prometheus-rule-cleanup-synchronization-repair.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}")

print("v0.11.5.2.0.3 strict Kubernetes cleanup, bounded Prometheus rule-inventory convergence, and exact formal-baseline ordering passed.")
print("v0.11.5.2.0.3 pre-convergence baseline and best-effort final-cleanup mutations were rejected.")
PY

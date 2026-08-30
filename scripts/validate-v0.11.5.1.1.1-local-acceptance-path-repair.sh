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


contract_path = "delivery/contracts/v0.11.5.1.1.1-local-acceptance-path-repair.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.1.1.1", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.1.1.1", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.1.1", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.1.1-prometheus-target-down-semantics-repair.json").is_file(), "Missing predecessor contract")

evidence = contract.get("observedEvidence", {})
require(evidence.get("historicalImageTag") == "sha-3e50802", "Observed historical image changed")
require(evidence.get("historicalMetric") == "demo_api_requests_total", "Observed historical metric changed")
require(evidence.get("requiredMetricsObservedAfterFreshBuild") == [
    "demo_api_http_requests_total",
    "demo_api_dependency_checks_total",
], "Fresh image evidence changed")
require(evidence.get("prometheusRuleObserved") == "operator-diagnostic-recording-rules", "Observed PrometheusRule changed")

repairs = contract.get("repairs", {})
ownership = repairs.get("prometheusRuleOwnershipCheck", {})
require(ownership == {
    "script": "scripts/check-prometheus-target-counts.sh",
    "previousName": "operator-recording-rules",
    "actualName": "operator-diagnostic-recording-rules",
    "sourceTemplate": "platform/observability/helm/templates/operator-recording-rules.yaml",
    "overrideVariable": "OPERATOR_RECORDING_RULE_NAME",
}, "PrometheusRule ownership repair changed")


def validate_rule_binding(template: str, script: str) -> None:
    metadata = re.search(r"(?ms)^metadata:\n\s+name:\s*(\S+)", template)
    default = re.search(
        r'OPERATOR_RECORDING_RULE_NAME="\$\{OPERATOR_RECORDING_RULE_NAME:-([^}]+)\}"',
        script,
    )
    require(metadata is not None, "PrometheusRule template metadata name is missing")
    require(default is not None, "Target-count rule-name default is missing")
    require(metadata.group(1) == default.group(1), "Target-count rule-name default differs from Chart metadata")
    require(
        'get prometheusrule "${OPERATOR_RECORDING_RULE_NAME}"' in script,
        "Target-count preflight does not use the bounded rule-name variable",
    )


template = read(ownership["sourceTemplate"])
script = read(ownership["script"])
validate_rule_binding(template, script)
require("get prometheusrule operator-recording-rules" not in script, "Old PrometheusRule lookup regression detected")

mutated_script = script.replace(
    "operator-diagnostic-recording-rules",
    "operator-recording-rules",
    1,
)
try:
    validate_rule_binding(template, mutated_script)
except ContractError:
    pass
else:
    raise ContractError("PrometheusRule-name mutation was not rejected")

image_repair = repairs.get("freshImageTransition", {})
require(image_repair == {
    "neutralBaselineIsReplayStartOnly": True,
    "freshUniqueLocalImageRequired": True,
    "buildScript": "scripts/build-load-demo-api-image.sh",
    "deployScript": "scripts/deploy-local-feature-gitops.sh",
    "applicationVersionEqualsImageTag": True,
    "requiredDirectMetrics": [
        "demo_api_http_requests_total",
        "demo_api_dependency_checks_total",
    ],
}, "Fresh-image transition contract changed")

for relative in (
    "docs/V0.11.5.1.1_PROMETHEUS_TARGET_DOWN_SEMANTICS_REPAIR.md",
    "docs/V0.11.5.1.1.1_LOCAL_ACCEPTANCE_PATH_REPAIR.md",
):
    text = read(relative)
    for marker in (
        "neutral",
        "scripts/build-load-demo-api-image.sh",
        "scripts/deploy-local-feature-gitops.sh",
        'APPLICATION_VERSION="${IMAGE_TAG}"',
        "demo_api_http_requests_total",
        "demo_api_dependency_checks_total",
        "operator-diagnostic-recording-rules",
    ):
        require(marker in text, f"Fresh-image or ownership guidance missing in {relative}: {marker}")
    require("reuse the exact accepted" not in text, f"Stale-image reuse guidance remains in {relative}")

unchanged = contract.get("unchanged", {})
require(unchanged.get("observabilityChartVersion") == "0.4.1", "Chart version changed")
require(unchanged.get("observabilityApplicationVersion") == "v0.11.5.1.1", "Application version changed")
require(unchanged.get("recordingRuleExpression") == "sum by (namespace, job) (up == bool 0)", "Recording expression changed")
require(unchanged.get("alertCount") == 9, "Alert count changed")
require(unchanged.get("warningCount") == 2, "Warning count changed")
require(unchanged.get("criticalCount") == 7, "Critical count changed")
for name, flag in unchanged.items():
    if name not in {
        "observabilityChartVersion",
        "observabilityApplicationVersion",
        "recordingRuleExpression",
        "alertCount",
        "warningCount",
        "criticalCount",
    }:
        require(flag is False, f"Repair boundary expanded: {name}")

chart = read("platform/observability/helm/Chart.yaml")
slo_foundation_successor = (root / "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json").is_file()
expected_views = ("version: 0.5.0", 'appVersion: "v0.11.7.0"') if slo_foundation_successor else ("version: 0.4.1", 'appVersion: "v0.11.5.1.1"')
require(all(marker in chart for marker in expected_views), "Observability Chart changed")
require("up == bool 0" in template, "Boolean target-down expression changed")
alerts = re.findall(r"(?m)^\s*- alert:\s*(\S+)\s*$", read("platform/observability/helm/templates/actionable-alerts.yaml"))
require(len(alerts) == 9 and len(set(alerts)) == 9, "Nine-alert inventory changed")
require("PrometheusTargetDown" in alerts, "Target-down alert is missing")

acceptance = contract.get("acceptance", {})
require(acceptance.get("profiles") == ["local", "aws"], "Profiles changed")
require(acceptance.get("localFreshImageReplayRequired") is True, "Fresh local replay is optional")
require(acceptance.get("completeQualityGateRequired") is True, "Complete quality gate is optional")
require(acceptance.get("formalFiringRoutingInhibitionResolutionDrillDeferredTo") == "v0.11.5.2", "Drill boundary moved")
require(acceptance.get("formalAwsEvidenceDeferredTo") == "v0.11.8", "AWS evidence boundary moved")
for key in ("offlineValidator", "targetCountValidator", "actionableAlertValidator"):
    require((root / acceptance.get(key, "")).is_file(), f"Missing acceptance script: {key}")

predecessor_validator = read("scripts/validate-v0.11.5.1.1-prometheus-target-down-semantics-repair.sh")
require("v0.11.5.1.1.1-local-acceptance-path-repair.json" in predecessor_validator, "Predecessor validator is not repair-aware")
require("operator-diagnostic-recording-rules" in predecessor_validator, "Predecessor validator lacks corrected ownership")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.1.1.1-local-acceptance-path-repair.sh"),
    ("README.md", "v0.11.5.1.1.1-local-acceptance-path-repair"),
    ("docs/ROADMAP.md", "v0.11.5.1.1.1"),
    ("docs/OBSERVABILITY.md", "operator-diagnostic-recording-rules"),
    ("CHANGELOG.md", "## v0.11.5.1.1.1"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.5.1.1.1-local-acceptance-path-repair.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Required integration marker missing: {relative}: {marker}")

print("v0.11.5.1.1.1 PrometheusRule ownership, fresh-image replay, unchanged runtime boundary, and integration contracts passed.")
print("v0.11.5.1.1.1 incorrect PrometheusRule-name mutation was rejected.")
PY

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


contract_path = "delivery/contracts/v0.11.5.1.1-prometheus-target-down-semantics-repair.json"
contract = load_json(contract_path)
require(contract.get("schemaVersion") == "v0.11.5.1.1", "Bad schemaVersion")
require(contract.get("version") == "v0.11.5.1.1", "Bad version")
require(contract.get("status") == "offline-implemented-local-live-required", "Bad status")
require(contract.get("predecessor") == "v0.11.5.1", "Bad predecessor")
require((root / contract.get("designDocument", "")).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file(), "Missing predecessor contract")

chart_contract = contract.get("chart", {})
require(chart_contract == {
    "path": "platform/observability/helm",
    "previousVersion": "0.4.0",
    "version": "0.4.1",
    "applicationVersion": "v0.11.5.1.1",
}, "Chart contract changed")
chart = read("platform/observability/helm/Chart.yaml")
for marker in ("name: startup-devops-observability-views", "version: 0.4.1", 'appVersion: "v0.11.5.1.1"'):
    require(marker in chart, f"Chart is missing: {marker}")

rule_contract = contract.get("recordingRule", {})
require(rule_contract.get("name") == "platform:prometheus_targets_down:count", "Recording-rule name changed")
require(rule_contract.get("previousExpression") == "sum by (namespace, job) (up == 0)", "Previous expression identity changed")
require(rule_contract.get("repairedExpression") == "sum by (namespace, job) (up == bool 0)", "Repaired expression identity changed")
require(rule_contract.get("groupingLabels") == ["namespace", "job"], "Recording-rule dimensions changed")
require(rule_contract.get("semantics") == {"allUp": 0, "oneDown": 1, "twoDown": 2, "absent": "no-data"}, "Semantic fixture contract changed")

rules = read(rule_contract.get("path", ""))
match = re.search(
    r"(?ms)^\s*- record:\s*platform:prometheus_targets_down:count\s*$\n(?P<body>.*?)(?=^\s*- record:|\Z)",
    rules,
)
require(match is not None, "Target-down recording rule is missing")
segment = match.group("body")
require("sum by (namespace, job)" in segment, "Target-down grouping changed")
require("up == bool 0" in segment, "Boolean target-down comparison is missing")
require(re.search(r"up\s*==\s*0", segment) is None, "Filter comparison regression detected")
require(segment.count("up == bool 0") == 1, "Boolean comparison must appear exactly once")


def down_count(values: list[int] | None) -> int | None:
    if values is None:
        return None
    return sum(1 if value == 0 else 0 for value in values)


require(down_count([1, 1]) == 0, "All-up fixture failed")
require(down_count([1, 0]) == 1, "One-down fixture failed")
require(down_count([0, 0]) == 2, "Two-down fixture failed")
require(down_count(None) is None, "Absent fixture must remain no-data")

alert_contract = contract.get("alert", {})
require(alert_contract == {
    "name": "PrometheusTargetDown",
    "severity": "critical",
    "component": "prometheus",
    "alertFamily": "monitoring-target-health",
    "sourceRule": "platform:prometheus_targets_down:count",
    "threshold": ">0",
    "for": "10m",
    "runbook": "docs/runbooks/alerts/prometheus-target-down.md",
}, "Target-down alert contract changed")

predecessor = load_json("delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json")
predecessor_names = [item.get("name") for item in predecessor.get("alerts", [])]
require(len(predecessor_names) == 8 and len(set(predecessor_names)) == 8, "Predecessor alert inventory changed")

template = read("platform/observability/helm/templates/actionable-alerts.yaml")
blocks = re.split(r"(?m)^\s*- alert:\s*", template)[1:]
names = [block.partition("\n")[0].strip() for block in blocks]
require(names == predecessor_names + ["PrometheusTargetDown"], "Successor alert order or predecessor inventory changed")
target_block = blocks[-1]
for marker in (
    "platform:prometheus_targets_down:count{",
    '} > 0',
    "for: {{ .Values.alerting.prometheusTargetDownFor }}",
    "severity: critical",
    'environment: {{ .Values.environment | quote }}',
    'cluster: {{ .Values.cluster | quote }}',
    "component: prometheus",
    "alert_family: monitoring-target-health",
    "summary:",
    "description:",
    "prometheus-target-down.md",
):
    require(marker in target_block, f"Target-down alert marker missing: {marker}")
require("up ==" not in target_block and "up{" not in target_block, "Alert bypasses the repaired recording rule")
require("prometheusTargetDownFor: 10m" in read("platform/observability/helm/values.yaml"), "Target-down duration value changed")

policy = contract.get("successorPolicy", {})
require(policy == {
    "alertCount": 9,
    "warningCount": 2,
    "criticalCount": 7,
    "predecessorAlertsUnchanged": True,
    "cleanBaselineMustBeInactive": True,
    "absentRemainsNoData": True,
}, "Successor policy changed")

runbook = read(alert_contract["runbook"])
require(runbook.startswith("# PrometheusTargetDown\n"), "Runbook heading changed")
for marker in ("## Meaning", "## Impact", "## First response", "## Diagnosis and recovery"):
    require(marker in runbook, f"Runbook section missing: {marker}")
for forbidden in ("kubectl delete", "kubectl patch", "kubectl rollout restart", "kubectl scale"):
    require(forbidden not in runbook, f"Runbook contains unapproved direct mutation: {forbidden}")

boundaries = contract.get("boundaries", {})
require(boundaries.get("recordingRuleExpressionRepaired") is True, "Semantic repair is not explicit")
require(all(flag is False for name, flag in boundaries.items() if name != "recordingRuleExpressionRepaired"), "Repair boundary expanded")

acceptance = contract.get("acceptance", {})
require(acceptance.get("offlineSemanticFixtures") == ["all-up", "one-down", "two-down", "absent"], "Fixture set changed")
require(acceptance.get("recordedAndDirectQueryMustMatch") is True, "Live query cross-check is optional")
require(acceptance.get("cleanBaselineAllTargetsUpRequired") is True, "Clean target health is optional")
require(acceptance.get("formalFiringRoutingInhibitionResolutionDrillDeferredTo") == "v0.11.5.2", "Drill boundary moved")
require(acceptance.get("formalAwsEvidenceDeferredTo") == "v0.11.8", "AWS evidence boundary moved")
for validator_key in ("offlineValidator", "liveValidator", "actionableAlertValidator"):
    require((root / acceptance.get(validator_key, "")).is_file(), f"Missing acceptance script: {validator_key}")

historical_validators = (
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    "scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh",
    "scripts/validate-v0.11.4.1.1-operator-dashboards.sh",
    "scripts/validate-v0.11.4.2.0-capacity-signal-foundation.sh",
    "scripts/validate-v0.11.4.2.1-capacity-efficiency-dashboard.sh",
    "scripts/validate-v0.11.4.2.2-replay-diagnostics-repair.sh",
    "scripts/validate-v0.11.5.0-alertmanager-foundation.sh",
    "scripts/validate-v0.11.5.1-actionable-alerts-runbooks.sh",
)
for relative in historical_validators:
    text = read(relative)
    require("v0.11.5.1.1-prometheus-target-down-semantics-repair.json" in text, f"Historical validator is not successor-aware: {relative}")
    require("0.4.1" in text and "v0.11.5.1.1" in text, f"Historical Chart successor missing: {relative}")

for relative, marker in (
    ("scripts/check-prometheus-target-counts.sh", "up == bool 0"),
    ("scripts/check-actionable-alerts.sh", "PrometheusTargetDown"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.5.1.1-prometheus-target-down-semantics-repair.sh"),
    ("docs/ROADMAP.md", "v0.11.5.1.1"),
    ("README.md", "v0.11.5.1.1-prometheus-target-down-semantics-repair"),
    ("CHANGELOG.md", "## v0.11.5.1.1"),
    (".github/CODEOWNERS", "/scripts/check-prometheus-target-counts.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Required integration marker missing: {relative}: {marker}")

acceptance_path_successor = root / "delivery/contracts/v0.11.5.1.1.1-local-acceptance-path-repair.json"
if acceptance_path_successor.is_file():
    repaired_check = read("scripts/check-prometheus-target-counts.sh")
    require("operator-diagnostic-recording-rules" in repaired_check, "Correct PrometheusRule ownership is missing")
    require("get prometheusrule operator-recording-rules" not in repaired_check, "Old PrometheusRule lookup remains")
    repair_doc = read("docs/V0.11.5.1.1.1_LOCAL_ACCEPTANCE_PATH_REPAIR.md")
    for marker in (
        "scripts/build-load-demo-api-image.sh",
        'APPLICATION_VERSION="${IMAGE_TAG}"',
        "demo_api_http_requests_total",
        "demo_api_dependency_checks_total",
    ):
        require(marker in repair_doc, f"Acceptance-path repair guidance missing: {marker}")

print("v0.11.5.1.1 Boolean target-down semantics, ninth alert, Runbook, boundaries, and successor coverage passed.")
PY

fixture_dir="$(mktemp -d)"
trap 'rm -rf -- "${fixture_dir}"' EXIT

python3 - "${fixture_dir}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


fixture_dir = Path(sys.argv[1])


def payload(rows: list[tuple[str, str, int]]) -> dict[str, object]:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"namespace": namespace, "job": job},
                    "value": [1700000000, str(value)],
                }
                for namespace, job, value in rows
            ],
        },
    }


fixtures = {
    "all-up-recorded": payload([("observability", "prometheus", 0), ("startup-apps", "demo-api", 0)]),
    "all-up-direct": payload([("startup-apps", "demo-api", 0), ("observability", "prometheus", 0)]),
    "stale-recorded": payload([("observability", "prometheus", 0)]),
    "one-down": payload([("observability", "prometheus", 1)]),
    "absent": payload([]),
}
for name, value in fixtures.items():
    (fixture_dir / f"{name}.json").write_text(json.dumps(value))
PY

RECORDED_QUERY_FIXTURE="${fixture_dir}/all-up-recorded.json" \
DIRECT_QUERY_FIXTURE="${fixture_dir}/all-up-direct.json" \
  "${ROOT_DIR}/scripts/check-prometheus-target-counts.sh" >/dev/null

REQUIRE_ALL_TARGETS_UP=false \
RECORDED_QUERY_FIXTURE="${fixture_dir}/one-down.json" \
DIRECT_QUERY_FIXTURE="${fixture_dir}/one-down.json" \
  "${ROOT_DIR}/scripts/check-prometheus-target-counts.sh" >/dev/null

for invalid_case in stale down absent; do
  case "${invalid_case}" in
    stale)
      recorded="${fixture_dir}/stale-recorded.json"
      direct="${fixture_dir}/one-down.json"
      diagnostic="recorded and direct Prometheus target-down vectors do not match"
      ;;
    down)
      recorded="${fixture_dir}/one-down.json"
      direct="${fixture_dir}/one-down.json"
      diagnostic="clean baseline contains a down Prometheus target"
      ;;
    absent)
      recorded="${fixture_dir}/absent.json"
      direct="${fixture_dir}/absent.json"
      diagnostic="direct target-down query returned no namespace/job series"
      ;;
  esac
  if RECORDED_QUERY_FIXTURE="${recorded}" DIRECT_QUERY_FIXTURE="${direct}" \
    "${ROOT_DIR}/scripts/check-prometheus-target-counts.sh" >"${fixture_dir}/${invalid_case}.log" 2>&1; then
    echo "ERROR: ${invalid_case} target-count fixture unexpectedly passed." >&2
    exit 1
  fi
  grep -F -- "${diagnostic}" "${fixture_dir}/${invalid_case}.log" >/dev/null || {
    echo "ERROR: ${invalid_case} target-count diagnostic changed." >&2
    cat "${fixture_dir}/${invalid_case}.log" >&2
    exit 1
  }
done

echo "v0.11.5.1.1 recorded/direct query fixtures and clean-baseline negative regressions passed."

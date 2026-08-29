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
    except json.JSONDecodeError as error:
        raise ContractError(f"Invalid JSON in {relative}: {error}") from error
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.11.6.1.1.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.1.1", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.1.1", "Bad predecessor")

    incident = value.get("incident", {})
    for key in (
        "focusedStaticContractPassed",
        "alloyChartRenderingFailed",
        "alloyRbacTemplateWasFailureLocation",
        "emptyClusterRulesWasRootCause",
        "v0112HistoricalValidatorRejectedSuccessor",
        "v01132HistoricalValidatorRejectedSuccessor",
        "v011401FixtureRejectedLoggingSuccessor",
    ):
        require(incident.get(key) is True, f"Incident evidence omitted: {key}")
    require(incident.get("clusterRuntimeAcceptanceReached") is False, "Runtime acceptance overstated")

    repair = value.get("repair", {})
    for key in (
        "alloyRulesNonEmpty",
        "alloyClusterRulesNonEmpty",
        "renderedClusterRoleInventoryRequired",
        "emptyRbacListRegressionRejected",
        "v0112SuccessorAware",
        "v01132SuccessorAware",
        "v011401FixtureSuccessorAware",
    ):
        require(repair.get(key) is True, f"Repair requirement disabled: {key}")
    require(repair.get("alloyRbacResources") == ["namespaces", "pods", "pods/log"], "RBAC resources changed")
    require(repair.get("alloyRbacVerbs") == ["get", "list", "watch"], "RBAC verbs changed")
    require(
        repair.get("successorContract")
        == "delivery/contracts/v0.11.6.1.0-structured-demo-api-logging-runtime.json",
        "Successor authority changed",
    )
    require(
        (
            repair.get("legacyDemoApiChart"),
            repair.get("legacyDemoApiApplicationVersion"),
            repair.get("successorDemoApiChart"),
            repair.get("successorDemoApiApplicationVersion"),
        )
        == ("0.5.1", "0.3.0", "0.6.0", "0.4.0"),
        "Historical/successor Chart identities changed",
    )

    unchanged = value.get("unchanged", {})
    require(
        (
            unchanged.get("localPlatformChart"),
            unchanged.get("localPlatformApplicationVersion"),
            unchanged.get("lokiChart"),
            unchanged.get("lokiApplicationVersion"),
            unchanged.get("alloyChart"),
            unchanged.get("alloyApplicationVersion"),
            unchanged.get("demoApiChart"),
            unchanged.get("demoApiApplicationVersion"),
        )
        == ("0.5.0", "v0.11.6.1.1", "18.11.3", "3.7.6", "1.11.0", "1.18.0", "0.6.0", "0.4.0"),
        "Version boundary changed",
    )
    for key, item in unchanged.items():
        if key not in {
            "localPlatformChart",
            "localPlatformApplicationVersion",
            "lokiChart",
            "lokiApplicationVersion",
            "alloyChart",
            "alloyApplicationVersion",
            "demoApiChart",
            "demoApiApplicationVersion",
        }:
            require(item is False, f"Repair boundary expanded: {key}")

    acceptance = value.get("acceptance", {})
    for key in (
        "focusedPredecessorValidatorRequired",
        "completeQualityGateRequired",
        "pinnedExternalChartRenderRequired",
        "localLiveRerunRequired",
        "loggingGitOpsReconciliationRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    for key in ("demoApiImageRebuildRequired", "demoApiRedeployRequired"):
        require(acceptance.get(key) is False, f"Unnecessary demo-api action required: {key}")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Closure boundary moved")


contract_path = "delivery/contracts/v0.11.6.1.1.1-alloy-rbac-rendering-historical-validator-repair.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require((root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file(), "Missing predecessor contract")

alloy_values = read("clusters/local/platform/files/logging/alloy-values.yaml")
rbac_start = alloy_values.find("\nrbac:\n")
rbac_end = alloy_values.find("\nserviceAccount:\n", rbac_start)
require(rbac_start >= 0 and rbac_end > rbac_start, "Could not isolate Alloy RBAC values")
rbac = alloy_values[rbac_start:rbac_end]
require("rules: []" not in rbac and "clusterRules: []" not in rbac, "Empty Alloy RBAC list remains")
require(rbac.count("    - apiGroups:") == 2, "Both Alloy RBAC lists must be non-empty")
resources = {item.strip() for item in re.findall(r"(?m)^\s{8}- (namespaces|pods|pods/log)$", rbac)}
require(resources == {"namespaces", "pods", "pods/log"}, f"Alloy RBAC resources changed: {sorted(resources)}")
require(rbac.count("        - get") == 2, "Alloy get permission split changed")
require(rbac.count("        - list") == 2, "Alloy list permission split changed")
require(rbac.count("        - watch") == 2, "Alloy watch permission split changed")

focused = read("scripts/validate-v0.11.6.1.1-local-loki-alloy-pod-logs.sh")
for marker in (
    'require("rules: []" not in rbac_values',
    'require("clusterRules: []" not in rbac_values',
    'rendered_resources == {"namespaces", "pods", "pods/log"}',
):
    require(marker in focused, f"Focused validator lacks RBAC regression marker: {marker}")

for relative in (
    "scripts/validate-v0.11.2-application-platform-telemetry.sh",
    "scripts/validate-v0.11.3.2-prometheus-no-data-hardening.sh",
):
    historical = read(relative)
    for marker in (
        "v0.11.6.1.0-structured-demo-api-logging-runtime.json",
        "structured_logging_successor",
        "v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.json",
        "tracing_successor",
        "version: 0.7.0",
        'appVersion: "0.5.0"',
        "version: 0.6.0",
        'appVersion: "0.4.0"',
        "version: 0.5.1",
        'appVersion: "0.3.0"',
    ):
        require(marker in historical, f"Historical validator is not successor-aware: {relative}: {marker}")

historical_helm_fixture = read("scripts/validate-v0.11.4.0.1-helm-successor-coverage.sh")
for marker in (
    "v0.11.6.1.1-local-loki-alloy-pod-logs.json",
    "INCLUDE_LOGGING_APPS",
    "name: logging-loki",
    "targetRevision: 18.11.3",
    "name: logging-alloy",
    "targetRevision: 1.11.0",
):
    require(marker in historical_helm_fixture, f"Historical Helm fixture lacks logging successor: {marker}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.1.1-alloy-rbac-rendering-historical-validator-repair.sh"),
    ("CHANGELOG.md", "## v0.11.6.1.1.1"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.6.1.1.1-alloy-rbac-rendering-historical-validator-repair.json @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.6.1.1.1-alloy-rbac-rendering-historical-validator-repair.sh @SterlingAureum"),
    (".github/CODEOWNERS", "/docs/V0.11.6.1.1.1_ALLOY_RBAC_RENDERING_HISTORICAL_VALIDATOR_REPAIR.md @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("empty rules accepted", lambda value: value["repair"].__setitem__("alloyRulesNonEmpty", False)),
    ("empty clusterRules accepted", lambda value: value["repair"].__setitem__("alloyClusterRulesNonEmpty", False)),
    ("RBAC expansion", lambda value: value["repair"]["alloyRbacResources"].append("nodes")),
    ("successor downgrade", lambda value: value["repair"].__setitem__("successorDemoApiChart", "0.5.1")),
    ("runtime acceptance overstated", lambda value: value["incident"].__setitem__("clusterRuntimeAcceptanceReached", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.1.1.1 Alloy RBAC rendering and historical validator compatibility repair passed.")
print("v0.11.6.1.1.1 empty-list, RBAC-expansion, successor-downgrade, and runtime-overstatement mutations were rejected.")
PY

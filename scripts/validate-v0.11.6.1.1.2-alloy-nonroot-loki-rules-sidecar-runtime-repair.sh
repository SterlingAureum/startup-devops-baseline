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
    require(value.get("schemaVersion") == "v0.11.6.1.1.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.1.2", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-rerun-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.1.1.1", "Bad predecessor")

    incident = value.get("incident", {})
    for key in (
        "alloyCreateContainerConfigErrorObserved",
        "alloyImageDefaultRootConflictedWithRunAsNonRoot",
        "lokiRulesSidecarCrashLoopObserved",
        "lokiMainContainerReadyObserved",
        "lokiGatewayReadyObserved",
        "memberlistHeadlessServiceObserved",
        "memberlistEndpointObserved",
    ):
        require(incident.get(key) is True, f"Incident evidence omitted: {key}")
    require(incident.get("lokiRulesObjectsDeployed") is False, "Ruler objects were invented")
    require(incident.get("localRuntimeAcceptanceReached") is False, "Runtime acceptance overstated")

    repair = value.get("repair", {})
    require(repair.get("alloyRunAsNonRoot") is True, "Alloy non-root enforcement disabled")
    require(
        (repair.get("alloyRunAsUser"), repair.get("alloyRunAsGroup"), repair.get("alloyFsGroup"))
        == (473, 473, 473),
        "Alloy image identity changed",
    )
    require(repair.get("alloyReadOnlyRootFilesystem") is True, "Alloy read-only root filesystem disabled")
    require(repair.get("alloyPrivilegeEscalationAllowed") is False, "Alloy privilege escalation enabled")
    require(repair.get("lokiRulesSidecarEnabled") is False, "Unused Loki rules sidecar enabled")
    require(repair.get("lokiServiceAccountTokenAutomount") is False, "Loki token automount enabled")
    require(repair.get("lokiExpectedApplicationContainers") == ["loki"], "Loki container topology changed")
    require(repair.get("memberlistConfigurationChanged") is False, "Memberlist repair invented")
    require(
        (
            repair.get("memberlistService"),
            repair.get("memberlistServiceHeadless"),
            repair.get("memberlistPort"),
        )
        == ("observability-logs-memberlist", True, 7946),
        "Memberlist contract changed",
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
        "loggingGitOpsReconciliationRequired",
        "alloyDaemonSetReadyRequired",
        "lokiSingleContainerReadyRequired",
        "lokiGatewayReadyRequired",
        "memberlistEndpointRequired",
        "stableLokiRestartCountRequired",
        "localLiveRerunRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    for key in ("demoApiImageRebuildRequired", "demoApiRedeployRequired"):
        require(acceptance.get(key) is False, f"Unnecessary demo-api action required: {key}")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Closure boundary moved")


contract_path = "delivery/contracts/v0.11.6.1.1.2-alloy-nonroot-loki-rules-sidecar-runtime-repair.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require(
    (root / "delivery/contracts/v0.11.6.1.1.1-alloy-rbac-rendering-historical-validator-repair.json").is_file(),
    "Missing predecessor repair contract",
)

alloy_values = read("clusters/local/platform/files/logging/alloy-values.yaml")
pod_security = re.search(r"(?ms)^global:\n  podSecurityContext:\n(.*?)(?=^alloy:)", alloy_values)
require(pod_security is not None, "Could not isolate Alloy Pod security context")
for marker in ("runAsNonRoot: true", "fsGroup: 473", "type: RuntimeDefault"):
    require(marker in pod_security.group(1), f"Alloy Pod security marker missing: {marker}")

container_security = re.search(r"(?ms)^  securityContext:\n(.*?)(?=^  resources:)", alloy_values)
require(container_security is not None, "Could not isolate Alloy container security context")
for marker in (
    "allowPrivilegeEscalation: false",
    "readOnlyRootFilesystem: true",
    "runAsNonRoot: true",
    "runAsUser: 473",
    "runAsGroup: 473",
    "drop:\n        - ALL",
    "type: RuntimeDefault",
):
    require(marker in container_security.group(1), f"Alloy container security marker missing: {marker}")
for forbidden in ("runAsUser: 0", "runAsGroup: 0", "privileged: true"):
    require(forbidden not in alloy_values, f"Unsafe Alloy identity found: {forbidden}")

loki_values = read("clusters/local/platform/files/logging/loki-values.yaml")
require("defaults:\n  automountServiceAccountToken: false" in loki_values, "Loki token automount changed")
require("sidecar:\n  rules:\n    enabled: false" in loki_values, "Loki rules sidecar is not disabled")
require("memberlist" not in loki_values, "Repair unexpectedly changed Loki memberlist values")

focused = read("scripts/validate-v0.11.6.1.1-local-loki-alloy-pod-logs.sh")
for marker in (
    '"runAsUser: 473"',
    '"runAsGroup: 473"',
    '"fsGroup: 473"',
    '"name: loki-sc-rules" not in statefulset',
    '"automountServiceAccountToken: false" in statefulset',
    'f"Rendered Alloy security context missing: {marker}"',
):
    require(marker in focused, f"Focused validator lacks runtime-repair regression marker: {marker}")

live = read("scripts/check-local-logging-runtime.sh")
for marker in (
    "LOKI_MEMBERLIST_SERVICE",
    '.securityContext.fsGroup == 473',
    '.runAsUser == 473',
    '.runAsGroup == 473',
    'containers[].name] == ["loki"]',
    "automountServiceAccountToken == false",
    "kubernetes.io/service-name=${LOKI_MEMBERLIST_SERVICE}",
    "Loki main-container restart count changed",
):
    require(marker in live, f"Live checker lacks runtime-repair marker: {marker}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.1.2-alloy-nonroot-loki-rules-sidecar-runtime-repair.sh"),
    ("CHANGELOG.md", "## v0.11.6.1.1.2"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.6.1.1.2-alloy-nonroot-loki-rules-sidecar-runtime-repair.json @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/validate-v0.11.6.1.1.2-alloy-nonroot-loki-rules-sidecar-runtime-repair.sh @SterlingAureum"),
    (".github/CODEOWNERS", "/docs/V0.11.6.1.1.2_ALLOY_NONROOT_LOKI_RULES_SIDECAR_RUNTIME_REPAIR.md @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("root Alloy user", lambda value: value["repair"].__setitem__("alloyRunAsUser", 0)),
    ("root Alloy group", lambda value: value["repair"].__setitem__("alloyRunAsGroup", 0)),
    ("rules sidecar enabled", lambda value: value["repair"].__setitem__("lokiRulesSidecarEnabled", True)),
    ("token automount enabled", lambda value: value["repair"].__setitem__("lokiServiceAccountTokenAutomount", True)),
    ("memberlist changed", lambda value: value["repair"].__setitem__("memberlistConfigurationChanged", True)),
    ("runtime acceptance overstated", lambda value: value["incident"].__setitem__("localRuntimeAcceptanceReached", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.1.1.2 Alloy non-root identity and Loki rules-sidecar runtime repair passed.")
print("v0.11.6.1.1.2 root, sidecar, token, memberlist, and runtime-overstatement mutations were rejected.")
PY

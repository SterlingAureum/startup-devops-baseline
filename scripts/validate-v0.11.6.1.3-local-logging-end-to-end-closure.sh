#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Callable

root = Path(sys.argv[1])


class ContractError(RuntimeError):
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
    require(value.get("schemaVersion") == "v0.11.6.1.3", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.3", "Bad version")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    require(value.get("predecessor") == "v0.11.6.1.2.2", "Bad predecessor")

    scope = value.get("scope", {})
    require(scope.get("environment") == "local", "Environment boundary changed")
    require(scope.get("structuredLoggingClosure") is True, "Logging closure disabled")
    for key in (
        "runtimeConfigurationChanged",
        "kubernetesResourceChanged",
        "applicationCodeChanged",
        "applicationImageChanged",
        "tracingImplemented",
    ):
        require(scope.get(key) is False, f"Scope expanded: {key}")

    require(value.get("sequence") == [
        "scripts/validate.sh",
        "scripts/check-local-logging-runtime.sh",
        "scripts/check-local-events-grafana.sh",
        "final-state",
    ], "Acceptance stage order changed")

    acceptance = value.get("acceptance", {})
    require(
        acceptance.get("entrypoint") == "scripts/check-local-logging-end-to-end.sh",
        "Bad live entrypoint",
    )
    require(
        acceptance.get("offlineValidator")
        == "scripts/validate-v0.11.6.1.3-local-logging-end-to-end-closure.sh",
        "Bad offline validator",
    )
    require(acceptance.get("consecutiveSuccessfulRunsRequired") == 2, "Two-run proof removed")
    for key in (
        "completeQualityGateRequired",
        "applicationHealthRechecked",
        "podLogQueryRequired",
        "releaseIdentityRequired",
        "podReplacementRetentionRequired",
        "eventQueryRequired",
        "eventCollectorRestartRequired",
        "eventReplayRejected",
        "grafanaDatasourceProxyRequired",
        "exactSixLabelInventoryRequired",
        "eventsPvcBoundRequired",
        "strictNormalEventCleanup",
        "bestEffortFailureTrapCleanup",
        "eventHistoryRetainedAfterSourceCleanup",
        "stageFailureDiagnosticsRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("temporaryEventResidualAllowed") is False, "Event residue allowed")

    troubleshooting = value.get("troubleshooting", {})
    require(troubleshooting.get("waitForFirstConsumerIncidentRetained") is True, "Incident record dropped")
    require(
        troubleshooting.get("document")
        == "docs/V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md",
        "Troubleshooting document changed",
    )
    for key in ("destructiveReproductionRequired", "pvcDeletionAllowed", "storageClassMutationAllowed"):
        require(troubleshooting.get(key) is False, f"Destructive troubleshooting enabled: {key}")

    unchanged = value.get("unchanged", {})
    require(
        (
            unchanged.get("localPlatformChart"),
            unchanged.get("localPlatformApplicationVersion"),
            unchanged.get("lokiChart"),
            unchanged.get("lokiApplicationVersion"),
            unchanged.get("alloyChart"),
            unchanged.get("alloyApplicationVersion"),
        ) == ("0.6.0", "v0.11.6.1.2", "18.11.3", "3.7.6", "1.11.0", "1.18.0"),
        "Runtime version boundary changed",
    )
    version_keys = {
        "localPlatformChart",
        "localPlatformApplicationVersion",
        "lokiChart",
        "lokiApplicationVersion",
        "alloyChart",
        "alloyApplicationVersion",
    }
    for key, item in unchanged.items():
        if key not in version_keys:
            require(item is False, f"Unchanged boundary expanded: {key}")

    operations = value.get("operations", {})
    for key, item in operations.items():
        require(item is False, f"Unnecessary operation enabled: {key}")
    require(value.get("nextIncrement", {}).get("version") == "v0.11.6.2", "Next increment changed")


contract_path = "delivery/contracts/v0.11.6.1.3-local-logging-end-to-end-closure.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing closure document")

for predecessor in (
    "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json",
    "delivery/contracts/v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.json",
    "delivery/contracts/v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.json",
):
    require((root / predecessor).is_file(), f"Missing predecessor contract: {predecessor}")

live = read("scripts/check-local-logging-end-to-end.sh")
stage_markers = (
    'run_stage platform-baseline "${ROOT_DIR}/scripts/validate.sh"',
    'run_stage pod-log-runtime "${ROOT_DIR}/scripts/check-local-logging-runtime.sh"',
    'run_stage events-grafana-runtime "${ROOT_DIR}/scripts/check-local-events-grafana.sh"',
    "run_stage final-state final_state_check",
)
positions = [live.find(marker) for marker in stage_markers]
require(all(position >= 0 for position in positions), "Closure stage missing")
require(positions == sorted(positions), "Closure stage order changed")
for marker in (
    "emit_failure_diagnostics",
    "startup-devops-root monitoring logging-loki logging-alloy logging-alloy-events",
    "get pod,pvc -o wide",
    "--tail=80",
    'startswith("v011612-")',
    "no temporary acceptance Event remains",
):
    require(marker in live, f"Closure live marker missing: {marker}")
for forbidden in ("delete pvc", "delete storageclass", "deploy-local-feature-gitops.sh", "docker build"):
    require(forbidden not in live.lower(), f"Unsafe closure action found: {forbidden}")

events = read("scripts/check-local-events-grafana.sh")
for marker in (
    "delete_acceptance_events_strict",
    '--ignore-not-found --wait=true',
    'EVENT_NAMES=()',
    "Proving accepted Event history remains queryable after source cleanup",
    "post-cleanup-first-event.json",
    "post-cleanup-second-event.json",
):
    require(marker in events, f"Strict Event cleanup marker missing: {marker}")
strict_position = events.rfind("delete_acceptance_events_strict")
success_position = events.rfind("singleton Kubernetes Events and Grafana Loki data-source acceptance passed")
require(strict_position < success_position, "Event cleanup occurs after success")
require('delete event "${EVENT_NAMES[@]}"' in events, "Best-effort failure cleanup was removed")
require("|| true" in events.split("trap cleanup EXIT", 1)[0], "Failure trap cleanup is not best-effort")

microtime_validator = read("scripts/validate-v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.sh")
for marker in (
    "v0.11.6.1.3-local-logging-end-to-end-closure.json",
    "Closure successor marker missing",
    "v0.11.6.1.3 local logging closure successor coverage passed",
):
    require(marker in microtime_validator, f"MicroTime successor coverage missing: {marker}")

doc = read("docs/V0.11.6.1.3_LOCAL_LOGGING_END_TO_END_CLOSURE.md")
for marker in (
    "strictly deletes both temporary Kubernetes Events",
    "both unique Event markers must still be queryable",
    "Execute the closure command",
    "WaitForFirstConsumer",
    "v0.11.6.2 minimal extensible tracing",
):
    require(marker in doc, f"Closure documentation marker missing: {marker}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.3-local-logging-end-to-end-closure.sh"),
    ("CHANGELOG.md", "## v0.11.6.1.3"),
    ("README.md", "v0.11.6.1.3-local-logging-end-to-end-closure"),
    ("docs/ROADMAP.md", "v0.11.6.1.3 closes the local structured-logging runtime"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.1.3 local structured-logging closure"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.1.3 closes structured logging"),
    ("docs/V0.11.6.1.2_KUBERNETES_EVENTS_GRAFANA_LOKI.md", "Closure `v0.11.6.1.3`"),
    ("docs/V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md", "v0.11.6.1.3 closure"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/check-local-logging-end-to-end.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("single live run", lambda value: value["acceptance"].__setitem__("consecutiveSuccessfulRunsRequired", 1)),
    ("best-effort normal cleanup", lambda value: value["acceptance"].__setitem__("strictNormalEventCleanup", False)),
    ("Event residue", lambda value: value["acceptance"].__setitem__("temporaryEventResidualAllowed", True)),
    ("destructive PVC reproduction", lambda value: value["troubleshooting"].__setitem__("pvcDeletionAllowed", True)),
    ("runtime mutation", lambda value: value["scope"].__setitem__("runtimeConfigurationChanged", True)),
    ("image rebuild", lambda value: value["operations"].__setitem__("imageRebuildRequired", True)),
    ("tracing early", lambda value: value["scope"].__setitem__("tracingImplemented", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.1.3 ordered local logging closure, strict Event cleanup, retained history, and diagnostics contracts passed.")
print("v0.11.6.1.3 single-run, residue, destructive-storage, runtime, rebuild, and tracing mutations were rejected.")
PY

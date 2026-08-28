#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

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
    require(value.get("schemaVersion") == "v0.11.6.1.2.1", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.2.1", "Bad version")
    require(
        value.get("status") == "offline-implemented-local-live-rerun-required",
        "Bad status",
    )
    require(value.get("predecessor") == "v0.11.6.1.2", "Bad predecessor")

    incident = value.get("incident", {})
    require(
        (
            incident.get("storageClass"),
            incident.get("provisioner"),
            incident.get("volumeBindingMode"),
        )
        == ("standard", "rancher.io/local-path", "WaitForFirstConsumer"),
        "Observed StorageClass evidence changed",
    )
    require(
        (
            incident.get("pvcSyncWave"),
            incident.get("originalConsumerApplicationSyncWave"),
        )
        == (8, 9),
        "Original cross-wave incident omitted",
    )
    require(
        (
            incident.get("rootHealth"),
            incident.get("pvcHealth"),
            incident.get("consumerApplicationHealth"),
        )
        == ("Progressing", "Progressing", "Missing"),
        "Observed Argo CD state changed",
    )
    for key in ("rootSyncBlocked", "predecessorFocusedValidationPassed"):
        require(incident.get(key) is True, f"Incident evidence omitted: {key}")
    for key in ("permissionDeniedWasPrimaryCause", "completeQualityGatePassed"):
        require(incident.get(key) is False, f"Incident result overstated: {key}")

    repair = value.get("repair", {})
    require(
        (repair.get("pvcSyncWave"), repair.get("consumerApplicationSyncWave"))
        == (8, 8),
        "PVC and consumer are not co-scheduled",
    )
    for key in (
        "sameWaveRequired",
        "waitForFirstConsumerPreserved",
        "exactRenderedApplicationNamesRequired",
        "boundedFeatureSyncRequired",
        "boundedBaselineRestoreSyncRequired",
        "syncFailureDiagnosticsRequired",
        "stuckOperationRequiresExplicitTermination",
    ):
        require(repair.get(key) is True, f"Repair requirement disabled: {key}")
    for key in (
        "manualChildApplicationCreationRequired",
        "pvcDeletionRequired",
        "lokiRestartRequired",
        "substringApplicationCardinalityAllowed",
    ):
        require(repair.get(key) is False, f"Unsafe recovery enabled: {key}")
    require(
        repair.get("syncTimeoutVariable") == "WAIT_TIMEOUT_SECONDS",
        "Sync timeout source changed",
    )

    troubleshooting = value.get("troubleshooting", {})
    require(troubleshooting and all(troubleshooting.values()), "Troubleshooting coverage incomplete")

    unchanged = value.get("unchanged", {})
    require(
        (
            unchanged.get("localPlatformChart"),
            unchanged.get("localPlatformApplicationVersion"),
            unchanged.get("lokiChart"),
            unchanged.get("lokiApplicationVersion"),
            unchanged.get("alloyChart"),
            unchanged.get("alloyApplicationVersion"),
        )
        == ("0.6.0", "v0.11.6.1.2", "18.11.3", "3.7.6", "1.11.0", "1.18.0"),
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
            require(item is False, f"Repair boundary expanded: {key}")

    acceptance = value.get("acceptance", {})
    for key in (
        "predecessorValidatorRequired",
        "historicalPodLogValidatorRequired",
        "completeQualityGateRequired",
        "rootGitOpsReconciliationRequired",
        "rootApplicationHealthyRequired",
        "eventsApplicationHealthyRequired",
        "positionsClaimBoundRequired",
        "podLogRegressionRequired",
        "eventGrafanaLiveAcceptanceRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("demoApiImageRebuildRequired") is False, "Unnecessary image rebuild required")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Closure boundary moved")


def validate_same_wave(application: str, storage: str) -> None:
    application_waves = re.findall(r'argocd\.argoproj\.io/sync-wave:\s*"([0-9]+)"', application)
    storage_waves = re.findall(r'argocd\.argoproj\.io/sync-wave:\s*"([0-9]+)"', storage)
    require(application_waves == ["8"], "Events Application sync wave changed")
    require(storage_waves == ["8"], "Event position PVC sync wave changed")
    require(application_waves == storage_waves, "WaitForFirstConsumer PVC and consumer are cross-wave")


def validate_bounded_sync(script: str, label: str) -> None:
    require(
        'argocd app sync "${application_name}" --timeout "${WAIT_TIMEOUT_SECONDS}"' in script,
        f"{label} sync is not bounded by WAIT_TIMEOUT_SECONDS",
    )
    require(
        'argocd_application_diagnostics "${application_name}"' in script,
        f"{label} lacks sync failure diagnostics",
    )
    require(
        f"bounded sync failed for Application/${{application_name}}" in script,
        f"{label} lacks explicit bounded-sync failure",
    )


contract_path = "delivery/contracts/v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing troubleshooting document")
require(
    (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file(),
    "Missing predecessor contract",
)

chart = read("clusters/local/platform/Chart.yaml")
require(
    "version: 0.6.0" in chart and 'appVersion: "v0.11.6.1.2"' in chart,
    "Repair unexpectedly changed local platform version",
)

application = read("clusters/local/platform/templates/logging-alloy-events.yaml")
storage = read("clusters/local/platform/templates/logging-alloy-events-storage.yaml")
validate_same_wave(application, storage)
for marker in (
    "name: logging-alloy-events",
    "chart: alloy",
    "releaseName: observability-events-collector",
    "files/logging/alloy-events-values.yaml",
):
    require(marker in application, f"Events Application marker missing: {marker}")
for marker in (
    "kind: PersistentVolumeClaim",
    "name: observability-events-collector-storage",
    "storage: 256Mi",
):
    require(marker in storage, f"Event position PVC marker missing: {marker}")

feature = read("scripts/deploy-local-feature-gitops.sh")
restore = read("scripts/restore-local-gitops-baseline.sh")
validate_bounded_sync(feature, "Feature deploy")
validate_bounded_sync(restore, "Baseline restore")

historical = read("scripts/validate-v0.11.6.1.1-local-loki-alloy-pod-logs.sh")
for marker in (
    "applications.count(name) != 1",
    "Rendered logging Application cardinality changed: {name}",
):
    require(marker in historical, f"Historical exact-name repair marker missing: {marker}")
for forbidden in (
    'text.count("name: logging-loki")',
    'text.count("name: logging-alloy")',
):
    require(forbidden not in historical, f"Substring cardinality regression found: {forbidden}")

predecessor = read("scripts/validate-v0.11.6.1.2-kubernetes-events-grafana-loki.sh")
for marker in (
    "v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.json",
    'expected_events_wave = "8" if sync_wave_repair else "9"',
    "same-wave WaitForFirstConsumer successor coverage passed",
):
    require(marker in predecessor, f"Predecessor successor marker missing: {marker}")

troubleshooting = read("docs/V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md")
for marker in (
    "WaitForFirstConsumer",
    "argocd app terminate-op startup-devops-root",
    "kubectl -n observability get pvc observability-events-collector-storage",
    "kubectl -n argocd get application logging-alloy-events",
    "PermissionDenied",
    "does not need to be deleted",
    "Prevention Invariant",
):
    require(marker in troubleshooting, f"Troubleshooting marker missing: {marker}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.sh"),
    ("CHANGELOG.md", "## v0.11.6.1.2.1"),
    ("README.md", "v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair"),
    ("clusters/local/platform/README.md", "same wave prevents an Argo CD health-gated sync deadlock"),
    ("docs/V0.11.6.1.2_KUBERNETES_EVENTS_GRAFANA_LOKI.md", "v0.11.6.1.2.1"),
    ("docs/ROADMAP.md", "implemented through v0.11.6.1.2.1"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.1.2.1 local observability foundation"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.1.2.1 repairs its WaitForFirstConsumer"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/docs/V0.11.6.1.2.1_EVENTS_PVC_SYNC_WAVE_TROUBLESHOOTING.md @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("cross-wave consumer", lambda value: value["repair"].__setitem__("consumerApplicationSyncWave", 9)),
    ("immediate binding dependency", lambda value: value["repair"].__setitem__("waitForFirstConsumerPreserved", False)),
    ("manual child creation", lambda value: value["repair"].__setitem__("manualChildApplicationCreationRequired", True)),
    ("PVC deletion", lambda value: value["repair"].__setitem__("pvcDeletionRequired", True)),
    ("substring cardinality", lambda value: value["repair"].__setitem__("substringApplicationCardinalityAllowed", True)),
    ("unbounded feature sync", lambda value: value["repair"].__setitem__("boundedFeatureSyncRequired", False)),
    ("missing troubleshooting", lambda value: value["troubleshooting"].__setitem__("documentsCausalChain", False)),
    ("premature quality success", lambda value: value["incident"].__setitem__("completeQualityGatePassed", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

try:
    validate_same_wave(application.replace('sync-wave: "8"', 'sync-wave: "9"', 1), storage)
except ContractError:
    pass
else:
    raise ContractError("Cross-wave rendered Application mutation was accepted")

try:
    validate_bounded_sync(
        feature.replace(' --timeout "${WAIT_TIMEOUT_SECONDS}"', "", 1),
        "Mutated feature deploy",
    )
except ContractError:
    pass
else:
    raise ContractError("Unbounded feature sync mutation was accepted")

print("v0.11.6.1.2.1 same-wave PVC/consumer, exact-name validation, bounded sync, and troubleshooting contracts passed.")
print("v0.11.6.1.2.1 cross-wave, manual, destructive, substring, unbounded, incomplete, and premature-success mutations were rejected.")
PY

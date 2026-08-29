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
from datetime import datetime, timezone
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
    require(value.get("schemaVersion") == "v0.11.6.1.2.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.2.2", "Bad version")
    require(
        value.get("status") == "offline-implemented-local-live-rerun-required",
        "Bad status",
    )
    require(value.get("predecessor") == "v0.11.6.1.2.1", "Bad predecessor")

    incident = value.get("incident", {})
    for key in (
        "eventsApplicationHealthy",
        "eventsDeploymentReady",
        "securityStorageNetworkChecksPassed",
        "grafanaLokiDatasourceChecksPassed",
        "eventCreateReached",
    ):
        require(incident.get(key) is True, f"Incident evidence omitted: {key}")
    for key in (
        "eventCreated",
        "temporaryEventResidualCreated",
        "liveAcceptancePassed",
    ):
        require(incident.get(key) is False, f"Incident result overstated: {key}")
    require(incident.get("apiResponse") == "BadRequest", "API response changed")
    require(incident.get("eventTimeType") == "metav1.MicroTime", "Event time type changed")
    require(
        (incident.get("observedFractionDigits"), incident.get("requiredFractionDigits"))
        == (9, 6),
        "Timestamp precision evidence changed",
    )
    require(incident.get("observedSuffix") == "Z", "Observed timestamp suffix changed")

    repair = value.get("repair", {})
    require(
        (
            repair.get("implementation"),
            repair.get("timezone"),
            repair.get("suffix"),
            repair.get("fractionDigits"),
            repair.get("timespec"),
        )
        == ("python-datetime", "UTC", "Z", 6, "microseconds"),
        "MicroTime repair changed",
    )
    require(repair.get("eventApiVersion") == "events.k8s.io/v1", "Event API changed")
    require(repair.get("cleanupRegisteredAfterCreate") is True, "Cleanup registration moved before create")
    for key in (
        "nanosecondDateFormatAllowed",
        "eventTimeFieldChanged",
        "platformReconciliationRequired",
        "eventsCollectorRestartRequired",
        "lokiRestartRequired",
        "demoApiRedeployRequired",
    ):
        require(repair.get(key) is False, f"Repair boundary expanded: {key}")

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
            require(item is False, f"Unchanged boundary expanded: {key}")

    acceptance = value.get("acceptance", {})
    for key in (
        "predecessorEventsValidatorRequired",
        "predecessorSyncWaveRepairValidatorRequired",
        "completeQualityGateRequired",
        "timestampShapeFixtureRequired",
        "eventGrafanaLiveAcceptanceRerunRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    for key in (
        "podLogLiveAcceptanceRerunRequired",
        "localGitOpsRedeployRequired",
        "imageRebuildRequired",
    ):
        require(acceptance.get(key) is False, f"Unnecessary acceptance work enabled: {key}")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Closure boundary moved")


def validate_live_script(value: str) -> None:
    for marker in (
        "apiVersion: events.k8s.io/v1",
        "eventTime: ${timestamp}",
        "from datetime import datetime, timezone",
        'datetime.now(timezone.utc).isoformat(timespec="microseconds")',
        '.replace("+00:00", "Z")',
        'EVENT_NAMES+=("${name}")',
    ):
        require(marker in value, f"Live MicroTime marker missing: {marker}")
    for forbidden in (
        "date -u +%Y-%m-%dT%H:%M:%S.%NZ",
        "%N",
        'timespec="nanoseconds"',
    ):
        require(forbidden not in value, f"Nanosecond timestamp regression found: {forbidden}")
    create_position = value.find("kubectl create -f -")
    cleanup_position = value.find('EVENT_NAMES+=("${name}")')
    require(create_position >= 0, "Event create command missing")
    require(cleanup_position > create_position, "Cleanup is registered before Event creation")


contract_path = "delivery/contracts/v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing repair document")
for predecessor in (
    "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json",
    "delivery/contracts/v0.11.6.1.2.1-events-pvc-sync-wave-validation-repair.json",
):
    require((root / predecessor).is_file(), f"Missing predecessor contract: {predecessor}")

live = read("scripts/check-local-events-grafana.sh")
validate_live_script(live)

timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
require(
    re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", timestamp) is not None,
    f"Generated Event timestamp does not have exact MicroTime shape: {timestamp}",
)

predecessor_validator = read("scripts/validate-v0.11.6.1.2-kubernetes-events-grafana-loki.sh")
for marker in (
    "v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.json",
    "Event MicroTime repair marker missing",
    "Nanosecond Event timestamp regression found",
    "six-digit Event MicroTime successor coverage passed",
):
    require(marker in predecessor_validator, f"Predecessor successor marker missing: {marker}")

repair_doc = read("docs/V0.11.6.1.2.2_KUBERNETES_EVENT_MICROTIME_ACCEPTANCE_REPAIR.md")
for marker in (
    "metav1.MicroTime",
    "exactly six fractional digits",
    "left no acceptance Event to delete",
    "Do not reconcile the Root",
    "./scripts/check-local-events-grafana.sh",
):
    require(marker in repair_doc, f"Repair documentation marker missing: {marker}")

closure_contract = (
    root / "delivery/contracts/v0.11.6.1.3-local-logging-end-to-end-closure.json"
).is_file()

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair.sh"),
    ("CHANGELOG.md", "## v0.11.6.1.2.2"),
    ("docs/ROADMAP.md", "implemented through v0.11.6.1.2.2"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.1.2.2 then repairs only"),
    ("docs/V0.11.6.1.2_KUBERNETES_EVENTS_GRAFANA_LOKI.md", "Repair `v0.11.6.1.2.2`"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/docs/V0.11.6.1.2.2_KUBERNETES_EVENT_MICROTIME_ACCEPTANCE_REPAIR.md @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

if closure_contract:
    for relative, marker in (
        ("README.md", "v0.11.6.1.3-local-logging-end-to-end-closure"),
        ("docs/OBSERVABILITY.md", "active v0.11.6.1.3 local structured-logging closure"),
        ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.3-local-logging-end-to-end-closure.sh"),
    ):
        require(marker in read(relative), f"Closure successor marker missing: {relative}: {marker}")
else:
    for relative, marker in (
        ("README.md", "v0.11.6.1.2.2-kubernetes-event-microtime-acceptance-repair"),
        ("docs/OBSERVABILITY.md", "active v0.11.6.1.2.2 local observability foundation"),
    ):
        require(marker in read(relative), f"Repair integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("nanosecond precision", lambda value: value["repair"].__setitem__("fractionDigits", 9)),
    ("nanosecond date allowed", lambda value: value["repair"].__setitem__("nanosecondDateFormatAllowed", True)),
    ("local timezone", lambda value: value["repair"].__setitem__("timezone", "local")),
    ("missing Z suffix", lambda value: value["repair"].__setitem__("suffix", "+00:00")),
    ("cleanup before create", lambda value: value["repair"].__setitem__("cleanupRegisteredAfterCreate", False)),
    ("platform redeploy", lambda value: value["repair"].__setitem__("platformReconciliationRequired", True)),
    ("runtime success overstated", lambda value: value["incident"].__setitem__("liveAcceptancePassed", True)),
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
    validate_live_script(
        live.replace('timespec="microseconds"', 'timespec="nanoseconds"', 1)
    )
except ContractError:
    pass
else:
    raise ContractError("Nanosecond source mutation was accepted")

try:
    validate_live_script(
        live.replace(
            'EVENT_NAMES+=("${name}")',
            'EVENT_NAMES+=("${name}")\n  # registered before create',
            1,
        ).replace("kubectl create -f -", "kubectl apply -f -", 1)
    )
except ContractError:
    pass
else:
    raise ContractError("Missing Event create mutation was accepted")

print("v0.11.6.1.2.2 exact six-digit UTC Event MicroTime and post-create cleanup contracts passed.")
print("v0.11.6.1.2.2 nanosecond, local-time, suffix, cleanup-order, redeploy, and overstatement mutations were rejected.")
if closure_contract:
    print("v0.11.6.1.3 local logging closure successor coverage passed.")
PY

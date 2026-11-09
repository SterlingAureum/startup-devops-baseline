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
    require(value.get("schemaVersion") == "v0.11.6.1.1.5", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.1.5", "Bad version")
    require(
        value.get("status") == "offline-implemented-local-live-rerun-required",
        "Bad status",
    )
    require(value.get("predecessor") == "v0.11.6.1.1.4", "Bad predecessor")

    incident = value.get("incident", {})
    for key in (
        "loggingApplicationsHealthy",
        "lokiAndAlloyWorkloadsReady",
        "demoApiStructuredVersionLogObserved",
        "alloyDemoApiTargetsObserved",
        "lokiWritePathObserved",
        "fsnotifyWatcherExhaustionObserved",
        "clusterWideKubernetesApiTailersObserved",
        "structuredMetadataMergedIntoQueryLabelsObserved",
    ):
        require(incident.get(key) is True, f"Incident evidence omitted: {key}")
    require(incident.get("liveAcceptanceReached") is False, "Live acceptance overstated")

    repair = value.get("repair", {})
    require(repair.get("collectedNamespaces") == ["startup-apps"], "Collection scope changed")
    require(repair.get("clusterWidePodTailingEnabled") is False, "Cluster-wide tailing restored")
    for key in (
        "nodeLocalDiscoveryPreserved",
        "kubernetesApiCollectionPreserved",
        "demoApiContentFilteredQuery",
        "podIdentityReadFromReturnedMetadataLabels",
        "podUidRequired",
        "fsnotifyExhaustionRejected",
    ):
        require(repair.get(key) is True, f"Repair requirement disabled: {key}")
    for key in (
        "hostPathRequired",
        "privilegedRequired",
        "hostSysctlMutationRequired",
        "queryLabelApiUsedAsIndexInventory",
    ):
        require(repair.get(key) is False, f"Unsafe repair enabled: {key}")
    require(repair.get("indexedInventoryApi") == "series", "Index inventory API changed")
    require(repair.get("boundedAcceptanceLookbackSeconds") == 5, "Acceptance window changed")

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
        == (
            "0.5.0",
            "v0.11.6.1.1",
            "18.11.3",
            "3.7.6",
            "1.11.0",
            "1.18.0",
            "0.6.0",
            "0.4.0",
        ),
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
        "alloyDaemonSetRolloutRequired",
        "localLiveRerunRequired",
        "seriesIndexedLabelInventoryRequired",
        "structuredMetadataIdentityRequired",
        "fsnotifyExhaustionAbsenceRequired",
        "oldPodLogSurvivesDemoApiReplacementRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    for key in (
        "lokiRolloutRequired",
        "demoApiImageRebuildRequired",
        "demoApiRedeployRequired",
    ):
        require(acceptance.get(key) is False, f"Unnecessary rollout required: {key}")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")
    require(acceptance.get("cleanRoomClosureDeferredTo") == "v0.11.9", "Closure boundary moved")


contract_path = (
    "delivery/contracts/"
    "v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.json"
)
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require(
    (root / "delivery/contracts/v0.11.6.1.1.2-alloy-nonroot-loki-rules-sidecar-runtime-repair.json").is_file(),
    "Missing runtime predecessor contract",
)

alloy_values = read("clusters/local/platform/files/logging/alloy-values.yaml")
discovery = re.search(
    r'(?ms)^      discovery\.kubernetes "pod" \{\n(.*?)^      \}\n\n'
    r'      discovery\.relabel "pod_logs"',
    alloy_values,
)
require(discovery is not None, "Could not isolate Alloy Pod discovery")
discovery_body = discovery.group(1)
for marker in (
    'role = "pod"',
    'names = ["startup-apps"]',
    'field = "spec.nodeName=" + coalesce(sys.env("HOSTNAME"), constants.hostname)',
):
    require(marker in discovery_body, f"Bounded discovery marker missing: {marker}")
require(discovery_body.count("namespaces {") == 1, "Alloy discovery namespace block changed")
require("startup-apps" in alloy_values, "Application namespace scope missing")
for forbidden in (
    'names = ["argocd"]',
    'names = ["observability"]',
    'names = ["kube-system"]',
    "hostPath:",
    "privileged: true",
    "sysctl -w",
):
    require(forbidden not in alloy_values, f"Unsafe or expanded collection found: {forbidden}")

live = read("scripts/check-local-logging-runtime.sh")
for marker in (
    "/loki/api/v1/query_range",
    "/loki/api/v1/series",
    'match[]={environment="local",cluster="startup-devops-local",namespace="startup-apps",application="demo-api",container="demo-api"}',
    '\\"message\\":\\"http_request_completed\\"',
    '\\"http.route\\":\\"/version\\"',
    '.stream.pod_name == $pod',
    '(.stream.pod_uid // "") != ""',
    "query_fsnotify_errors",
    "failed to create fsnotify watcher: too many open files",
    "time.time_ns() - 5_000_000_000",
    "Loki Series API returned no demo-api stream",
    "Indexed Loki stream labels are exactly bounded",
    "pre-replacement demo-api log disappeared",
):
    require(marker in live, f"Live acceptance repair marker missing: {marker}")
require(
    'python3 - "${WORK_DIR}/labels.json"' not in live,
    "Live checker still treats the label API as indexed inventory",
)
require(
    '.["kubernetes.pod.name"]' not in live,
    "Live checker still expects Pod identity in application JSON",
)

focused = read("scripts/validate-v0.11.6.1.1-local-loki-alloy-pod-logs.sh")
for marker in (
    'names = ["startup-apps"]',
    '"/loki/api/v1/series"',
    '"query_fsnotify_errors"',
    "for name_literal in (",
    "def normalized_yaml_list_item(raw: str) -> str:",
    "v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.json",
):
    require(marker in focused, f"Focused validator lacks successor regression marker: {marker}")

for relative, marker in (
    (
        "scripts/validate-ci-quality-gates.sh",
        "validate-v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.sh",
    ),
    ("CHANGELOG.md", "## v0.11.6.1.1.5"),
    (
        ".github/CODEOWNERS",
        "/delivery/contracts/v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.json @SterlingAureum",
    ),
    (
        ".github/CODEOWNERS",
        "/scripts/validate-v0.11.6.1.1.5-application-scoped-alloy-loki-acceptance-repair.sh @SterlingAureum",
    ),
    (
        ".github/CODEOWNERS",
        "/docs/V0.11.6.1.1.5_APPLICATION_SCOPED_ALLOY_LOKI_ACCEPTANCE_REPAIR.md @SterlingAureum",
    ),
):
    require(marker in read(relative), f"Integration marker missing: {relative}: {marker}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("cluster-wide tailing", lambda value: value["repair"].__setitem__("clusterWidePodTailingEnabled", True)),
    ("system namespace", lambda value: value["repair"]["collectedNamespaces"].append("kube-system")),
    ("host sysctl", lambda value: value["repair"].__setitem__("hostSysctlMutationRequired", True)),
    ("label API inventory", lambda value: value["repair"].__setitem__("indexedInventoryApi", "labels")),
    ("fsnotify accepted", lambda value: value["repair"].__setitem__("fsnotifyExhaustionRejected", False)),
    ("runtime success overstated", lambda value: value["incident"].__setitem__("liveAcceptanceReached", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.1.1.5 application-scoped Alloy and Loki acceptance repair passed.")
print("v0.11.6.1.1.5 cluster-wide, system-namespace, sysctl, label-API, fsnotify, and overstatement mutations were rejected.")
PY

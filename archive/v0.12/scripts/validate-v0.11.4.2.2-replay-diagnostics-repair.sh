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
    return json.loads(read(relative))


def markers(relative: str, required: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in required:
        require(marker in text, f"{relative}: missing marker {marker}")
    return text


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.4.2.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.2.2", "Bad version")
    require(value.get("predecessor") == "v0.11.4.2.1", "Bad predecessor")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    incident = value.get("incident", {})
    for name in (
        "neutralFeatureBaselineObserved",
        "demoApiSourceMetricsAbsent",
        "capacitySignalsHealthy",
        "fiveDashboardsHealthy",
        "freshLocalImageRedeployRecoveredTelemetry",
    ):
        require(incident.get(name) is True, f"Incident fact missing: {name}")

    cause = value.get("rootCause", {})
    for name in (
        "neutralBaselineClearsLocalImageParameters",
        "neutralBaselineIsReplayStartOnly",
        "exactFeatureImageRedeployRequiredBeforeAcceptance",
    ):
        require(cause.get(name) is True, f"Root cause weakened: {name}")
    require(cause.get("resourceWarmupWasNotRootCause") is True, "Warm-up misclassified")
    require(cause.get("dashboardOrRecordingRuleWasNotRootCause") is True, "Runtime scope misclassified")

    repair = value.get("repair", {})
    require(repair.get("sharedLibrary") == "scripts/lib/observability-live.sh", "Wrong shared helper")
    require(len(repair.get("liveScripts", [])) == 4, "Live-script set changed")
    for name, flag in repair.items():
        if name not in {"sharedLibrary", "liveScripts"}:
            require(flag is True, f"Repair disabled: {name}")

    unchanged = value.get("unchanged", {})
    require(unchanged.get("observabilityChartVersion") == "0.3.1", "Chart version changed")
    require(unchanged.get("observabilityApplicationVersion") == "v0.11.4.2.1", "App version changed")
    require(unchanged.get("dashboardCount") == 5, "Dashboard count changed")
    for name, flag in unchanged.items():
        if name not in {"observabilityChartVersion", "observabilityApplicationVersion", "dashboardCount"}:
            require(flag is False, f"Boundary expanded: {name}")

    acceptance = value.get("acceptance", {})
    for name, flag in acceptance.items():
        if name != "offlineValidator":
            require(flag is True, f"Acceptance weakened: {name}")


contract = load_json("delivery/contracts/v0.11.4.2.2-replay-diagnostics-repair.json")
validate_contract(contract)

helper = markers(
    contract["repair"]["sharedLibrary"],
    (
        "observability_generate_demo_api_metrics",
        "observability_assert_prometheus_jobs_up",
        'expression="min(up{job=',
        "(.data.result[0].value[1] | tonumber) >= 1",
        "/api/v1/targets?state=active",
        "lastError",
        "does not expose populated HTTP telemetry",
        "neutral feature baseline is only a replay start state",
    ),
)
require("or vector(0)" not in helper, "Shared helper added a global zero fallback")

for live_script in contract["repair"]["liveScripts"]:
    text = markers(
        live_script,
        (
            "scripts/lib/observability-live.sh",
            "observability_generate_demo_api_metrics",
            "observability_assert_prometheus_jobs_up",
        ),
    )
    require('query_prometheus \'sum(up{job=' not in text, f"Legacy non-empty target check remains: {live_script}")

markers(
    "docs/V0.11.4.2.2_REPLAY_DIAGNOSTICS_REPAIR.md",
    (
        "neutral feature baseline",
        "v0.11.4.2.2-replay-local",
        "build-load-demo-api-image.sh",
        "deploy-local-feature-gitops.sh",
        "lastError",
        "restore-local-feature-baseline.sh",
        "Do not run `restore-local-gitops-head.sh`",
    ),
)
semantic_repair_successor = (root / "delivery/contracts/v0.11.5.1.1-prometheus-target-down-semantics-repair.json").is_file()
actionable_alerts_successor = (root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file()
slo_foundation_successor = (root / "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json").is_file()
burn_rate_successor = (root / "delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json").is_file()
markers(
    "platform/observability/helm/Chart.yaml",
    (
        "version: 0.6.0" if burn_rate_successor else ("version: 0.5.0" if slo_foundation_successor else ("version: 0.4.1" if semantic_repair_successor else ("version: 0.4.0" if actionable_alerts_successor else "version: 0.3.1"))),
        'appVersion: "v0.11.7.1"' if burn_rate_successor else ('appVersion: "v0.11.7.0"' if slo_foundation_successor else ('appVersion: "v0.11.5.1.1"' if semantic_repair_successor else ('appVersion: "v0.11.5.1"' if actionable_alerts_successor else 'appVersion: "v0.11.4.2.1"'))),
    ),
)
markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.2.2 replay diagnostics repair", "validate-v0.11.4.2.2-replay-diagnostics-repair.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/delivery/contracts/v0.11.4.2.2-replay-diagnostics-repair.json @SterlingAureum",
        "/scripts/validate-v0.11.4.2.2-replay-diagnostics-repair.sh @SterlingAureum",
        "/scripts/lib/observability-live.sh @SterlingAureum",
        "/docs/V0.11.4.2.2_REPLAY_DIAGNOSTICS_REPAIR.md @SterlingAureum",
    ),
)

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("zero accepted", lambda value: value["repair"].update(zeroUpRejected=False)),
    ("lastError hidden", lambda value: value["repair"].update(targetLastErrorPrinted=False)),
    ("fresh image optional", lambda value: value["acceptance"].update(freshUniqueLocalImageRequired=False)),
    ("Dashboard changed", lambda value: value["unchanged"].update(dashboardChanged=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case was accepted: {name}")

print("v0.11.4.2.2 replay image transition and Prometheus target diagnostics passed.")
PY

positive_output="$({
  FAKE_UP=1 bash -c '
    source "$1"
    curl() {
      if [[ "$*" == *"/api/v1/query"* ]]; then
        printf '\''{"status":"success","data":{"resultType":"vector","result":[{"metric":{},"value":[0,"%s"]}]}}'\'' "${FAKE_UP}"
      else
        printf '\''{"status":"success","data":{"activeTargets":[]}}'\''
      fi
    }
    observability_assert_prometheus_jobs_up http://prometheus demo-api-stable
  ' _ "${ROOT_DIR}/scripts/lib/observability-live.sh"
} 2>&1)"
grep -q "every discovered Prometheus target is up" <<<"${positive_output}"

if negative_output="$({
  FAKE_UP=0 bash -c '
    source "$1"
    curl() {
      if [[ "$*" == *"/api/v1/query"* ]]; then
        printf '\''{"status":"success","data":{"resultType":"vector","result":[{"metric":{},"value":[0,"%s"]}]}}'\'' "${FAKE_UP}"
      else
        printf '\''{"status":"success","data":{"activeTargets":[{"labels":{"job":"demo-api-stable"},"health":"down","scrapeUrl":"http://10.0.0.2:8080/metrics","lastError":"context deadline exceeded","lastScrape":"2026-08-25T00:00:00Z"}]}}'\''
      fi
    }
    observability_assert_prometheus_jobs_up http://prometheus demo-api-stable
  ' _ "${ROOT_DIR}/scripts/lib/observability-live.sh"
} 2>&1)"; then
  echo "Synthetic up=0 target was accepted." >&2
  exit 1
fi
grep -q "up=0" <<<"${negative_output}"
grep -q "context deadline exceeded" <<<"${negative_output}"

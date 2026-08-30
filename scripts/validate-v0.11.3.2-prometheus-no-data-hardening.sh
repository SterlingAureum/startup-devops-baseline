#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys


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


def validate_contract(value: dict, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.3.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.3.2", "Bad version")
    require(value.get("status") == "offline-implemented-live-failure-observed", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    incident = value.get("incident", {})
    require(incident.get("rolloutRevision") == 22, "Incident revision changed")
    require(incident.get("analysisPhase") == "Error", "Incident phase changed")
    require(incident.get("consecutiveErrors") == 5, "Incident error count changed")
    require(incident.get("message") == "reflect: slice index out of range", "Incident message changed")
    require(
        incident.get("rootCause") == "empty-prometheus-vector-indexed-without-length-guard",
        "Incident root cause changed",
    )

    chart = value.get("chart", {})
    require(chart.get("previousVersion") == "0.5.0", "Previous Chart version changed")
    require(chart.get("version") == "0.5.1", "Chart patch version missing")
    require(chart.get("appVersionChanged") is False, "Application version boundary changed")

    analysis = value.get("analysis", {})
    require(analysis.get("query") == 'sum(up{job="demo-api-canary"})', "Prometheus query changed")
    require(analysis.get("initialDelay") == "60s", "Initial delay changed")
    require(analysis.get("interval") == "15s", "Interval changed")
    require(analysis.get("count") == 2, "Measurement count changed")
    require(analysis.get("failureLimit") == 1, "Failure limit changed")
    require(
        analysis.get("successCondition") == "len(result) > 0 && result[0] >= 1",
        "No-data guard changed",
    )
    require(analysis.get("emptyResultPolicy") == "failed-closed", "No-data policy is not fail-closed")
    require(analysis.get("emptyResultAccepted") is False, "Empty result is accepted")
    require(analysis.get("unsafeIndexingRejected") is True, "Unsafe indexing is allowed")
    require(analysis.get("existingPreAnalysisPause") == "60s", "Existing warm-up pause changed")

    boundaries = value.get("boundaries", {})
    require(all(boundaries.get(key) is False for key in boundaries), "Patch boundary expanded")

    acceptance = value.get("acceptance", {})
    for key in (
        "offlineValidatorRequired",
        "cleanHeadToFeatureReplayRequired",
        "latestAnalysisRunMustBeSuccessful",
        "retryMayNotReplaceCleanReplay",
        "headRestorationRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance gate disabled: {key}")
    require(acceptance.get("successfulMeasurementsRequired") == 2, "Successful measurement gate changed")


contract = json.loads(read("delivery/contracts/v0.11.3.2-prometheus-no-data-hardening.json"))
validate_contract(contract)

chart = read("apps/demo-api/helm/Chart.yaml")
values = read("apps/demo-api/helm/values.yaml")
template = read("apps/demo-api/helm/templates/analysis-template.yaml")

structured_logging_successor = (
    root / "delivery/contracts/v0.11.6.1.0-structured-demo-api-logging-runtime.json"
).is_file()
tracing_successor = (
    root / "delivery/contracts/v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.json"
).is_file()
require(
    ("version: 0.7.0" if tracing_successor else ("version: 0.6.0" if structured_logging_successor else "version: 0.5.1")) in chart,
    "Unexpected successor-aware Chart version",
)
require(
    ('appVersion: "0.5.0"' if tracing_successor else ('appVersion: "0.4.0"' if structured_logging_successor else 'appVersion: "0.3.0"')) in chart,
    "Unexpected successor-aware application version",
)
require("canaryTargetUp:" in values, "Canary metric values missing")
require("initialDelay: 60s" in values, "No-data warm-up delay missing from values")
require(
    'initialDelay: {{ $canaryTargetUp.initialDelay | default "60s" }}' in template,
    "Configurable metric initialDelay missing",
)
require(
    "successCondition: len(result) > 0 && result[0] >= 1" in template,
    "Safe Prometheus vector condition missing",
)
require('sum(up{job="demo-api-canary"})' in template, "Canary target query changed")

for forbidden in (
    "successCondition: result[0] >= 1",
    "successCondition: len(result) == 0 ||",
    "successCondition: len(result) == 0 &&",
    "OR on() vector(1)",
):
    require(forbidden not in template, f"Unsafe no-data behavior present: {forbidden}")

for relative, markers in (
    (
        ".github/CODEOWNERS",
        (
            "/delivery/contracts/v0.11.3.2-prometheus-no-data-hardening.json @SterlingAureum",
            "/scripts/validate-v0.11.3.2-prometheus-no-data-hardening.sh @SterlingAureum",
            "/docs/V0.11.3.2_PROMETHEUS_NO_DATA_HARDENING.md @SterlingAureum",
        ),
    ),
    (
        "scripts/validate-ci-quality-gates.sh",
        ("validate-v0.11.3.2-prometheus-no-data-hardening.sh",),
    ),
    (
        "docs/V0.11.3.2_PROMETHEUS_NO_DATA_HARDENING.md",
        (
            "reflect: slice index out of range",
            "len(result) > 0",
            "initialDelay",
            "Clean Replay",
        ),
    ),
    (
        "docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md",
        ("initialDelay: 60s", "len(result) > 0 && result[0] >= 1", "no-data"),
    ),
):
    text = read(relative)
    for marker in markers:
        require(marker in text, f"{relative}: missing marker {marker!r}")

for name, mutate in (
    ("empty accepted", lambda v: v["analysis"].update(emptyResultAccepted=True)),
    ("unsafe indexing", lambda v: v["analysis"].update(unsafeIndexingRejected=False)),
    ("delay removed", lambda v: v["analysis"].update(initialDelay="0s")),
    ("success condition weakened", lambda v: v["analysis"].update(successCondition="result[0] >= 1")),
    ("query changed", lambda v: v["boundaries"].update(prometheusQueryChanged=True)),
    ("clean replay optional", lambda v: v["acceptance"].update(cleanHeadToFeatureReplayRequired=False)),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.3.2 Prometheus no-data hardening validation passed.")
PY

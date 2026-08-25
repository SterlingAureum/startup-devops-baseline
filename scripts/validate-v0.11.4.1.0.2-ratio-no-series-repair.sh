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


def markers(relative: str, required: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in required:
        require(marker in text, f"{relative}: missing marker {marker}")
    return text


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.11.4.1.0.2", "Bad schemaVersion")
    require(value.get("version") == "v0.11.4.1.0.2", "Bad version")
    require(value.get("predecessor") == "v0.11.4.1.0.1", "Bad predecessor")
    require(value.get("status") == "offline-implemented-local-live-required", "Bad status")
    if check_files:
        require((root / value.get("designDocument", "")).is_file(), "Missing design document")

    chart = value.get("chart", {})
    require(chart.get("previousVersion") == "0.2.0", "Wrong predecessor Chart")
    require(chart.get("version") == "0.2.1", "Wrong repair Chart")
    require(chart.get("applicationVersion") == "v0.11.4.1.0.2", "Wrong application version")

    http = value.get("httpSuccessRatio", {})
    require(http.get("totalAnchor") == "demo_api:http_requests:rate5m", "Wrong HTTP anchor")
    require(http.get("optionalNumerator") == "demo_api:http_errors:rate5m", "Wrong HTTP numerator")
    require(http.get("trafficWithoutErrorsResult") == 1, "No-error HTTP result changed")
    require(http.get("trafficWithErrorsCalculated") is True, "HTTP errors ignored")
    require(http.get("noTrafficProducesSeries") is False, "No-traffic HTTP series synthesized")

    dependency = value.get("dependencySuccessRatio", {})
    require(dependency.get("failuresWithoutSuccessResult") == 0, "Failure-only dependency result changed")
    require(dependency.get("mixedOutcomesCalculated") is True, "Mixed dependency outcomes ignored")
    require(dependency.get("noDependencyChecksProduceSeries") is False, "No-check dependency series synthesized")

    policy = value.get("missingDataPolicy", {})
    require(policy.get("requestOrDependencyAnchoredFillRequired") is True, "Anchored fill disabled")
    require(policy.get("globalVectorZeroForbidden") is True, "Global zero fallback accepted")
    require(policy.get("missingTargetRemainsNoData") is True, "Missing target hidden")
    require(policy.get("inactiveWorkloadRemainsNoData") is True, "Inactive workload hidden")

    boundaries = value.get("boundaries", {})
    require(boundaries.get("recordingRuleExpressionsChanged") is True, "Expression repair omitted")
    require(boundaries.get("chartMetadataChanged") is True, "Chart successor omitted")
    for name, flag in boundaries.items():
        if name not in {"recordingRuleExpressionsChanged", "chartMetadataChanged"}:
            require(flag is False, f"Repair boundary expanded: {name}")
    require(all(value.get("acceptance", {}).values()), "Acceptance requirement disabled")


def rule_segment(text: str, name: str) -> str:
    marker = f"        - record: {name}\n"
    require(marker in text, f"Missing recording rule: {name}")
    segment = text.split(marker, 1)[1]
    return segment.split("\n        - record:", 1)[0]


def http_success_ratio(request_rate: float | None, error_rate: float | None) -> float | None:
    if request_rate is None:
        return None
    bounded_error_rate = 0.0 if error_rate is None else error_rate
    return 1.0 - bounded_error_rate / max(request_rate, 0.000000001)


def dependency_success_ratio(total_rate: float | None, success_rate: float | None) -> float | None:
    if total_rate is None:
        return None
    bounded_success_rate = 0.0 if success_rate is None else success_rate
    return bounded_success_rate / max(total_rate, 0.000000001)


contract = json.loads(read("delivery/contracts/v0.11.4.1.0.2-ratio-no-series-repair.json"))
validate_contract(contract)
operator_dashboards_successor = (root / "delivery/contracts/v0.11.4.1.1-operator-dashboards.json").is_file()
capacity_signal_successor = (root / "delivery/contracts/v0.11.4.2.0-capacity-signal-foundation.json").is_file()
capacity_dashboard_successor = (root / "delivery/contracts/v0.11.4.2.1-capacity-efficiency-dashboard.json").is_file()
actionable_alerts_successor = (root / "delivery/contracts/v0.11.5.1-actionable-alerts-runbooks.json").is_file()

if actionable_alerts_successor:
    expected_views_chart_version = "version: 0.4.0"
    expected_views_app_version = 'appVersion: "v0.11.5.1"'
elif capacity_dashboard_successor:
    expected_views_chart_version = "version: 0.3.1"
    expected_views_app_version = 'appVersion: "v0.11.4.2.1"'
elif capacity_signal_successor:
    expected_views_chart_version = "version: 0.3.0"
    expected_views_app_version = 'appVersion: "v0.11.4.2.0"'
elif operator_dashboards_successor:
    expected_views_chart_version = "version: 0.2.2"
    expected_views_app_version = 'appVersion: "v0.11.4.1.1"'
else:
    expected_views_chart_version = "version: 0.2.1"
    expected_views_app_version = 'appVersion: "v0.11.4.1.0.2"'

markers(
    "platform/observability/helm/Chart.yaml",
    (
        "name: startup-devops-observability-views",
        expected_views_chart_version,
        expected_views_app_version,
    ),
)
rules = read("platform/observability/helm/templates/recording-rules.yaml")
http = rule_segment(rules, "demo_api:http_success_ratio:rate5m")
dependency = rule_segment(rules, "demo_api:dependency_success_ratio:rate5m")

require("demo_api:http_errors:rate5m" in http, "HTTP error numerator missing")
require("0 * demo_api:http_requests:rate5m" in http, "HTTP request-anchored zero fill missing")
require(re.search(r"demo_api:http_errors:rate5m\s+or\s+0 \* demo_api:http_requests:rate5m", http), "HTTP union changed")
require('outcome="success"' in dependency, "Dependency success numerator missing")
require('outcome=~"success|failure"' in dependency, "Dependency total anchor missing")
require("0 * sum by" in dependency, "Dependency total-anchored zero fill missing")
require("or vector(0)" not in rules, "Global missing-data zero fallback added")
require(rules.count("        - record:") == 9, "Recording-rule name set changed")

require(http_success_ratio(10.0, None) == 1.0, "HTTP no-error scenario is not healthy")
require(http_success_ratio(10.0, 2.0) == 0.8, "HTTP mixed scenario is wrong")
require(http_success_ratio(None, None) is None, "HTTP no-traffic scenario creates data")
require(dependency_success_ratio(10.0, None) == 0.0, "Dependency failure-only scenario is not zero")
require(dependency_success_ratio(10.0, 8.0) == 0.8, "Dependency mixed scenario is wrong")
require(dependency_success_ratio(None, None) is None, "Dependency no-check scenario creates data")

diagnostics = markers(
    "scripts/check-observability-views.sh",
    (
        "print_query_cardinality()",
        'demo_api:http_requests:rate5m',
        'demo_api:http_errors:rate5m',
        'demo_api:dependency_checks:rate5m',
        "increase RULE_WARMUP_SECONDS only when the source rate is also empty",
    ),
)
require("Generate demo-api traffic and increase RULE_WARMUP_SECONDS if" not in diagnostics, "Misleading generic warm-up hint returned")

historical_v040 = markers(
    "scripts/validate-v0.11.4.0-grafana-recording-rules.sh",
    (
        "v0.11.4.1.0.2-ratio-no-series-repair.json",
        'expected_views_chart_version = "version: 0.2.1"',
        'expected_views_app_version = \'appVersion: "v0.11.4.1.0.2"\'',
    ),
)
require("ratio_no_series_successor" in historical_v040, "v0.11.4.0 successor branch missing")
markers(
    "scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh",
    (
        "v0.11.4.1.0.2-ratio-no-series-repair.json",
        'expected_views_chart_version = "version: 0.2.1"',
        'expected_views_app_version = \'appVersion: "v0.11.4.1.0.2"\'',
    ),
)

markers(
    "scripts/validate-ci-quality-gates.sh",
    ("Validating v0.11.4.1.0.2 ratio no-series repair", "validate-v0.11.4.1.0.2-ratio-no-series-repair.sh"),
)
markers(
    ".github/CODEOWNERS",
    (
        "/delivery/contracts/v0.11.4.1.0.2-ratio-no-series-repair.json @SterlingAureum",
        "/scripts/validate-v0.11.4.1.0.2-ratio-no-series-repair.sh @SterlingAureum",
        "/docs/V0.11.4.1.0.2_RATIO_NO_SERIES_REPAIR.md @SterlingAureum",
    ),
)

for monitoring_path in (
    "clusters/local/platform/templates/monitoring.yaml",
    "clusters/aws/base/platform/monitoring.yaml",
):
    require("revisionHistoryLimit" not in read(monitoring_path), f"Grafana history changed in {monitoring_path}")

negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("global zero", lambda value: value["missingDataPolicy"].update(globalVectorZeroForbidden=False)),
    ("no-traffic series", lambda value: value["httpSuccessRatio"].update(noTrafficProducesSeries=True)),
    ("no-check series", lambda value: value["dependencySuccessRatio"].update(noDependencyChecksProduceSeries=True)),
    ("Grafana mutation", lambda value: value["boundaries"].update(grafanaDeploymentChanged=True)),
    ("ReplicaSet cleanup", lambda value: value["boundaries"].update(replicaSetCleanupAdded=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case accepted: {name}")

print("v0.11.4.1.0.2 bounded ratio semantics, diagnostics, and boundaries passed.")
PY

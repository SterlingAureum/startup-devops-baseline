#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Validating v0.11.2 application and platform telemetry"

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
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON in {relative}: {exc}") from exc
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


EXPECTED_METRICS = [
    {
        "name": "demo_api_http_requests_total",
        "type": "counter",
        "labels": ["method", "route", "status_class"],
    },
    {
        "name": "demo_api_http_request_duration_seconds",
        "type": "histogram",
        "labels": ["method", "route"],
    },
    {
        "name": "demo_api_dependency_checks_total",
        "type": "counter",
        "labels": ["dependency", "outcome"],
    },
    {
        "name": "demo_api_dependency_check_duration_seconds",
        "type": "histogram",
        "labels": ["dependency"],
    },
]

EXPECTED_TARGET_LABELS = [
    "service_name",
    "service_version",
    "deployment_environment_name",
    "platform_release_id",
    "platform_source_commit",
    "container_image_digest",
]


def validate_contract(contract: dict[str, Any], check_files: bool = True) -> None:
    require(contract.get("schemaVersion") == "v0.11.2", "Bad schemaVersion")
    require(contract.get("version") == "v0.11.2", "Bad version")
    require(contract.get("status") == "offline-implemented", "Bad status")
    require(contract.get("liveAcceptanceClaimed") is False, "Live acceptance is claimed")

    if check_files:
        for field in (
            "foundationContract",
            "metricsFoundationContract",
            "deliveryContract",
            "designDocument",
        ):
            value = contract.get(field)
            require(isinstance(value, str) and (root / value).is_file(), f"Missing {field}")

    telemetry = contract.get("applicationTelemetry")
    require(isinstance(telemetry, dict), "Missing applicationTelemetry")
    require(telemetry.get("owner") == "apps/demo-api/helm", "Application does not own telemetry")
    require(
        telemetry.get("serviceMonitor") == "apps/demo-api/helm/templates/servicemonitor.yaml",
        "Unexpected ServiceMonitor path",
    )
    require(telemetry.get("honorLabels") is False, "Application may override trusted target labels")
    require(telemetry.get("jobLabelSource") == "__meta_kubernetes_service_name", "Job identity changed")
    require(
        telemetry.get("requiredJobs") == ["demo-api", "demo-api-stable", "demo-api-canary"],
        "Required job set changed",
    )
    require(
        telemetry.get("legacyCanaryQuery") == 'sum(up{job="demo-api-canary"})',
        "Legacy Canary query changed",
    )

    require(contract.get("metrics") == EXPECTED_METRICS, "Metric schema changed")

    dimensions = contract.get("boundedDimensions")
    require(isinstance(dimensions, dict), "Missing boundedDimensions")
    require(dimensions.get("method") == ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER"], "Method labels are unbounded")
    require(dimensions.get("route") == ["/", "/health", "/ready", "/db/health", "/version", "/metrics", "__unmatched__"], "Route labels are unbounded")
    require(dimensions.get("status_class") == ["2xx", "3xx", "4xx", "5xx", "unknown"], "Status labels are unbounded")
    require(dimensions.get("dependency") == ["postgresql"], "Dependency labels are unbounded")
    require(dimensions.get("outcome") == ["success", "failure", "disabled"], "Outcome labels are unbounded")

    release = contract.get("releaseCorrelation")
    require(isinstance(release, dict), "Missing releaseCorrelation")
    require(release.get("releaseIdTemplate") == "demo-api-{sourceCommit12}-{imageDigest12}", "Release ID changed")
    require(release.get("authoritativeContractPath") == "delivery/contracts/demo-api.json", "Wrong delivery authority")
    require(release.get("source") == "target-pod-annotations", "Release identity is not Pod-derived")
    require(release.get("serviceMetadataIsAuthoritativeDuringCanary") is False, "Service metadata may mislabel Canary targets")
    require(release.get("requiredTargetLabels") == EXPECTED_TARGET_LABELS, "Target label set changed")
    fallback = release.get("localFallback")
    require(isinstance(fallback, dict) and fallback.get("productionClaim") is False, "Local fallback claims production")
    require(fallback.get("sourceCommit") == "local-unavailable", "Local source fallback changed")
    require(fallback.get("imageDigest") == "local-unpinned", "Local image fallback changed")

    limits = contract.get("scrapeLimits")
    require(
        limits == {
            "interval": "15s",
            "scrapeTimeout": "10s",
            "sampleLimit": 50000,
            "targetLimit": 10,
            "labelLimit": 100,
            "labelNameLengthLimit": 128,
            "labelValueLengthLimit": 512,
        },
        "Scrape limits changed",
    )

    platform = contract.get("platformTelemetry")
    require(isinstance(platform, dict), "Missing platformTelemetry")
    for metric in (
        "kube_pod_status_ready",
        "kube_pod_container_resource_requests",
        "node_cpu_seconds_total",
        "node_memory_MemAvailable_bytes",
        "prometheus_tsdb_head_series",
    ):
        require(metric in platform.get("requiredMetrics", []), f"Missing platform metric: {metric}")
    require(platform.get("specializedControllerMonitorsAdded") is False, "Specialized controller scope expanded")

    forbidden = contract.get("forbiddenDimensions")
    require(isinstance(forbidden, list), "Missing forbiddenDimensions")
    for value in ("raw-url", "url-query", "request-body", "authorization-header", "database-parameter", "user-identifier", "exception-message"):
        require(value in forbidden, f"Missing forbidden dimension: {value}")

    automation = contract.get("automationBoundary")
    require(isinstance(automation, dict), "Missing automationBoundary")
    for field in (
        "releaseOrchestratorChanged",
        "imagePublishWorkflowChanged",
        "promotionWorkflowChanged",
        "rollbackWorkflowChanged",
        "automaticEnvironmentCreation",
        "automaticProductionWrite",
    ):
        require(automation.get(field) is False, f"Automation boundary expanded: {field}")
    require(automation.get("productionApprovalPreserved") is True, "Production approval removed")

    acceptance = contract.get("acceptance")
    require(isinstance(acceptance, dict), "Missing acceptance")
    require(acceptance.get("offlineValidationRequired") is True, "Offline validation is optional")
    require(acceptance.get("localLiveValidationRequiredBeforeTag") is True, "Local live validation is optional")
    require(acceptance.get("awsDevLiveValidationRequiredBeforeFinalV011Acceptance") is True, "AWS live proof removed")


def require_markers(relative: str, markers: tuple[str, ...]) -> str:
    text = read(relative)
    for marker in markers:
        require(marker in text, f"{relative}: missing marker {marker!r}")
    return text


def validate_repository() -> None:
    delivery = load_json("delivery/contracts/demo-api.json")
    require(
        delivery.get("application", {}).get("releaseIdTemplate") == "demo-api-{sourceCommit12}-{imageDigest12}",
        "Authoritative delivery release ID changed",
    )

    service_monitor = require_markers(
        "apps/demo-api/helm/templates/servicemonitor.yaml",
        (
            "kind: ServiceMonitor",
            "honorLabels: false",
            "sampleLimit:",
            "targetLimit:",
            "labelLimit:",
            "- __meta_kubernetes_service_name",
            "targetLabel: job",
            "- __meta_kubernetes_pod_annotation_platform_startup_dev_release_id",
            "targetLabel: platform_release_id",
            "- __meta_kubernetes_pod_annotation_platform_startup_dev_source_commit",
            "targetLabel: platform_source_commit",
            "- __meta_kubernetes_pod_annotation_platform_startup_dev_image_digest",
            "targetLabel: container_image_digest",
        ),
    )
    require("__meta_kubernetes_service_annotation_platform_startup_dev_release_id" not in service_monitor, "Service metadata is incorrectly authoritative")
    require(
        re.search(
            r"(?ms)^spec:\n"
            r"\s+sampleLimit:.*\n"
            r"\s+targetLimit:.*\n"
            r"\s+labelLimit:.*\n"
            r"\s+labelNameLengthLimit:.*\n"
            r"\s+labelValueLengthLimit:.*\n"
            r".*?\s+endpoints:\n"
            r"\s+- port: http",
            service_monitor,
        )
        is not None,
        "ServiceMonitor scrape limits must be spec-level CRD fields",
    )

    helpers = require_markers(
        "apps/demo-api/helm/templates/_helpers.tpl",
        (
            'define "demo-api.releaseId"',
            'printf "demo-api-%s-%s"',
            'trunc 12 $sourceCommit',
            'trunc 12 $digestHex',
            'printf "demo-api-local-%s"',
            "platform.startup.dev/release-id:",
            'default "local-unavailable"',
            'default "local-unpinned"',
        ),
    )
    require("platform.startup.dev/release-id" in helpers, "Pod release annotation missing")

    values = require_markers(
        "apps/demo-api/helm/values.yaml",
        (
            "telemetry:",
            "serviceMonitor:",
            "interval: 15s",
            "scrapeTimeout: 10s",
            "sampleLimit: 50000",
            "targetLimit: 10",
            "labelLimit: 100",
        ),
    )
    require("rawUrl" not in values and "rawPath" not in values, "Raw request dimension configured")

    main = require_markers(
        "apps/demo-api/src/main.py",
        (
            '"demo_api_http_requests_total"',
            '["method", "route", "status_class"]',
            '"demo_api_http_request_duration_seconds"',
            '"demo_api_dependency_checks_total"',
            '["dependency", "outcome"]',
            '"demo_api_dependency_check_duration_seconds"',
            'return candidate if candidate in ALLOWED_ROUTES else "__unmatched__"',
            'return candidate if candidate in ALLOWED_METHODS else "OTHER"',
        ),
    )
    for unsafe in ("request.url.path", "request.url.query", "Authorization", "DATABASE_URL"):
        require(unsafe not in main, f"Application metric path contains unsafe input: {unsafe}")
    require("demo_api_requests_total" not in main, "Legacy request metric remains active")

    tests = require_markers(
        "apps/demo-api/tests/test_main.py",
        (
            'route="__unmatched__"',
            'status_class="4xx"',
            "token=sensitive",
            "secret-password",
            'outcome="success"',
            'outcome="failure"',
        ),
    )
    require("assertNotIn" in tests, "Sensitive metric negative tests missing")

    structured_logging_successor = (
        root / "delivery/contracts/v0.11.6.1.0-structured-demo-api-logging-runtime.json"
    ).is_file()
    chart = require_markers(
        "apps/demo-api/helm/Chart.yaml",
        (
            "version: 0.6.0" if structured_logging_successor else "version: 0.5.1",
            'appVersion: "0.4.0"' if structured_logging_successor else 'appVersion: "0.3.0"',
        ),
    )
    require("version: 0.4.0" not in chart, "Chart version was not advanced")

    for relative in (
        "clusters/local/platform/templates/monitoring.yaml",
        "clusters/aws/base/platform/monitoring.yaml",
    ):
        monitoring = read(relative)
        require("demo-api-compatibility" not in monitoring, f"{relative}: compatibility monitor remains")
        require("additionalServiceMonitors:" not in monitoring, f"{relative}: application telemetry remains platform-owned")
        require("serviceMonitorSelector: {}" in monitoring, f"{relative}: ServiceMonitor discovery restricted")
        require("serviceMonitorNamespaceSelector: {}" in monitoring, f"{relative}: namespace discovery restricted")

    require_markers(
        "docs/V0.11.2_APPLICATION_PLATFORM_TELEMETRY.md",
        (
            "Pod-derived release correlation",
            "Local Live Validation",
            "AWS Validation Boundary",
            "v0.11.3",
        ),
    )
    require_markers(
        ".github/CODEOWNERS",
        (
            "/delivery/contracts/v0.11.2-application-platform-telemetry.json @SterlingAureum",
            "/scripts/validate-v0.11.2-application-platform-telemetry.sh @SterlingAureum",
            "/docs/V0.11.2_APPLICATION_PLATFORM_TELEMETRY.md @SterlingAureum",
        ),
    )


contract = load_json("delivery/contracts/v0.11.2-application-platform-telemetry.json")
validate_contract(contract)
validate_repository()


negative_cases: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("live evidence claim", lambda value: value.update(liveAcceptanceClaimed=True)),
    ("Service-owned release identity", lambda value: value["releaseCorrelation"].update(source="service-annotations")),
    ("release ID drift", lambda value: value["releaseCorrelation"].update(releaseIdTemplate="demo-api-{environment}-{sourceCommit12}")),
    ("unbounded route", lambda value: value["boundedDimensions"]["route"].append("raw-url")),
    ("missing label limit", lambda value: value["scrapeLimits"].update(labelLimit=0)),
    ("automatic production write", lambda value: value["automationBoundary"].update(automaticProductionWrite=True)),
    ("Grafana scope expansion", lambda value: value["platformTelemetry"].update(specializedControllerMonitorsAdded=True)),
]
for name, mutate in negative_cases:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Negative case was accepted: {name}")

print("v0.11.2 application and platform telemetry validation passed.")
PY

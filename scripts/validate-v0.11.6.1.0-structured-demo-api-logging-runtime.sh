#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command_name in helm python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 -m py_compile \
  "${ROOT_DIR}/apps/demo-api/src/logging_config.py" \
  "${ROOT_DIR}/apps/demo-api/src/main.py" \
  "${ROOT_DIR}/apps/demo-api/src/server.py" \
  "${ROOT_DIR}/apps/demo-api/tests/test_logging.py" \
  "${ROOT_DIR}/apps/demo-api/tests/test_main.py"

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
    try:
        value = json.loads(read(relative))
    except json.JSONDecodeError as error:
        raise ContractError(f"Invalid JSON in {relative}: {error}") from error
    require(isinstance(value, dict), f"Expected JSON object: {relative}")
    return value


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.11.6.1.0", "Bad schemaVersion")
    require(value.get("version") == "v0.11.6.1.0", "Bad version")
    require(
        value.get("status") == "offline-implemented-local-image-rerun-required",
        "Bad status",
    )
    require(value.get("predecessor") == "v0.11.6.0", "Bad predecessor")

    scope = value.get("scope", {})
    for key in (
        "structuredLoggingImplemented",
        "releaseIdentityProjectionImplemented",
        "localImageRebuildRequired",
    ):
        require(scope.get(key) is True, f"Required scope disabled: {key}")
    for key in (
        "loggingBackendImplemented",
        "logCollectorImplemented",
        "kubernetesEventCollectionImplemented",
        "tracingImplemented",
    ):
        require(scope.get(key) is False, f"Scope expanded prematurely: {key}")

    foundation = load_json(
        "delivery/contracts/v0.11.6.0-centralized-logging-minimal-tracing-foundation.json"
    )
    require(
        value.get("requiredFields") == foundation.get("logSchema", {}).get("requiredFields"),
        "Required logging fields diverged from v0.11.6.0",
    )
    require(
        value.get("httpFields")
        == [
            "http.request.method",
            "http.route",
            "http.response.status_code",
            "duration_ms",
            "outcome",
        ],
        "HTTP fields changed",
    )

    projection = value.get("identityProjection", {})
    require(projection.get("source") == "pod-annotations", "Identity source changed")
    require(
        projection.get("mechanism") == "kubernetes-downward-api",
        "Identity projection mechanism changed",
    )
    require(projection.get("deploymentAndRolloutParityRequired") is True, "Workload parity disabled")
    require(projection.get("applicationRecomputationForbidden") is True, "Application may recalculate release identity")

    request_logging = value.get("requestLogging", {})
    require(request_logging.get("routeTemplateOnly") is True, "Raw route logging allowed")
    require(request_logging.get("unmatchedRoute") == "__unmatched__", "Unmatched route changed")
    require(
        request_logging.get("successfulQuietRoutes") == ["/health", "/ready", "/metrics"],
        "Quiet route set changed",
    )
    require(request_logging.get("failedQuietRoutesStillLogged") is True, "Failed probes became silent")

    security = value.get("security", {})
    for key in (
        "rawPathLogged",
        "queryStringLogged",
        "requestHeadersLogged",
        "exceptionMessageExported",
        "requiredIdentityOverrideAllowed",
    ):
        require(security.get(key) is False, f"Unsafe logging behavior enabled: {key}")

    runtime = value.get("runtime", {})
    require(runtime.get("entrypoint") == "python -m src.server", "Entrypoint changed")
    require(runtime.get("uvicornAccessLogEnabled") is False, "Duplicate access log enabled")
    require(runtime.get("uvicornUsesJsonFormatter") is True, "Uvicorn formatter changed")
    require(runtime.get("multilineRecordAllowed") is False, "Multiline records allowed")
    require(runtime.get("fileLoggingEnabled") is False, "Application file logging enabled")
    require(runtime.get("loggingSidecarRequired") is False, "Logging sidecar introduced")

    versions = value.get("versions", {})
    require(versions.get("demoApiChart") == "0.6.0", "demo-api Chart version changed")
    require(versions.get("demoApiApp") == "0.4.0", "demo-api appVersion changed")
    require(versions.get("localPlatformChart") == "0.4.1", "Local platform Chart changed")
    require(versions.get("localPlatformApp") == "v0.11.5.2.0", "Local platform appVersion changed")
    require(versions.get("observabilityViewsChart") == "0.4.1", "Observability Chart changed")
    require(versions.get("observabilityViewsApp") == "v0.11.5.1.1", "Observability appVersion changed")
    require(all(item is False for item in value.get("unchanged", {}).values()), "Unchanged boundary expanded")

    acceptance = value.get("acceptance", {})
    for key in (
        "completeQualityGateRequired",
        "localClusterRerunRequired",
        "imageRebuildRequired",
        "demoApiRedeployRequired",
    ):
        require(acceptance.get(key) is True, f"Acceptance requirement disabled: {key}")
    require(acceptance.get("monitoringRedeployRequired") is False, "Monitoring redeploy added")
    require(acceptance.get("lokiQueryRequired") is False, "Loki accepted before deployment")
    require(acceptance.get("formalAwsExecutionDeferredTo") == "v0.11.8", "AWS boundary moved")


contract_path = "delivery/contracts/v0.11.6.1.0-structured-demo-api-logging-runtime.json"
contract = load_json(contract_path)
validate_contract(contract)
require((root / contract["designDocument"]).is_file(), "Missing design document")
require(
    (root / "delivery/contracts/v0.11.6.0-centralized-logging-minimal-tracing-foundation.json").is_file(),
    "Missing predecessor contract",
)

logging_source = read("apps/demo-api/src/logging_config.py")
for marker in (
    "class JsonLineFormatter",
    '"service.name"',
    '"service.version"',
    '"deployment.environment.name"',
    '"platform.release.id"',
    '"platform.source.commit"',
    '"container.image.digest"',
    '"unhandled_exception"',
    "separators=(\",\", \":\")",
):
    require(marker in logging_source, f"Structured formatter lacks marker: {marker}")
require("record.getMessage()" in logging_source, "Bounded normal message handling missing")
require("if record.exc_info" in logging_source, "Exception redaction boundary missing")
require("if key not in payload" in logging_source, "Required identity override guard missing")

main_source = read("apps/demo-api/src/main.py")
for marker in (
    'QUIET_SUCCESS_ROUTES = frozenset({"/health", "/ready", "/metrics"})',
    '"http_request_completed"',
    '"http.request.method"',
    '"http.route"',
    '"http.response.status_code"',
    '"duration_ms"',
    '"outcome"',
):
    require(marker in main_source, f"Request logger lacks marker: {marker}")
for forbidden in (
    "request.query_params",
    "request.headers",
    "request.cookies",
    "request.url.query",
    "await request.body",
    "str(request.url)",
):
    require(forbidden not in main_source, f"Request logger reads forbidden input: {forbidden}")

server = read("apps/demo-api/src/server.py")
require("configure_logging()" in server, "Server does not configure JSON logging")
require("access_log=False" in server, "Uvicorn access logging is not disabled")
require("log_config=None" in server, "Uvicorn does not retain the process formatter")
require(
    'CMD ["python", "-m", "src.server"]' in read("apps/demo-api/Dockerfile"),
    "Container entrypoint changed",
)

helpers = read("apps/demo-api/helm/templates/_helpers.tpl")
for variable, annotation in contract["identityProjection"]["environmentVariables"].items():
    require(f"- name: {variable}" in helpers, f"Missing projected variable: {variable}")
    require(f"metadata.annotations['{annotation}']" in helpers, f"Missing projected annotation: {annotation}")
for template in (
    "apps/demo-api/helm/templates/deployment.yaml",
    "apps/demo-api/helm/templates/rollout.yaml",
):
    require(
        'include "demo-api.deliveryEnvironment"' in read(template),
        f"Delivery identity projection missing from {template}",
    )

chart = read("apps/demo-api/helm/Chart.yaml")
require("version: 0.6.0" in chart and 'appVersion: "0.4.0"' in chart, "demo-api Chart identity changed")
local_chart = read("clusters/local/platform/Chart.yaml")
logging_runtime_successor = (root / "delivery/contracts/v0.11.6.1.1-local-loki-alloy-pod-logs.json").is_file()
events_runtime_successor = (root / "delivery/contracts/v0.11.6.1.2-kubernetes-events-grafana-loki.json").is_file()
require(
    ("version: 0.6.0" if events_runtime_successor else ("version: 0.5.0" if logging_runtime_successor else "version: 0.4.1")) in local_chart
    and ('appVersion: "v0.11.6.1.2"' if events_runtime_successor else ('appVersion: "v0.11.6.1.1"' if logging_runtime_successor else 'appVersion: "v0.11.5.2.0"')) in local_chart,
    "Local platform runtime changed",
)
views_chart = read("platform/observability/helm/Chart.yaml")
require("version: 0.4.1" in views_chart and 'appVersion: "v0.11.5.1.1"' in views_chart, "Observability runtime changed")

for relative, marker in (
    ("scripts/check-demo-api-structured-logs.sh", "v0.11.6.1.0 demo-api structured JSON logging runtime acceptance passed."),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.1.0-structured-demo-api-logging-runtime.sh"),
    ("docs/V0.11.6.1.0_STRUCTURED_DEMO_API_LOGGING_RUNTIME.md", "The next increment is v0.11.6.1.1"),
    ("apps/demo-api/README.md", "v0.11.6.1.0 runtime"),
    ("README.md", "v0.11.6.1.0-structured-demo-api-logging-runtime"),
    ("docs/ROADMAP.md", "v0.11.6.1.0"),
    ("docs/OBSERVABILITY.md", "v0.11.6.1.0"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.1.0"),
    ("CHANGELOG.md", "## v0.11.6.1.0"),
    (".github/CODEOWNERS", "/scripts/check-demo-api-structured-logs.sh @SterlingAureum"),
):
    require(marker in read(relative), f"Integration marker missing: {relative}")

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("raw path logging", lambda value: value["security"].__setitem__("rawPathLogged", True)),
    ("query logging", lambda value: value["security"].__setitem__("queryStringLogged", True)),
    ("identity override", lambda value: value["security"].__setitem__("requiredIdentityOverrideAllowed", True)),
    ("duplicate access log", lambda value: value["runtime"].__setitem__("uvicornAccessLogEnabled", True)),
    ("premature Loki", lambda value: value["scope"].__setitem__("loggingBackendImplemented", True)),
    ("premature tracing", lambda value: value["scope"].__setitem__("tracingImplemented", True)),
]
for name, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation was accepted: {name}")

print("v0.11.6.1.0 structured JSON schema, release identity, request noise, and security contracts passed.")
print("v0.11.6.1.0 raw-request, identity-override, duplicate-access-log, premature-Loki, and tracing mutations were rejected.")
PY

echo "==> Rendering Deployment and Rollout identity projection"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  >"${WORK_DIR}/rollout.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --set rollout.enabled=false \
  >"${WORK_DIR}/deployment.yaml"

python3 - "${WORK_DIR}/rollout.yaml" "${WORK_DIR}/deployment.yaml" <<'PY'
from pathlib import Path
import sys


for manifest_path in sys.argv[1:]:
    manifest = Path(manifest_path).read_text()
    for variable, annotation in (
        ("PLATFORM_RELEASE_ID", "platform.startup.dev/release-id"),
        ("PLATFORM_SOURCE_COMMIT", "platform.startup.dev/source-commit"),
        ("CONTAINER_IMAGE_DIGEST", "platform.startup.dev/image-digest"),
    ):
        if manifest.count(f"- name: {variable}") != 1:
            raise SystemExit(f"{variable} is not rendered exactly once in {manifest_path}")
        if manifest.count(f"fieldPath: metadata.annotations['{annotation}']") != 1:
            raise SystemExit(f"{annotation} is not rendered exactly once in {manifest_path}")
PY

bash -n "${ROOT_DIR}/scripts/check-demo-api-structured-logs.sh"

echo "v0.11.6.1.0 structured demo-api logging runtime validation passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])

def read(relative: str) -> str:
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"Missing file: {relative}")
    return path.read_text()

contract_path = "delivery/contracts/v0.11.6.2.3-local-minimal-tracing-closure.json"
contract = json.loads(read(contract_path))

def validate(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.6.2.3"
    assert value["predecessor"] == "v0.11.6.2.2.4"
    scope = value["scope"]
    assert scope["environment"] == "local"
    assert not any(scope[key] for key in (
        "runtimeComponentAdded", "applicationCodeChanged", "applicationImageChanged",
        "awsRuntimeChanged", "productionDnsResilienceAdded",
    ))
    state = value["acceptedState"]
    assert all(state[key] for key in (
        "applicationAutoInstrumentation", "collectorPrivate", "tempoPrivate",
        "lokiLogCorrelation", "grafanaDerivedField", "localOverlayTracingEnabled",
    ))
    assert not any(state[key] for key in (
        "baseChartTracingEnabled", "traceIdIndexedAsLokiLabel",
        "spanIdIndexedAsLokiLabel", "postgresqlTraceRequired",
    ))
    assert state["otlpProtocol"] == "http/protobuf"
    acceptance = value["acceptance"]
    assert acceptance["realCorrelationRuns"] == 2
    assert acceptance["syntheticCollectorReplacementInvoked"] is False
    assert acceptance["runtimeMutationAllowed"] is False
    assert all(acceptance[key] for key in (
        "uniqueTracePerRunRequired", "privateServicePreflightRequired",
        "rolloutHealthPreflightRequired",
    ))
    assert all(value["deferred"].values())

validate(contract)
assert (root / contract["designDocument"]).is_file()
for predecessor in (
    "delivery/contracts/v0.11.6.2.0-demo-api-opentelemetry-tracing-contract.json",
    "delivery/contracts/v0.11.6.2.1-private-local-otel-collector-tempo-runtime.json",
    "delivery/contracts/v0.11.6.2.1.1-synthetic-otlp-json-encoding-diagnostics-repair.json",
    "delivery/contracts/v0.11.6.2.2-real-demo-api-trace-log-correlation.json",
    "delivery/contracts/v0.11.6.2.2.4-loki-gateway-stale-upstream-repair.json",
):
    assert (root / predecessor).is_file(), predecessor

live = read("scripts/check-local-tracing-end-to-end.sh")
assert live.count('"${ROOT_DIR}/scripts/check-local-demo-api-trace-correlation.sh"') == 2
for marker in (
    "kubectl config current-context", ".status.phase == \"Healthy\"",
    '.spec.type == "ClusterIP"', "observability-otel-collector-cluster-only",
    "observability-tempo-cluster-only", "observability-logs-cluster-only",
    "grafana-cluster-only", "get ingress --all-namespaces",
    "run 1 of 2", "run 2 of 2", "v0.11.6.2.3 local minimal tracing closure passed",
):
    assert marker in live, marker
for forbidden in (
    "check-local-tracing-runtime.sh", "check-demo-api-tracing-contract.sh",
    "kubectl delete", "kubectl patch", "rollout restart", "argo rollouts promote",
):
    assert forbidden not in live, forbidden

assert re.search(r"tracing:\s+enabled: false", read("apps/demo-api/helm/values.yaml"))
assert re.search(r"tracing:\s+enabled: true", read("clusters/local/platform/values.yaml"))
alloy = read("clusters/local/platform/files/logging/alloy-values.yaml")
label_keep = alloy.split("stage.label_keep {", 1)[1].split("}", 1)[0]
assert "trace_id" not in label_keep and "span_id" not in label_keep

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.6.2.3-local-minimal-tracing-closure.sh"),
    ("README.md", "v0.11.6.2.3-local-minimal-tracing-closure"),
    ("docs/OBSERVABILITY.md", "active v0.11.6.2.3 local minimal tracing closure"),
    ("docs/ROADMAP.md", "v0.11.6.2.3 closes"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.6.2.3 closes"),
    ("CHANGELOG.md", "## v0.11.6.2.3"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
    (".github/CODEOWNERS", "/scripts/check-local-tracing-end-to-end.sh @SterlingAureum"),
):
    assert marker in read(relative), f"{relative}: {marker}"

mutations = (
    lambda value: value["scope"].update(awsRuntimeChanged=True),
    lambda value: value["acceptedState"].update(baseChartTracingEnabled=True),
    lambda value: value["acceptedState"].update(traceIdIndexedAsLokiLabel=True),
    lambda value: value["acceptance"].update(realCorrelationRuns=1),
    lambda value: value["acceptance"].update(runtimeMutationAllowed=True),
    lambda value: value["deferred"].update(dynamicGatewayDns=False),
)
for mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden tracing-closure mutation was accepted")

print("v0.11.6.2.3 ordered read-only local tracing closure and negative boundary contracts passed.")
PY

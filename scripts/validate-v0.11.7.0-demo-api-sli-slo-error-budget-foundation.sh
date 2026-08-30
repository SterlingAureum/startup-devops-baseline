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

contract_path = "delivery/contracts/v0.11.7.0-demo-api-sli-slo-error-budget-foundation.json"
contract = json.loads(read(contract_path))

def validate(value: dict) -> None:
    assert value["schemaVersion"] == value["version"] == "v0.11.7.0"
    assert value["predecessor"] == "v0.11.6.2.3.1"
    assert not any(value["scope"][key] for key in (
        "applicationCodeChanged", "applicationImageChanged", "rolloutGateChanged",
        "alertRuleAdded", "awsRuntimeChanged",
    ))
    slo = value["slo"]
    assert slo["rollingWindow"] == "30d"
    assert slo["eligibleMethod"] == "GET" and slo["eligibleRoute"] == "/version"
    assert slo["availabilityObjective"] == 0.999
    assert slo["availabilityBadStatusClass"] == "5xx"
    assert slo["latencyObjective"] == 0.99
    assert slo["latencyThresholdSeconds"] == 0.5
    assert slo["identityDimensions"] == [
        "deployment_environment_name", "service_name", "service_version",
        "platform_release_id",
    ]
    assert slo["healthAndMetricsRoutesExcluded"] is True
    assert slo["missingTrafficTreatedAsHealthy"] is False
    assert value["recordingRules"]["count"] == 8
    assert value["recordingRules"]["burnRateRulesAdded"] is False
    assert value["dashboard"]["uid"] == "startup-devops-demo-api-slo"
    assert value["dashboard"]["editable"] is False
    assert value["dashboard"]["recordingRulesOnly"] is True
    assert value["dashboard"]["panelCount"] == 4
    assert value["acceptance"]["productionThirtyDayAchievementClaimed"] is False
    assert value["deferred"] == {
        "multiWindowBurnRateAlerts": "v0.11.7.1",
        "sloAwareRolloutAnalysis": "v0.11.7.2",
        "sloClosure": "v0.11.7.3",
        "awsEvidence": "v0.11.8",
    }

validate(contract)
assert (root / contract["designDocument"]).is_file()
assert (root / "delivery/contracts/v0.11.6.2.3.1-demo-api-runtime-artifact-preflight-repair.json").is_file()

chart = read("platform/observability/helm/Chart.yaml")
assert "version: 0.5.0" in chart and 'appVersion: "v0.11.7.0"' in chart
values = read("platform/observability/helm/values.yaml")
for marker in (
    "rollingWindow: 30d", "method: GET", "route: /version",
    "availabilityObjective: 0.999", "latencyObjective: 0.99",
    "latencyThresholdSeconds: 0.5",
):
    assert marker in values, marker

rules = read("platform/observability/helm/templates/slo-recording-rules.yaml")
expected_rules = [
    "demo_api:slo_http_requests:rate30d",
    "demo_api:slo_http_5xx:rate30d",
    "demo_api:slo_availability:ratio30d",
    "demo_api:slo_availability_error_budget_remaining:ratio30d",
    "demo_api:slo_latency_requests:rate30d",
    "demo_api:slo_latency_good:rate30d",
    "demo_api:slo_latency:ratio30d",
    "demo_api:slo_latency_error_budget_remaining:ratio30d",
]
assert re.findall(r"^\s*- record:\s*(\S+)\s*$", rules, re.MULTILINE) == expected_rules
for marker in (
    "demo-api.slo.v0.11.7.0", 'status_class="5xx"',
    "demo_api_http_request_duration_seconds_bucket", "clamp_min", "clamp_max",
    "subf 1.0 .Values.slo.availabilityObjective",
    "subf 1.0 .Values.slo.latencyObjective",
):
    assert marker in rules, marker
assert rules.count("clamp_min(\n              clamp_max(") == 2
for forbidden in (
    "- alert:", "or vector(0)", "request_id", "trace_id", "span_id",
    "pod_name", "container_id", "raw_url", "/health", "/ready", "/metrics",
):
    assert forbidden not in rules, forbidden

dashboard = json.loads(read("platform/observability/helm/dashboards/slo-overview.json"))
assert dashboard["uid"] == contract["dashboard"]["uid"]
assert dashboard["title"] == contract["dashboard"]["title"]
assert dashboard["editable"] is False and len(dashboard["panels"]) == 4
assert [item["name"] for item in dashboard["templating"]["list"]] == ["environment", "release"]
for panel in dashboard["panels"]:
    assert panel["datasource"]["uid"] == "prometheus"
    assert all("demo_api:slo_" in target["expr"] for target in panel["targets"])

def remaining_budget(good_ratio: float, objective: float) -> float:
    return max(0.0, min(1.0, 1.0 - ((1.0 - good_ratio) / (1.0 - objective))))

assert remaining_budget(1.0, 0.999) == 1.0
assert abs(remaining_budget(0.9995, 0.999) - 0.5) < 1e-9
assert remaining_budget(0.999, 0.999) == 0.0
assert remaining_budget(0.998, 0.999) == 0.0
assert abs(remaining_budget(0.995, 0.99) - 0.5) < 1e-9
assert remaining_budget(0.99, 0.99) == 0.0

live = read("scripts/check-local-slo-foundation.sh")
for marker in (
    "service/demo-api-stable", "/version", "for _ in $(seq 1 12)",
    "demo-api-slo-recording-rules", "observability-dashboard-slo-overview",
    "startup-devops-demo-api-slo", "RULE_WARMUP_SECONDS",
):
    assert marker in live, marker
for forbidden in (
    "kubectl patch", "kubectl delete", "argo rollouts promote", "rollout restart",
    "check-local-tracing-end-to-end.sh",
):
    assert forbidden not in live, forbidden

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.0-demo-api-sli-slo-error-budget-foundation.sh"),
    ("README.md", "v0.11.7.0-demo-api-sli-slo-error-budget-foundation"),
    ("docs/OBSERVABILITY.md", "v0.11.7.0"),
    ("docs/ROADMAP.md", "v0.11.7.0"),
    ("docs/V0.11_OBSERVABILITY_SRE_DESIGN.md", "v0.11.7.0"),
    ("CHANGELOG.md", "## v0.11.7.0"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
):
    assert marker in read(relative), f"{relative}: {marker}"

for mutate in (
    lambda value: value["scope"].update(rolloutGateChanged=True),
    lambda value: value["scope"].update(alertRuleAdded=True),
    lambda value: value["slo"].update(eligibleRoute="/health"),
    lambda value: value["slo"].update(missingTrafficTreatedAsHealthy=True),
    lambda value: value["recordingRules"].update(burnRateRulesAdded=True),
    lambda value: value["acceptance"].update(productionThirtyDayAchievementClaimed=True),
):
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate)
    except AssertionError:
        continue
    raise SystemExit("Forbidden SLO-foundation mutation was accepted")

print("v0.11.7.0 demo-api SLI/SLO, error-budget, Dashboard, and negative boundary contracts passed.")
PY

for command_name in helm; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

echo "==> Linting and rendering the observability views Chart"
helm lint "${ROOT_DIR}/platform/observability/helm" >/dev/null
rendered="$(helm template observability-views "${ROOT_DIR}/platform/observability/helm" \
  --namespace observability)"

grep -q 'name: demo-api-slo-recording-rules' <<<"${rendered}"
grep -q 'demo_api:slo_availability:ratio30d' <<<"${rendered}"
grep -q 'demo_api:slo_latency:ratio30d' <<<"${rendered}"
grep -q 'name: observability-dashboard-slo-overview' <<<"${rendered}"
if grep -A120 'name: demo-api-slo-recording-rules' <<<"${rendered}" | grep -q -- '- alert:'; then
  echo "SLO foundation rendered an alert rule." >&2
  exit 1
fi

echo "v0.11.7.0 observability Chart lint and render acceptance passed."

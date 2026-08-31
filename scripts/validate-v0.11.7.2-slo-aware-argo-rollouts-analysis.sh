#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture_dir="$(mktemp -d)"
trap 'rm -rf -- "${fixture_dir}"' EXIT

python3 - "${ROOT_DIR}" "${fixture_dir}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
fixture_dir = Path(sys.argv[2])
def read(relative):
    path = root / relative
    assert path.is_file(), relative
    return path.read_text()

contract_path = "delivery/contracts/v0.11.7.2-slo-aware-argo-rollouts-analysis.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.2"
assert contract["predecessor"] == "v0.11.7.1.3"
assert contract["candidate"] == {
    "method": "GET", "route": "/version", "window": "5m",
    "minimumRequests": 20, "maximumAvailabilityBurnRate": 14.4,
    "maximumLatencyBurnRate": 14.4, "releaseIdArgument": "expected-release-id",
    "releaseIdExactMatchRequired": True,
}
assert contract["analysis"]["prometheusMetricCount"] == 6
assert contract["analysis"]["executionWeights"] == [20, 50]
assert contract["analysis"]["noDataPasses"] is False
assert contract["analysis"]["queryErrorPasses"] is False
assert not contract["scope"]["automaticGitRollbackAdded"]
assert not contract["scope"]["automaticRolloutUndoAdded"]
assert not contract["scope"]["awsRuntimeChanged"]

chart = read("apps/demo-api/helm/Chart.yaml")
repair_successor = (root / "delivery/contracts/v0.11.7.2.1-slo-analysis-promql-live-race-repair.json").is_file()
assert ("version: 0.8.1" if repair_successor else "version: 0.8.0") in chart and 'appVersion: "0.5.0"' in chart
values = read("apps/demo-api/helm/values.yaml")
for marker in (
    "minimumRequests: 20", "maximumFastBurnRate: 14.4",
    "minimumStableBudgetRemaining: 0", "window: 5m",
): assert marker in values
assert values.count("templateName: demo-api-canary-health") == 2

analysis = read("apps/demo-api/helm/templates/analysis-template.yaml")
expected_metrics = [
    "canary-prometheus-target-up",
    "canary-minimum-eligible-requests",
    "canary-availability-error-budget-burn-rate",
    "canary-latency-error-budget-burn-rate",
    "stable-availability-error-budget-remaining",
    "stable-latency-error-budget-remaining",
]
for marker in expected_metrics + [
    "platform_release_id=\"{{ `{{ args.expected-release-id }}` }}\"",
    'job="demo-api-canary"', 'job="demo-api-stable"',
    'method="GET"', 'route="/version"', "len(result) > 0",
]: assert marker in analysis, marker
for forbidden in (
    'platform_release_id=~', 'job=~"demo-api', "len(result) == 0 ||",
    "kubectl argo rollouts undo", "git revert", "alertstate",
): assert forbidden not in analysis

rollout = read("apps/demo-api/helm/templates/rollout.yaml")
assert "name: expected-release-id" in rollout
assert "platform.startup.dev/release-id" in rollout

def burn_rate(bad_fraction, objective): return bad_fraction / (1 - objective)
def gate(samples, availability_bad, latency_bad, stable_availability, stable_latency):
    return (
        samples >= 20 and burn_rate(availability_bad, 0.999) <= 14.4
        and burn_rate(latency_bad, 0.99) <= 14.4
        and stable_availability > 0 and stable_latency > 0
    )
assert gate(20, 0, 0, 1, 1)
assert not gate(19, 0, 0, 1, 1)
assert not gate(20, 0.02, 0, 1, 1)
assert not gate(20, 0, 0.15, 1, 1)
assert not gate(20, 0, 0, 0, 1)
assert not gate(20, 0, 0, 1, 0)

live = read("scripts/check-local-slo-aware-rollout-analysis.sh")
for marker in (
    "ANALYSIS_RUN_FIXTURE", "expected-release-id", "demo-api-stable",
    "demo-api-canary", "TRAFFIC_REQUESTS", 'phase == "Successful"',
): assert marker in live
for forbidden in ("rollouts promote", "rollouts abort", "kubectl patch", "kubectl delete", "git push"):
    assert forbidden not in live

metric_results = [{"name": name, "phase": "Successful"} for name in expected_metrics]
success = {
    "metadata": {"name": "demo-api-canary-health-fixture"},
    "spec": {"args": [{"name": "expected-release-id", "value": "demo-api-local-fixture"}]},
    "status": {"phase": "Successful", "metricResults": metric_results},
}
(fixture_dir / "success.json").write_text(json.dumps(success))
failed = json.loads(json.dumps(success))
failed["status"]["phase"] = "Failed"
failed["status"]["metricResults"][1]["phase"] = "Failed"
(fixture_dir / "failed.json").write_text(json.dumps(failed))

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.2-slo-aware-argo-rollouts-analysis.sh"),
    ("README.md", "v0.11.7.2-slo-aware-argo-rollouts-analysis"),
    ("docs/OBSERVABILITY.md", "v0.11.7.2"),
    ("docs/ROADMAP.md", "v0.11.7.2"),
    ("CHANGELOG.md", "## v0.11.7.2"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.2 SLO-aware candidate, stable-budget, fail-closed, and human-governance contracts passed.")
PY

EXPECTED_RELEASE_ID=demo-api-local-fixture \
ANALYSIS_RUN_FIXTURE="${fixture_dir}/success.json" \
  "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh" >/dev/null

if EXPECTED_RELEASE_ID=demo-api-local-fixture \
  ANALYSIS_RUN_FIXTURE="${fixture_dir}/failed.json" \
  "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh" >"${fixture_dir}/failed.log" 2>&1; then
  echo "Failed AnalysisRun fixture unexpectedly passed." >&2
  exit 1
fi
grep -F 'SLO-aware AnalysisRun identity, phase, or metric results are invalid.' "${fixture_dir}/failed.log" >/dev/null

command -v helm >/dev/null 2>&1 || { echo "Required command not found: helm" >&2; exit 1; }
helm lint "${ROOT_DIR}/apps/demo-api/helm" >/dev/null
rendered="$(helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" --namespace startup-apps)"
grep -q "helm.sh/chart: demo-api-$([ -f "${ROOT_DIR}/delivery/contracts/v0.11.7.2.1-slo-analysis-promql-live-race-repair.json" ] && printf '0.8.1' || printf '0.8.0')" <<<"${rendered}"
[ "$(grep -c '^    - name: canary-.*\|^    - name: stable-.*-error-budget-remaining' <<<"${rendered}")" -eq 6 ]
[ "$(grep -c 'templateName: demo-api-canary-health' <<<"${rendered}")" -eq 2 ]
grep -q 'name: expected-release-id' <<<"${rendered}"
grep -q 'platform_release_id="{{ args.expected-release-id }}"' <<<"${rendered}"

echo "v0.11.7.2 Demo API Chart lint, render, AnalysisRun fixtures, and metric inventory passed."

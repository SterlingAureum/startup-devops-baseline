#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
def read(relative):
    path = root / relative
    assert path.is_file(), relative
    return path.read_text()

contract_path = "delivery/contracts/v0.11.7.1-multi-window-burn-rate-alerts.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.1"
assert contract["predecessor"] == "v0.11.7.0.1"
assert not any(contract["scope"].values())
assert contract["slo"]["windows"] == ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]
assert contract["slo"]["thresholds"] == {"fastPage": 14.4, "sustainedPage": 6, "slowTicket": 3, "longTicket": 1}
assert contract["slo"]["requiresLongAndShortWindow"] is True
assert contract["slo"]["missingTrafficTreatedAsHealthy"] is False
assert contract["recordingRules"] == {"badRatioCount": 14, "burnRateCount": 14, "identityDimensionsPreserved": True}

chart = read("platform/observability/helm/Chart.yaml")
assert "version: 0.6.0" in chart and 'appVersion: "v0.11.7.1"' in chart
values = read("platform/observability/helm/values.yaml")
for marker in ("fastPageThreshold: 14.4", "sustainedPageThreshold: 6", "slowTicketThreshold: 3", "longTicketThreshold: 1"):
    assert marker in values

rules = read("platform/observability/helm/templates/slo-burn-rate-recording-rules.yaml")
assert "demo-api.slo.burn-rate.v0.11.7.1" in rules
assert "range .Values.slo.burnRate.windows" in rules
for marker in (
    "demo_api:slo_availability_bad:ratio{{ .name }}",
    "demo_api:slo_availability_burn_rate:ratio{{ .name }}",
    "demo_api:slo_latency_bad:ratio{{ .name }}",
    "demo_api:slo_latency_burn_rate:ratio{{ .name }}",
    "and on (deployment_environment_name, service_name, service_version, platform_release_id)",
    "subf 1.0 $.Values.slo.availabilityObjective",
    "subf 1.0 $.Values.slo.latencyObjective",
): assert marker in rules, marker
for forbidden in ("or vector(0)", "pod_name", "container_id", "trace_id", "request_id", "- alert:"):
    assert forbidden not in rules

alerts = read("platform/observability/helm/templates/slo-burn-rate-alerts.yaml")
alert_names = re.findall(r"(?m)^\s*- alert:\s*(\S+)\s*$", alerts)
assert alert_names == contract["alerts"]["names"]
for pair in (("ratio5m", "ratio1h", "fastPageThreshold"), ("ratio30m", "ratio6h", "sustainedPageThreshold"), ("ratio2h", "ratio1d", "slowTicketThreshold"), ("ratio6h", "ratio3d", "longTicketThreshold")):
    assert all(item in alerts for item in pair)
assert alerts.count("severity: critical") == 2 and alerts.count("severity: warning") == 2
assert alerts.count("runbook_url:") == 4
for name in alert_names:
    slug = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower().replace("demo-api-", "demo-api-")
assert all((root / "docs/runbooks/alerts" / filename).is_file() for filename in (
    "demo-api-availability-error-budget-fast-burn.md",
    "demo-api-availability-error-budget-slow-burn.md",
    "demo-api-latency-error-budget-fast-burn.md",
    "demo-api-latency-error-budget-slow-burn.md",
))

dashboard = json.loads(read("platform/observability/helm/dashboards/slo-overview.json"))
assert dashboard["uid"] == "startup-devops-demo-api-slo" and len(dashboard["panels"]) == 6
assert all("demo_api:slo_" in target["expr"] for panel in dashboard["panels"] for target in panel["targets"])
assert any(panel["title"] == "Availability Error-budget Burn Rate" for panel in dashboard["panels"])
assert any(panel["title"] == "Latency Error-budget Burn Rate" for panel in dashboard["panels"])

def burn_rate(bad, objective): return bad / (1.0 - objective)
def fast(a5m, a1h, a30m, a6h): return (a5m > 14.4 and a1h > 14.4) or (a30m > 6 and a6h > 6)
def slow(a2h, a1d, a6h, a3d): return (a2h > 3 and a1d > 3) or (a6h > 1 and a3d > 1)
assert abs(burn_rate(0.0144, 0.999) - 14.4) < 1e-9
assert abs(burn_rate(0.06, 0.99) - 6.0) < 1e-9
assert fast(15, 15, 0, 0) and fast(0, 0, 7, 7)
assert not fast(15, 14, 7, 6)
assert slow(4, 4, 0, 0) and slow(0, 0, 2, 2)
assert not slow(4, 3, 2, 1)

live = read("scripts/check-local-slo-burn-rate-alerts.sh")
for marker in ("check-local-slo-foundation.sh", "check-actionable-alerts.sh", "28-rule SLO burn-rate inventory"):
    assert marker in live
for forbidden in ("kubectl patch", "kubectl delete", "rollout restart", "argo rollouts promote"):
    assert forbidden not in live

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.1-multi-window-burn-rate-alerts.sh"),
    ("README.md", "v0.11.7.1-multi-window-burn-rate-alerts"),
    ("docs/V0.11.7.1_MULTI_WINDOW_BURN_RATE_ALERTS.md", "both windows must breach"),
    ("docs/OBSERVABILITY.md", "v0.11.7.1"),
    ("docs/ROADMAP.md", "v0.11.7.1"),
    ("CHANGELOG.md", "## v0.11.7.1"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.1 multi-window burn-rate rules, alerts, Runbooks, Dashboard, and deterministic fixtures passed.")
PY

command -v helm >/dev/null 2>&1 || { echo "Required command not found: helm" >&2; exit 1; }
helm lint "${ROOT_DIR}/platform/observability/helm" >/dev/null
rendered="$(helm template observability-views "${ROOT_DIR}/platform/observability/helm" --namespace observability)"
grep -q 'name: demo-api-slo-burn-rate-recording-rules' <<<"${rendered}"
grep -q 'name: demo-api-slo-burn-rate-alerts' <<<"${rendered}"
[ "$(grep -c -- '- record: demo_api:slo_.*_burn_rate:ratio' <<<"${rendered}")" -eq 14 ]
[ "$(grep -c -- '- record: demo_api:slo_.*_bad:ratio' <<<"${rendered}")" -eq 14 ]
[ "$(grep -c -- '- alert: DemoApi.*ErrorBudget.*Burn' <<<"${rendered}")" -eq 4 ]
echo "v0.11.7.1 observability Chart lint and render acceptance passed."

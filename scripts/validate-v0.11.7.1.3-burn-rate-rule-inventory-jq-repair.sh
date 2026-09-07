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

contract_path = "delivery/contracts/v0.11.7.1.3-burn-rate-rule-inventory-jq-repair.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.1.3"
assert contract["predecessor"] == "v0.11.7.1.2"
assert contract["inventory"]["requiredRuleCount"] == 28
assert contract["inventory"]["windows"] == ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]
assert contract["scope"]["liveValidatorChanged"] is True
assert not any(value for key, value in contract["scope"].items() if key != "liveValidatorChanged")

live = read("scripts/check-local-slo-burn-rate-alerts.sh")
for marker in (
    "assert_burn_rate_rule_inventory()",
    "($expected - $records)[]?",
    "the following SLO burn-rate recording rules are not loaded",
    "Prometheus rules response is invalid or unsuccessful",
    "PROMETHEUS_RULES_FIXTURE",
): assert marker in live, marker
assert "all($windows[] as $w;" not in live

windows = contract["inventory"]["windows"]
families = [
    "demo_api:slo_availability_bad:ratio",
    "demo_api:slo_availability_burn_rate:ratio",
    "demo_api:slo_latency_bad:ratio",
    "demo_api:slo_latency_burn_rate:ratio",
]
names = [family + window for window in windows for family in families]
assert len(names) == len(set(names)) == 28

def payload(rule_names, status="success"):
    return {"status": status, "data": {"groups": [{"rules": [
        {"type": "recording", "name": name} for name in rule_names
    ]}]}}

(fixture_dir / "complete.json").write_text(json.dumps(payload(names + ["unrelated:recording:rule"])))
(fixture_dir / "missing.json").write_text(json.dumps(payload(names[1:])))
(fixture_dir / "unsuccessful.json").write_text(json.dumps(payload(names, status="error")))
(fixture_dir / "malformed.json").write_text("{not-json\n")
(fixture_dir / "missing-name.txt").write_text(names[0] + "\n")

for relative, marker in (
    ("scripts/validate-v0.11.7.1-multi-window-burn-rate-alerts.sh", "PROMETHEUS_RULES_FIXTURE"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.1.3-burn-rate-rule-inventory-jq-repair.sh"),
    ("README.md", "v0.11.7.1.3-burn-rate-rule-inventory-jq-repair"),
    ("docs/OBSERVABILITY.md", "v0.11.7.1.3"),
    ("docs/ROADMAP.md", "v0.11.7.1.3"),
    ("CHANGELOG.md", "## v0.11.7.1.3"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.1.3 jq inventory program and repair contracts passed.")
PY

PROMETHEUS_RULES_FIXTURE="${fixture_dir}/complete.json" \
  "${ROOT_DIR}/scripts/check-local-slo-burn-rate-alerts.sh" >/dev/null

for fixture in missing unsuccessful malformed; do
  if PROMETHEUS_RULES_FIXTURE="${fixture_dir}/${fixture}.json" \
    "${ROOT_DIR}/scripts/check-local-slo-burn-rate-alerts.sh" >"${fixture_dir}/${fixture}.log" 2>&1; then
    echo "Invalid ${fixture} fixture unexpectedly passed." >&2
    exit 1
  fi
done

missing_name="$(<"${fixture_dir}/missing-name.txt")"
grep -F -- "- ${missing_name}" "${fixture_dir}/missing.log" >/dev/null
grep -F 'Prometheus rules response is invalid or unsuccessful.' "${fixture_dir}/unsuccessful.log" >/dev/null
grep -F 'Prometheus rules response is invalid or unsuccessful.' "${fixture_dir}/malformed.log" >/dev/null

echo "v0.11.7.1.3 complete, missing-rule, unsuccessful, and malformed fixtures passed."

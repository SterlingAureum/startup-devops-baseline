#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
def read(relative):
    path = root / relative
    assert path.is_file(), relative
    return path.read_text()

contract_path = "delivery/contracts/v0.11.7.1.1-alert-inventory-order-independence-repair.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.1.1"
assert contract["predecessor"] == "v0.11.7.1"
assert contract["scope"] == {
    "historicalValidatorChanged": True,
    "runtimeResourceChanged": False,
    "recordingRuleChanged": False,
    "alertRuleChanged": False,
    "dashboardChanged": False,
    "applicationImageChanged": False,
    "rolloutChanged": False,
    "awsRuntimeChanged": False,
}

historical = read("scripts/validate-v0.11.5.1-actionable-alerts-runbooks.sh")
for marker in (
    "expected_runtime_alerts = template_names + burn_rate_alerts",
    "len(all_template_alerts) == len(expected_runtime_alerts)",
    "len(all_template_alerts) == len(set(all_template_alerts))",
    "set(all_template_alerts) == set(expected_runtime_alerts)",
): assert marker in historical, marker
assert "all_template_alerts == template_names + burn_rate_alerts" not in historical

def validate(actual, expected):
    assert len(actual) == len(expected)
    assert len(actual) == len(set(actual))
    assert set(actual) == set(expected)

predecessor = ["A", "B", "C"]
successor = ["D", "E"]
expected = predecessor + successor
validate(expected, expected)
validate(successor + predecessor, expected)

for candidate in (
    predecessor + ["D", "D"],
    predecessor + ["D", "Unexpected"],
    predecessor + ["D"],
):
    try:
        validate(candidate, expected)
    except AssertionError:
        continue
    raise SystemExit(f"Invalid inventory fixture was accepted: {candidate}")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.1.1-alert-inventory-order-independence-repair.sh"),
    ("README.md", "v0.11.7.1.1-alert-inventory-order-independence-repair"),
    ("docs/OBSERVABILITY.md", "v0.11.7.1.1"),
    ("docs/ROADMAP.md", "v0.11.7.1.1"),
    ("CHANGELOG.md", "## v0.11.7.1.1"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.1.1 order-independent alert inventory and negative fixtures passed.")
PY

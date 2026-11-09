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

contract_path = "delivery/contracts/v0.11.7.1.2-grafana-dashboard-successor-live-validation-repair.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.1.2"
assert contract["predecessor"] == "v0.11.7.1.1"
assert contract["dashboard"] == {
    "uid": "startup-devops-demo-api-slo",
    "predecessorPanelCount": 4,
    "burnRateSuccessorPanelCount": 6,
    "editable": False,
}
assert contract["scope"]["liveValidatorChanged"] is True
assert not any(value for key, value in contract["scope"].items() if key != "liveValidatorChanged")

live = read("scripts/check-local-slo-foundation.sh")
for marker in (
    "EXPECTED_SLO_DASHBOARD_PANEL_COUNT=6",
    "EXPECTED_SLO_DASHBOARD_PANEL_COUNT=4",
    "assert_slo_dashboard_payload()",
    "Grafana SLO Dashboard API returned HTTP",
    "Grafana response body:",
    "Grafana SLO Dashboard UID is missing or unexpected",
    "Grafana SLO Dashboard is editable",
    "panel count mismatch: expected",
): assert marker in live, marker
assert '(.dashboard.panels | length) == 4' not in live

for name, count in (("predecessor", 4), ("successor", 6), ("wrong", 5)):
    payload = {"dashboard": {
        "uid": "startup-devops-demo-api-slo",
        "editable": False,
        "panels": [{"id": index + 1} for index in range(count)],
    }}
    (fixture_dir / f"{name}.json").write_text(json.dumps(payload))

for relative, marker in (
    ("scripts/validate-v0.11.7.1-multi-window-burn-rate-alerts.sh", "EXPECTED_SLO_DASHBOARD_PANEL_COUNT"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.1.2-grafana-dashboard-successor-live-validation-repair.sh"),
    ("README.md", "v0.11.7.1.2-grafana-dashboard-successor-live-validation-repair"),
    ("docs/OBSERVABILITY.md", "v0.11.7.1.2"),
    ("docs/ROADMAP.md", "v0.11.7.1.2"),
    ("CHANGELOG.md", "## v0.11.7.1.2"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.1.2 Grafana successor live-validation contracts passed.")
PY

EXPECTED_SLO_DASHBOARD_PANEL_COUNT=4 \
GRAFANA_DASHBOARD_FIXTURE="${fixture_dir}/predecessor.json" \
  "${ROOT_DIR}/scripts/check-local-slo-foundation.sh" >/dev/null

GRAFANA_DASHBOARD_FIXTURE="${fixture_dir}/successor.json" \
  "${ROOT_DIR}/scripts/check-local-slo-foundation.sh" >/dev/null

if GRAFANA_DASHBOARD_FIXTURE="${fixture_dir}/wrong.json" \
  "${ROOT_DIR}/scripts/check-local-slo-foundation.sh" >"${fixture_dir}/wrong.log" 2>&1; then
  echo "Wrong Dashboard panel count fixture unexpectedly passed." >&2
  exit 1
fi
grep -F 'panel count mismatch: expected 6, found 5' "${fixture_dir}/wrong.log" >/dev/null

echo "v0.11.7.1.2 four-panel predecessor, six-panel successor, and wrong-count fixtures passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
def read(relative):
    path = root / relative
    assert path.is_file(), relative
    return path.read_text()

contract_path = "delivery/contracts/v0.11.7.2.1-slo-analysis-promql-live-race-repair.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.2.1"
assert contract["predecessor"] == "v0.11.7.2"
assert all(contract["repairs"].values())
assert not any(contract["scope"].values())

chart = read("apps/demo-api/helm/Chart.yaml")
assert "version: 0.8.1" in chart and 'appVersion: "0.5.0"' in chart
analysis = read("apps/demo-api/helm/templates/analysis-template.yaml")
assert "clamp_min(\n              clamp_max(" in analysis
assert ")) / {{ subf 1.0 ($sloAware.availabilityObjective" not in analysis

checker = read("scripts/check-local-slo-aware-rollout-analysis.sh")
for marker in (
    'EXPECTED_APPLICATION_VERSION="${EXPECTED_APPLICATION_VERSION:-}"',
    'ROLLOUT_WAIT_SECONDS="${ROLLOUT_WAIT_SECONDS:-300}"',
    "Waiting for Rollout application version",
    "observed_application_version",
    "platform\\.startup\\.dev/application-version",
): assert marker in checker, marker

design = read("docs/V0.11.7.2_SLO_AWARE_ARGO_ROLLOUTS_ANALYSIS.md")
troubleshooting = read(contract["troubleshootingDocument"])
for document in (design, troubleshooting):
    assert "TARGET_REVISION=feature/v0.11-observability-sre-baseline" in document
    assert "EXPECTED_APPLICATION_VERSION=" in document
    assert "APPLICATION_VERSION=" in document
assert design.index("EXPECTED_APPLICATION_VERSION=") < design.index("TARGET_REVISION=")

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.2.1-slo-analysis-promql-live-race-repair.sh"),
    ("README.md", "v0.11.7.2.1-slo-analysis-promql-and-live-race-repair"),
    ("CHANGELOG.md", "## v0.11.7.2.1"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.2.1 identity separation, coordinated traffic, documentation, and boundary contracts passed.")
PY

command -v helm >/dev/null 2>&1 || { echo "Required command not found: helm" >&2; exit 1; }
helm lint "${ROOT_DIR}/apps/demo-api/helm" >/dev/null
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" --namespace startup-apps >"${WORK_DIR}/rendered.yaml"

python3 - "${WORK_DIR}/rendered.yaml" <<'PY'
from pathlib import Path
import sys
import yaml

documents = list(yaml.safe_load_all(Path(sys.argv[1]).read_text()))
template = next(document for document in documents if document and document.get("kind") == "AnalysisTemplate")
metrics = template["spec"]["metrics"]
assert len(metrics) == 6
for metric in metrics:
    query = metric["provider"]["prometheus"]["query"]
    depth = 0
    for character in query:
        if character == "(": depth += 1
        elif character == ")":
            depth -= 1
            assert depth >= 0, f"{metric['name']}: closes before opening"
    assert depth == 0, f"{metric['name']}: unbalanced PromQL parentheses: {depth}"
stable = next(metric for metric in metrics if metric["name"] == "stable-availability-error-budget-remaining")
assert stable["provider"]["prometheus"]["query"].count("clamp_min(") == 2
assert stable["provider"]["prometheus"]["query"].count("clamp_max(") == 1
print("v0.11.7.2.1 rendered six-metric PromQL grouping and Helm acceptance passed.")
PY

bash -n \
  "${ROOT_DIR}/scripts/check-local-slo-aware-rollout-analysis.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.7.2.1-slo-analysis-promql-live-race-repair.sh"

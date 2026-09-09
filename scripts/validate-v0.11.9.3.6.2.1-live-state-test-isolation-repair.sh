#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.2.1-live-state-test-isolation-repair.json"
TEST_FILE="${ROOT_DIR}/scripts/test-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.py"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" "${TEST_FILE}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
test_path = Path(sys.argv[3])
test_source = test_path.read_text()

assert contract["schemaVersion"] == "v0.11.9.3.6.2.1"
assert contract["version"] == "v0.11.9.3.6.2.1"
assert contract["predecessor"] == "v0.11.9.3.6.2"
assert contract["status"] == "live-state-test-isolation-repaired"
assert contract["applicationBaseline"] == {
    "commit": "b01e76c4155536dd85088bda462d28f49cfde07f",
    "requiredAppliedIncrement": "v0.11.9.3.6.2-aws-dev-infrastructure-create-execution",
}
assert contract["observedFailure"] == {
    "validator": "scripts/validate-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.sh",
    "test": "AwsDevInventoryTests.test_complete_ready_preflight_uses_mocked_read_only_discovery",
    "expectedExitCode": 0,
    "observedExitCode": 2,
    "liveTerraformStateAddressCount": 103,
    "mockedActiveClusters": [],
    "classification": "blocked-partial-aws-dev-state",
}
assert contract["rootCause"] == {
    "awsAndGitCommandsMocked": True,
    "filesystemStateReaderMockedBeforeRepair": False,
    "repositoryRootPassedToPreflight": True,
    "environmentDependentTest": True,
    "productionFailure": False,
}
assert contract["repair"] == {
    "modifiedFile": "scripts/test-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.py",
    "mockedFunction": "PREFLIGHT.summarize_state",
    "fixture": "self.empty_state",
    "expectedInterceptedPath": "infra/terraform/aws/environments/dev/terraform.tfstate",
    "interceptionAsserted": True,
    "productionPreflightModified": False,
    "productionClassificationModified": False,
    "liveTerraformStateModified": False,
}
assert all(value is False for value in contract["operationBoundary"].values())
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.3-aws-dev-gitops-bootstrap-execution"

tree = ast.parse(test_source)
state_patch_found = False
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    function = node.func
    if not (
        isinstance(function, ast.Attribute)
        and function.attr == "object"
        and isinstance(function.value, ast.Attribute)
        and function.value.attr == "patch"
    ):
        continue
    if len(node.args) < 2:
        continue
    target, attribute = node.args[:2]
    if not (
        isinstance(target, ast.Name)
        and target.id == "PREFLIGHT"
        and isinstance(attribute, ast.Constant)
        and attribute.value == "summarize_state"
    ):
        continue
    return_value = next(
        (keyword.value for keyword in node.keywords if keyword.arg == "return_value"),
        None,
    )
    if (
        isinstance(return_value, ast.Attribute)
        and isinstance(return_value.value, ast.Name)
        and return_value.value.id == "self"
        and return_value.attr == "empty_state"
    ):
        state_patch_found = True
        break
assert state_patch_found, "mocked ready preflight must replace summarize_state"
assert "summarize_state.assert_called_once_with(ROOT / CHECKER.STATE_PATH)" in test_source

production_path = root / "scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py"
production_source = production_path.read_text()
for marker in (
    '"blocked-partial-aws-dev-state"',
    'state_value = summarize_state(state_path)',
    'return result, 0 if reason is None else 2',
):
    assert marker in production_source

for relative, marker in (
    ("README.md", "v0.11.9.3.6.2.1-live-state-test-isolation-repair"),
    ("CHANGELOG.md", "## v0.11.9.3.6.2.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.2.1"),
    ("docs/V0.11.9.3.6.2.1_LIVE_STATE_TEST_ISOLATION_REPAIR.md", "Live-environment boundary"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.2.1-live-state-test-isolation-repair.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.2.1-live-state-test-isolation-repair.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.2.1 mocked Git, AWS and filesystem state isolation contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TEST_FILE}" \
  AwsDevInventoryTests.test_complete_ready_preflight_uses_mocked_read_only_discovery
PYTHONDONTWRITEBYTECODE=1 python3 "${TEST_FILE}"
bash "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.2-aws-dev-infrastructure-create-execution.sh"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.2.1-live-state-test-isolation-repair.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.2.1-live-state-test-isolation-repair.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.2.1 live-state test isolation repair passed; no live operation was executed."

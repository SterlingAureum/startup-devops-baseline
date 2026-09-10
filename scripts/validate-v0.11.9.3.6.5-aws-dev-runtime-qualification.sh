#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.5-aws-dev-runtime-qualification.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.3-aws-environment-teardown-convergence.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
source = Path(sys.argv[3]).read_text()
tree = ast.parse(source)

assert contract["schemaVersion"] == "v0.11.9.3.6.5"
assert contract["version"] == "v0.11.9.3.6.5"
assert contract["predecessor"] == "v0.11.9.3.6.4.3"
assert contract["status"] == "guarded-aws-dev-runtime-qualification-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "bdda08c018b3bb47378857216fe4dbe6b2848cd2"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.5.1-aws-dev-runtime-qualification-execution"
assert contract["executor"] == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.5-aws-dev-runtime-qualification.py",
    "phases": ["verify", "execute"],
    "requiredBranch": "main",
    "cleanWorktreeRequired": True,
    "headOriginAndRemoteMainMustMatchReviewedCommit": True,
    "awsAccountInput": "EXPECTED_AWS_ACCOUNT_ID",
    "awsAccountCommitted": False,
    "reviewedEndInput": "AWS_DEV_RUNTIME_QUALIFICATION_END_UTC",
    "minimumRemainingMinutes": 15,
    "maximumWindowHours": 8,
}
traffic = contract["approvedTrafficScope"]
assert traffic["paths"] == ["/health", "/ready", "/version"]
assert traffic["warmupRounds"] == 12
assert traffic["finalRounds"] == 6
assert traffic["requestsPerRound"] == 3
assert traffic["maximumRequests"] == 54
assert traffic["prometheusScrapeWaitsSeconds"] == [40, 35]
success = contract["successBoundary"]
assert success == {
    "status": "aws-dev-runtime-qualification-complete",
    "runtimeQualified": True,
    "trafficGenerated": True,
    "boundedRequestCount": 54,
    "progressiveDeliveryPromoted": False,
    "analysisRunExpected": False,
    "faultInjected": False,
    "automaticTeardownExecuted": False,
    "nextAction": "review-separate-aws-dev-runtime-qualification-execution-evidence",
}
assert all(value is False for value in contract["packageProducer"].values())
assert contract["failureBoundary"]["expiredOrInsufficientWindowStopsBeforeTraffic"] is True
assert contract["failureBoundary"]["postTrafficFailureRequiresReview"] is True

for marker in (
    'OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-runtime-qualification"',
    'EXECUTION_CONFIRMATION = "qualify-reviewed-aws-dev-runtime"',
    'AWS_DEV_RUNTIME_QUALIFICATION_END_UTC',
    '["ls-remote", "origin", "refs/heads/main"]',
    'EXPECTED_IMAGE = f"{EXPECTED_IMAGE_REPOSITORY}@{EXPECTED_IMAGE_DIGEST}"',
    '("health", "ready", "version")',
    '"bounded_request_count": traffic["request_count"]',
    '"progressive_delivery_promoted": False',
    '"automatic_teardown_executed": False',
):
    assert marker in source, marker

for forbidden in (
    '"terraform", "apply"',
    '"terraform", "destroy"',
    '"kubectl", "patch"',
    '"kubectl", "delete"',
    '"kubectl", "apply"',
    '"argocd", "app", "sync"',
    '"rollouts", "promote"',
    '"rollouts", "retry"',
    '"rollouts", "abort"',
    "destroy-aws-dev.sh",
):
    assert forbidden not in source, forbidden
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval" for node in ast.walk(tree))

for relative, marker in (
    ("README.md", "v0.11.9.3.6.5-aws-dev-runtime-qualification"),
    ("CHANGELOG.md", "## v0.11.9.3.6.5"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.5"),
    ("docs/V0.11.9.3.6.5_AWS_DEV_RUNTIME_QUALIFICATION.md", "Separate approval and execution"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.5-aws-dev-runtime-qualification.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.5-aws-dev-runtime-qualification.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.5 exact-main, time-window, immutable runtime and bounded traffic contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
bash "${PREDECESSOR}"

python3 -m py_compile "${EXECUTOR}" "${TESTS}"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5-aws-dev-runtime-qualification.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5-aws-dev-runtime-qualification.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.5 aws-dev runtime qualification validation passed; no live operation or traffic was executed."

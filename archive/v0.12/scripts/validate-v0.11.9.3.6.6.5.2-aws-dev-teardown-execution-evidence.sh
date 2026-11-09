#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.5.1-guarded-aws-dev-teardown-executor.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

version = "v0.11.9.3.6.6.5.2"
commit = "0a90e86ca84498b1d639bbb009491f72e5142454"
preflight_sha = "98dc729f588f0167f7c89ce19d3c978232855c7e477576b3b1b464fd65b0ae7a"
execution_sha = "4801d61d55a08af08ecec4469e64b8f215254b9fdc0eff5d89ba984b6b8c76cf"

assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.6.5.1"
assert contract["status"] == "aws-dev-teardown-execution-recorded"
assert contract["implementationBaselineCommit"] == commit
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "review-separate-aws-dev-residual-cost-audit"

preflight = contract["reviewedPreflight"]
assert preflight == {
    "status": "aws-dev-teardown-preflight-ready-for-separate-approval",
    "controlPlaneCommit": commit,
    "privateResultSha256": preflight_sha,
    "directoryModeRestated": "0700",
    "resultFileModeRestated": "0600",
    "executionAuthorized": False,
    "teardownAuthorized": False,
    "mutationExecuted": False,
}

approval = contract["approval"]
assert approval["scope"] == "one aws-dev teardown"
assert approval["startUtc"] == "2026-09-11T05:26:01Z"
assert approval["endUtc"] == "2026-09-11T08:26:01Z"
start = datetime.fromisoformat(approval["startUtc"].replace("Z", "+00:00"))
end = datetime.fromisoformat(approval["endUtc"].replace("Z", "+00:00"))
assert int((end - start).total_seconds()) == 10800
assert all(approval[key] is True for key in (
    "awsDevTeardownApproved",
    "eksVpcComputeStorageAndAlbDeletionApproved",
    "cnpgBackupBucketBaseBackupWalCurrentAndHistoricalDeletionApproved",
))
assert all(approval[key] is False for key in (
    "awsTestCreationApproved",
    "automaticRetryApproved",
    "residualCostAuditApproved",
))

rejected = contract["failClosedAttempt"]
assert rejected == {
    "status": "immediate-preflight-confirmation-rejected",
    "reason": "missing-immediate-preflight-confirmation",
    "executorExit": 1,
    "awsAccessed": False,
    "destroyWrapperInvoked": False,
    "mutationExecuted": False,
    "approvalConsumed": False,
}

execution = contract["execution"]
assert execution == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.6.5.1-aws-dev-teardown.py",
    "phase": "execute",
    "executorExit": 0,
    "status": "aws-dev-teardown-execution-complete",
    "controlPlaneCommit": commit,
    "reviewedPreflightSha256": preflight_sha,
    "privateResultSha256": execution_sha,
    "privateResultFileModeRestated": "0600",
    "immediatePreflightMatched": True,
    "remainingWindowSeconds": 3481,
    "targetEnvironment": "aws-dev",
    "destroyExitCode": 0,
    "terraformDestroyedResourceCount": 90,
    "postSuccessDependencyConvergencePassed": True,
    "fleetRecordsObserved": 8,
    "fleetDeleteRequestsIssued": 4,
    "fleetRecordsAlreadyTerminal": 4,
    "teardownExecuted": True,
    "automaticRetryPerformed": False,
    "awsTestCreated": False,
    "residualCostAuditExecuted": False,
}
assert execution["remainingWindowSeconds"] >= 900
assert execution["fleetRecordsObserved"] == (
    execution["fleetDeleteRequestsIssued"]
    + execution["fleetRecordsAlreadyTerminal"]
)

evidence = contract["privateEvidence"]
assert evidence["rawPreflightStoredOutsideRepository"] is True
assert evidence["rawExecutionResultStoredOutsideRepository"] is True
assert evidence["completionTimestampClaimed"] is False
assert all(evidence[key] is False for key in (
    "rawFilesCommitted",
    "privatePathCommitted",
    "awsAccountCommitted",
    "eksArnCommitted",
    "clusterEndpointCommitted",
    "vpcOrVolumeIdentityCommitted",
    "fleetIdentityCommitted",
))

assert contract["operationBoundary"] == {
    "awsDevTeardownExecuted": True,
    "permanentBackupDeletionIncluded": True,
    "awsTestCreated": False,
    "automaticRetryPerformed": False,
    "residualCostAuditExecuted": False,
}
assert all(value is False for value in contract["packageProducer"].values())

for digest in (preflight_sha, execution_sha):
    assert re.fullmatch(r"[0-9a-f]{64}", digest)

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert "amazonaws.com" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

preflight_source = (
    root / "scripts/preflight-v0.11.9.3.6.6.5-aws-dev-teardown.py"
).read_text()
preflight_body = preflight_source.split("def execute(expected:", 1)[1].split(
    "\ndef main()", 1
)[0]
assert preflight_body.index("CONFIRM_AWS_DEV_TEARDOWN_PREFLIGHT") < preflight_body.index(
    "require_exact_git(expected, runner)"
)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.6.5.2 aws-dev teardown execution evidence"),
    ("CHANGELOG.md", "## v0.11.9.3.6.6.5.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.6.5.2"),
    ("docs/V0.11.9.3.6.6.5.2_AWS_DEV_TEARDOWN_EXECUTION_EVIDENCE.md", execution_sha),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.6.5.2 exact-main teardown, fail-closed input and private evidence contracts passed.")
PY

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.6.5.2 aws-dev teardown execution evidence passed; no live operation was executed."

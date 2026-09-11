#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

version = "v0.11.9.3.6.6.6.1"
commit = "0ae04e26188ab55dc1c76f7d508b40856e798aa5"
empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
preflight_sha = "e2e3de522b20e72e7eabd8d0f47412fbcd0a1a5a347d152b42111d1333cf38e3"
verify_sha = "fd9fdf11202e13718a08dd7d59853848a6607ac16ab2d5805c6f7668367b2655"
result_sha = "6b59e5700a9b24e5f23a26d428e19aca13f80363ea6e32d10931f756613efe29"
stdout_sha = "0ff1b8033a18c449cf0fc228e643a549657c41f5fea3619cf9c80b60356d91e3"

assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.6.6"
assert contract["status"] == "aws-dev-residual-cost-audit-execution-recorded"
assert contract["implementationBaselineCommit"] == commit
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "design-separate-aws-test-live-creation-preflight"

implementation = contract["guardedImplementation"]
assert implementation == {
    "contractPath": "delivery/contracts/v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.json",
    "contractSha256": "7a395d28d23bbe168a412b948eae668c1f770ac639cf9b7f17458a8315bfee0e",
    "executorPath": "scripts/execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py",
    "executorSha256": "6528137035535b1cd4dd865584b7d9ef5861d9e81a1443b2d4283dce41646989",
}
for path_key, sha_key in (
    ("contractPath", "contractSha256"),
    ("executorPath", "executorSha256"),
):
    assert hashlib.sha256(
        (root / implementation[path_key]).read_bytes()
    ).hexdigest() == implementation[sha_key]

preflight = contract["reviewedPreflight"]
assert preflight == {
    "status": "aws-dev-residual-cost-audit-preflight-ready-for-separate-approval",
    "controlPlaneCommit": commit,
    "privateResultSha256": preflight_sha,
    "directoryModeRestated": "0700",
    "resultFileModeRestated": "0600",
    "stderrFileModeRestated": "0600",
    "stderrSha256": empty_sha,
    "stderrBytes": 0,
    "accountVerified": True,
    "accountIdEmitted": False,
    "activeRehearsalEnvironmentCount": 0,
    "terraformBackendReadable": True,
    "terraformStateResourceCount": 0,
    "backupBucketAbsent": True,
    "secretLiveValueAbsent": True,
    "secretTombstonePresent": False,
    "executionAuthorized": False,
    "fullAuditExecuted": False,
    "mutationExecuted": False,
    "awsTestCreated": False,
}

verify = contract["executorVerify"]
assert verify == {
    "status": "aws-dev-residual-cost-audit-execution-inputs-verified",
    "controlPlaneCommit": commit,
    "privateResultSha256": verify_sha,
    "resultFileModeRestated": "0600",
    "stderrFileModeRestated": "0600",
    "stderrSha256": empty_sha,
    "stderrBytes": 0,
    "reviewedPreflightSha256": preflight_sha,
    "remainingWindowSeconds": 14388,
    "immediatePreflightMatched": True,
    "targetEnvironment": "aws-dev",
    "executionAuthorized": False,
    "fullAuditExecuted": False,
    "mutationExecuted": False,
    "automaticRetryPerformed": False,
    "awsTestCreated": False,
}

approval = contract["approval"]
assert approval == {
    "scope": "one read-only aws-dev residual-cost audit",
    "startUtc": "2026-09-11T09:07:56Z",
    "endUtc": "2026-09-11T13:07:56Z",
    "targetEnvironment": "aws-dev",
    "controlPlaneCommit": commit,
    "reviewedPreflightSha256": preflight_sha,
    "reviewedExecutorVerifySha256": verify_sha,
    "fullAuditMaximumExecutions": 1,
    "privateRawOutputApproved": True,
    "awsMutationApproved": False,
    "terraformApplyOrDestroyApproved": False,
    "environmentCreationOrTeardownApproved": False,
    "awsTestCreationApproved": False,
    "automaticRetryApproved": False,
}
start = datetime.fromisoformat(approval["startUtc"].replace("Z", "+00:00"))
end = datetime.fromisoformat(approval["endUtc"].replace("Z", "+00:00"))
assert int((end - start).total_seconds()) == 14400

execution = contract["execution"]
assert execution == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py",
    "phase": "execute",
    "executorExit": 0,
    "status": "aws-dev-residual-cost-audit-complete",
    "controlPlaneCommit": commit,
    "reviewedPreflightSha256": preflight_sha,
    "redactedResultSha256": result_sha,
    "redactedResultFileModeRestated": "0600",
    "executorStderrSha256": empty_sha,
    "executorStderrBytes": 0,
    "immediatePreflightMatched": True,
    "remainingWindowSeconds": 14039,
    "targetEnvironment": "aws-dev",
    "auditExitCode": 0,
    "auditPassed": True,
    "continuingCostIdentityFound": False,
    "terminalOrExpiredFleetRecordCount": 8,
    "privateOutputDirectoryModeRestated": "0700",
    "privateStdoutFileModeRestated": "0600",
    "privateStderrFileModeRestated": "0600",
    "privateStdoutSha256": stdout_sha,
    "privateStderrSha256": empty_sha,
    "privateStdoutBytes": 2399,
    "privateStderrBytes": 0,
    "accountIdEmitted": False,
    "privateResourceIdOutputCommitted": False,
    "executionAuthorized": True,
    "fullAuditExecuted": True,
    "mutationExecuted": False,
    "automaticRetryPerformed": False,
    "awsTestCreated": False,
}
assert 900 <= execution["remainingWindowSeconds"] < verify["remainingWindowSeconds"]

evidence = contract["privateEvidence"]
assert all(evidence[key] is True for key in (
    "rawPreflightStoredOutsideRepository",
    "rawExecutorVerifyStoredOutsideRepository",
    "redactedExecutionResultStoredOutsideRepository",
    "rawAuditStdoutStoredOutsideRepository",
    "rawAuditStderrStoredOutsideRepository",
))
assert evidence["completionTimestampClaimed"] is False
assert all(evidence[key] is False for key in (
    "rawFilesCommitted",
    "privatePathCommitted",
    "awsAccountCommitted",
    "awsArnCommitted",
    "clusterEndpointCommitted",
    "vpcOrVolumeIdentityCommitted",
    "fleetIdentityCommitted",
    "continuingResourceIdentityCommitted",
))

assert contract["operationBoundary"] == {
    "awsDevResidualCostAuditExecuted": True,
    "awsDevResidualCostAuditPassed": True,
    "continuingCostIdentityFound": False,
    "awsMutationExecuted": False,
    "terraformApplyOrDestroyExecuted": False,
    "environmentCreationOrTeardownExecuted": False,
    "awsTestCreated": False,
    "automaticRetryPerformed": False,
}
assert all(value is False for value in contract["packageProducer"].values())

for digest in (empty_sha, preflight_sha, verify_sha, result_sha, stdout_sha):
    assert re.fullmatch(r"[0-9a-f]{64}", digest)

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert "amazonaws.com" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.6.6.1 aws-dev residual-cost audit execution evidence"),
    ("CHANGELOG.md", "## v0.11.9.3.6.6.6.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.6.6.1"),
    ("docs/V0.11.9.3.6.6.6.1_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION_EVIDENCE.md", result_sha),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.6.6.1 read-only aws-dev residual-cost audit execution evidence contracts passed.")
PY

python3 -m json.tool "${CONTRACT}" >/dev/null
bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.6.6.1 aws-dev residual-cost audit execution evidence passed; no live operation was executed."

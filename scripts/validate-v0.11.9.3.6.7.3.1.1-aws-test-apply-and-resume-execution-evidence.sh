#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.3.1.1-aws-test-apply-and-resume-execution-evidence.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.3.1-aws-test-state-classification-repair.sh"

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
contract_path = Path(sys.argv[2])
contract = json.loads(contract_path.read_text())

VERSION = "v0.11.9.3.6.7.3.1.1"
CURRENT_MAIN = "8b039bddbb565d19f52a82ca309b9e4dcf97a574"
APPLIED_MAIN = "1376129d42c6dbc19ffb57c97244d2b31ddd4ff7"
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert contract["schemaVersion"] == contract["version"] == VERSION
assert contract["predecessor"] == "v0.11.9.3.6.7.3.1"
assert contract["status"] == (
    "aws-test-apply-and-post-apply-resume-execution-evidence-recorded"
)
assert contract["implementationBaselineCommit"] == CURRENT_MAIN
assert contract["nextCheckpoint"] == (
    "design-guarded-aws-test-gitops-bootstrap-with-separate-preflight-review-and-approval"
)

expected_repository_inputs = {
    "stateRepairContract": (
        "delivery/contracts/v0.11.9.3.6.7.3.1-aws-test-state-classification-repair.json",
        "6c692e5cb378ad81cb80d12d4a3915f69b5ccfc2f2d175f29e1cb49c3fdbc11f",
    ),
    "resumeExecutor": (
        "scripts/execute-v0.11.9.3.6.7.3.1-aws-test-post-apply-resume.py",
        "10e8cc7d615401518bd9a2bf9bebb640eb591a776aeb1f13f7d005fab13554e9",
    ),
    "stateRepairValidator": (
        "scripts/validate-v0.11.9.3.6.7.3.1-aws-test-state-classification-repair.sh",
        "4b0523babbecba3e4b362b9d1bcd967d78458e35961886601e46c3cf428f2955",
    ),
}
assert set(contract["reviewedRepositoryInputs"]) == set(expected_repository_inputs)
for key, (relative, expected_sha) in expected_repository_inputs.items():
    assert contract["reviewedRepositoryInputs"][key] == {
        "path": relative,
        "sha256": expected_sha,
    }
    assert digest(root / relative) == expected_sha, relative

plan = contract["originalPlan"]
assert plan["appliedControlPlaneCommit"] == APPLIED_MAIN
assert plan["candidateReleaseId"] == "demo-api-cf0a6bcbc466-cdffd3d71763"
expected_plan_hashes = {
    "freshPreflightSha256": "444ecdd6fb17bba42f48dc72083501d3cc64753aa38b8eda907d03d258f37f79",
    "privateCreationPlanSha256": "70a3899c8475552b2bf155e287477e7f81091e3cee9cfb01deb7932e3c449be8",
    "planExecutorVerifySha256": "0d839073b8bb8aca5187fd6a007e58540f5a0e152d8c132cea6b6e7d7d3e2212",
    "planExecutionResultSha256": "4bedd473845ec6d3b43b9b8afeeeece7c3dc5f33bf10e88d0574bbc7d18e0ec6",
    "applyExecutorVerifySha256": "ffdc54c2c152654b63ceac050a5e951de4a2fa0bf259ba821c52440ce691b1e5",
}
for key, expected in expected_plan_hashes.items():
    assert plan[key] == expected, key
expected_plan_artifacts = {
    "binaryPlan": (
        "7c8b5c17b17dcface9fbc97810ec1cedc1985bcb32f3157f4e476b8211d82d0e",
        47323,
    ),
    "terraformPlanJson": (
        "d93343ca8b7294537eeccff8797827c8af3a63ea6f0088a7dc101236dbf231f3",
        300637,
    ),
    "terraformPlanText": (
        "152bf76a977a1636706987df4210c6db085f17bc7c1aa2f2c40d87d84ee1c561",
        118707,
    ),
    "planGate": (
        "acf67d2fc1cbf81a06d92b3d774446d5c5224f9fd0069d0e377fa11dc03b6cce",
        347,
    ),
    "planRecord": (
        "a196b0b7370d7c3772c3a4a60ebeff43fd39ddd59aa7921fa8afabdefab98852",
        1327,
    ),
}
for key, (expected_sha, expected_bytes) in expected_plan_artifacts.items():
    assert plan[key] == {"sha256": expected_sha, "bytes": expected_bytes}, key
assert plan["resourceChangeCount"] == 96
assert plan["actionCounts"] == {
    "create": 90,
    "read": 6,
    "no-op": 0,
    "update": 0,
    "delete": 0,
    "replacement": 0,
}
assert plan["humanReviewAccepted"] is True
assert plan["planReviewExpiredAtUtc"] == "2026-09-12T10:45:16Z"
assert plan["replanAllowed"] is False
assert plan["savedPlanMayBeReapplied"] is False

apply_approval = contract["applyApproval"]
assert apply_approval["scope"] == "one exact reviewed aws-test saved binary plan"
assert apply_approval["reviewedCreateMutationCount"] == 90
assert apply_approval["reviewedSessionBudgetUsd"] == 12.0
assert apply_approval["applyApproved"] is True
for key in (
    "replanApproved",
    "destroyApproved",
    "automaticRetryApproved",
    "automaticRepairApproved",
    "gitopsBootstrapApproved",
    "trafficApproved",
    "qualificationApproved",
    "promotionApproved",
    "teardownApproved",
):
    assert apply_approval[key] is False, key

apply_execution = contract["applyExecution"]
assert apply_execution["executorExit"] == 1
assert apply_execution["resultSha256"] == EMPTY_SHA
assert apply_execution["stderrSha256"] == (
    "410415ad92580ecd0650655776821821caf6653bbc57cb4dd70f63995760be4e"
)
assert apply_execution["stderrBytes"] == 88
for key in ("terraformApplyCommandSucceeded", "terraformStateListCommandSucceeded"):
    assert apply_execution[key] is True, key
assert apply_execution["failureStage"] == "post-apply-state-address-classification"
for key in (
    "failureWasInfrastructureFailure",
    "automaticRetryPerformed",
    "terraformApplyReexecuted",
):
    assert apply_execution[key] is False, key
assert apply_execution["environmentCreatedBySavedPlan"] is True
apply_output = apply_execution["privateOutput"]
assert apply_output["directoryModeRestated"] == "0700"
assert apply_output["fileModeRestated"] == "0600"
expected_apply_output = {
    "immediatePreflightStdout": (
        "444ecdd6fb17bba42f48dc72083501d3cc64753aa38b8eda907d03d258f37f79",
        1300,
    ),
    "metadataBeforeApplyStderr": (
        "0b434d98da1f8aae5510ee92e0e256138139ab4293b0ed566305ca1e48cca4cf",
        139,
    ),
    "terraformShowJsonStdout": (
        "d93343ca8b7294537eeccff8797827c8af3a63ea6f0088a7dc101236dbf231f3",
        300637,
    ),
    "terraformApplyStdout": (
        "ca2e3d7e1884e40a0339ce7912dae61d28be9abb720b0e3262df5e93a446e046",
        37273,
    ),
    "terraformStateListStdout": (
        "9c0c0fbce81f313a12d088bb0d071cfa20f911c1abb69fb35841de8dea7cdd96",
        5662,
    ),
}
for key, (expected_sha, expected_bytes) in expected_apply_output.items():
    assert apply_output[key] == {"sha256": expected_sha, "bytes": expected_bytes}
assert apply_output["allCommandStderrExceptExpectedAbsenceCheckEmpty"] is True
assert apply_output["rawContentCommitted"] is False

classification = contract["stateClassification"]
assert classification["terraformState"] == {
    "sha256": "a53f7bb1091990195680c9b3918a6110d4b3b8cb61441ce22aec2faf68fa725b",
    "bytes": 241960,
    "fileModeRestated": "0600",
    "unchangedByResume": True,
    "committed": False,
}
assert classification["planResourceChangeCount"] == 96
assert classification["planCreateAddressCount"] == 90
assert classification["stateListAddressCount"] == 103
assert classification["stateResourceBlockCount"] == 80
assert classification["stateResourceInstanceCount"] == 103
assert classification["missingPlannedCreateCount"] == 0
assert classification["unexpectedManagedAddressCount"] == 0
assert classification["acceptedUnplannedDataAddressCount"] == 7
assert classification["unexpectedUnclassifiedAddressCount"] == 0
assert classification["acceptedDataTypeCounts"] == {
    "callerIdentity": 3,
    "partition": 3,
    "dnsZone": 1,
}

verification = contract["resumeVerification"]
assert verification == {
    "executorExit": 0,
    "resultSha256": "baf9dd1b887682dd7e475f1b58317c87a5bc26da21fb81073c8a8087a8a63051",
    "stderrSha256": EMPTY_SHA,
    "stderrBytes": 0,
    "status": "aws-test-post-apply-resume-inputs-verified",
    "remainingSessionSeconds": 14112,
    "commandsExecuted": [],
    "resumeExecutionAuthorized": False,
    "terraformPlanAuthorized": False,
    "terraformApplyAuthorized": False,
    "terraformDestroyAuthorized": False,
}

resume_approval = contract["resumeApproval"]
assert resume_approval["verifyResultSha256"] == verification["resultSha256"]
deadline = datetime.fromisoformat(resume_approval["notAfterUtc"].replace("Z", "+00:00"))
assert deadline.isoformat() == "2026-09-12T17:38:53+00:00"
assert resume_approval["oneExecutionApproved"] is True
assert resume_approval["readOnlyAwsChecksApproved"] == [
    "caller identity",
    "cluster inventory",
    "aws-test cluster status and reviewed API boundary",
    "credential-container metadata",
]
assert resume_approval["privateOutputCaptureApproved"] is True
for key in (
    "terraformCommandApproved",
    "terraformApplyApproved",
    "awsMutationApproved",
    "credentialValueReadApproved",
    "automaticRetryApproved",
    "automaticRepairApproved",
    "kubernetesApproved",
    "gitopsApproved",
    "trafficApproved",
    "qualificationApproved",
    "promotionApproved",
    "teardownApproved",
):
    assert resume_approval[key] is False, key

resume = contract["resumeExecution"]
assert resume["executorExit"] == 0
assert resume["resultSha256"] == (
    "b9f240afa6df38167cf2e3c5abcc8a7db583afa9a59488f3c3cbe6b9250d183f"
)
assert resume["stderrSha256"] == EMPTY_SHA
assert resume["stderrBytes"] == 0
assert resume["status"] == "aws-test-post-apply-resume-verification-complete"
assert resume["controlPlaneCommit"] == CURRENT_MAIN
assert resume["appliedControlPlaneCommit"] == APPLIED_MAIN
assert resume["candidateReleaseId"] == plan["candidateReleaseId"]
for key in ("priorTerraformApplySucceeded", "eksClusterActive", "credentialContainerMetadataPresent"):
    assert resume[key] is True, key
assert resume["plannedCreateAddressCount"] == 90
assert resume["missingPlannedCreateCount"] == 0
assert resume["unexpectedManagedAddressCount"] == 0
assert resume["acceptedUnplannedDataAddressCount"] == 7
assert resume["stateAddressCount"] == 103
for key in (
    "terraformApplyReexecuted",
    "resumeTerraformCommandExecuted",
    "resumeAwsMutationExecuted",
    "gitopsBootstrapExecuted",
    "trafficGenerated",
    "qualificationExecuted",
    "automaticRetryPerformed",
    "privateResourceIdentityEmitted",
):
    assert resume[key] is False, key

artifacts = contract["privateResumeArtifacts"]
assert artifacts["directoryModeRestated"] == "0700"
assert artifacts["fileModeRestated"] == "0600"
expected_resume_artifacts = {
    "callerIdentityStdout": (
        "1e19721c43738416dcf7e781f5b55858cc70ab7024693eb18f060dea10f18d94",
        197,
    ),
    "clusterInventoryStdout": (
        "9e95155afd2fcca6cd7eebc4158020b8b32800ac42948a6237f9b80949615ef9",
        67,
    ),
    "clusterDescriptionStdout": (
        "f1de181f9e03d379a819468ea6b3f5df3774cf0a32f26eff8cae66980515888f",
        4225,
    ),
    "credentialContainerMetadataStdout": (
        "b56815ad21d9c784844929c040d9ec27a83ad016bdfff7405798801b5ae3a1ac",
        1099,
    ),
}
for key, (expected_sha, expected_bytes) in expected_resume_artifacts.items():
    assert artifacts[key] == {"sha256": expected_sha, "bytes": expected_bytes}
assert artifacts["allStderrSha256"] == EMPTY_SHA
assert artifacts["allStderrBytes"] == 0
assert artifacts["rawContentCommitted"] is False
assert artifacts["privatePathCommitted"] is False

assert contract["finalRepositoryState"] == {
    "head": CURRENT_MAIN,
    "originMain": CURRENT_MAIN,
    "worktreeClean": True,
    "protectedMainChecksPassed": True,
}
assert all(value is False for value in contract["privacyBoundary"].values())
assert contract["operationBoundary"] == {
    "originalSavedPlanApplyExecutedOnce": True,
    "reviewedAwsCreateMutationCount": 90,
    "environmentCreatedByOriginalApply": True,
    "terraformApplyReexecuted": False,
    "terraformPlanReexecuted": False,
    "terraformDestroyExecuted": False,
    "resumeAwsMutationExecuted": False,
    "stateMutatedByResume": False,
    "gitopsBootstrapped": False,
    "trafficGenerated": False,
    "qualificationExecuted": False,
    "promotionExecuted": False,
    "teardownExecuted": False,
    "automaticRetryPerformed": False,
}
assert all(value is False for value in contract["packageProducer"].values())

for path in (
    contract_path,
    root / "docs/V0.11.9.3.6.7.3.1.1_AWS_TEST_APPLY_AND_RESUME_EXECUTION_EVIDENCE.md",
):
    text = path.read_text()
    assert "/tmp/" not in text, path
    assert "arn:aws:" not in text, path
    assert "AKIA" not in text, path
    assert re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text) is None, path
    assert re.search(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32", text) is None, path
    assert re.search(r"\b(?:aws|data)\.[A-Za-z0-9_]+\.", text) is None, path
PY

"${PREDECESSOR}"

echo "v0.11.9.3.6.7.3.1.1 aws-test apply and post-apply resume execution evidence passed; no live operation was executed."

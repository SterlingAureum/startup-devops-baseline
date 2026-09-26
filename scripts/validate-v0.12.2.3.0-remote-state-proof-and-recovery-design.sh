#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR

python3 - <<'PY'
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.3.0-remote-state-proof-and-recovery-design.json"
predecessor_path = root / "delivery/contracts/v0.12.2.2.1-bootstrap-state-migration-recovery-evidence.json"
doc_path = root / "docs/V0.12.2.3.0_REMOTE_STATE_PROOF_AND_RECOVERY_DESIGN.md"
validator_path = root / "scripts/validate-v0.12.2.3.0-remote-state-proof-and-recovery-design.sh"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.0-remote-state-proof-and-recovery-design-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.0", "version drift")
    require(value.get("status") == "delivered-offline-remote-state-proof-and-recovery-design", "status drift")
    require(value.get("implementationBaselineCommit") == "2e0b6a9050cb9338dea4770111b2f9b002f5e115", "baseline drift")
    predecessor = value.get("predecessor")
    require(predecessor == {
        "version": "v0.12.2.2.1",
        "contract": "delivery/contracts/v0.12.2.2.1-bootstrap-state-migration-recovery-evidence.json",
        "requiredStatus": "completed-redacted-bootstrap-state-migration-recovery-evidence",
    }, "predecessor drift")
    identity = value.get("canonicalRemoteIdentity")
    require(identity == {
        "stateSha256": "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139",
        "lineageSha256": "4f42afe2b009593773f37059419ca3ea4e87ca89d4ef1a7ff1278d60f2ed2fab",
        "serial": 1,
        "managedAddressCount": 13,
        "dataAddressCount": 9,
        "semanticProjectionSha256": "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d",
        "currentStateObjectVersionCount": 1,
        "stateObjectDeleteMarkerCount": 0,
        "adoptedFromValidatedIdentityRebase": True,
    }, "canonical identity drift")
    superseded = value.get("supersededV01220Postconditions")
    require(superseded.get("backupLineageMustEqualRemoteLineage") is False, "obsolete lineage condition restored")
    require(superseded.get("remoteSerialMustBeAtLeastBackupSerial") is False, "obsolete serial condition restored")
    require(superseded.get("immutableBackupStillRequired") is True and superseded.get("addressAndSemanticEqualityStillRequired") is True, "preserved invariants drift")
    lock = value.get("lockContentionProof")
    require(lock.get("holderCommand") == "terraform console" and lock.get("contenderCommand") == "terraform plan -lock-timeout=0s", "lock commands drift")
    require(all(lock.get(key) is True for key in ("holderMustUseCanonicalBackendMetadata", "holderMustRemainOpen", "lockObjectMustBeObservedWhileHolderRuns", "contenderMustFailOnStateLock", "holderExitMustBeClean", "lockObjectMustBeAbsentAfterHolderExit", "lockObjectVersionHistoryStoredPrivately")), "positive lock invariant drift")
    require(all(lock.get(key) is False for key in ("contenderNonLockFailureAccepted", "forceUnlockAllowed", "directLockObjectWriteAllowed", "automaticRetryAllowed")), "unsafe lock behavior enabled")
    plan = value.get("zeroChangePlanProof")
    require(plan.get("runsOnlyAfterLockRelease") is True and plan.get("savedBinaryPlanRequired") is True and plan.get("detailedExitCodeRequired") is True, "plan sequencing drift")
    require(plan.get("expectedExitCode") == 0 and plan.get("managedChangesExpected") == 0 and plan.get("resourceDriftExpected") == 0 and plan.get("importsExpected") == 0, "zero-change gate drift")
    require(plan.get("machineReadablePlanRequired") is True and plan.get("humanReadablePlanRequired") is True and plan.get("humanReviewRequired") is True, "plan evidence drift")
    require(plan.get("sourceManifestBound") is True and plan.get("remoteStateIdentityBound") is True and plan.get("terraformApplyAllowed") is False, "plan authority drift")
    recovery = value.get("controlledObjectVersionRecovery")
    require(all(recovery.get(key) is True for key in (
        "separateRequestApprovalAndWindowRequired", "reviewedPreDrillVersionIdRequired",
        "freshPrivateStatePullBackupRequired", "canonicalTerraformConsoleLockRequired",
        "stateLockObservedBeforeCopy", "firstCopyCreatesByteIdenticalDrillVersion",
        "recoveryCopiesReviewedPreDrillVersionToCurrent", "explicitCopySourceVersionIdRequired",
        "copySourceEtagPreconditionRequired", "expectedBucketOwnerRequired",
        "sseKmsAndBucketKeyRequired", "postRecoveryStatePullAndListRequired",
        "postRecoveryZeroChangePlanRequired",
    )), "recovery invariant drift")
    require(all(recovery.get(key) is False for key in ("existingStateVersionsDeleted", "statePushAllowed", "forceUnlockAllowed", "automaticRollbackAllowed")), "unsafe recovery authority enabled")
    failure = value.get("failureBoundary")
    require(all(failure.get(key) is True for key in (
        "holderExitsBeforeContentionMeansFailure", "lockNotObservedMeansFailure",
        "contenderSuccessMeansFailure", "nonZeroZeroChangePlanMeansFailure",
        "copyAmbiguityMeansStop", "lockCleanupAmbiguityMeansStop",
        "preserveAllPrivateEvidence", "preserveEveryStateObjectVersion",
    )), "failure boundary drift")
    require(failure.get("automaticRetry") is False, "automatic retry enabled")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in (
        "publishesAwsAccount", "publishesBucket", "publishesKmsArn", "publishesRawLineage",
        "publishesStateBytes", "publishesPlanContents", "publishesStateObjectVersionIds",
        "publishesLockInfo", "publishesPrivatePaths",
    )), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "public evidence boundary drift")
    sequence = value.get("implementationSequence")
    require([item.get("version") for item in sequence] == ["v0.12.2.3.1", "v0.12.2.3.2", "v0.12.2.3.3", "v0.12.2.3.4"], "implementation sequence drift")
    require([item.get("liveStateContentMutation") for item in sequence] == [False, False, True, False], "state mutation sequencing drift")
    producer = value.get("packageProducer")
    require(all(producer.get(key) is False for key in ("runsAws", "runsTerraform", "readsPrivateEvidence", "writesRemoteState", "writesLockObject", "grantsLiveAuthority")), "package authority drift")


contract = json.loads(contract_path.read_text())
validate(contract)
predecessor = json.loads(predecessor_path.read_text())
require(predecessor.get("version") == "v0.12.2.2.1" and predecessor.get("status") == contract["predecessor"]["requiredStatus"], "predecessor contract changed")

mutations = []
def mutate(path, value):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    mutations.append(item)

mutate(["status"], "complete")
mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["canonicalRemoteIdentity", "stateSha256"], "0" * 64)
mutate(["canonicalRemoteIdentity", "serial"], 20)
mutate(["canonicalRemoteIdentity", "managedAddressCount"], 12)
mutate(["canonicalRemoteIdentity", "adoptedFromValidatedIdentityRebase"], False)
mutate(["supersededV01220Postconditions", "backupLineageMustEqualRemoteLineage"], True)
mutate(["supersededV01220Postconditions", "immutableBackupStillRequired"], False)
mutate(["lockContentionProof", "holderCommand"], "aws s3api put-object")
mutate(["lockContentionProof", "holderMustRemainOpen"], False)
mutate(["lockContentionProof", "contenderMustFailOnStateLock"], False)
mutate(["lockContentionProof", "contenderNonLockFailureAccepted"], True)
mutate(["lockContentionProof", "forceUnlockAllowed"], True)
mutate(["lockContentionProof", "directLockObjectWriteAllowed"], True)
mutate(["zeroChangePlanProof", "expectedExitCode"], 2)
mutate(["zeroChangePlanProof", "managedChangesExpected"], 1)
mutate(["zeroChangePlanProof", "humanReviewRequired"], False)
mutate(["zeroChangePlanProof", "terraformApplyAllowed"], True)
mutate(["controlledObjectVersionRecovery", "separateRequestApprovalAndWindowRequired"], False)
mutate(["controlledObjectVersionRecovery", "explicitCopySourceVersionIdRequired"], False)
mutate(["controlledObjectVersionRecovery", "copySourceEtagPreconditionRequired"], False)
mutate(["controlledObjectVersionRecovery", "existingStateVersionsDeleted"], True)
mutate(["controlledObjectVersionRecovery", "statePushAllowed"], True)
mutate(["controlledObjectVersionRecovery", "forceUnlockAllowed"], True)
mutate(["controlledObjectVersionRecovery", "automaticRollbackAllowed"], True)
mutate(["failureBoundary", "contenderSuccessMeansFailure"], False)
mutate(["failureBoundary", "automaticRetry"], True)
mutate(["privacyBoundary", "publishesStateObjectVersionIds"], True)
mutate(["implementationSequence", 2, "liveStateContentMutation"], False)
mutate(["packageProducer", "writesLockObject"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open design mutation {index}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.strip()
require(tracked.startswith("100755 "), "validator Git index mode drift")

documentation = doc_path.read_text()
for marker in ("terraform console", "-lock-timeout=0s", "source version ID", "v0.12.2.3.4"):
    require(marker in documentation, f"documentation marker missing: {marker}")
public_text = contract_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public design contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public design contains an AWS account")

print(f"v0.12.2.3.0 remote-state proof/recovery design and {len(mutations)} fail-closed mutations passed offline.")
PY

bash "${ROOT_DIR}/scripts/validate-v0.12.2.2.1-bootstrap-state-migration-recovery-evidence.sh"

echo "v0.12.2.3.0 remote-state proof and recovery design passed offline; no AWS or Terraform command was executed."

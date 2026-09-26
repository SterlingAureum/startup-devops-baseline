#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR

python3 - <<'PY'
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.1-guarded-refresh-only-recovery-plan.json"
predecessor_path = root / "delivery/contracts/v0.12.2.3.1-guarded-remote-state-proof.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.1-bootstrap-refresh-only-plan-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.1-guarded-refresh-only-recovery-plan.sh"
doc_path = root / "docs/V0.12.2.3.1.0.1_GUARDED_REFRESH_ONLY_RECOVERY_PLAN.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.1-guarded-refresh-only-recovery-plan-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.1", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-refresh-only-plan-approval", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "a80400593fce7cd40a90a0d5649f31d4e1d85d1a", "baseline drift")
    incident = value.get("incident")
    require(incident.get("version") == "v0.12.2.3.1" and incident.get("contract") == "delivery/contracts/v0.12.2.3.1-guarded-remote-state-proof.json", "incident predecessor drift")
    require(incident.get("controlPlaneCommit") == "a80400593fce7cd40a90a0d5649f31d4e1d85d1a", "incident control plane drift")
    require(incident.get("privateProofRequestSha256") == "b9c6a1a5499e9aad31d0482981d5c97a783e5bcac0ec567a9e886a929f0b7730", "proof request drift")
    require(incident.get("canonicalRemoteStateSha256") == "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139", "state drift")
    require(incident.get("binaryPlanSha256") == "5dfe31147df6f7d6b02acb5631ab0f5a06552459286931b5b6e3804ac0940d8a", "binary plan drift")
    require(incident.get("planJsonSha256") == "51625bf05e06b4fee6260e2acb2a23765707f6dac045adb0661361fc97dd3bfc", "plan JSON drift")
    require(incident.get("planTextSha256") == "f13fa1c59cb83003176963af0243b3b94ed2c419d81a47f11b76028513cad939", "plan text drift")
    require(incident.get("resourceDriftSha256") == "cda2f5fefc620e11747c88e38db673e906fb7c4a29a5a5c886a5f7ec0140ab7a", "resource drift digest changed")
    require(incident.get("resourceDriftCount") == 7 and incident.get("resourceChangeCount") == 13, "incident counts drift")
    require(all(incident.get(key) is True for key in ("allResourceChangesNoOp", "allOutputChangesNoOp", "allRefreshAfterValuesMatchNoOpState", "lockContentionProved", "lockReleasedAfterHolder")), "incident success evidence drift")
    require(incident.get("proofResultPresent") is False and incident.get("automaticRetryPerformed") is False, "incident stopping point drift")
    interpretation = value.get("interpretation")
    require(interpretation == {"remoteInfrastructureMatchesConfiguration": True, "savedStateRequiresReviewedRefresh": True, "ordinaryPlanRefreshWasInMemoryOnly": True, "originalResourceDriftGateStoppedCorrectly": True, "originalProofMayNotBeRetried": True}, "incident interpretation drift")
    verify = value.get("verifyBoundary")
    require(all(verify.get(key) is False for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence", "refreshPlanAuthorizedByVerify")), "verify boundary drift")
    require(verify.get("revalidatesCompleteIncident") is True and verify.get("revalidatesExactSevenResourceDrifts") is True, "verify incident gate drift")
    execute = value.get("executeBoundary")
    require(all(execute.get(key) is True for key in ("awsReadOnlyValidation", "terraformStatePull", "terraformStateList", "terraformRefreshOnlyPlan", "terraformShow", "transientLockMutation")), "refresh plan authority drift")
    require(all(execute.get(key) is False for key in ("stateContentMutation", "terraformInit", "terraformApply", "ordinaryTerraformPlan", "statePush", "destroy", "iamPolicyAttachment", "directLockWrite", "forceUnlock", "automaticRetry")), "mutation authority drift")
    success = value.get("successGate")
    require(success.get("refreshOnlyDetailedExitCode") == 2 and success.get("lockVersionDelta") == 1 and success.get("lockDeleteMarkerDelta") == 1, "success count drift")
    require(all(success.get(key) is True for key in ("exactSevenResourceDrifts", "exactDriftDigestRequired", "emptyResourceChangesRequired", "allOutputChangesNoOp", "canonicalStateBytesUnchanged", "stateObjectHistoryUnchanged", "savedBinaryPlanRequired", "humanReviewRequired")), "success gate drift")
    require(success.get("importsAllowed") is False, "import boundary drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in ("publishesAwsAccount", "publishesBucket", "publishesKmsArn", "publishesStateBytes", "publishesDriftValues", "publishesPlanContents", "publishesObjectVersionIds", "publishesPrivatePaths")), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "redacted evidence drift")
    require(value.get("successor") == {"version": "v0.12.2.3.1.0.2", "scope": "separately-reviewed-refresh-only-state-reconciliation", "refreshApplyAuthorizedByThisIncrement": False}, "successor drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "package producer drift")


contract = json.loads(contract_path.read_text())
validate(contract)
predecessor = json.loads(predecessor_path.read_text())
require(predecessor.get("version") == "v0.12.2.3.1", "predecessor contract changed")

mutations = []
def mutate(path, replacement):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    mutations.append(item)

mutate(["status"], "complete")
mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["incident", "privateProofRequestSha256"], "0" * 64)
mutate(["incident", "planJsonSha256"], "0" * 64)
mutate(["incident", "resourceDriftSha256"], "0" * 64)
mutate(["incident", "resourceDriftCount"], 6)
mutate(["incident", "allResourceChangesNoOp"], False)
mutate(["incident", "allRefreshAfterValuesMatchNoOpState"], False)
mutate(["incident", "lockReleasedAfterHolder"], False)
mutate(["incident", "automaticRetryPerformed"], True)
mutate(["interpretation", "originalProofMayNotBeRetried"], False)
mutate(["verifyBoundary", "terraformCommands"], True)
mutate(["verifyBoundary", "refreshPlanAuthorizedByVerify"], True)
mutate(["executeBoundary", "terraformApply"], True)
mutate(["executeBoundary", "ordinaryTerraformPlan"], True)
mutate(["executeBoundary", "statePush"], True)
mutate(["executeBoundary", "forceUnlock"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "refreshOnlyDetailedExitCode"], 0)
mutate(["successGate", "exactDriftDigestRequired"], False)
mutate(["successGate", "canonicalStateBytesUnchanged"], False)
mutate(["successGate", "lockVersionDelta"], 2)
mutate(["privacyBoundary", "publishesDriftValues"], True)
mutate(["successor", "refreshApplyAuthorizedByThisIncrement"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

spec = importlib.util.spec_from_file_location("refresh_plan_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
example = json.loads(example_path.read_text())
example["expectedMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)

source = executor_path.read_text()
for forbidden in ('"apply", str(', '"init"', '"state", "push"', '"force-unlock"', '"s3api", "put-object"', '"s3api", "delete-object"'):
    require(forbidden not in source, f"executor contains forbidden command: {forbidden}")
for marker in ('"plan", "-refresh-only"', '"-detailed-exitcode"', '"state", "pull"', '"state", "list"', '"list-object-versions"', '"show", "-json"'):
    require(marker in source, f"executor marker missing: {marker}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 3, "executable files are not tracked")
require(all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("resource_drift", "plan -refresh-only", "v0.12.2.3.1.0.2", "does not retry"):
    require(marker in documentation, f"documentation marker missing: {marker}")
public_text = contract_path.read_text() + example_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public artifact contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public artifact contains an AWS account")
require("VersionId\"" not in public_text, "public artifact contains an object version ID")

print(f"v0.12.2.3.1.0.1 refresh-only recovery-plan contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1-guarded-remote-state-proof.sh"

echo "v0.12.2.3.1.0.1 guarded refresh-only recovery plan passed offline; no AWS or Terraform command was executed."

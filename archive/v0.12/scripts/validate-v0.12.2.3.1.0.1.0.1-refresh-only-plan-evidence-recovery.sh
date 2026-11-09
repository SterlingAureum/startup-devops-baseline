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
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.1.0.1-refresh-only-plan-evidence-recovery.json"
predecessor_path = root / "delivery/contracts/v0.12.2.3.1.0.1-guarded-refresh-only-recovery-plan.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.1.0.1-refresh-only-plan-evidence-recovery.sh"
doc_path = root / "docs/V0.12.2.3.1.0.1.0.1_REFRESH_ONLY_PLAN_EVIDENCE_RECOVERY.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.1.0.1-refresh-only-plan-evidence-recovery-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.1.0.1", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-read-only-plan-evidence-recovery-approval", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "be27ef4aa9a6825473084bd48ff9a29cbd8f9909", "baseline drift")
    incident = value.get("incident")
    require(incident.get("version") == "v0.12.2.3.1.0.1" and incident.get("contract") == predecessor_path.relative_to(root).as_posix(), "predecessor drift")
    require(incident.get("controlPlaneCommit") == "be27ef4aa9a6825473084bd48ff9a29cbd8f9909", "incident main drift")
    expected = {
        "privateRefreshPlanRequestSha256": "d856dd8a88485a3a816e79c411e6551e2335bd435ffa61d05adc41e2622c6f3a",
        "canonicalRemoteStateSha256": "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139",
        "binaryRefreshPlanSha256": "25e0d13ea279af093fc138c9f6d946694e3e399df5c5c6c2648e401ce789f74c",
        "refreshPlanJsonSha256": "b89d89f3590f8cf7aab5bab15fa5d0dc2e522cb8d9c56098bcb6ea02a11887ad",
        "refreshPlanTextSha256": "746ef94f5ddb6bd3630006011745bf2f67d8ce7a43eff54642d7d54193e67d98",
        "resourceDriftSha256": "cda2f5fefc620e11747c88e38db673e906fb7c4a29a5a5c886a5f7ec0140ab7a",
    }
    require(all(incident.get(key) == digest for key, digest in expected.items()), "incident digest drift")
    require(incident.get("resourceDriftCount") == 7 and incident.get("resourceChangeCount") == 0 and incident.get("outputChangeCount") == 7, "plan counts drift")
    require(all(incident.get(key) is True for key in ("allOutputChangesNoOp", "planApplyable")), "plan result drift")
    require(all(incident.get(key) is False for key in ("stateContentMutated", "recoveryResultPresent", "automaticRetryPerformed")), "incident stop boundary drift")
    interpretation = value.get("correctedInterpretation")
    require(all(interpretation.get(key) is True for key in ("refreshOnlyPlanUsesResourceDriftForStateUpdates", "emptyResourceChangesIsExpected", "ordinaryPlanThirteenNoOpGateDoesNotApply", "exactDriftDigestStillRequired", "existingPlanMustBeRecoveredWithoutReplanning")), "refresh-only interpretation drift")
    verify = value.get("verifyBoundary")
    require(all(verify.get(key) is False for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence", "recoveryAuthorizedByVerify")), "verify boundary drift")
    require(verify.get("revalidatesExactExistingPlan") is True, "verify plan gate drift")
    execute = value.get("executeBoundary")
    require(all(execute.get(key) is True for key in ("awsIdentityRead", "terraformStatePull", "terraformStateList", "s3StateAndLockRead")), "read authority drift")
    require(all(execute.get(key) is False for key in ("terraformInit", "terraformPlan", "terraformApply", "statePush", "destroy", "iamPolicyAttachment", "directLockWrite", "forceUnlock", "automaticRetry")), "mutation authority drift")
    success = value.get("successGate")
    require(success.get("managedAddressCount") == 13 and success.get("dataAddressCount") == 9, "address count drift")
    require(success.get("refreshPlanLockVersionDelta") == 1 and success.get("refreshPlanLockDeleteMarkerDelta") == 1, "lock delta drift")
    require(all(success.get(key) is True for key in ("canonicalStateBytesUnchanged", "stateObjectHistoryUnchanged", "lockObjectAbsent", "existingPlanPreserved", "humanReviewRequired")), "success gate drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in ("publishesAwsAccount", "publishesBucket", "publishesKmsArn", "publishesStateBytes", "publishesPlanContents", "publishesObjectVersionIds", "publishesPrivatePaths")), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "redacted evidence drift")
    require(value.get("successor") == {"version": "v0.12.2.3.1.0.2", "scope": "separately-reviewed-refresh-only-state-reconciliation", "refreshApplyAuthorizedByThisRecovery": False}, "successor drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "package producer drift")


contract = json.loads(contract_path.read_text())
validate(contract)
predecessor = json.loads(predecessor_path.read_text())
require(predecessor.get("version") == "v0.12.2.3.1.0.1", "predecessor contract changed")
require(predecessor.get("successGate", {}).get("emptyResourceChangesRequired") is True, "predecessor refresh-only shape not repaired")

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
mutate(["incident", "privateRefreshPlanRequestSha256"], "0" * 64)
mutate(["incident", "binaryRefreshPlanSha256"], "0" * 64)
mutate(["incident", "refreshPlanJsonSha256"], "0" * 64)
mutate(["incident", "resourceDriftCount"], 6)
mutate(["incident", "resourceChangeCount"], 13)
mutate(["incident", "outputChangeCount"], 0)
mutate(["incident", "planApplyable"], False)
mutate(["incident", "stateContentMutated"], True)
mutate(["correctedInterpretation", "emptyResourceChangesIsExpected"], False)
mutate(["correctedInterpretation", "existingPlanMustBeRecoveredWithoutReplanning"], False)
mutate(["verifyBoundary", "terraformCommands"], True)
mutate(["executeBoundary", "terraformPlan"], True)
mutate(["executeBoundary", "terraformApply"], True)
mutate(["executeBoundary", "statePush"], True)
mutate(["executeBoundary", "forceUnlock"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "canonicalStateBytesUnchanged"], False)
mutate(["successGate", "stateObjectHistoryUnchanged"], False)
mutate(["successGate", "refreshPlanLockVersionDelta"], 2)
mutate(["successGate", "existingPlanPreserved"], False)
mutate(["privacyBoundary", "publishesPlanContents"], True)
mutate(["successor", "refreshApplyAuthorizedByThisRecovery"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

spec = importlib.util.spec_from_file_location("refresh_evidence_recovery_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
example = json.loads(example_path.read_text())
example["expectedRecoveryMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)

source = executor_path.read_text()
for forbidden in ('"plan",', '"init"', '"apply",', '"state", "push"', '"force-unlock"', '"s3api", "put-object"', '"s3api", "delete-object"'):
    require(forbidden not in source, f"executor contains forbidden command: {forbidden}")
for marker in ('"state", "pull"', '"state", "list"', '"head-object"', '"list-object-versions"'):
    require(marker in source, f"executor marker missing: {marker}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 3, "executable files are not tracked")
require(all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("resource_changes", "does not exist", "must not be regenerated", "v0.12.2.3.1.0.2"):
    require(marker in documentation, f"documentation marker missing: {marker}")
public_text = contract_path.read_text() + example_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public artifact contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public artifact contains an AWS account")
require("VersionId\"" not in public_text, "public artifact contains an object version ID")

print(f"v0.12.2.3.1.0.1.0.1 refresh-only plan-evidence recovery contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.1-guarded-refresh-only-recovery-plan.sh"

echo "v0.12.2.3.1.0.1.0.1 refresh-only plan-evidence recovery passed offline; no AWS or Terraform command was executed."

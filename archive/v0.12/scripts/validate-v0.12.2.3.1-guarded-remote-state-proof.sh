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
contract_path = root / "delivery/contracts/v0.12.2.3.1-guarded-remote-state-proof.json"
predecessor_path = root / "delivery/contracts/v0.12.2.3.0-remote-state-proof-and-recovery-design.json"
example_path = root / "delivery/examples/v0.12.2.3.1-bootstrap-remote-state-proof-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1-bootstrap-remote-state-proof.py"
test_path = root / "scripts/test-v0.12.2.3.1-bootstrap-remote-state-proof.py"
validator_path = root / "scripts/validate-v0.12.2.3.1-guarded-remote-state-proof.sh"
doc_path = root / "docs/V0.12.2.3.1_GUARDED_REMOTE_STATE_PROOF.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_text())


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1-guarded-remote-state-proof-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-remote-state-proof-approval", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "297a82b526ea9a137704ce4ba81fdfa35e16860f", "baseline drift")
    require(value.get("predecessor") == {
        "version": "v0.12.2.3.0",
        "contract": "delivery/contracts/v0.12.2.3.0-remote-state-proof-and-recovery-design.json",
        "requiredStatus": "delivered-offline-remote-state-proof-and-recovery-design",
    }, "predecessor drift")
    bindings = value.get("recoveryBindings")
    require(bindings.get("privateRecoveryRequestSha256") == "e4c3f713fb00387dfbeb82e81d528b7eb0b262afe8d45fa9010fbb0b84d68612", "recovery request drift")
    require(bindings.get("recoveryResultSha256") == "adeb7145db9751f3eabd47b8379173acffff666590079edc189eb75db56e66f2", "recovery result drift")
    require(bindings.get("identityValidationSha256") == "c6a560147ee4cd7c5fd787e9a895ebb90efd29cf2cbb23dae6a7943dd03d93b5", "identity validation drift")
    require(bindings.get("remoteStateSha256") == "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139", "remote state drift")
    require(bindings.get("semanticProjectionSha256") == "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d", "semantic projection drift")
    require(bindings.get("managedAddressCount") == 13 and bindings.get("dataAddressCount") == 9, "address count drift")
    require(bindings.get("stateObjectVersionCount") == 1 and bindings.get("stateObjectDeleteMarkerCount") == 0, "state object inventory drift")
    verify = value.get("verifyBoundary")
    require(all(verify.get(key) is False for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence", "proofAuthorizedByVerify")), "verify command boundary drift")
    require(all(verify.get(key) is True for key in ("requiresProtectedMain", "requiresFreshWindow", "revalidatesRecoveryChain", "revalidatesPrivateTfvars")), "verify gate drift")
    execute = value.get("executeBoundary")
    require(all(execute.get(key) is True for key in ("awsReadOnlyValidation", "terraformStatePull", "terraformStateList", "terraformConsoleLockHolder", "terraformPlanLockContender", "terraformZeroChangeSavedPlan", "transientLockMutation")), "live proof boundary drift")
    require(all(execute.get(key) is False for key in ("stateContentMutation", "terraformInit", "terraformApply", "statePush", "destroy", "iamPolicyAttachment", "directLockWrite", "forceUnlock", "objectVersionRecovery", "automaticRetry")), "mutation authority drift")
    success = value.get("successGate")
    require(all(success.get(key) is True for key in ("canonicalRemoteStateBytesUnchanged", "exactAddressInventoryRequired", "lockObjectObservedDuringHolder", "contenderMustFailOnlyOnLockAcquisition", "holderMustExitCleanly", "lockObjectAbsentAfterRelease", "savedBinaryPlanRequired", "stateObjectVersionCountUnchanged")), "success gate drift")
    require(success.get("zeroChangePlanExitCode") == 0 and success.get("lockVersionDelta") == 2 and success.get("lockDeleteMarkerDelta") == 2, "proof count drift")
    require(success.get("resourceDriftAllowed") is False and success.get("createUpdateDeleteReplaceImportAllowed") is False, "zero-change gate drift")
    failure = value.get("failureBoundary")
    require(failure == {"nonLockContenderFailureAccepted": False, "ambiguousLockCleanupMeansStop": True, "automaticRetry": False, "automaticRollback": False, "preserveAllPrivateEvidence": True}, "failure boundary drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in ("publishesAwsAccount", "publishesBucket", "publishesKmsArn", "publishesRawLineage", "publishesStateBytes", "publishesPlanContents", "publishesStateObjectVersionIds", "publishesLockInfo", "publishesPrivatePaths")), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "redacted result drift")
    require(value.get("successor") == {"version": "v0.12.2.3.2", "scope": "reviewed-lock-and-plan-evidence-plus-object-version-recovery-request", "requiresSeparateReview": True}, "successor drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "package producer drift")


contract = load(contract_path)
validate(contract)
predecessor = load(predecessor_path)
require(predecessor.get("version") == contract["predecessor"]["version"] and predecessor.get("status") == contract["predecessor"]["requiredStatus"], "predecessor contract changed")

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
mutate(["recoveryBindings", "privateRecoveryRequestSha256"], "0" * 64)
mutate(["recoveryBindings", "recoveryResultSha256"], "0" * 64)
mutate(["recoveryBindings", "remoteStateSha256"], "0" * 64)
mutate(["recoveryBindings", "managedAddressCount"], 12)
mutate(["recoveryBindings", "stateObjectVersionCount"], 2)
mutate(["verifyBoundary", "terraformCommands"], True)
mutate(["verifyBoundary", "proofAuthorizedByVerify"], True)
mutate(["executeBoundary", "terraformInit"], True)
mutate(["executeBoundary", "terraformApply"], True)
mutate(["executeBoundary", "statePush"], True)
mutate(["executeBoundary", "directLockWrite"], True)
mutate(["executeBoundary", "forceUnlock"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "contenderMustFailOnlyOnLockAcquisition"], False)
mutate(["successGate", "zeroChangePlanExitCode"], 2)
mutate(["successGate", "resourceDriftAllowed"], True)
mutate(["successGate", "lockVersionDelta"], 1)
mutate(["failureBoundary", "ambiguousLockCleanupMeansStop"], False)
mutate(["privacyBoundary", "publishesLockInfo"], True)
mutate(["successor", "requiresSeparateReview"], False)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

spec = importlib.util.spec_from_file_location("remote_state_proof_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
example = load(example_path)
example["expectedMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)

source = executor_path.read_text()
for forbidden in ('"init", "-input=false"', '"state", "push"', '"force-unlock"', '"s3api", "put-object"', '"s3api", "delete-object"'):
    require(forbidden not in source, f"executor contains forbidden command: {forbidden}")
for marker in ('"console"', '"-lock-timeout=0s"', '"-lock-timeout=60s"', '"-detailed-exitcode"', '"state", "pull"', '"state", "list"', '"list-object-versions"'):
    require(marker in source, f"executor marker missing: {marker}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 3, "executable files are not tracked")
require(all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("terraform console", "-lock-timeout=0s", "zero-change", "v0.12.2.3.2"):
    require(marker in documentation, f"documentation marker missing: {marker}")
public_text = contract_path.read_text() + example_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public artifact contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public artifact contains an AWS account")
require("VersionId\"" not in public_text, "public artifact contains a state object version ID")

print(f"v0.12.2.3.1 remote-state proof contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1-bootstrap-remote-state-proof.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1-bootstrap-remote-state-proof.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1-bootstrap-remote-state-proof.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.0-remote-state-proof-and-recovery-design.sh"

echo "v0.12.2.3.1 guarded remote-state proof passed offline; no AWS or Terraform command was executed."

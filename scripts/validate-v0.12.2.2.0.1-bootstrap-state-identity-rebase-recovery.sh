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
contract_path = root / "delivery/contracts/v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.json"
predecessor_path = root / "delivery/contracts/v0.12.2.2-reviewed-bootstrap-state-migration.json"
example_path = root / "delivery/examples/v0.12.2.2.0.1-bootstrap-state-recovery-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.2.0.1-bootstrap-state-recovery.py"
test_path = root / "scripts/test-v0.12.2.2.0.1-bootstrap-state-recovery.py"
validator_path = root / "scripts/validate-v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.sh"
doc_path = root / "docs/V0.12.2.2.0.1_BOOTSTRAP_STATE_IDENTITY_REBASE_RECOVERY.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_text())


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery-v1", "schema drift")
    require(value.get("version") == "v0.12.2.2.0.1", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-read-only-identity-rebase-recovery-approval", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("incidentControlPlaneCommit") == "5e10d0edbca3be5e87fdc5446f03e6d5c4c374f5", "incident commit drift")
    predecessor = value.get("predecessor")
    require(predecessor == {
        "version": "v0.12.2.2",
        "contract": "delivery/contracts/v0.12.2.2-reviewed-bootstrap-state-migration.json",
        "requiredStatus": "delivered-awaiting-separate-state-migration-approval",
        "approvedMigrationExecutedOnce": True,
        "automaticRetryPerformed": False,
    }, "predecessor drift")
    incident = value.get("incidentBindings")
    require(incident.get("privateMigrationRequestSha256") == "dbf011baaf96661f4317da1edcbbca0b3f84596c15965d1edd9c038b1e5a6467", "migration request drift")
    require(incident.get("immutableBackupSha256") == "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995", "backup drift")
    require(incident.get("remoteStateSha256") == "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139", "remote state drift")
    require(incident.get("terraformInitSucceeded") is True and incident.get("backendConfigured") is True, "migration success evidence drift")
    require(incident.get("migrationResultPresent") is False and incident.get("migrationValidationPresent") is False, "incident stopping point drift")
    rebase = value.get("reviewedIdentityRebase")
    require(rebase.get("oldLineageSha256") == "0bacf9c12fd5f2485d1b2acac980b6295a0f612335533b6abe7d1d03e3f7dc90", "old lineage drift")
    require(rebase.get("newLineageSha256") == "4f42afe2b009593773f37059419ca3ea4e87ca89d4ef1a7ff1278d60f2ed2fab", "new lineage drift")
    require(rebase.get("lineageChanged") is True and rebase.get("oldSerial") == 20 and rebase.get("newSerial") == 1, "identity rebase drift")
    require(rebase.get("managedAddressCount") == 13 and rebase.get("dataAddressCount") == 9, "address count drift")
    require(all(rebase.get(key) is True for key in ("addressesEqual", "resourcesEqual", "outputsEqual", "semanticProjectionEqual", "postMigrationWorkingStateEmpty")), "semantic equality drift")
    require(rebase.get("resourcesSha256") == "9ae208cbf85c37a2b9820e41be80b852efcc3cbdade7d9caa7e425784be0556e", "resources drift")
    require(rebase.get("outputsSha256") == "695a5087bac5068c4a7ae30ac5d3edc5cb09e28bd8cfe591d11a0c2d0aca8b2b", "outputs drift")
    require(rebase.get("semanticProjectionSha256") == "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d", "semantic projection drift")
    interpretation = value.get("interpretation")
    require(interpretation == {
        "terraformCopiedResourcesAndOutputs": True,
        "remoteBackendEstablishedNewStateIdentity": True,
        "resourceMutationObserved": False,
        "outputMutationObserved": False,
        "addressMutationObserved": False,
        "v01222FailClosedBehaviorWasCorrect": True,
        "incidentMayBeAcceptedWithoutSecondMigration": True,
    }, "incident interpretation drift")
    verify = value.get("verifyBoundary")
    require(verify.get("awsCommands") is False and verify.get("terraformCommands") is False and verify.get("writesPrivateEvidence") is False, "verify command boundary drift")
    require(verify.get("requiresProtectedMain") is True and verify.get("requiresFreshWindow") is True and verify.get("revalidatesCompleteIncidentChain") is True and verify.get("revalidatesExactIdentityRebase") is True, "verify gate drift")
    require(verify.get("recoveryAuthorizedByVerify") is False, "verify grants authority")
    execute = value.get("executeBoundary")
    require(all(execute.get(key) is True for key in ("awsIdentityRead", "terraformStatePull", "terraformStateList", "s3StateObjectHead", "s3StateObjectVersionsRead", "reusesExistingBackendMetadata")), "read-only continuation drift")
    require(all(execute.get(key) is False for key in ("terraformInit", "terraformPlan", "terraformApply", "stateMigration", "statePush", "destroy", "iamPolicyAttachment", "automaticRetry", "automaticRollback")), "mutation authority drift")
    success = value.get("successGate")
    require(all(success.get(key) is True for key in ("remoteStateBytesMustMatchIncidentPull", "reviewedIdentityRebaseMustMatch", "stateListMustMatchExactAddresses", "sseKmsIdentityMustMatch", "bucketKeyMustBeEnabled", "exactlyOneCurrentStateObjectVersionRequired", "stateObjectDeleteMarkerForbidden", "preservedBackupsRemainUntouched")), "success gate drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in ("publishesAwsAccount", "publishesBucket", "publishesKmsArn", "publishesRawLineage", "publishesStateBytes", "publishesPrivatePaths", "publishesStateObjectVersionId")), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "redacted evidence drift")
    successor = value.get("successor")
    require(successor.get("version") == "v0.12.2.3" and successor.get("requiresSeparateApproval") is True, "successor drift")
    producer = value.get("packageProducer")
    require(producer == {"runsAws": False, "runsTerraform": False, "touchesPrivateEvidence": False, "performsRecovery": False}, "package producer drift")


contract = load(contract_path)
validate(contract)
predecessor = load(predecessor_path)
require(predecessor.get("version") == "v0.12.2.2" and predecessor.get("status") == contract["predecessor"]["requiredStatus"], "predecessor contract changed")

mutations = []
def mutate(path, value):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    mutations.append(item)

mutate(["status"], "complete")
mutate(["incidentControlPlaneCommit"], "0" * 40)
mutate(["predecessor", "approvedMigrationExecutedOnce"], False)
mutate(["predecessor", "automaticRetryPerformed"], True)
mutate(["incidentBindings", "privateMigrationRequestSha256"], "0" * 64)
mutate(["incidentBindings", "remoteStateSha256"], "0" * 64)
mutate(["incidentBindings", "terraformInitSucceeded"], False)
mutate(["incidentBindings", "migrationResultPresent"], True)
mutate(["reviewedIdentityRebase", "newLineageSha256"], "0" * 64)
mutate(["reviewedIdentityRebase", "newSerial"], 20)
mutate(["reviewedIdentityRebase", "managedAddressCount"], 12)
mutate(["reviewedIdentityRebase", "resourcesEqual"], False)
mutate(["reviewedIdentityRebase", "outputsSha256"], "0" * 64)
mutate(["reviewedIdentityRebase", "semanticProjectionEqual"], False)
mutate(["interpretation", "resourceMutationObserved"], True)
mutate(["verifyBoundary", "terraformCommands"], True)
mutate(["verifyBoundary", "recoveryAuthorizedByVerify"], True)
mutate(["executeBoundary", "terraformInit"], True)
mutate(["executeBoundary", "stateMigration"], True)
mutate(["executeBoundary", "statePush"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "stateObjectDeleteMarkerForbidden"], False)
mutate(["privacyBoundary", "publishesRawLineage"], True)
mutate(["successor", "requiresSeparateApproval"], False)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

spec = importlib.util.spec_from_file_location("identity_rebase_recovery_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
example = load(example_path)
example["expectedRecoveryMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)

source = executor_path.read_text()
require("init\", \"-input=false\"" not in source and "state\", \"push" not in source, "recovery source contains a state mutation command")
for marker in ("state\", \"pull", "state\", \"list", "head-object", "list-object-versions", "terraform_init_reexecuted\": False", "state_migration_reexecuted\": False"):
    require(marker in source, f"executor marker missing: {marker}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 3, "executable files are not tracked")
require(all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("v0.12.2.2 migration executor", "terraform state pull", "terraform state list", "v0.12.2.3"):
    require(marker in documentation, f"documentation marker missing: {marker}")

public_text = contract_path.read_text() + example_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public artifact contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public artifact contains an AWS account")
require("VersionId\": \"" not in public_text, "public artifact contains a state object version")

print(f"v0.12.2.2.0.1 identity-rebase recovery contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.2.0.1-bootstrap-state-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.2.0.1-bootstrap-state-recovery.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.2.0.1-bootstrap-state-recovery.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.2-reviewed-bootstrap-state-migration.sh"

echo "v0.12.2.2.0.1 bootstrap state identity-rebase recovery passed offline; no AWS or Terraform command was executed."

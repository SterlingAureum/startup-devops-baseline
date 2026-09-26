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
contract_path = root / "delivery/contracts/v0.12.2.2.1-bootstrap-state-migration-recovery-evidence.json"
recovery_path = root / "delivery/contracts/v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.json"
repair_path = root / "delivery/contracts/v0.12.2.2.0.2-identity-rebase-digest-encoding-repair.json"
doc_path = root / "docs/V0.12.2.2.1_BOOTSTRAP_STATE_MIGRATION_RECOVERY_EVIDENCE.md"
validator_path = root / "scripts/validate-v0.12.2.2.1-bootstrap-state-migration-recovery-evidence.sh"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.2.1-bootstrap-state-migration-recovery-evidence-v1", "schema drift")
    require(value.get("version") == "v0.12.2.2.1", "version drift")
    require(value.get("status") == "completed-redacted-bootstrap-state-migration-recovery-evidence", "status drift")
    require(value.get("recordedAfterProtectedMainCommit") == "04eeaf6685b56c645267605de4b28541ca45b3c4", "recording baseline drift")
    predecessors = value.get("predecessors")
    require(isinstance(predecessors, list) and [(item.get("version"), item.get("requiredStatus")) for item in predecessors] == [
        ("v0.12.2.2.0.1", "delivered-awaiting-separate-read-only-identity-rebase-recovery-approval"),
        ("v0.12.2.2.0.2", "delivered-offline-digest-encoding-repair"),
    ], "predecessor drift")
    identity = value.get("executionIdentity")
    require(identity == {
        "incidentControlPlaneCommit": "5e10d0edbca3be5e87fdc5446f03e6d5c4c374f5",
        "recoveryControlPlaneCommit": "04eeaf6685b56c645267605de4b28541ca45b3c4",
        "privateMigrationRequestSha256": "dbf011baaf96661f4317da1edcbbca0b3f84596c15965d1edd9c038b1e5a6467",
        "privateRecoveryRequestSha256": "e4c3f713fb00387dfbeb82e81d528b7eb0b262afe8d45fa9010fbb0b84d68612",
        "completedAtUtc": "2026-09-26T03:22:59Z",
    }, "execution identity drift")
    state = value.get("stateEvidence")
    require(state.get("immutableBackupSha256") == "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995", "backup drift")
    require(state.get("remoteStateSha256") == state.get("revalidatedRemoteStateSha256") == "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139", "remote state drift")
    require(state.get("oldLineageSha256") == "0bacf9c12fd5f2485d1b2acac980b6295a0f612335533b6abe7d1d03e3f7dc90", "old lineage drift")
    require(state.get("newLineageSha256") == "4f42afe2b009593773f37059419ca3ea4e87ca89d4ef1a7ff1278d60f2ed2fab", "new lineage drift")
    require(state.get("oldSerial") == 20 and state.get("newSerial") == 1, "serial drift")
    require(state.get("managedAddressCount") == 13 and state.get("dataAddressCount") == 9, "address count drift")
    require(state.get("semanticProjectionSha256") == "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d", "semantic projection drift")
    require(state.get("identityRebaseValidated") is True and state.get("resourceAndOutputContentPreserved") is True, "state acceptance drift")
    bindings = value.get("privateResultBindings")
    require(bindings == {
        "identityRebaseValidationSha256": "c6a560147ee4cd7c5fd787e9a895ebb90efd29cf2cbb23dae6a7943dd03d93b5",
        "recoveryResultSha256": "adeb7145db9751f3eabd47b8379173acffff666590079edc189eb75db56e66f2",
        "allReadOnlyCommandStderrEmpty": True,
    }, "result binding drift")
    remote = value.get("remoteObjectEvidence")
    require(remote == {
        "currentStateObjectVersionCount": 1,
        "stateObjectDeleteMarkerCount": 0,
        "sseKmsValidated": True,
        "bucketKeyValidated": True,
        "stateObjectVersionIdPublished": False,
    }, "remote object evidence drift")
    authority = value.get("authorityEvidence")
    require(authority.get("priorTerraformInitSucceeded") is True, "prior init evidence drift")
    require(all(authority.get(key) is False for key in (
        "terraformInitReexecuted", "stateMigrationReexecuted", "terraformPlanExecuted",
        "terraformApplyExecuted", "statePushExecuted", "destroyExecuted",
        "iamPolicyAttachmentExecuted", "automaticRetryPerformed", "automaticRollbackPerformed",
    )), "mutation evidence drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in (
        "publishesAwsAccount", "publishesBucket", "publishesKmsArn", "publishesRawLineage",
        "publishesStateBytes", "publishesPrivatePaths", "publishesStateObjectVersionId",
        "publishesRawCommandOutput",
    )), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsTimestampsAndBooleans") is True, "public evidence boundary drift")
    package = value.get("packageBoundary")
    require(all(package.get(key) is False for key in ("runsAws", "runsTerraform", "readsPrivateEvidence", "modifiesRemoteState", "addsLiveAuthority")), "package authority drift")
    successor = value.get("successor")
    require(successor.get("version") == "v0.12.2.3" and successor.get("requiresFreshRequestAndApproval") is True, "successor drift")


contract = json.loads(contract_path.read_text())
validate(contract)
recovery = json.loads(recovery_path.read_text())
repair = json.loads(repair_path.read_text())
require(recovery.get("status") == contract["predecessors"][0]["requiredStatus"], "recovery predecessor changed")
require(repair.get("status") == contract["predecessors"][1]["requiredStatus"], "repair predecessor changed")

mutations = []
def mutate(path, value):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    mutations.append(item)

mutate(["status"], "planned")
mutate(["recordedAfterProtectedMainCommit"], "0" * 40)
mutate(["executionIdentity", "recoveryControlPlaneCommit"], "0" * 40)
mutate(["executionIdentity", "privateRecoveryRequestSha256"], "0" * 64)
mutate(["executionIdentity", "completedAtUtc"], "2026-09-26T00:00:00Z")
mutate(["stateEvidence", "remoteStateSha256"], "0" * 64)
mutate(["stateEvidence", "newLineageSha256"], "0" * 64)
mutate(["stateEvidence", "newSerial"], 20)
mutate(["stateEvidence", "managedAddressCount"], 12)
mutate(["stateEvidence", "identityRebaseValidated"], False)
mutate(["privateResultBindings", "recoveryResultSha256"], "0" * 64)
mutate(["privateResultBindings", "allReadOnlyCommandStderrEmpty"], False)
mutate(["remoteObjectEvidence", "currentStateObjectVersionCount"], 2)
mutate(["remoteObjectEvidence", "stateObjectDeleteMarkerCount"], 1)
mutate(["remoteObjectEvidence", "stateObjectVersionIdPublished"], True)
mutate(["authorityEvidence", "terraformInitReexecuted"], True)
mutate(["authorityEvidence", "terraformApplyExecuted"], True)
mutate(["authorityEvidence", "automaticRetryPerformed"], True)
mutate(["privacyBoundary", "publishesRawLineage"], True)
mutate(["packageBoundary", "runsAws"], True)
mutate(["packageBoundary", "addsLiveAuthority"], True)
mutate(["successor", "requiresFreshRequestAndApproval"], False)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open evidence mutation {index}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.strip()
require(tracked.startswith("100755 "), "validator Git index mode drift")

public_text = contract_path.read_text() + doc_path.read_text()
require(re.search(r"arn:aws:", public_text) is None, "public evidence contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public evidence contains an AWS account")
for marker in ("one current object version", "executes no AWS or Terraform", "v0.12.2.3"):
    require(marker in doc_path.read_text(), f"documentation marker missing: {marker}")

print(f"v0.12.2.2.1 migration recovery evidence and {len(mutations)} fail-closed mutations passed offline.")
PY

bash "${ROOT_DIR}/scripts/validate-v0.12.2.2.0.2-identity-rebase-digest-encoding-repair.sh"

echo "v0.12.2.2.1 redacted migration recovery evidence passed offline; no AWS or Terraform command was executed."

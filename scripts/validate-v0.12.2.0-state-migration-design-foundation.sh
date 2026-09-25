#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

bash -n "${BASH_SOURCE[0]}"

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PYTHON'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.2.0-state-migration-design-foundation.json"
predecessor_path = root / "delivery/contracts/v0.12.1.2.1-state-bootstrap-execution-evidence.json"
document_path = root / "docs/V0.12.2.0_STATE_MIGRATION_DESIGN_FOUNDATION.md"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Missing file: {path.relative_to(root)}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"Expected JSON object: {path.relative_to(root)}")
    return value


def git_index_mode(relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0 and result.stdout.strip(), f"missing index entry: {relative}")
    return result.stdout.split()[0]


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.2.0-state-migration-design-foundation-v1", "schema drift")
    require(value.get("version") == "v0.12.2.0", "version drift")
    require(value.get("status") == "delivered-offline-bootstrap-state-migration-design", "unsafe status")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(
        value.get("implementationBaselineCommit") == "cdda05b3b98643ac690458787f43070b63ff7beb",
        "implementation baseline drift",
    )

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.1.2.1", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    require(
        predecessor.get("requiredStatus") == "completed-state-bootstrap-created-recovered-and-live-validated",
        "predecessor completion drift",
    )
    if check_files:
        prior = load(predecessor_path)
        require(prior.get("status") == predecessor["requiredStatus"], "predecessor not complete")
        require(prior.get("validatedOutcome", {}).get("managedStateAddressCount") == 13, "non-empty state not proven")
        require(prior.get("validatedOutcome", {}).get("bootstrapStateRemainsLocalAndPrivate") is True, "state already moved")
        require(prior.get("negativeExecutionEvidence", {}).get("stateMigrationExecuted") is False, "migration already recorded")

    first = value.get("firstMigration")
    require(isinstance(first, dict), "missing first migration")
    require(first.get("rootId") == "bootstrap", "first root drift")
    require(first.get("rootPath") == "infra/terraform/aws/state-bootstrap", "root path drift")
    require(first.get("localStatePath") == "infra/terraform/aws/state-bootstrap/terraform.tfstate", "local state path drift")
    require(
        first.get("backendConfigExample") == "infra/terraform/aws/backend-config/bootstrap.s3.tfbackend.example",
        "backend example drift",
    )
    require(first.get("remoteStateKey") == "bootstrap/terraform.tfstate", "state key drift")
    require(first.get("expectedManagedAddressCount") == 13, "managed address count drift")
    require(first.get("terraformMinimumVersion") == "1.11.0", "Terraform floor drift")
    require(first.get("terraformMaximumExclusiveVersion") == "2.0.0", "Terraform ceiling drift")
    for key in ("nonEmptyStateRequired", "defaultWorkspaceOnly"):
        require(first.get(key) is True, f"first migration guard disabled: {key}")

    sequence = value.get("rootSequencing")
    require(isinstance(sequence, dict), "missing root sequencing")
    for key in (
        "bootstrapMigratesFirst",
        "oneRootPerApprovalAndExecutionWindow",
        "runtimeIdentitiesAndEnvironmentRootsRemainLocal",
        "existingRootFloorRaiseRequiredBeforeEachLaterMigration",
    ):
        require(sequence.get(key) is True, f"root sequence guard disabled: {key}")
    for key in ("parallelRootMigrationAllowed", "emptyStateAcceptedAsMigrationEvidence", "floorRaiseMayShareMigrationExecutionWindow"):
        require(sequence.get(key) is False, f"unsafe root sequence enabled: {key}")

    preflight = value.get("privatePreflightEvidence")
    require(isinstance(preflight, dict) and preflight, "missing private preflight")
    require(all(item is True for item in preflight.values()), "private preflight control disabled")

    backup = value.get("immutableBackup")
    require(isinstance(backup, dict), "missing immutable backup")
    require(backup.get("ownerOnlyDirectoryMode") == "0700", "backup directory mode drift")
    require(backup.get("ownerOnlyFileMode") == "0600", "backup file mode drift")
    for key in (
        "createdBeforeBackendInitialization",
        "sha256Recorded",
        "lineageAndSerialRecorded",
        "storedOutsideRepository",
        "retainedAfterSuccess",
    ):
        require(backup.get(key) is True, f"backup control disabled: {key}")
    require(backup.get("automaticDeletionAllowed") is False, "automatic backup deletion enabled")

    migration = value.get("migrationCommandDesign")
    require(isinstance(migration, dict), "missing migration command design")
    require(migration.get("backendType") == "s3", "backend type drift")
    for key in (
        "partialBackendConfigurationRequired",
        "terraformInitMigrateStateRequired",
        "terraformInitForceCopyRequiresSeparateApproval",
    ):
        require(migration.get(key) is True, f"migration command guard disabled: {key}")
    for key in (
        "credentialsInBackendConfigAllowed",
        "terraformApplyAllowed",
        "terraformDestroyAllowed",
        "terraformStatePushAllowed",
        "terraformStatePushForceAllowed",
        "terraformImportAllowed",
        "resourceAddressRefactorAllowed",
        "moduleUpgradeAllowed",
        "providerUpgradeAllowed",
        "platformUpgradeAllowed",
    ):
        require(migration.get(key) is False, f"unsafe migration command enabled: {key}")

    proof = value.get("postMigrationProof")
    require(isinstance(proof, dict) and proof, "missing post-migration proof")
    require(all(item is True for item in proof.values()), "post-migration proof disabled")

    drill = value.get("recoveryDrillBoundary")
    require(isinstance(drill, dict), "missing recovery drill boundary")
    for key in (
        "separateApprovalRequired",
        "separateExecutionWindowRequired",
        "reviewedObjectVersionIdsRequired",
        "canonicalStateLockRequired",
        "preDrillRemoteStateBackupRequired",
        "controlledObjectVersionRecoveryRequired",
        "postRecoveryLineageAddressAndIdentityVerificationRequired",
        "postRecoveryZeroChangePlanRequired",
    ):
        require(drill.get(key) is True, f"recovery drill control disabled: {key}")
    for key in ("automaticRollbackAllowed", "unreviewedS3CopyAllowed", "forceStatePushAllowed"):
        require(drill.get(key) is False, f"unsafe recovery behavior enabled: {key}")

    failure = value.get("failureBoundary")
    require(isinstance(failure, dict), "missing failure boundary")
    for key in ("automaticMigrationRetryAllowed", "automaticBackendRollbackAllowed", "automaticLocalStateDeletionAllowed", "uncertaintyMeansSuccess"):
        require(failure.get(key) is False, f"unsafe failure behavior enabled: {key}")
    for key in ("preservePrivateEvidence", "preserveLocalBackup", "preserveRemoteObjectVersions", "manualReviewRequiredAfterAmbiguousInit"):
        require(failure.get(key) is True, f"failure preservation disabled: {key}")

    producer = value.get("packageProducer")
    require(isinstance(producer, dict) and producer and all(item is False for item in producer.values()), "package claims live effect")
    implementation = value.get("implementationSequence")
    require(isinstance(implementation, list) and len(implementation) == 3, "implementation sequence drift")
    require([item.get("version") for item in implementation] == ["v0.12.2.1", "v0.12.2.2", "v0.12.2.3"], "implementation version drift")
    require([item.get("liveMutation") for item in implementation] == [False, True, True], "implementation authority drift")

    if check_files:
        require(document_path.is_file() and not document_path.is_symlink(), "missing design document")
        validator = "scripts/validate-v0.12.2.0-state-migration-design-foundation.sh"
        require(git_index_mode(validator) == "100755", "Git executable mode drift: design validator")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("predecessor incomplete", lambda item: item["predecessor"].__setitem__("requiredStatus", "partial")),
    ("empty state accepted", lambda item: item["firstMigration"].__setitem__("nonEmptyStateRequired", False)),
    ("wrong state key", lambda item: item["firstMigration"].__setitem__("remoteStateKey", "shared/terraform.tfstate")),
    ("parallel migration", lambda item: item["rootSequencing"].__setitem__("parallelRootMigrationAllowed", True)),
    ("floor combined", lambda item: item["rootSequencing"].__setitem__("floorRaiseMayShareMigrationExecutionWindow", True)),
    ("remote key unchecked", lambda item: item["privatePreflightEvidence"].__setitem__("remoteStateKeyMustBeAbsent", False)),
    ("identity digest omitted", lambda item: item["privatePreflightEvidence"].__setitem__("resourceIdentityDigestRequired", False)),
    ("late backup", lambda item: item["immutableBackup"].__setitem__("createdBeforeBackendInitialization", False)),
    ("backup auto-delete", lambda item: item["immutableBackup"].__setitem__("automaticDeletionAllowed", True)),
    ("credentials tracked", lambda item: item["migrationCommandDesign"].__setitem__("credentialsInBackendConfigAllowed", True)),
    ("apply enabled", lambda item: item["migrationCommandDesign"].__setitem__("terraformApplyAllowed", True)),
    ("force push enabled", lambda item: item["migrationCommandDesign"].__setitem__("terraformStatePushForceAllowed", True)),
    ("address refactor enabled", lambda item: item["migrationCommandDesign"].__setitem__("resourceAddressRefactorAllowed", True)),
    ("lineage unchecked", lambda item: item["postMigrationProof"].__setitem__("lineageMustMatchBackup", False)),
    ("zero-change plan omitted", lambda item: item["postMigrationProof"].__setitem__("zeroChangeSavedPlanRequired", False)),
    ("lock proof omitted", lambda item: item["postMigrationProof"].__setitem__("s3NativeLockContentionProofRequired", False)),
    ("recovery shares window", lambda item: item["recoveryDrillBoundary"].__setitem__("separateExecutionWindowRequired", False)),
    ("unreviewed copy allowed", lambda item: item["recoveryDrillBoundary"].__setitem__("unreviewedS3CopyAllowed", True)),
    ("automatic retry", lambda item: item["failureBoundary"].__setitem__("automaticMigrationRetryAllowed", True)),
    ("uncertainty accepted", lambda item: item["failureBoundary"].__setitem__("uncertaintyMeansSuccess", True)),
    ("package migrates", lambda item: item["packageProducer"].__setitem__("migratesState", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

bootstrap_versions = (root / "infra/terraform/aws/state-bootstrap/versions.tf").read_text()
require('required_version = ">= 1.11.0, < 2.0.0"' in bootstrap_versions, "bootstrap Terraform floor drift")
for relative in (
    "infra/terraform/aws/runtime-identities/versions.tf",
    "infra/terraform/aws/environments/dev/versions.tf",
    "infra/terraform/aws/environments/test/versions.tf",
    "infra/terraform/aws/environments/prod/versions.tf",
):
    require('required_version = ">= 1.8.0, < 2.0.0"' in (root / relative).read_text(), f"existing root floor changed early: {relative}")

successor_path = root / "delivery/contracts/v0.12.2.1-private-bootstrap-migration-preflight.json"
bootstrap_backend_path = root / "infra/terraform/aws/state-bootstrap/backend.tf"
if successor_path.exists():
    successor = load(successor_path)
    require(successor.get("version") == "v0.12.2.1", "unknown backend-declaration successor")
    require(
        successor.get("status") == "delivered-awaiting-separate-private-preflight-approval",
        "unsafe backend-declaration successor status",
    )
    require(
        successor.get("predecessor", {}).get("contract") == str(contract_path.relative_to(root)).replace(
            "v0.12.2.0-state-migration-design-foundation.json",
            "v0.12.2.0.1-private-bootstrap-state-location-repair.json",
        ),
        "backend successor chain drift",
    )
    backend_text = bootstrap_backend_path.read_text()
    require(backend_text.count('backend "s3" {}') == 1, "bootstrap partial backend declaration drift")
    for secret in ("access_key", "secret_key", "session_token"):
        require(secret not in backend_text, f"credential field present in bootstrap backend: {secret}")
else:
    require('backend "s3"' not in bootstrap_backend_path.read_text(), "backend activated early")

for relative in (
    "infra/terraform/aws/runtime-identities/backend.tf",
    "infra/terraform/aws/environments/dev/backend.tf",
    "infra/terraform/aws/environments/test/backend.tf",
    "infra/terraform/aws/environments/prod/backend.tf",
):
    require('backend "s3"' not in (root / relative).read_text(), f"backend activated early: {relative}")

backend_example = (root / contract["firstMigration"]["backendConfigExample"]).read_text()
for marker in (
    "bucket",
    'key                 = "bootstrap/terraform.tfstate"',
    'region              = "us-east-1"',
    "encrypt             = true",
    "kms_key_id",
    "use_lockfile        = true",
):
    require(marker in backend_example, f"backend example marker missing: {marker}")
for secret in ("access_key", "secret_key", "session_token"):
    require(secret not in backend_example, f"credential field present: {secret}")

document = " ".join(document_path.read_text().split()).replace("`", "")
for fragment in (
    "does not change a backend declaration",
    "13-address state",
    "one root is migrated per approval and execution window",
    "terraform init -migrate-state",
    "never use terraform state push -force",
    "v0.12.2.1 adds command-free verification",
):
    require(fragment.lower() in document.lower(), f"design document marker missing: {fragment}")

public_text = contract_path.read_text() + "\n" + document_path.read_text()
for pattern, label in (
    (r"arn:aws(?:-[a-z]+)?:", "AWS ARN"),
    (r"(?<![0-9])[0-9]{12}(?![0-9])", "AWS account-like identifier"),
    (r"/(?:home|Users)/[^/\s]+/", "user home path"),
):
    require(re.search(pattern, public_text) is None, f"public design contains {label}")

print("v0.12.2.0 migration design contract and 21 fail-closed mutations passed offline.")
PYTHON

bash "${ROOT_DIR}/scripts/validate-v0.12.1.2.1-state-bootstrap-execution-evidence.sh"

echo "v0.12.2.0 migration design foundation passed offline; no AWS or Terraform command was executed."

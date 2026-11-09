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
contract_path = root / "delivery/contracts/v0.12.2.0.1-private-bootstrap-state-location-repair.json"
predecessor_path = root / "delivery/contracts/v0.12.2.0-state-migration-design-foundation.json"
evidence_path = root / "delivery/contracts/v0.12.1.2.1-state-bootstrap-execution-evidence.json"
document_path = root / "docs/V0.12.2.0.1_PRIVATE_BOOTSTRAP_STATE_LOCATION_REPAIR.md"


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
    require(
        value.get("schemaVersion") == "v0.12.2.0.1-private-bootstrap-state-location-repair-v1",
        "schema drift",
    )
    require(value.get("version") == "v0.12.2.0.1", "version drift")
    require(value.get("status") == "delivered-offline-private-state-location-repair", "unsafe status")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(
        value.get("implementationBaselineCommit") == "c9008874bbcc1c864114c9067d7d54026f5f1338",
        "implementation baseline drift",
    )

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.2.0", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    require(predecessor.get("supersededField") == "firstMigration.localStatePath", "superseded field drift")

    mismatch = value.get("observedMismatch")
    require(isinstance(mismatch, dict), "missing mismatch classification")
    require(
        mismatch.get("incorrectTrackedPath") == "infra/terraform/aws/state-bootstrap/terraform.tfstate",
        "incorrect path drift",
    )
    require(mismatch.get("trackedPathWasApplyTarget") is False, "tracked path incorrectly accepted")
    require(mismatch.get("actualApplyUsedPrivateStagedSource") is True, "private apply source not recorded")
    require(mismatch.get("actualRecoveryVerifiedPrivateStagedSource") is True, "private recovery proof missing")
    require(mismatch.get("repositoryStateFileRequired") is False, "repository state required")

    evidence = value.get("canonicalPrivateStateEvidence")
    require(isinstance(evidence, dict), "missing canonical private state evidence")
    require(evidence.get("planBundleRequestField") == "privatePlanBundleDirectory", "plan bundle field drift")
    require(evidence.get("planBundleStateRelativePath") == "source/terraform.tfstate", "working state path drift")
    require(evidence.get("applyOutputRequestField") == "privateApplyOutputDirectory", "apply output field drift")
    require(
        evidence.get("preservedApplyStateRelativePath") == "state-bootstrap.tfstate.applied",
        "preserved state path drift",
    )
    require(
        evidence.get("expectedAppliedStateSha256")
        == "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995",
        "applied state digest drift",
    )
    for key in (
        "copiesMustBeByteIdentical",
        "bothFilesMustBeRegularAndNotSymlinks",
        "bothFilesMustBeMode0600",
        "bothParentsMustRemainPrivate",
    ):
        require(evidence.get(key) is True, f"private state evidence guard disabled: {key}")
    for key in ("privatePathsMayBePublished", "stateBytesMayBePublished"):
        require(evidence.get(key) is False, f"private state publication enabled: {key}")

    boundary = value.get("migrationSourceBoundary")
    require(isinstance(boundary, dict), "missing migration source boundary")
    for key in (
        "sourceIsPrivatePlanBundleWorkingState",
        "preservedApplyCopyIsIndependentCrossCheck",
        "sourceMustRemainBoundToOriginalPlanApplyRecoveryChain",
        "newImmutableBackupMustCopyCanonicalPrivateSource",
        "newBackupMustNotReplaceExistingEvidenceCopies",
    ):
        require(boundary.get(key) is True, f"source boundary disabled: {key}")
    for key in (
        "repositoryRootStateMayBeCreatedOrSelected",
        "unreviewedStateFileMayBeSelected",
        "sourceMayBeRenamedMovedOrEditedBeforeMigration",
    ):
        require(boundary.get(key) is False, f"unsafe source behavior enabled: {key}")

    request = value.get("v01221RequestBoundary")
    require(isinstance(request, dict), "missing v0.12.2.1 request boundary")
    for key, item in request.items():
        if key == "trackedRepositoryStatePathAccepted":
            require(item is False, "tracked repository state accepted")
        else:
            require(item is True, f"future request binding disabled: {key}")

    execution = value.get("executionBoundary")
    require(isinstance(execution, dict), "missing execution boundary")
    require(execution.get("offlineRepairOnly") is True, "repair is not offline-only")
    for key, item in execution.items():
        if key != "offlineRepairOnly":
            require(item is False, f"live repair effect enabled: {key}")

    successor = value.get("successor")
    require(isinstance(successor, dict), "missing successor")
    require(successor.get("version") == "v0.12.2.1", "successor version drift")
    require("original-plan-apply-recovery-state-chain" in successor.get("scope", ""), "successor chain missing")

    if check_files:
        prior = load(predecessor_path)
        require(prior.get("version") == "v0.12.2.0", "invalid predecessor")
        require(
            prior.get("firstMigration", {}).get("localStatePath") == mismatch["incorrectTrackedPath"],
            "predecessor mismatch no longer reproducible",
        )
        terminal = load(evidence_path)
        require(
            terminal.get("artifactBindings", {}).get("appliedStateSha256")
            == evidence["expectedAppliedStateSha256"],
            "terminal evidence state digest mismatch",
        )
        require(document_path.is_file() and not document_path.is_symlink(), "missing repair document")
        validator = "scripts/validate-v0.12.2.0.1-private-bootstrap-state-location-repair.sh"
        require(git_index_mode(validator) == "100755", "Git executable mode drift: repair validator")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("wrong superseded field", lambda item: item["predecessor"].__setitem__("supersededField", "none")),
    ("tracked path accepted", lambda item: item["observedMismatch"].__setitem__("trackedPathWasApplyTarget", True)),
    ("repository state required", lambda item: item["observedMismatch"].__setitem__("repositoryStateFileRequired", True)),
    ("working path changed", lambda item: item["canonicalPrivateStateEvidence"].__setitem__("planBundleStateRelativePath", "terraform.tfstate")),
    ("preserved path changed", lambda item: item["canonicalPrivateStateEvidence"].__setitem__("preservedApplyStateRelativePath", "state.tfstate")),
    ("digest changed", lambda item: item["canonicalPrivateStateEvidence"].__setitem__("expectedAppliedStateSha256", "0" * 64)),
    ("byte comparison removed", lambda item: item["canonicalPrivateStateEvidence"].__setitem__("copiesMustBeByteIdentical", False)),
    ("paths published", lambda item: item["canonicalPrivateStateEvidence"].__setitem__("privatePathsMayBePublished", True)),
    ("unreviewed state selected", lambda item: item["migrationSourceBoundary"].__setitem__("unreviewedStateFileMayBeSelected", True)),
    ("source edited", lambda item: item["migrationSourceBoundary"].__setitem__("sourceMayBeRenamedMovedOrEditedBeforeMigration", True)),
    ("backup replaces evidence", lambda item: item["migrationSourceBoundary"].__setitem__("newBackupMustNotReplaceExistingEvidenceCopies", False)),
    ("prior request omitted", lambda item: item["v01221RequestBoundary"].__setitem__("privateRecoveryRequestRequired", False)),
    ("repository fallback accepted", lambda item: item["v01221RequestBoundary"].__setitem__("trackedRepositoryStatePathAccepted", True)),
    ("repair copies state", lambda item: item["executionBoundary"].__setitem__("copiesState", True)),
    ("repair migrates", lambda item: item["executionBoundary"].__setitem__("migratesState", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

apply_source = (root / "scripts/execute-v0.12.1.2-state-bootstrap-apply.py").read_text()
for marker in (
    'Path(apply_request["privatePlanBundleDirectory"])',
    'Path(apply_request["privateApplyOutputDirectory"])',
    'state_path = source / "terraform.tfstate"',
    'state_copy = output / "state-bootstrap.tfstate.applied"',
):
    require(marker in apply_source, f"apply source-location marker missing: {marker}")

recovery_source = (root / "scripts/execute-v0.12.1.2.0.1-state-bootstrap-recovery.py").read_text()
for marker in (
    'bundle = require_private_directory(Path(request["privatePlanBundleDirectory"])',
    'state_copy = require_private_file(failed_output / "state-bootstrap.tfstate.applied"',
    'working_state = source / "terraform.tfstate"',
    'file_sha256(working_state) == request["appliedStateSha256"]',
):
    require(marker in recovery_source, f"recovery source-location marker missing: {marker}")

document = " ".join(document_path.read_text().split()).replace("`", "")
for fragment in (
    "corrects one design-only state-location assumption",
    "source/terraform.tfstate",
    "state-bootstrap.tfstate.applied",
    "repository-root state path is neither required nor accepted as a fallback",
    "does not establish a live approval window",
):
    require(fragment.lower() in document.lower(), f"repair document marker missing: {fragment}")

public_text = contract_path.read_text() + "\n" + document_path.read_text()
for pattern, label in (
    (r"arn:aws(?:-[a-z]+)?:", "AWS ARN"),
    (r"(?<![0-9])[0-9]{12}(?![0-9])", "AWS account-like identifier"),
    (r"/(?:home|Users)/[^/\s]+/", "user home path"),
):
    require(re.search(pattern, public_text) is None, f"public repair contains {label}")

print("v0.12.2.0.1 private state-location repair and 15 fail-closed mutations passed offline.")
PYTHON

bash "${ROOT_DIR}/scripts/validate-v0.12.2.0-state-migration-design-foundation.sh"

echo "v0.12.2.0.1 private state-location repair passed offline; no AWS or Terraform command was executed."

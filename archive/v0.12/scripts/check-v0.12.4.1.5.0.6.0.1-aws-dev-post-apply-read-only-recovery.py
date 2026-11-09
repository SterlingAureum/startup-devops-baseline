#!/usr/bin/env python3
"""Offline contract checker for aws-dev post-apply read-only recovery."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


BASELINE = "d5faf42112066831e53fbd761c603f815d06884a"
APPLY_REQUEST = "c8a3e0a33019246ef5a34f9f17024e1f2c4fd095047dc5f38aa6eef616ceca4b"
STATE = "d3960815889c8d192ffc09b19a98a11f965ed660670ce87d07701944bce3e205"
LINEAGE = "e7607c625b0ce10f80d09715b8bfb43b6e0a251a82aeabe08f52fb4296ed0391"
PRIOR_DATA = "3d28dc57ff69f6763bd6aafe3ef78930ee177cc3d1dddc59f49d58f6a4336cb6"
STATE_INVENTORY = "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def changed(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    result = copy.deepcopy(value)
    cursor: Any = result
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return result


def validate_contract(value: Any) -> None:
    require(isinstance(value, dict), "contract must be an object")
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.6.0.1", "version drift")
    require(value.get("status") == "aws-dev-post-apply-read-only-recovery-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == BASELINE, "baseline drift")
    require(value.get("incidentEvidence") == {
        "privateApplyRequestSha256": APPLY_REQUEST,
        "applySummary": "90 added, 0 changed, 0 destroyed.",
        "applyStderrEmpty": True,
        "stateSha256": STATE,
        "stateLineageSha256": LINEAGE,
        "stateSerial": 9,
        "reviewedManagedAddressCount": 90,
        "reviewedDataAddressCount": 6,
        "priorStateDataAddressCount": 7,
        "priorStateDataAddressSha256": PRIOR_DATA,
        "totalStateAddressCount": 103,
        "totalStateAddressSha256": STATE_INVENTORY,
        "unexplainedAddressCount": 0,
    }, "incident evidence drift")
    require(value.get("verifyPhase") == {
        "operationalCommandsAllowed": False,
        "protectedMainMustBeExactAndClean": True,
        "originalApplyRequestMustMatch": True,
        "successfulApplyEvidenceMustMatch": True,
        "preservedStateMustMatch": True,
        "reviewedPlusPriorStateInventoryMustMatch": True,
        "recoveryOutputMustBeNew": True,
    }, "verify boundary drift")
    require(value.get("executePhase") == {
        "requiredConfirmationVariable": "CONFIRM_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY",
        "requiredConfirmationValue": "recover-aws-dev-post-apply-validation-read-only",
        "awsIdentityReadAllowed": True,
        "eksDescribeClusterAllowed": True,
        "s3ObjectHistoryReadAllowed": True,
        "terraformStateReadAllowed": True,
        "terraformInitAllowed": False,
        "terraformPlanAllowed": False,
        "terraformApplyAllowed": False,
        "terraformDestroyAllowed": False,
        "expectedManagedStateAddressCount": 90,
        "expectedReviewedDataStateAddressCount": 6,
        "expectedPriorStateDataAddressCount": 7,
        "expectedTotalStateAddressCount": 103,
        "eksClusterMustBeActive": True,
    }, "execute boundary drift")
    require(value.get("stateAndLockBoundary") == {
        "stateMustEqualPreservedPostApplyState": True,
        "stateObjectVersionDeltaFromPreApplyMustBePositive": True,
        "stateDeleteMarkerDeltaMustBe": 0,
        "nativeLockObjectVersionDeltaFromPreApplyMustBe": 1,
        "nativeLockDeleteMarkerDeltaFromPreApplyMustBe": 1,
        "nativeLockMustBeAbsent": True,
        "statePushAllowed": False,
        "stateMigrationAllowed": False,
        "directS3MutationAllowed": False,
        "forceUnlockAllowed": False,
    }, "state boundary drift")
    require(value.get("failureBoundary") == {
        "automaticRetryAllowed": False,
        "automaticRollbackAllowed": False,
        "automaticDestroyAllowed": False,
        "allPrivateEvidenceMustBePreserved": True,
    }, "failure boundary drift")
    require(value.get("privacyBoundary") == {
        "publicResultContainsRawResourceIdentity": False,
        "publicResultContainsManagementCidr": False,
        "publicResultContainsObjectVersionId": False,
        "rawStateAndTerraformShowRemainPrivate": True,
    }, "privacy boundary drift")
    require(value.get("successor") == {
        "version": "v0.12.4.1.5.0.7",
        "scope": "aws-dev-post-create-qualification-and-external-secrets-preflight-resume",
        "requiresSeparateApproval": True,
        "authorizedByThisCheckpoint": False,
    }, "successor drift")


def validate_repository(root: Path) -> dict[str, Any]:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.6.0.1_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.sh"
    contract = load(contract_path)
    validate_contract(contract)
    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("incidentEvidence", "privateApplyRequestSha256"), "0" * 64),
        (("incidentEvidence", "applyStderrEmpty"), False),
        (("incidentEvidence", "stateSha256"), "0" * 64),
        (("incidentEvidence", "stateSerial"), 8),
        (("incidentEvidence", "reviewedManagedAddressCount"), 89),
        (("incidentEvidence", "reviewedDataAddressCount"), 7),
        (("incidentEvidence", "priorStateDataAddressCount"), 6),
        (("incidentEvidence", "priorStateDataAddressSha256"), "0" * 64),
        (("incidentEvidence", "totalStateAddressCount"), 102),
        (("incidentEvidence", "unexplainedAddressCount"), 1),
        (("verifyPhase", "operationalCommandsAllowed"), True),
        (("verifyPhase", "successfulApplyEvidenceMustMatch"), False),
        (("executePhase", "terraformApplyAllowed"), True),
        (("executePhase", "terraformPlanAllowed"), True),
        (("executePhase", "expectedTotalStateAddressCount"), 96),
        (("stateAndLockBoundary", "directS3MutationAllowed"), True),
        (("stateAndLockBoundary", "nativeLockObjectVersionDeltaFromPreApplyMustBe"), 0),
        (("failureBoundary", "automaticRetryAllowed"), True),
        (("privacyBoundary", "publicResultContainsRawResourceIdentity"), True),
        (("successor", "authorizedByThisCheckpoint"), True),
    ]
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(changed(contract, path, replacement))
        except (AttributeError, ContractError, KeyError, TypeError):
            continue
        raise ContractError(f"fail-open mutation {index}")

    example = load(example_path)
    require(example.get("schemaVersion") == "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-request-v1", "example schema drift")
    require(example.get("operation") == "recover-aws-dev-post-apply-validation-read-only", "example operation drift")
    require(example.get("evidenceBoundary", {}).get("privateApplyRequestSha256") == APPLY_REQUEST, "example apply request drift")
    require(example.get("evidenceBoundary", {}).get("priorStateDataAddressSha256") == PRIOR_DATA, "example prior-data drift")
    require(example.get("evidenceBoundary", {}).get("totalStateAddressSha256") == STATE_INVENTORY, "example state inventory drift")
    boundary = example.get("executionBoundary", {})
    require(all(boundary.get(key) is True for key in ("awsIdentityRead", "eksDescribeCluster", "s3ObjectHistoryRead", "terraformVersionRead", "terraformStatePull", "terraformStateList", "terraformShowState")), "example read authority drift")
    require(all(boundary.get(key) is False for key in ("terraformInit", "terraformPlan", "terraformApply", "terraformDestroy", "statePush", "stateMigration", "directS3Mutation", "forceUnlock", "iamPolicyAttachment", "kubernetesCommand", "secretValueRead", "automaticRetry", "automaticRollback")), "example mutation authority drift")

    document = " ".join(document_path.read_text().split())
    for phrase in ("90 reviewed managed addresses", "six reviewed data addresses", "seven prior-state data addresses", "103 total", "zero unexplained addresses", "never executes Terraform init, plan, apply or destroy"):
        require(phrase in document, f"document boundary missing: {phrase}")
    executor = executor_path.read_text()
    for marker in (
        '"operational_commands_executed": []',
        '"terraform_apply_authorized": False',
        'prior_managed, prior_data = collect_value_addresses(prior_root)',
        'listed == expected_addresses',
        'listed == incident["expected_addresses"]',
        'APPLY.validate_after_apply_history',
        '"terraform_apply_executed_by_recovery": False',
    ):
        require(marker in executor, f"executor control missing: {marker}")
    for forbidden in ('["terraform", "apply"', '["terraform", "plan"', '["terraform", "init"', '["terraform", "destroy"', 'force-unlock', '-migrate-state', 'shell=True'):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.6.0.1 - AWS dev post-apply read-only recovery"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.6.0.1"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "recovery source tracking drift")
    modes: dict[str, str] = {}
    for line in tracked:
        metadata, path = line.split("\t", 1)
        modes[path] = metadata.split()[0]
    for path in (contract_path, example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode drift: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode drift: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"mutationCount": len(mutations), "liveCommandExecuted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = validate_repository(args.root.resolve(strict=True))
    print(f"v0.12.4.1.5.0.6.0.1 post-apply read-only recovery contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

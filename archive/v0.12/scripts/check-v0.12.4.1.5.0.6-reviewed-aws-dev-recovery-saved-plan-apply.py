#!/usr/bin/env python3
"""Offline contract gate for the reviewed aws-dev recovery saved-plan apply."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


BASELINE = "a20fba2eac0b4642b239193730ed72402065c1b5"
RECOVERY_REQUEST = "d77abf17613dd5b9d311292a3404a1799efe4f0468d920f95f3ead586193895d"
BINARY_PLAN = "4e69241462430992203d79674a2eefa70c309eb756b33a6874a8b8b38ee71a1b"
PLAN_JSON = "5f2de857159c042e8588b743ca66364015496dc16f78e215bee5c3da525ed3de"
PLAN_TEXT = "cc96ec46c0b8184bd47eff6dae5f968f83d2502bef1df8e2b782e8643c0ff02e"
INVENTORY = "8ee52b515704cf5e6e4a3824c06da83c7b639b52f6320c852f20d53ca99ead81"
PLAN_RECORD = "b0ac35c31977cc87f88ee3c568b6e76878bf21765ffe6be507ad9ae1401c57df"
LOCKFILE = "a824bda667aac25533101eb99e1b5c6ec5415cc5f2e773793f7b1699b453fd6f"
PLAN_EXPIRY = "2026-09-30T20:31:00Z"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def changed(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.6", "version drift")
    require(value.get("status") == "reviewed-aws-dev-recovery-saved-plan-apply-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == BASELINE, "baseline drift")
    reviewed = value.get("reviewedPlan")
    require(reviewed == {
        "privateRecoveryRequestSha256": RECOVERY_REQUEST,
        "binaryPlanSha256": BINARY_PLAN,
        "planJsonSha256": PLAN_JSON,
        "planTextSha256": PLAN_TEXT,
        "addressInventorySha256": INVENTORY,
        "planRecordSha256": PLAN_RECORD,
        "providerLockfileSha256": LOCKFILE,
        "managedCreateCount": 90,
        "dataReadOrNoopCount": 6,
        "resourceDriftCount": 0,
        "importCount": 0,
        "planReviewExpiresAtUtc": PLAN_EXPIRY,
        "humanReviewRequired": True,
    }, "reviewed plan drift")
    private = value.get("privateRequest")
    require(private == {
        "schemaVersion": "v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-request-v1",
        "operation": "apply-reviewed-aws-dev-recovery-saved-create-plan",
        "maximumApprovalWindowSeconds": 10800,
        "minimumRemainingApprovalSeconds": 900,
        "approvalMustEndByPlanReviewExpiry": True,
        "requestAndEvidenceMustRemainOutsideRepository": True,
        "privateFileMode": "0600", "privateDirectoryMode": "0700", "applyOutputMustBeNew": True,
    }, "private request drift")
    verify = value.get("verifyPhase")
    require(verify == {
        "protectedMainMustBeExactAndClean": True,
        "recoveryRequestAndAllReviewedDigestsMustMatch": True,
        "recoverySourceMustMatchImmutableTerraformSource": True,
        "planMustRemainCompleteAndApplyable": True,
        "managedActionsMustRemainCreateOnly": True,
        "dataActionsMustRemainReadOrNoop": True,
        "resourceDriftCountMustBe": 0, "importCountMustBe": 0,
        "awsCommandsAllowed": False, "terraformCommandsAllowed": False,
        "operationalCommandsExecuted": [],
    }, "verify boundary drift")
    execute = value.get("executePhase")
    require(execute == {
        "requiredConfirmationVariable": "CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY",
        "requiredConfirmationValue": "apply-reviewed-aws-dev-recovery-saved-create-plan",
        "terraformInitAllowed": False, "terraformPlanAllowed": False,
        "terraformApplyArguments": ["apply", "-input=false", "-auto-approve", "EXACT_REVIEWED_BINARY_PLAN"],
        "exactSavedPlanApplyCount": 1, "unsavedApplyAllowed": False,
        "preApplyAwsAndPlanEvidenceReadsAllowed": True,
        "postApplyTerraformStateAndAwsReadsAllowed": True,
        "expectedManagedStateAddressCount": 90, "expectedDataStateAddressCount": 6,
        "expectedTotalStateAddressCount": 96, "eksClusterMustBeActiveAfterApply": True,
        "automaticRetry": False, "automaticRollback": False,
    }, "execute boundary drift")
    state = value.get("stateAndLockBoundary")
    require(state == {
        "remoteStateMustBeAbsentBeforeApply": True,
        "remoteStateVersionDeltaMustBePositive": True,
        "remoteStateDeleteMarkerDeltaMustBe": 0,
        "nativeLockObjectVersionDeltaMustBe": 1,
        "nativeLockDeleteMarkerDeltaMustBe": 1,
        "nativeLockMustBeAbsentAfterApply": True,
        "directS3MutationAllowed": False, "statePushAllowed": False,
        "stateMigrationAllowed": False, "forceUnlockAllowed": False,
    }, "state boundary drift")
    failure = value.get("failureBoundary")
    require(failure == {
        "failedApplyMustStop": True, "postApplyValidationFailureMustPreserveWrittenState": True,
        "automaticRetryAllowed": False, "automaticRollbackAllowed": False,
        "automaticDestroyAllowed": False,
    }, "failure boundary drift")
    privacy = value.get("privacyBoundary")
    require(privacy == {
        "publicResultContainsManagementCidr": False,
        "publicResultContainsRawResourceIdentity": False,
        "publicResultContainsObjectVersionId": False,
        "rawStateAndTerraformShowRemainPrivate": True,
    }, "privacy boundary drift")
    forbidden = set(value.get("forbiddenOperations", []))
    require({
        "terraform-init", "terraform-plan", "terraform-destroy", "terraform-state-push",
        "terraform-state-migration", "terraform-force-unlock", "unsaved-terraform-apply",
        "direct-s3-state-mutation", "direct-s3-lock-mutation", "iam-policy-attachment",
        "kubernetes-command", "secret-value-read", "automatic-retry", "automatic-rollback",
    } == forbidden, "forbidden operation drift")
    require(value.get("overallGate") == {
        "status": "blocked-awaiting-private-apply-request-verification-and-separate-apply-approval",
        "terraformApplyExecuted": False, "environmentCreated": False, "stateWritten": False,
    }, "overall gate drift")
    require(value.get("successor") == {
        "version": "v0.12.4.1.5.0.7",
        "scope": "aws-dev-post-create-qualification-and-external-secrets-preflight-resume",
        "requiresSeparateApproval": True, "authorizedByThisCheckpoint": False,
    }, "successor drift")


def validate_repository(root: Path) -> dict[str, Any]:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.6_REVIEWED_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.sh"
    contract = load(contract_path)
    validate_contract(contract)
    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("reviewedPlan", "privateRecoveryRequestSha256"), "0" * 64),
        (("reviewedPlan", "binaryPlanSha256"), "0" * 64),
        (("reviewedPlan", "managedCreateCount"), 89),
        (("reviewedPlan", "dataReadOrNoopCount"), 7),
        (("reviewedPlan", "resourceDriftCount"), 1),
        (("reviewedPlan", "planReviewExpiresAtUtc"), "2026-10-01T20:31:00Z"),
        (("privateRequest", "maximumApprovalWindowSeconds"), 86400),
        (("privateRequest", "approvalMustEndByPlanReviewExpiry"), False),
        (("verifyPhase", "awsCommandsAllowed"), True),
        (("verifyPhase", "terraformCommandsAllowed"), True),
        (("executePhase", "terraformInitAllowed"), True),
        (("executePhase", "terraformPlanAllowed"), True),
        (("executePhase", "exactSavedPlanApplyCount"), 2),
        (("executePhase", "expectedTotalStateAddressCount"), 95),
        (("stateAndLockBoundary", "directS3MutationAllowed"), True),
        (("stateAndLockBoundary", "nativeLockDeleteMarkerDeltaMustBe"), 0),
        (("failureBoundary", "automaticRetryAllowed"), True),
        (("privacyBoundary", "publicResultContainsManagementCidr"), True),
        (("overallGate", "terraformApplyExecuted"), True),
        (("successor", "authorizedByThisCheckpoint"), True),
    ]
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(changed(contract, path, replacement))
        except (AttributeError, ContractError, KeyError, TypeError):
            continue
        raise ContractError(f"fail-open mutation {index}")

    example = load(example_path)
    require(example.get("schemaVersion") == contract["privateRequest"]["schemaVersion"], "example schema drift")
    require(example.get("operation") == contract["privateRequest"]["operation"], "example operation drift")
    require(example.get("privateRecoveryRequestSha256") == RECOVERY_REQUEST, "example recovery request drift")
    require(example.get("reviewedArtifactSha256s", {}).get("aws-dev-create-recovery.tfplan") == BINARY_PLAN, "example binary plan drift")
    require(example.get("reviewedProviderLockfileSha256") == LOCKFILE, "example lockfile drift")
    require(example.get("humanReview", {}).get("managedCreateCount") == 90, "example managed count drift")
    require(example.get("humanReview", {}).get("dataReadOrNoopCount") == 6, "example data count drift")
    require(example.get("approval", {}).get("planReviewExpiresAtUtc") == PLAN_EXPIRY, "example plan expiry drift")
    boundary = example.get("executionBoundary")
    require(isinstance(boundary, dict), "example boundary missing")
    require(all(boundary.get(key) is True for key in ("awsReadOnlyValidation", "terraformShowExistingPlan", "exactSavedPlanApply", "terraformStateRead")), "example required authority drift")
    disabled = {
        "terraformInit", "terraformPlan", "unsavedApply", "stateMigration", "statePush",
        "destroy", "iamPolicyAttachment", "kubernetesCommand", "".join(("secret", "ValueRead")),
        "directS3Mutation", "forceUnlock", "automaticRetry", "automaticRollback",
    }
    require(all(boundary.get(key) is False for key in disabled), "example enables forbidden authority")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "90 managed creates", "six data read/no-op", "does not run Terraform init or plan",
        "does not retry, roll back, destroy", "preserve all private evidence",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    executor = executor_path.read_text()
    for marker in (
        '"operational_commands_executed": []', '"apply_execution_authorized": False',
        '["terraform", "apply", "-input=false", "-auto-approve", str(binary_plan)]',
        'validate_before_apply_history', 'validate_after_apply_history',
        '"automatic_retry_performed": False', '"private_resource_identity_emitted": False',
    ):
        require(marker in executor, f"executor control missing: {marker}")
    require('"terraform", "init"' not in executor and '"terraform", "plan"' not in executor, "forbidden Terraform construction found")
    require("force-unlock" not in executor and "-migrate-state" not in executor and "shell=True" not in executor, "forbidden executable path found")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.6 - reviewed AWS dev recovery saved-plan apply"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.6"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "apply source tracking drift")
    modes = {}
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
    print(f"v0.12.4.1.5.0.6 reviewed saved-plan apply contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the guarded aws-dev remote-state saved create-plan contract."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


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


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.5-guarded-aws-dev-remote-state-saved-create-plan-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.5", "version drift")
    require(value.get("status") == "aws-dev-remote-state-saved-create-plan-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "37a5c9c90b6cfcfedefe2e5804c9e45744e7f0ec", "baseline drift")
    require(value.get("designedAtDate") == "2026-09-30", "date drift")
    require(value.get("predecessor") == {
        "path": "delivery/contracts/v0.12.4.1.5.0.4-guarded-aws-dev-remote-state-clean-room-preflight.json",
        "requiredStatus": "aws-dev-remote-state-clean-room-preflight-ready-offline",
        "requiredLiveStatus": "aws-dev-remote-state-clean-room-preflight-complete-awaiting-separate-plan-review",
        "requiresHumanReview": True,
    }, "predecessor drift")
    private = value.get("privateRequest")
    require(private == {
        "schemaVersion": "v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-request-v1",
        "operation": "produce-reviewed-aws-dev-clean-room-create-plan",
        "maximumApprovalWindowSeconds": 7200,
        "minimumRemainingApprovalSeconds": 900,
        "maximumPlanReviewLifetimeSeconds": 28800,
        "requestAndInputsMustRemainOutsideRepository": True,
        "privateFileMode": "0600",
        "privateDirectoryMode": "0700",
        "outputAndPlanSourceDirectoriesMustBeNew": True,
    }, "private request drift")
    verify = value.get("verifyPhase")
    require(isinstance(verify, dict) and len(verify) == 9, "verify phase shape drift")
    for key in (
        "protectedMainMustBeExactAndClean", "preflightRequestResultAndEvidenceDigestsMustMatch",
        "preflightMustBeHumanReviewed", "backendConfigAndTfvarsDigestsMustMatch",
        "stagedSourceManifestMustMatch", "remoteStateAndLockMustHaveBeenAbsent",
    ):
        require(verify.get(key) is True, f"verify control disabled: {key}")
    require(verify.get("awsCommandsAllowed") is False and verify.get("terraformCommandsAllowed") is False, "verify command authority enabled")
    require(verify.get("operationalCommandsExecuted") == [], "verify command inventory changed")
    execute = value.get("executePhase")
    require(isinstance(execute, dict) and len(execute) == 17, "execute phase shape drift")
    require(execute.get("requiredConfirmationVariable") == "CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN", "confirmation variable drift")
    require(execute.get("requiredConfirmationValue") == "produce-reviewed-aws-dev-clean-room-create-plan", "confirmation value drift")
    require(execute.get("terraformInitArguments") == ["init", "-input=false", "-reconfigure", "-backend-config=PRIVATE_COPY"], "init command drift")
    require(execute.get("terraformPlanMode") == "saved-create-plan" and execute.get("terraformPlanLockTimeout") == "0s", "plan mode drift")
    require(execute.get("terraformApplyAllowed") is False, "apply enabled")
    require(execute.get("expectedEksResult") == "ResourceNotFoundException", "EKS absence drift")
    require(execute.get("remoteStateVersionCountMustRemain") == 0 and execute.get("remoteStateDeleteMarkerCountMustRemain") == 0, "state write allowance enabled")
    require(execute.get("expectedPlanManagedActions") == ["create"], "managed action drift")
    require(execute.get("expectedPlanDataActions") == ["read", "no-op"], "data action drift")
    require(execute.get("resourceDriftCountMustBe") == 0 and execute.get("importCountMustBe") == 0, "drift or import allowed")
    require(execute.get("planMustBeCompleteAndApplyable") is True and execute.get("planReviewRequiresHumanApproval") is True, "plan gate weakened")
    require(execute.get("automaticRetry") is False, "automatic retry enabled")
    lock = value.get("lockHistoryBoundary")
    require(isinstance(lock, dict) and len(lock) == 7, "lock boundary shape drift")
    for key in ("nativeS3LockfileRequired", "lockMustBeAbsentBeforeAndAfter", "temporaryLockObjectVersionAllowed", "temporaryLockDeleteMarkerAllowed"):
        require(lock.get(key) is True, f"lock control disabled: {key}")
    for key in ("stateObjectWriteAllowed", "directS3MutationAllowed", "forceUnlockAllowed"):
        require(lock.get(key) is False, f"unsafe lock/state authority enabled: {key}")
    require(value.get("timeBoundary") == {
        "planExecutionWindowMaximumHours": 2,
        "savedPlanReviewLifetimeMaximumHours": 8,
        "futureApplyWindowMaximumHours": 3,
        "planAndApplyUseSeparateApprovals": True,
        "validationAfterApplyUsesSeparateApproval": True,
    }, "time boundary drift")
    forbidden = value.get("forbiddenOperations")
    require(isinstance(forbidden, list) and len(forbidden) == 15 and len(set(forbidden)) == 15, "forbidden inventory drift")
    for item in ("terraform-apply", "terraform-state-migration", "terraform-state-push", "direct-s3-state-or-lock-mutation", "terraform-force-unlock", "kubernetes-command", "secret-value-read", "automatic-retry"):
        require(item in forbidden, f"forbidden operation missing: {item}")
    evidence = value.get("privateEvidence")
    require(isinstance(evidence, dict) and len(evidence) == 9, "evidence shape drift")
    for key in ("binaryPlanRequired", "machineReadablePlanRequired", "humanReadablePlanRequired", "exactAddressInventoryRequired", "inputAndObjectHistoryDigestsRequired", "rawResourceIdentityRemainsPrivate", "failurePreservesEvidence"):
        require(evidence.get(key) is True, f"evidence control disabled: {key}")
    require(evidence.get("publicResultContainsResourceIdentity") is False and evidence.get("publicResultContainsObjectVersionId") is False, "private identity publication enabled")
    overall = value.get("overallGate")
    require(overall.get("status") == "blocked-awaiting-private-request-verification-and-separate-plan-approval", "overall status drift")
    require(len(overall) == 7 and all(item is False for key, item in overall.items() if key != "status"), "live authority enabled")
    require(value.get("successor") == {
        "version": "v0.12.4.1.5.0.6",
        "scope": "reviewed-aws-dev-exact-saved-create-plan-apply",
        "requiresHumanReviewOfPrivatePlan": True,
        "maximumApplyApprovalWindowSeconds": 10800,
        "authorizedByThisCheckpoint": False,
    }, "successor drift")


def changed(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def validate_repository(root: Path) -> dict[str, Any]:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.5-guarded-aws-dev-remote-state-saved-create-plan.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.5_GUARDED_AWS_DEV_REMOTE_STATE_SAVED_CREATE_PLAN.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.5-guarded-aws-dev-saved-create-plan.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.5-guarded-aws-dev-saved-create-plan.sh"
    contract = load(contract_path)
    validate_contract(contract)
    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("predecessor", "requiresHumanReview"), False),
        (("privateRequest", "maximumApprovalWindowSeconds"), 3600),
        (("privateRequest", "minimumRemainingApprovalSeconds"), 0),
        (("privateRequest", "maximumPlanReviewLifetimeSeconds"), 86400),
        (("verifyPhase", "preflightMustBeHumanReviewed"), False),
        (("verifyPhase", "backendConfigAndTfvarsDigestsMustMatch"), False),
        (("verifyPhase", "awsCommandsAllowed"), True),
        (("verifyPhase", "terraformCommandsAllowed"), True),
        (("executePhase", "terraformInitArguments"), ["init", "-migrate-state"]),
        (("executePhase", "terraformApplyAllowed"), True),
        (("executePhase", "expectedEksResult"), "AccessDeniedException"),
        (("executePhase", "remoteStateVersionCountMustRemain"), 1),
        (("executePhase", "expectedPlanManagedActions"), ["create", "update"]),
        (("executePhase", "resourceDriftCountMustBe"), 1),
        (("executePhase", "importCountMustBe"), 1),
        (("executePhase", "planReviewRequiresHumanApproval"), False),
        (("executePhase", "automaticRetry"), True),
        (("lockHistoryBoundary", "lockMustBeAbsentBeforeAndAfter"), False),
        (("lockHistoryBoundary", "stateObjectWriteAllowed"), True),
        (("lockHistoryBoundary", "directS3MutationAllowed"), True),
        (("lockHistoryBoundary", "forceUnlockAllowed"), True),
        (("timeBoundary", "planExecutionWindowMaximumHours"), 8),
        (("timeBoundary", "futureApplyWindowMaximumHours"), 1),
        (("timeBoundary", "planAndApplyUseSeparateApprovals"), False),
        (("privateEvidence", "exactAddressInventoryRequired"), False),
        (("privateEvidence", "publicResultContainsResourceIdentity"), True),
        (("overallGate", "terraformPlanExecuted"), True),
        (("overallGate", "environmentCreated"), True),
        (("successor", "requiresHumanReviewOfPrivatePlan"), False),
        (("successor", "maximumApplyApprovalWindowSeconds"), 3600),
        (("successor", "authorizedByThisCheckpoint"), True),
    ]
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(changed(contract, path, replacement))
        except (AttributeError, ContractError, KeyError, TypeError):
            continue
        raise ContractError(f"fail-open mutation {index}")
    predecessor = load(root / contract["predecessor"]["path"])
    require(predecessor.get("status") == contract["predecessor"]["requiredStatus"], "predecessor status drift")
    example = load(example_path)
    require(example.get("schemaVersion") == contract["privateRequest"]["schemaVersion"], "example schema drift")
    require(example.get("operation") == contract["privateRequest"]["operation"], "example operation drift")
    require(example.get("humanReview") == {"preflightReviewed": True, "reviewedMaximumBudgetUsd": 50}, "example human review drift")
    require(all(example["executionBoundary"].get(key) is False for key in ("terraformApply", "stateMigration", "statePush", "destroy", "iamPolicyAttachment", "kubernetesCommand", "secretValueRead", "automaticRetry", "automaticRollback")), "example enables forbidden authority")
    document = " ".join(document_path.read_text().split())
    for phrase in ("up to two hours", "up to eight hours", "up to three hours", "never `-migrate-state`", "does not apply the plan"):
        require(phrase in document, f"document boundary missing: {phrase}")
    executor = executor_path.read_text()
    for marker in ('"operational_commands_executed": []', '"terraform_apply_executed": False', '"state_migration_executed": False', '"private_resource_identity_emitted": False', 'terraform-plan-create', 'terraform-show-create-json', 'ResourceNotFoundException', 'create-plan-address-inventory.json'):
        require(marker in executor, f"executor control missing: {marker}")
    require("-migrate-state" not in executor and "force-unlock" not in executor and "shell=True" not in executor, "forbidden executable path found")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.5-guarded-aws-dev-remote-state-saved-create-plan"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.5 - guarded AWS dev remote-state saved create plan"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.5"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")
    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "create-plan source tracking drift")
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
    print(f"v0.12.4.1.5.0.5 guarded aws-dev saved create-plan contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

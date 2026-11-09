#!/usr/bin/env python3
"""Validate the guarded aws-dev remote-state clean-room preflight contract."""

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
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.4-guarded-aws-dev-remote-state-clean-room-preflight-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.4", "version drift")
    require(value.get("status") == "aws-dev-remote-state-clean-room-preflight-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "cf867c9bcec43987fddf601740385bf3521812df", "baseline drift")
    require(value.get("designedAtDate") == "2026-09-30", "date drift")
    require(value.get("predecessor") == {
        "path": "delivery/contracts/v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design.json",
        "requiredStatus": "aws-dev-remote-state-clean-room-reconstruction-designed-offline",
        "triggerOperation": "v0.12.4.1.5-external-secrets-live-preflight",
        "triggerErrorCode": "ResourceNotFoundException",
    }, "predecessor drift")
    require(value.get("partialBackend") == {
        "root": "infra/terraform/aws/environments/dev",
        "type": "s3",
        "emptyDeclarationOnly": True,
        "trackedBackendValues": False,
        "trackedCredentials": False,
        "exactKey": "environments/dev/terraform.tfstate",
        "nativeLockfile": True,
        "dynamodbLocking": False,
        "cleanRoomInitMode": "-reconfigure",
        "localStateMigration": False,
    }, "partial backend drift")
    require(value.get("privateRequest") == {
        "schemaVersion": "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-request-v1",
        "operation": "inspect-empty-aws-dev-remote-state-clean-room",
        "maximumApprovalWindowSeconds": 3600,
        "minimumRemainingApprovalSeconds": 900,
        "requestMustBeOutsideRepository": True,
        "requestMode": "0600",
        "requestParentMode": "0700",
        "backendConfigMustBeOutsideRepository": True,
        "backendConfigMode": "0600",
        "outputAndStagingDirectoriesMustBeNew": True,
        "outputAndStagingParentMode": "0700",
    }, "private request drift")

    verify = value.get("verifyPhase")
    require(isinstance(verify, dict) and len(verify) == 11, "verify phase shape drift")
    for key in (
        "protectedMainMustBeExactAndClean", "headAndOriginMainMustEqualRequestCommit",
        "partialBackendMustBeExact", "privateBackendConfigDigestMustMatch",
        "privateBackendConfigFieldsMustBeExact", "privateBackendIdentityMustMatchRequest",
        "approvalMustBeCurrentlyActive", "sourceManifestCalculatedFromTrackedFiles",
    ):
        require(verify.get(key) is True, f"verify control disabled: {key}")
    require(verify.get("awsCommandsAllowed") is False and verify.get("terraformCommandsAllowed") is False, "verify command authority enabled")
    require(verify.get("operationalCommandsExecuted") == [], "verify command inventory changed")

    execute = value.get("executePhase")
    require(isinstance(execute, dict) and len(execute) == 17, "execute phase shape drift")
    require(execute.get("requiredConfirmationVariable") == "CONFIRM_AWS_DEV_CLEAN_ROOM_PREFLIGHT", "confirmation variable drift")
    require(execute.get("requiredConfirmationValue") == "inspect-empty-aws-dev-remote-state-clean-room", "confirmation value drift")
    require(execute.get("awsReadCommands") == [
        "sts-get-caller-identity", "eks-describe-cluster-expecting-not-found",
        "s3-get-bucket-versioning", "s3-get-public-access-block",
        "s3-get-bucket-encryption", "s3-list-object-versions-for-exact-state-prefix",
        "kms-describe-key", "kms-get-key-rotation-status", "iam-get-policy",
        "iam-get-policy-version",
    ], "AWS read inventory drift")
    require(execute.get("expectedEksReadResult") == "ResourceNotFoundException", "EKS absence result drift")
    for key in (
        "remoteStateVersionCountMustBe", "remoteStateDeleteMarkerCountMustBe",
        "remoteLockVersionCountMustBe", "remoteLockDeleteMarkerCountMustBe",
    ):
        require(execute.get(key) == 0, f"remote absence count drift: {key}")
    for key in (
        "bucketVersioningMustBeEnabled", "bucketPublicAccessBlockMustBeComplete",
        "bucketDefaultEncryptionMustUseExactKmsKey", "kmsKeyMustBeEnabledCustomerManagedAndRotating",
        "devStatePolicyMustBeExactAndUnattached", "copiesTrackedAwsTerraformSourcePrivately",
        "privateSourceManifestRequired",
    ):
        require(execute.get(key) is True, f"execute control disabled: {key}")
    require(execute.get("commandTimeoutSeconds") == 120, "command timeout drift")
    require(execute.get("automaticRetry") is False, "automatic retry enabled")

    local = value.get("localAbsenceGate")
    require(isinstance(local, dict) and len(local) == 8, "local absence gate shape drift")
    require(all(item is False for item in local.values()), "local state allowance enabled")
    forbidden = value.get("forbiddenOperations")
    require(isinstance(forbidden, list) and len(forbidden) == 17 and len(set(forbidden)) == 17, "forbidden operation inventory drift")
    for required in ("terraform-init", "terraform-plan", "terraform-apply", "terraform-state-migration", "aws-mutation", "iam-policy-attachment", "s3-state-or-lock-write", "force-unlock", "kubernetes-command", "secret-value-read", "automatic-retry"):
        require(required in forbidden, f"forbidden operation missing: {required}")
    require(value.get("privateEvidence") == {
        "directoryMode": "0700",
        "fileMode": "0600",
        "rawAwsOutputsRemainPrivate": True,
        "sourceManifestRemainsPrivate": True,
        "publicResultContainsResourceIdentity": False,
        "publicResultContainsObjectVersionId": False,
        "publicResultContainsPrivatePath": False,
        "failurePreservesEvidence": True,
    }, "private evidence drift")
    overall = value.get("overallGate")
    require(overall.get("status") == "blocked-awaiting-private-request-verification-and-separate-read-only-approval", "overall status drift")
    require(len(overall) == 8 and all(item is False for key, item in overall.items() if key != "status"), "live authority enabled")
    require(value.get("successor") == {
        "version": "v0.12.4.1.5.0.5",
        "scope": "guarded-aws-dev-remote-state-clean-room-saved-create-plan",
        "requiresHumanReviewOfPrivatePreflight": True,
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
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.4-guarded-aws-dev-remote-state-clean-room-preflight.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.4_GUARDED_AWS_DEV_REMOTE_STATE_CLEAN_ROOM_PREFLIGHT.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.4-guarded-aws-dev-clean-room-preflight.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.4-guarded-aws-dev-clean-room-preflight.sh"
    contract = load(contract_path)
    validate_contract(contract)

    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("predecessor", "triggerErrorCode"), "AccessDeniedException"),
        (("partialBackend", "trackedBackendValues"), True),
        (("partialBackend", "trackedCredentials"), True),
        (("partialBackend", "exactKey"), "bootstrap/terraform.tfstate"),
        (("partialBackend", "nativeLockfile"), False),
        (("partialBackend", "dynamodbLocking"), True),
        (("partialBackend", "cleanRoomInitMode"), "-migrate-state"),
        (("partialBackend", "localStateMigration"), True),
        (("privateRequest", "maximumApprovalWindowSeconds"), 7200),
        (("privateRequest", "minimumRemainingApprovalSeconds"), 0),
        (("privateRequest", "backendConfigMustBeOutsideRepository"), False),
        (("privateRequest", "outputAndStagingDirectoriesMustBeNew"), False),
        (("verifyPhase", "protectedMainMustBeExactAndClean"), False),
        (("verifyPhase", "privateBackendConfigDigestMustMatch"), False),
        (("verifyPhase", "awsCommandsAllowed"), True),
        (("verifyPhase", "terraformCommandsAllowed"), True),
        (("executePhase", "expectedEksReadResult"), "AccessDeniedException"),
        (("executePhase", "remoteStateVersionCountMustBe"), 1),
        (("executePhase", "bucketVersioningMustBeEnabled"), False),
        (("executePhase", "bucketPublicAccessBlockMustBeComplete"), False),
        (("executePhase", "kmsKeyMustBeEnabledCustomerManagedAndRotating"), False),
        (("executePhase", "devStatePolicyMustBeExactAndUnattached"), False),
        (("executePhase", "copiesTrackedAwsTerraformSourcePrivately"), False),
        (("executePhase", "automaticRetry"), True),
        (("localAbsenceGate", "workingTreeStateFileAllowed"), True),
        (("localAbsenceGate", "privateStagedSourceMayContainTerraformDirectory"), True),
        (("privateEvidence", "rawAwsOutputsRemainPrivate"), False),
        (("privateEvidence", "publicResultContainsResourceIdentity"), True),
        (("overallGate", "awsCommandExecuted"), True),
        (("overallGate", "terraformInitExecuted"), True),
        (("overallGate", "terraformPlanExecuted"), True),
        (("overallGate", "environmentCreated"), True),
        (("successor", "requiresHumanReviewOfPrivatePreflight"), False),
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
    backend = (root / "infra/terraform/aws/environments/dev/backend.tf").read_text()
    require(backend.count('backend "s3" {}') == 1, "dev partial backend drift")
    for forbidden_text in ("bucket =", "key =", "kms_key_id", "allowed_account_ids", "access_key", "secret_key", "profile =", "role_arn"):
        require(forbidden_text not in backend, f"tracked backend value found: {forbidden_text}")
    require("-reconfigure, never -migrate-state" in backend, "clean-room init boundary missing")

    example = load(example_path)
    require(example.get("schemaVersion") == contract["privateRequest"]["schemaVersion"], "example schema drift")
    require(example.get("operation") == contract["privateRequest"]["operation"], "example operation drift")
    require("REPLACE_WITH_40_CHARACTER_PROTECTED_MAIN_SHA" in example_path.read_text(), "example main placeholder missing")
    require(all(example.get("executionBoundary", {}).get(key) is False for key in ("terraformInit", "terraformPlan", "terraformApply", "stateMigration", "statePush", "destroy", "iamPolicyAttachment", "kubernetesCommand", "secretValueRead", "automaticRetry", "automaticRollback")), "example enables forbidden authority")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "Neither phase runs Terraform",
        "expected EKS `ResourceNotFoundException` is evidence of absence",
        "There is no automatic retry",
        "terraform init -reconfigure",
        "does not authorize that successor",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")

    executor = executor_path.read_text()
    for marker in (
        '"operational_commands_executed": []', '"terraform_init_executed": False',
        '"terraform_plan_executed": False', '"terraform_apply_executed": False',
        '"state_migration_executed": False', '"private_resource_identity_emitted": False',
        'list-object-versions', 'get-key-rotation-status', 'get-policy-version',
        'ResourceNotFoundException', 'source-manifest.json',
    ):
        require(marker in executor, f"executor control missing: {marker}")
    require('["terraform"' not in executor and '["kubectl"' not in executor and '["helm"' not in executor, "forbidden command executable found")
    require("shell=True" not in executor, "shell execution enabled")

    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.4-guarded-aws-dev-remote-state-clean-room-preflight"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.4 - guarded AWS dev remote-state clean-room preflight"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.4"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "preflight source tracking drift")
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
    print(f"v0.12.4.1.5.0.4 guarded aws-dev clean-room preflight contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

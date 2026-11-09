#!/usr/bin/env python3
"""Validate the AWS dev create-plan management-CIDR recovery contract."""

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
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-management-cidr-recovery-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.5.0.1", "version drift")
    require(value.get("status") == "aws-dev-create-plan-management-cidr-recovery-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "4d4d3db2fe6e6e194e979131799ddfff5b1b7487", "baseline drift")
    require(value.get("designedAtDate") == "2026-09-30", "date drift")
    incident = value.get("incident")
    require(isinstance(incident, dict) and len(incident) == 11, "incident shape drift")
    require(incident.get("controlPlaneCommit") == "4d4d3db2fe6e6e194e979131799ddfff5b1b7487", "incident commit drift")
    require(incident.get("privateFailedPlanRequestSha256") == "5d915fac07cbcc4ea0bfd763b1a78230ac66bc969c623498d1a4056868d0c151", "failed request drift")
    require(incident.get("failedBinaryPlanSha256") == "bc99d8d8d1c2a5b8f163f983e953b1fd64d3f03ed44fd86c90bf120b08e2d781", "failed plan drift")
    require(incident.get("failedProviderLockfileSha256") == "a824bda667aac25533101eb99e1b5c6ec5415cc5f2e773793f7b1699b453fd6f", "provider lock drift")
    require(incident.get("failureClass") == "eks-public-endpoint-missing-restricted-cidr", "failure class drift")
    require(incident.get("terraformInitSucceeded") is True and incident.get("terraformPlanSucceeded") is False, "incident execution drift")
    require(incident.get("terraformShowExecuted") is False and incident.get("terraformApplyExecuted") is False, "incident mutation drift")
    require(incident.get("failedBinaryPlanApplyEligible") is False and incident.get("preserveAllFailedEvidence") is True, "incident evidence drift")
    private = value.get("privateRequest")
    require(isinstance(private, dict) and len(private) == 11, "private request shape drift")
    require(private.get("schemaVersion") == "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-request-v1", "request schema drift")
    require(private.get("operation") == "recover-aws-dev-create-plan-with-reviewed-management-cidr", "request operation drift")
    require(private.get("maximumApprovalWindowSeconds") == 7200 and private.get("minimumRemainingApprovalSeconds") == 900, "approval boundary drift")
    require(private.get("maximumPlanReviewLifetimeSeconds") == 28800, "review boundary drift")
    for key in ("managementCidrMustBeOneGloballyRoutableIpv4Slash32", "managementCidrMustRemainPrivate", "requestAndInputsMustRemainOutsideRepository", "recoveryOutputAndSourceMustBeNew"):
        require(private.get(key) is True, f"private control disabled: {key}")
    require(private.get("privateFileMode") == "0600" and private.get("privateDirectoryMode") == "0700", "private mode drift")
    verify = value.get("verifyPhase")
    require(isinstance(verify, dict) and len(verify) == 9, "verify phase shape drift")
    for key in ("protectedMainMustBeExactAndClean", "failedRequestAndArtifactDigestsMustMatch", "failedPlanErrorMustBeExactCidrPrecondition", "failedProviderLockfileMustMatch", "preflightChainAndTerraformSourceMustMatch", "managementCidrMustPassPrivateValidation"):
        require(verify.get(key) is True, f"verify control disabled: {key}")
    require(verify.get("awsCommandsAllowed") is False and verify.get("terraformCommandsAllowed") is False, "verify command authority enabled")
    require(verify.get("operationalCommandsExecuted") == [], "verify command inventory changed")
    execute = value.get("executePhase")
    require(isinstance(execute, dict) and len(execute) == 19, "execute phase shape drift")
    require(execute.get("requiredConfirmationVariable") == "CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY", "confirmation variable drift")
    require(execute.get("requiredConfirmationValue") == "recover-aws-dev-create-plan-with-reviewed-management-cidr", "confirmation value drift")
    require(execute.get("requiredIncidentLockObjectVersionCount") == 1 and execute.get("requiredIncidentLockDeleteMarkerCount") == 1, "incident lock boundary drift")
    require(execute.get("remoteStateVersionCountMustRemain") == 0 and execute.get("remoteStateDeleteMarkerCountMustRemain") == 0, "state write enabled")
    require(execute.get("providerLockfileCopiedFromFailedAttempt") is True, "provider lock reuse disabled")
    require(execute.get("terraformInitArguments") == ["init", "-input=false", "-reconfigure", "-lockfile=readonly", "-backend-config=PRIVATE_COPY"], "init command drift")
    require(execute.get("terraformPlanManagementCidrArgument") == "-var=eks_public_access_cidrs=[PRIVATE_IPV4/32]", "CIDR plan argument drift")
    require(execute.get("terraformPlanMode") == "saved-create-plan" and execute.get("terraformPlanLockTimeout") == "0s", "plan mode drift")
    require(execute.get("expectedPlanManagedActions") == ["create"] and execute.get("expectedPlanDataActions") == ["read", "no-op"], "plan action drift")
    require(execute.get("resourceDriftCountMustBe") == 0 and execute.get("importCountMustBe") == 0, "plan content gate weakened")
    require(execute.get("planMustBeCompleteAndApplyable") is True and execute.get("terraformApplyAllowed") is False and execute.get("automaticRetry") is False, "execution boundary weakened")
    lock = value.get("lockHistoryBoundary")
    require(isinstance(lock, dict) and len(lock) == 7, "lock boundary shape drift")
    for key in ("failedAttemptLockMustBeAbsentBeforeRecovery", "onePriorFailedLockCycleRequired", "oneRecoveryLockObjectVersionAllowed", "oneRecoveryLockDeleteMarkerAllowed"):
        require(lock.get(key) is True, f"lock control disabled: {key}")
    for key in ("stateObjectWriteAllowed", "directS3MutationAllowed", "forceUnlockAllowed"):
        require(lock.get(key) is False, f"unsafe state control enabled: {key}")
    privacy = value.get("privacyBoundary")
    require(privacy == {"publicResultContainsManagementCidr": False, "publicResultContainsRawResourceIdentity": False, "publicResultContainsObjectVersionId": False, "privateRequestSha256BindsManagementCidr": True}, "privacy boundary drift")
    forbidden = value.get("forbiddenOperations")
    require(isinstance(forbidden, list) and len(forbidden) == 14 and len(set(forbidden)) == 14, "forbidden inventory drift")
    for item in ("terraform-apply", "terraform-state-push", "terraform-force-unlock", "failed-plan-apply", "failed-evidence-delete", "automatic-retry"):
        require(item in forbidden, f"forbidden operation missing: {item}")
    overall = value.get("overallGate")
    require(isinstance(overall, dict) and len(overall) == 6, "overall gate shape drift")
    require(overall.get("status") == "blocked-awaiting-private-recovery-request-verification-and-separate-plan-approval", "overall status drift")
    require(all(item is False for key, item in overall.items() if key != "status"), "live authority enabled")
    require(value.get("successor") == {"version": "v0.12.4.1.5.0.6", "scope": "reviewed-aws-dev-exact-recovery-saved-create-plan-apply", "requiresHumanReviewOfPrivatePlan": True, "maximumApplyApprovalWindowSeconds": 10800, "authorizedByThisCheckpoint": False}, "successor drift")


def changed(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def validate_repository(root: Path) -> dict[str, Any]:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-management-cidr-recovery.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.5.0.1_AWS_DEV_CREATE_PLAN_MANAGEMENT_CIDR_RECOVERY.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"
    validator_path = root / "scripts/validate-aws-dev-create-plan-management-cidr-recovery.sh"
    contract = load(contract_path)
    validate_contract(contract)
    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("incident", "privateFailedPlanRequestSha256"), "0" * 64),
        (("incident", "failedBinaryPlanApplyEligible"), True),
        (("incident", "preserveAllFailedEvidence"), False),
        (("privateRequest", "maximumApprovalWindowSeconds"), 86400),
        (("privateRequest", "managementCidrMustBeOneGloballyRoutableIpv4Slash32"), False),
        (("privateRequest", "managementCidrMustRemainPrivate"), False),
        (("verifyPhase", "failedRequestAndArtifactDigestsMustMatch"), False),
        (("verifyPhase", "awsCommandsAllowed"), True),
        (("executePhase", "requiredIncidentLockObjectVersionCount"), 0),
        (("executePhase", "remoteStateVersionCountMustRemain"), 1),
        (("executePhase", "providerLockfileCopiedFromFailedAttempt"), False),
        (("executePhase", "terraformInitArguments"), ["init", "-reconfigure"]),
        (("executePhase", "expectedPlanManagedActions"), ["create", "update"]),
        (("executePhase", "terraformApplyAllowed"), True),
        (("executePhase", "automaticRetry"), True),
        (("lockHistoryBoundary", "directS3MutationAllowed"), True),
        (("privacyBoundary", "publicResultContainsManagementCidr"), True),
        (("overallGate", "recoveryPlanExecuted"), True),
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
    require(example.get("failedArtifactSha256s", {}).get("terraform-plan-create.stderr") == "df1e2e6084fc655c5528258fa9ec9460a648eb2e68b7b0286011b56e22e948a0", "example incident evidence drift")
    require(example.get("privateManagementCidr") == "REPLACE_WITH_CURRENT_PUBLIC_IPV4/32", "example CIDR placeholder drift")
    enabled_example_operations = {
        "awsReadOnlyValidation",
        "localPrivateSourceCopy",
        "terraformInitReconfigureReadonlyLockfile",
        "terraformSavedPlan",
        "terraformShow",
    }
    disabled_example_operations = {
        "terraformApply",
        "stateMigration",
        "statePush",
        "destroy",
        "iamPolicyAttachment",
        "kubernetesCommand",
        "".join(("secret", "ValueRead")),
        "".join(("direct", "S3", "Mutation")),
        "forceUnlock",
        "automaticRetry",
        "automaticRollback",
    }
    boundary = example.get("executionBoundary")
    require(isinstance(boundary, dict) and set(boundary) == enabled_example_operations | disabled_example_operations, "example execution boundary shape drift")
    require(all(boundary.get(key) is True for key in enabled_example_operations), "example required authority drift")
    require(all(boundary.get(key) is False for key in disabled_example_operations), "example enables forbidden authority")
    document = " ".join(document_path.read_text().split())
    for phrase in ("globally routable IPv4 `/32`", "never emit the CIDR", "up to two hours", "up to eight hours", "up to three hours", "does not authorize Terraform apply"):
        require(phrase in document, f"document boundary missing: {phrase}")
    executor = executor_path.read_text()
    for marker in ('"operational_commands_executed": []', '"management_cidr_emitted": False', '"terraform_apply_executed": False', '"automatic_retry_performed": False', '"-lockfile=readonly"', 'eks_public_access_cidrs=', 'validate_incident_history'):
        require(marker in executor, f"executor control missing: {marker}")
    require("force-unlock" not in executor and "-migrate-state" not in executor and "shell=True" not in executor, "forbidden executable path found")
    for path, marker in ((root / "README.md", "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-management-cidr-recovery"), (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.5.0.1 - AWS dev create-plan management CIDR recovery"), (root / "CHANGELOG.md", "## v0.12.4.1.5.0.5.0.1")):
        require(marker in path.read_text(), f"repository marker missing: {marker}")
    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "recovery source tracking drift")
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
    print(f"v0.12.4.1.5.0.5.0.1 management-CIDR recovery contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

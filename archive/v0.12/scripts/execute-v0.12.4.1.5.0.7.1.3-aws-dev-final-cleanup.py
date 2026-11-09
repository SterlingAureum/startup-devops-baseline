#!/usr/bin/env python3
"""Delete one bound orphan ENI, then plan and apply final aws-dev cleanup."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.py"
PREPARE_CONFIRMATION = "delete-bound-orphan-eni-and-plan-two-resource-destroy"
FINAL_CONFIRMATION = "apply-reviewed-two-resource-final-cleanup"
RECOVERY_CONTROL_PLANE_COMMIT = "3e648db871489bd4e01a0552e75f4751ff1c126c"
RECOVERY_REQUEST_SHA256 = "c8c079dec7908a881ec4a8e204ae3eae454404c738a805b3e989603c052d9fe8"
RECOVERY_EVIDENCE_SHA256 = "5e2f556aaeaf1d5b11f33216aee7a86275b80019f60427877c5a804080e0de75"
RECOVERY_RESULT_SHA256 = "e9fa4bfe1a8383549ffb1001fce7306fd8a42efb2686c6b9de8f518e3c973b55"
PARTIAL_STATE_SHA256 = "9b8819191a47a7523e0625f0d1d7bf1cde2e93cd884f2989d40e0247e22a4159"
PARTIAL_INVENTORY_SHA256 = "d702bcd93a915d8bca6a79d206810a8064ce79430c6faf3906b8b742d0c5f522"
ENI_STDOUT_SHA256 = "abc75c7377f39957ae4a4c3d0a889a91e39b6757e86fe0e93d1147b8d311e162"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ENI_ID_SHA256 = "991fa1fa031b0d05c4b58c529f777dce62e2adbc26d9a7c184b9b9144ba421cd"
SUBNET_ID_SHA256 = "26adbd5abd7ab8beeaec25d838b83c1fb129c8a8455a743ae8a77033e1852f8f"
VPC_ID_SHA256 = "a4d29c087629f58fe4fcec657df9d26bafed45693f89aaeb1020a2c62106e0cf"
SECURITY_GROUP_INVENTORY_SHA256 = "bb66e1edeeebd7ee6e5a58c5571e525fbc090b81c9c3823c5b64a6fee4c3de03"
PRIVATE_IP_INVENTORY_SHA256 = "009a9e7af2e538b463605802f686028e54442a8dde741839745011f86d2939be"
DESCRIPTION_SHA256 = "3edff45bd0121fd314a86de7bc63d106089bbfa452603920b24beb0037a12e45"
PENDING_ADDRESSES = {
    'module.vpc.aws_subnet.private["us-east-1b"]',
    "module.vpc.aws_vpc.this",
}
MAXIMUM_PREPARE_WINDOW_SECONDS = 3600
MAXIMUM_FINAL_WINDOW_SECONDS = 10800
MAXIMUM_REVIEW_LIFETIME_SECONDS = 14400
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 300
TERRAFORM_TIMEOUT_SECONDS = 3600
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class CleanupError(ValueError):
    pass


class CommandFailure(CleanupError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CleanupError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY = load_module(RECOVERY_PATH, "partial_teardown_recovery_final_cleanup_dependency")
TEARDOWN = RECOVERY.TEARDOWN
SEMANTIC = RECOVERY.SEMANTIC
PRIOR = RECOVERY.PRIOR
APPLY = RECOVERY.APPLY
BASE = RECOVERY.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CleanupError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()


def lines_sha256(values: list[Any]) -> str:
    normalized = sorted(str(value) for value in values)
    return hashlib.sha256(("\n".join(normalized) + ("\n" if normalized else "")).encode()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def address_digest(addresses: set[str]) -> str:
    return lines_sha256(list(addresses))


def semantic_partial_state(document: dict[str, Any]) -> dict[str, Any]:
    """Ignore only Terraform's non-deterministic check-results ordering."""
    result = copy.deepcopy(document)
    checks = result.get("check_results")
    if checks is not None:
        require(isinstance(checks, list), "Terraform check_results must be a list")
        result["check_results"] = SEMANTIC.normalize_unordered(checks)
    return result


def write_private(path: Path, value: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(value)
    path.chmod(0o600)


def write_private_json(path: Path, value: Any) -> None:
    write_private(path, canonical_json(value))


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise CleanupError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise CleanupError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise CleanupError(f"{label} must be a valid UTC timestamp") from error
    require(parsed.tzinfo == timezone.utc, f"{label} must be UTC")
    return parsed


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def require_private_directory(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a non-symlink directory")
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, f"{label} mode must be 0700")
    return path.resolve(strict=True)


def require_private_file(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular non-symlink file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 0600")
    require_private_directory(path.parent, f"{label} parent")
    return path.resolve(strict=True)


def require_new_private_directory(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(not path.exists() and not path.is_symlink(), f"{label} must be new")
    return require_private_directory(path.parent, f"{label} parent") / path.name


def recovery_boundary() -> dict[str, Any]:
    return {
        "recoveryControlPlaneCommit": RECOVERY_CONTROL_PLANE_COMMIT,
        "privateRecoveryRequestSha256": RECOVERY_REQUEST_SHA256,
        "privateRecoveryEvidenceSha256": RECOVERY_EVIDENCE_SHA256,
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "partialStateSha256": PARTIAL_STATE_SHA256,
        "stateAddressInventorySha256": PARTIAL_INVENTORY_SHA256,
        "managedStateAddressCount": 2, "dataStateAddressCount": 0,
        "totalStateAddressCount": 2, "networkInterfaceCount": 1,
        "networkInterfaceEvidenceSha256": ENI_STDOUT_SHA256,
        "networkInterfaceIdSha256": ENI_ID_SHA256,
        "subnetIdSha256": SUBNET_ID_SHA256, "vpcIdSha256": VPC_ID_SHA256,
        "securityGroupInventorySha256": SECURITY_GROUP_INVENTORY_SHA256,
        "privateIpInventorySha256": PRIVATE_IP_INVENTORY_SHA256,
        "descriptionSha256": DESCRIPTION_SHA256,
        "networkInterfaceAvailable": True, "networkInterfaceAttached": False,
        "networkInterfaceAssociationPresent": False,
        "networkInterfaceRequesterManaged": False, "networkInterfaceOperatorManaged": False,
        "networkInterfaceOwnerMatchesAccount": True, "networkInterfaceTagCount": 4,
        "networkInterfacePrivateIpCount": 6, "networkInterfaceSecurityGroupCount": 1,
        "eksClusterAbsent": True, "activeInstanceCount": 0,
        "activeNatGatewayCount": 0, "subnetRouteTableAssociationCount": 0,
    }


def prepare_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True, "exactNetworkInterfaceRead": True,
        "exactNetworkInterfaceDelete": True, "exactNetworkInterfaceAbsenceRead": True,
        "s3ObjectHistoryRead": True, "terraformVersionRead": True,
        "terraformStateRead": True, "terraformSavedDestroyPlan": True,
        "terraformInit": False, "terraformApply": False,
        "terraformUnsavedDestroy": False, "statePush": False,
        "directS3Mutation": False, "forceUnlock": False,
        "otherAwsMutation": False, "automaticRetry": False, "automaticRollback": False,
    }


def final_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True, "networkInterfaceAbsenceRead": True,
        "vpcSubnetAbsenceRead": True, "s3ObjectHistoryRead": True,
        "terraformVersionRead": True, "terraformStateRead": True,
        "terraformExactSavedPlanApply": True, "terraformInit": False,
        "terraformPlan": False, "terraformUnsavedDestroy": False,
        "statePush": False, "directAwsMutation": False, "directS3Mutation": False,
        "forceUnlock": False, "automaticRetry": False, "automaticRollback": False,
    }


def validate_prepare_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateRecoveryRequestPath",
        "privateRecoveryOutputDirectory", "privatePrepareOutputDirectory",
        "recoveryBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Prepare request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-prepare-request-v1", "Prepare schema changed")
    require(value["operation"] == PREPARE_CONFIRMATION, "Prepare operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateRecoveryRequestPath", "privateRecoveryOutputDirectory", "privatePrepareOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["recoveryBoundary"] == recovery_boundary(), "Recovery boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc", "planReviewExpiresAtUtc"}, "Prepare approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Prepare approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Prepare approval expiry")
    review = utc_timestamp(approval["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_PREPARE_WINDOW_SECONDS), "Prepare approval must be positive and at most one hour")
    require(review > expiry and review - start <= timedelta(seconds=MAXIMUM_REVIEW_LIFETIME_SECONDS), "Plan review must end after prepare and within four hours")
    require(value["executionBoundary"] == prepare_execution_boundary(), "Prepare execution boundary changed")
    return value


def validate_final_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privatePrepareRequestPath",
        "privatePrepareOutputDirectory", "privateFinalOutputDirectory",
        "planBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Final request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-apply-request-v1", "Final schema changed")
    require(value["operation"] == FINAL_CONFIRMATION, "Final operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    boundary = value["planBoundary"]
    keys = {"privatePrepareRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256", "managedDeleteCount", "dataChangeCount", "resourceDriftCount", "importCount", "humanReviewed", "orphanNetworkInterfaceDeleted", "planReviewExpiresAtUtc"}
    require(isinstance(boundary, dict) and set(boundary) == keys, "Plan boundary fields changed")
    for key in ("privatePrepareRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256"):
        require(isinstance(boundary[key], str) and SHA_RE.fullmatch(boundary[key]), f"Invalid digest: {key}")
    require(boundary["managedDeleteCount"] == 2 and boundary["dataChangeCount"] == 0 and boundary["resourceDriftCount"] == 0 and boundary["importCount"] == 0, "Final plan count boundary changed")
    require(boundary["humanReviewed"] is True and boundary["orphanNetworkInterfaceDeleted"] is True, "Final human review or ENI deletion boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Final approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Final approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Final approval expiry")
    review = utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_FINAL_WINDOW_SECONDS), "Final approval must be positive and at most three hours")
    require(expiry <= review, "Final approval exceeds plan review lifetime")
    require(value["executionBoundary"] == final_execution_boundary(), "Final execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise CleanupError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def validate_eni(value: dict[str, Any], expected_account: str) -> dict[str, Any]:
    interfaces = value.get("NetworkInterfaces")
    require(isinstance(interfaces, list) and len(interfaces) == 1, "Bound ENI count changed")
    eni = interfaces[0]
    require(isinstance(eni, dict), "Bound ENI shape changed")
    require(text_sha256(eni.get("NetworkInterfaceId")) == ENI_ID_SHA256, "Bound ENI identity changed")
    require(text_sha256(eni.get("SubnetId")) == SUBNET_ID_SHA256 and text_sha256(eni.get("VpcId")) == VPC_ID_SHA256, "Bound ENI network changed")
    require(eni.get("OwnerId") == expected_account, "Bound ENI owner changed")
    require(eni.get("Status") == "available" and eni.get("InterfaceType") == "interface", "Bound ENI is not an available ordinary interface")
    require(eni.get("RequesterManaged") is False and eni.get("Operator", {}).get("Managed") is False, "Bound ENI management changed")
    require(not isinstance(eni.get("Attachment"), dict) and not isinstance(eni.get("Association"), dict), "Bound ENI is attached or associated")
    require(eni.get("SourceDestCheck") is True, "Bound ENI source/destination check changed")
    require(text_sha256(eni.get("Description", "")) == DESCRIPTION_SHA256, "Bound ENI description changed")
    groups = [item.get("GroupId") for item in eni.get("Groups", []) if isinstance(item, dict) and item.get("GroupId")]
    private_ips = [item.get("PrivateIpAddress") for item in eni.get("PrivateIpAddresses", []) if isinstance(item, dict) and item.get("PrivateIpAddress")]
    require(len(groups) == 1 and lines_sha256(groups) == SECURITY_GROUP_INVENTORY_SHA256, "Bound ENI security groups changed")
    require(len(private_ips) == 6 and lines_sha256(private_ips) == PRIVATE_IP_INVENTORY_SHA256, "Bound ENI private IP inventory changed")
    require(isinstance(eni.get("TagSet"), list) and len(eni["TagSet"]) == 4, "Bound ENI tag count changed")
    return eni


def validate_recovery(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    recovery_request_path = require_private_file(Path(request["privateRecoveryRequestPath"]), "Partial recovery request")
    require(file_sha256(recovery_request_path) == RECOVERY_REQUEST_SHA256, "Partial recovery request digest changed")
    recovery_request = RECOVERY.validate_request(load_json(recovery_request_path, "Partial recovery request"))
    require(recovery_request["expectedMainCommit"] == RECOVERY_CONTROL_PLANE_COMMIT, "Recovery control-plane commit changed")
    require(recovery_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and recovery_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Recovery runtime target changed")
    incident = RECOVERY.validate_incident(recovery_request, repository_root)
    output = require_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Partial recovery output")
    require(str(output) == recovery_request["privateRecoveryOutputDirectory"], "Partial recovery output path changed")
    evidence_path = require_private_file(output / "aws-dev-partial-teardown-recovery-evidence.json", "Partial recovery evidence")
    result_path = require_private_file(output / "aws-dev-partial-teardown-recovery-result.json", "Partial recovery result")
    state_path = require_private_file(output / "aws-dev-state-partial-recovery.json", "Partial recovery state")
    eni_path = require_private_file(output / "network-interfaces-partial-recovery.stdout", "Partial recovery ENI evidence")
    eni_stderr = require_private_file(output / "network-interfaces-partial-recovery.stderr", "Partial recovery ENI stderr")
    require(file_sha256(evidence_path) == RECOVERY_EVIDENCE_SHA256 and file_sha256(result_path) == RECOVERY_RESULT_SHA256, "Partial recovery result evidence changed")
    require(file_sha256(state_path) == PARTIAL_STATE_SHA256, "Partial recovery state changed")
    require(file_sha256(eni_path) == ENI_STDOUT_SHA256 and file_sha256(eni_stderr) == EMPTY_SHA256, "Partial recovery ENI evidence changed")
    result = load_json(result_path, "Partial recovery result")
    require(result.get("status") == "aws-dev-partial-teardown-read-only-recovery-completed" and result.get("managed_state_address_count") == 2 and result.get("data_state_address_count") == 0 and result.get("state_address_inventory_sha256") == PARTIAL_INVENTORY_SHA256, "Partial recovery state boundary changed")
    require(result.get("network_interface_count") == 1 and result.get("dependency_classification") == "network-interface-dependency", "Partial recovery dependency changed")
    eni = validate_eni(load_json(eni_path, "Partial recovery ENI evidence"), request["expectedAwsAccountId"])
    state = load_json(state_path, "Partial recovery state")
    return {"request_path": recovery_request_path, "request": recovery_request, "incident": incident, "output": output, "state": state, "state_path": state_path, "eni": eni, "eni_path": eni_path}


def active_window(request: dict[str, Any], now: datetime, label: str) -> int:
    start = utc_timestamp(request["approval"]["notBeforeUtc"], f"{label} start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], f"{label} expiry")
    require(start <= now < expiry, f"{label} is not currently active")
    remaining = int((expiry - now).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, f"{label} has less than 15 minutes remaining")
    return remaining


def clean_main(request: dict[str, Any], git_runner: GitRunner, label: str) -> None:
    expected = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", f"{label} must run from main")
    require(git_runner(["status", "--porcelain"]) == "", f"{label} requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected and git_runner(["rev-parse", "origin/main"]) == expected, "HEAD and origin/main must equal reviewed main")


def verify_prepare(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private final-cleanup prepare request")
    require(not is_within(private_request, repository_root), "Prepare request must remain outside the repository")
    request = validate_prepare_request(load_json(private_request, "Prepare request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = active_window(request, current, "Prepare approval")
    clean_main(request, git_runner, "Final-cleanup prepare")
    recovery = validate_recovery(request, repository_root)
    output = require_new_private_directory(Path(request["privatePrepareOutputDirectory"]), "Private prepare output")
    require(not is_within(output, repository_root), "Prepare output must remain outside the repository")
    return {"request": request, "request_path": private_request, "recovery": recovery, "output": output, "remaining": remaining}


def redacted_prepare_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-final-cleanup-prepare-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_prepare_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "private_recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "partial_state_sha256": PARTIAL_STATE_SHA256,
        "managed_state_address_count": 2, "network_interface_count": 1,
        "network_interface_id_sha256": ENI_ID_SHA256,
        "network_interface_deletion_authorized": False,
        "terraform_plan_authorized": False, "terraform_apply_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "remaining_prepare_approval_seconds": context["remaining"],
        "next_action": "obtain-separate-orphan-eni-delete-and-two-resource-plan-approval",
    }


def record_result(output: Path, label: str, result: subprocess.CompletedProcess[bytes]) -> None:
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)


def run_logged(output: Path, label: str, arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path, runner: CommandRunner) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(arguments, environment, timeout, cwd)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    record_result(output, label, result)
    require(result.returncode == 0, f"{label} failed")
    require(result.stderr == b"", f"{label} produced stderr")
    return result


def run_expected_missing(output: Path, label: str, arguments: list[str], code: bytes, environment: dict[str, str], cwd: Path, runner: CommandRunner) -> None:
    try:
        result = runner(arguments, environment, COMMAND_TIMEOUT_SECONDS, cwd)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    record_result(output, label, result)
    require(result.returncode != 0 and result.stdout == b"" and code in result.stderr, f"{label} is not conclusively absent")


def final_plan_gate(document: dict[str, Any]) -> dict[str, Any]:
    require(document.get("complete") is True and document.get("errored") is False and document.get("applyable") is True, "Final saved plan is not complete and applyable")
    drift = document.get("resource_drift", [])
    require(isinstance(drift, list) and not drift, "Final saved plan contains resource drift")
    changes = document.get("resource_changes")
    require(isinstance(changes, list), "Final plan changes are missing")
    managed: set[str] = set()
    data: set[str] = set()
    for item in changes:
        change = item.get("change", {})
        require(change.get("importing") is None, "Final plan contains import")
        if item.get("mode") == "managed":
            require(change.get("actions") == ["delete"], f"Final managed action is not delete-only: {item.get('address')}")
            managed.add(item.get("address"))
        elif item.get("mode") == "data":
            require(change.get("actions") in (["read"], ["no-op"], ["delete"]), "Final data action changed")
            data.add(item.get("address"))
        else:
            raise CleanupError("Unsupported final plan resource mode")
    require(managed == PENDING_ADDRESSES and not data, "Final plan is not the exact two-resource cleanup")
    outputs = document.get("output_changes", {})
    require(
        isinstance(outputs, dict)
        and all(isinstance(item, dict) and item.get("actions") in (["delete"], ["no-op"]) for item in outputs.values()),
        "Final plan output action changed",
    )
    return {"schemaVersion": "v0.12.4.1.5.0.7.1.3-private-final-plan-address-inventory-v1", "managedDeleteAddresses": sorted(managed), "dataChangeAddresses": [], "managedDeleteCount": 2, "dataChangeCount": 0, "resourceDriftCount": 0, "importCount": 0}


def execute_prepare(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_prepare(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_FINAL_CLEANUP_PREPARE") == PREPARE_CONFIRMATION, f"Set CONFIRM_AWS_DEV_FINAL_CLEANUP_PREPARE={PREPARE_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH")
    require(all(not os.environ.get(name) for name in forbidden), "Other mutation confirmations must be unset")
    request = context["request"]
    recovery = context["recovery"]
    incident = recovery["incident"]
    plan_evidence = incident["recovery"]["plan_evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700); output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    tfvars = require_private_file(plan_evidence["output"] / "terraform.tfvars.private", "Private Terraform tfvars")
    eni_id = recovery["eni"]["NetworkInterfaceId"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-final-prepare", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-final-prepare", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = parse_json_bytes(run_logged(output, "terraform-state-pull-final-prepare", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live partial state")
    require(semantic_partial_state(pulled) == semantic_partial_state(recovery["state"]), "Live state changed since partial recovery")
    listed = TEARDOWN.state_list(run_logged(output, "terraform-state-list-final-prepare", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout)
    require(listed == PENDING_ADDRESSES, "Live state is not the exact pending inventory")
    live_eni_value = parse_json_bytes(run_logged(output, "network-interface-before-delete", ["aws", "ec2", "describe-network-interfaces", "--region", TEARDOWN.AWS_REGION, "--network-interface-ids", eni_id, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Live bound ENI")
    validate_eni(live_eni_value, request["expectedAwsAccountId"])
    before_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-before-final-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before final plan"))
    TEARDOWN.require_clean_lock(before_history)
    deleted = run_logged(output, "delete-bound-orphan-network-interface", ["aws", "ec2", "delete-network-interface", "--region", TEARDOWN.AWS_REGION, "--network-interface-id", eni_id], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner)
    require(deleted.stdout == b"", "ENI delete returned unexpected stdout")
    run_expected_missing(output, "network-interface-after-delete", ["aws", "ec2", "describe-network-interfaces", "--region", TEARDOWN.AWS_REGION, "--network-interface-ids", eni_id, "--output", "json"], b"InvalidNetworkInterfaceID.NotFound", environment, repository_root, runner)

    binary = output / "aws-dev-final-cleanup.tfplan"
    cidr = plan_evidence["recovery_request"]["privateManagementCidr"]
    cidr_argument = "-var=eks_public_access_cidrs=" + json.dumps([cidr], separators=(",", ":"))
    run_logged(output, "terraform-plan-final-cleanup", ["terraform", "plan", "-destroy", "-input=false", "-lock=true", "-lock-timeout=0s", f"-var-file={tfvars}", cidr_argument, f"-out={binary}"], environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(binary.is_file() and not binary.is_symlink(), "Terraform did not create final saved plan")
    binary.chmod(0o600)
    shown_json = run_logged(output, "terraform-show-final-plan-json", ["terraform", "show", "-json", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    plan_json = output / "aws-dev-final-cleanup-plan.json"; write_private(plan_json, shown_json.stdout)
    inventory = final_plan_gate(parse_json_bytes(shown_json.stdout, "Final saved plan"))
    inventory_path = output / "final-cleanup-address-inventory.json"; write_private_json(inventory_path, inventory)
    shown_text = run_logged(output, "terraform-show-final-plan-text", ["terraform", "show", "-no-color", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(shown_text.stdout, "Final human-readable plan is empty")
    plan_text = output / "aws-dev-final-cleanup-plan.txt"; write_private(plan_text, shown_text.stdout)
    after_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-after-final-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after final plan"))
    require(after_history["stateVersions"] == before_history["stateVersions"] and after_history["stateDeleteMarkers"] == 0, "Final plan changed remote state")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Final plan lock lifecycle changed")
    TEARDOWN.require_clean_lock(after_history)
    record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-plan-record-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "createdAtUtc": utc_text(current),
        "planReviewExpiresAtUtc": request["approval"]["planReviewExpiresAtUtc"],
        "privatePrepareRequestSha256": file_sha256(context["request_path"]),
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "networkInterfaceEvidenceSha256": ENI_STDOUT_SHA256,
        "networkInterfaceIdSha256": ENI_ID_SHA256, "orphanNetworkInterfaceDeleted": True,
        "binaryPlanSha256": file_sha256(binary), "planJsonSha256": file_sha256(plan_json),
        "planTextSha256": file_sha256(plan_text), "addressInventorySha256": file_sha256(inventory_path),
        "managedDeleteCount": 2, "dataChangeCount": 0, "resourceDriftCount": 0, "importCount": 0,
        "humanReviewed": False, "terraformInitExecuted": False, "terraformApplyExecuted": False,
        "stateObjectVersionDelta": 0, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1,
    }
    record_path = output / "final-cleanup-plan-record.json"; write_private_json(record_path, record)
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-prepare-result-v1",
        "status": "aws-dev-orphan-eni-deleted-and-two-resource-plan-awaiting-review",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "private_prepare_request_sha256": record["privatePrepareRequestSha256"],
        "network_interface_id_sha256": ENI_ID_SHA256, "orphan_network_interface_deleted": True,
        "binary_plan_sha256": record["binaryPlanSha256"], "plan_json_sha256": record["planJsonSha256"],
        "plan_text_sha256": record["planTextSha256"], "address_inventory_sha256": record["addressInventorySha256"],
        "plan_record_sha256": file_sha256(record_path), "managed_delete_count": 2,
        "data_change_count": 0, "resource_drift_count": 0, "import_count": 0,
        "human_reviewed": False, "terraform_apply_executed": False,
        "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "review-private-two-resource-plan-then-create-separate-final-apply-request",
    }


def validate_prepare_evidence(request: dict[str, Any], repository_root: Path, now: datetime) -> dict[str, Any]:
    prepare_request_path = require_private_file(Path(request["privatePrepareRequestPath"]), "Private prepare request")
    require(file_sha256(prepare_request_path) == request["planBoundary"]["privatePrepareRequestSha256"], "Prepare request digest changed")
    prepare_request = validate_prepare_request(load_json(prepare_request_path, "Prepare request"))
    require(prepare_request["expectedMainCommit"] == request["expectedMainCommit"] and prepare_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and prepare_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Prepare and final targets differ")
    recovery = validate_recovery(prepare_request, repository_root)
    output = require_private_directory(Path(request["privatePrepareOutputDirectory"]), "Private prepare output")
    require(str(output) == prepare_request["privatePrepareOutputDirectory"], "Prepare output path changed")
    names = {"binary": "aws-dev-final-cleanup.tfplan", "json": "aws-dev-final-cleanup-plan.json", "text": "aws-dev-final-cleanup-plan.txt", "inventory": "final-cleanup-address-inventory.json", "record": "final-cleanup-plan-record.json"}
    digest_keys = {"binary": "binaryPlanSha256", "json": "planJsonSha256", "text": "planTextSha256", "inventory": "addressInventorySha256", "record": "planRecordSha256"}
    artifacts: dict[str, Path] = {}
    for key, name in names.items():
        path = require_private_file(output / name, f"Prepare artifact {name}")
        require(file_sha256(path) == request["planBoundary"][digest_keys[key]], f"Prepare artifact digest changed: {name}")
        artifacts[key] = path
    boundary = request["planBoundary"]
    record = load_json(artifacts["record"], "Final plan record")
    for record_key, boundary_key in (("privatePrepareRequestSha256", "privatePrepareRequestSha256"), ("binaryPlanSha256", "binaryPlanSha256"), ("planJsonSha256", "planJsonSha256"), ("planTextSha256", "planTextSha256"), ("addressInventorySha256", "addressInventorySha256"), ("managedDeleteCount", "managedDeleteCount"), ("dataChangeCount", "dataChangeCount"), ("resourceDriftCount", "resourceDriftCount"), ("importCount", "importCount"), ("orphanNetworkInterfaceDeleted", "orphanNetworkInterfaceDeleted"), ("planReviewExpiresAtUtc", "planReviewExpiresAtUtc")):
        require(record.get(record_key) == boundary[boundary_key], f"Final plan record changed: {record_key}")
    require(record.get("humanReviewed") is False and boundary["humanReviewed"] is True, "Separate final plan review was not declared")
    inventory = load_json(artifacts["inventory"], "Final plan inventory")
    gated = final_plan_gate(load_json(artifacts["json"], "Final plan JSON"))
    require(gated == inventory, "Final plan inventory changed")
    require(now < utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry"), "Final reviewed plan expired")
    return {"prepare_request": prepare_request, "request_path": prepare_request_path, "recovery": recovery, "output": output, "artifacts": artifacts, "record": record, "inventory": inventory}


def verify_final(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private final apply request")
    require(not is_within(private_request, repository_root), "Final request must remain outside the repository")
    request = validate_final_request(load_json(private_request, "Final apply request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = active_window(request, current, "Final approval")
    clean_main(request, git_runner, "Final cleanup apply")
    evidence = validate_prepare_evidence(request, repository_root, current)
    output = require_new_private_directory(Path(request["privateFinalOutputDirectory"]), "Private final output")
    require(not is_within(output, repository_root), "Final output must remain outside repository")
    return {"request": request, "request_path": private_request, "evidence": evidence, "output": output, "remaining": remaining}


def redacted_final_verification(context: dict[str, Any]) -> dict[str, Any]:
    boundary = context["request"]["planBoundary"]
    return {
        "status": "aws-dev-final-two-resource-apply-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_final_request_sha256": file_sha256(context["request_path"]),
        "private_prepare_request_sha256": boundary["privatePrepareRequestSha256"],
        "binary_plan_sha256": boundary["binaryPlanSha256"],
        "managed_delete_count": 2, "human_review_verified": True,
        "orphan_network_interface_deleted": True,
        "operational_commands_executed": [], "terraform_init_authorized": False,
        "terraform_plan_authorized": False, "terraform_apply_authorized": False,
        "remaining_final_approval_seconds": context["remaining"],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-two-resource-final-apply-approval",
    }


def execute_final(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_final(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY") == FINAL_CONFIRMATION, f"Set CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY={FINAL_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_FINAL_CLEANUP_PREPARE", "CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH")
    require(all(not os.environ.get(name) for name in forbidden), "Other mutation confirmations must be unset")
    request = context["request"]
    evidence = context["evidence"]
    recovery = evidence["recovery"]
    incident = recovery["incident"]
    plan_evidence = incident["recovery"]["plan_evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700); output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    eni_id = recovery["eni"]["NetworkInterfaceId"]
    binary = evidence["artifacts"]["binary"]
    identity = parse_json_bytes(run_logged(output, "aws-identity-before-final-apply", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-before-final-apply", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = parse_json_bytes(run_logged(output, "terraform-state-pull-before-final-apply", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live state before final apply")
    require(semantic_partial_state(pulled) == semantic_partial_state(recovery["state"]), "Live state changed since final plan")
    require(TEARDOWN.state_list(run_logged(output, "terraform-state-list-before-final-apply", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == PENDING_ADDRESSES, "Final live state inventory changed")
    run_expected_missing(output, "network-interface-before-final-apply", ["aws", "ec2", "describe-network-interfaces", "--region", TEARDOWN.AWS_REGION, "--network-interface-ids", eni_id, "--output", "json"], b"InvalidNetworkInterfaceID.NotFound", environment, repository_root, runner)
    shown = run_logged(output, "terraform-show-reviewed-final-plan-json", ["terraform", "show", "-json", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(hashlib.sha256(shown.stdout).hexdigest() == request["planBoundary"]["planJsonSha256"], "Final reviewed plan JSON changed")
    final_plan_gate(parse_json_bytes(shown.stdout, "Final reviewed plan"))
    before_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-before-final-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before final apply"))
    TEARDOWN.require_clean_lock(before_history)
    applied = run_logged(output, "terraform-apply-reviewed-final-plan", ["terraform", "apply", "-input=false", "-auto-approve", str(binary)], environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    summary = re.search(rb"Apply complete! Resources: ([0-9]+) added, ([0-9]+) changed, ([0-9]+) destroyed\.", applied.stdout)
    require(summary is not None and tuple(map(int, summary.groups())) == (0, 0, 2), "Final Terraform apply summary changed")
    after_pull = run_logged(output, "terraform-state-pull-after-final-apply", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-after-final-cleanup.json"; write_private(state_path, after_pull.stdout)
    state = parse_json_bytes(after_pull.stdout, "Final remote state")
    require(PRIOR.state_instance_counts(state) == (0, 0), "Final remote state is not empty")
    require(TEARDOWN.state_list(run_logged(output, "terraform-state-list-after-final-apply", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == set(), "Final state list is not empty")
    after_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-after-final-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after final apply"))
    state_delta = after_history["stateVersions"] - before_history["stateVersions"]
    require(1 <= state_delta <= 3 and after_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Final state object lifecycle changed")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Final lock lifecycle changed")
    TEARDOWN.require_clean_lock(after_history)
    subnet_id = RECOVERY.raw_attribute(recovery["state"], "module.vpc", "aws_subnet", "private", "us-east-1b", "id")
    vpc_id = RECOVERY.raw_attribute(recovery["state"], "module.vpc", "aws_vpc", "this", None, "id")
    run_expected_missing(output, "subnet-after-final-apply", ["aws", "ec2", "describe-subnets", "--region", TEARDOWN.AWS_REGION, "--subnet-ids", subnet_id, "--output", "json"], b"InvalidSubnetID.NotFound", environment, repository_root, runner)
    run_expected_missing(output, "vpc-after-final-apply", ["aws", "ec2", "describe-vpcs", "--region", TEARDOWN.AWS_REGION, "--vpc-ids", vpc_id, "--output", "json"], b"InvalidVpcID.NotFound", environment, repository_root, runner)
    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "completedAtUtc": utc_text(current),
        "privateFinalRequestSha256": file_sha256(context["request_path"]),
        "binaryPlanSha256": request["planBoundary"]["binaryPlanSha256"],
        "orphanNetworkInterfaceDeleted": True, "managedDestroyedCount": 2,
        "managedStateAddressCount": 0, "dataStateAddressCount": 0,
        "stateAddressCount": 0, "stateAddressInventorySha256": address_digest(set()),
        "finalStateSha256": file_sha256(state_path), "subnetAbsent": True, "vpcAbsent": True,
        "stateObjectVersionDelta": state_delta, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
        "terraformInitExecuted": False, "terraformPlanExecutedByFinalApply": False,
        "exactSavedPlanApplied": True, "automaticRetryPerformed": False, "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-final-cleanup-evidence.json"; write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-result-v1",
        "status": "aws-dev-final-cleanup-completed", "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_final_request_sha256": evidence_record["privateFinalRequestSha256"],
        "binary_plan_sha256": evidence_record["binaryPlanSha256"],
        "final_cleanup_evidence_sha256": file_sha256(evidence_path),
        "orphan_network_interface_deleted": True, "managed_destroyed_count": 2,
        "managed_state_address_count": 0, "data_state_address_count": 0,
        "total_state_address_count": 0, "state_address_inventory_sha256": evidence_record["stateAddressInventorySha256"],
        "final_state_sha256": evidence_record["finalStateSha256"], "subnet_absent": True, "vpc_absent": True,
        "state_object_version_delta": state_delta, "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1, "lock_delete_marker_delta": 1, "lock_object_absent": True,
        "terraform_init_executed": False, "terraform_plan_executed_by_final_apply": False,
        "exact_saved_plan_applied": True, "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False, "private_object_version_id_emitted": False,
        "next_action": "record-private-final-cleanup-evidence-and-stop-aws-dev-work",
    }
    result_path = output / "aws-dev-final-cleanup-result.json"; write_private_json(result_path, result)
    result["final_cleanup_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify-prepare", "prepare", "verify-final", "final"))
    parser.add_argument("--private-prepare-request", type=Path)
    parser.add_argument("--private-final-request", type=Path)
    args = parser.parse_args()
    try:
        if args.phase in {"verify-prepare", "prepare"}:
            require(args.private_prepare_request is not None and args.private_final_request is None, "Prepare phase requires only --private-prepare-request")
            context = verify_prepare(args.private_prepare_request)
            result = redacted_prepare_verification(context) if args.phase == "verify-prepare" else execute_prepare(args.private_prepare_request)
        else:
            require(args.private_final_request is not None and args.private_prepare_request is None, "Final phase requires only --private-final-request")
            context = verify_final(args.private_final_request)
            result = redacted_final_verification(context) if args.phase == "verify-final" else execute_final(args.private_final_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, CleanupError) as error:
        parser.exit(1, f"AWS-dev final cleanup stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

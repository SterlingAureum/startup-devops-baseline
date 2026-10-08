#!/usr/bin/env python3
"""Delete one bound orphan EKS SG, then plan and apply VPC-only cleanup."""

from __future__ import annotations

import argparse
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
RECOVERY_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery.py"
PREPARE_CONFIRMATION = "delete-bound-orphan-eks-security-group-and-plan-vpc-destroy"
FINAL_CONFIRMATION = "apply-reviewed-vpc-only-final-cleanup"
RECOVERY_CONTROL_PLANE_COMMIT = "b48b745ef5acfac6f29bc54acfed8208b7601463"
RECOVERY_REQUEST_SHA256 = "466af32b41e85b3e9d1934c2a83ced4bcc8c94a9485d37a88cc4b2c705c81893"
RECOVERY_EVIDENCE_SHA256 = "74e9e23c0c2e721b39f96bd8add061b49f475bf19fe48ed7f991b9ebfc37bb65"
RECOVERY_RESULT_SHA256 = "ae13d7213582e1ce7ee40f13d3d6a4015d3ebe44f59b6cfc7bfd57905f80a7c3"
VPC_ONLY_STATE_SHA256 = "016a94e6fa7c7a5c98b40183134333ee0b5ea034faaa5f6468f4501054f7cb87"
VPC_ONLY_INVENTORY_SHA256 = "1be0314b76ccf644267ad1c6b18b06d9b42b815b1c3f0d1b3e54aa8ee4be297f"
SG_STDOUT_SHA256 = "dfba0b9e0aec18ce6bb82fa808fc2938069e33a8aef286bf22910aba1cb79918"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SG_ID_SHA256 = "e8a820dca7c3ab7408210f6779341938441519de137870e67278175c10f4d637"
SG_NAME_SHA256 = "cdff376c002020d2f6666e87ba0c72af35ac38563bfb14908d3a138493161c16"
SG_DESCRIPTION_SHA256 = "e9c8a56927a6d97776d8e6d87403590aa7943550448a3ceda74fb9aa306c64ba"
VPC_ID_SHA256 = "a4d29c087629f58fe4fcec657df9d26bafed45693f89aaeb1020a2c62106e0cf"
FORMER_ENI_SG_INVENTORY_SHA256 = "bb66e1edeeebd7ee6e5a58c5571e525fbc090b81c9c3823c5b64a6fee4c3de03"
SG_INVENTORY_SHA256 = "95a6c267fdf0287e5e75c5b61851fa6cb23c7f684d41ad664bce6724cf89e8c2"
VPC_ADDRESS = "module.vpc.aws_vpc.this"
PENDING_ADDRESSES = {VPC_ADDRESS}
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


VPC_RECOVERY = load_module(RECOVERY_PATH, "vpc_only_recovery_final_cleanup_dependency")
FINAL_13 = VPC_RECOVERY.FINAL
RECOVERY_12 = VPC_RECOVERY.RECOVERY
TEARDOWN = VPC_RECOVERY.TEARDOWN
PRIOR = VPC_RECOVERY.PRIOR
APPLY = VPC_RECOVERY.APPLY
BASE = VPC_RECOVERY.BASE


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


def prepare_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True,
        "exactSecurityGroupRead": True,
        "exactSecurityGroupDelete": True,
        "exactSecurityGroupAbsenceRead": True,
        "s3ObjectHistoryRead": True,
        "terraformVersionRead": True,
        "terraformStateRead": True,
        "terraformSavedDestroyPlan": True,
        "terraformInit": False,
        "terraformApply": False,
        "terraformUnsavedDestroy": False,
        "statePush": False,
        "directS3Mutation": False,
        "forceUnlock": False,
        "otherAwsMutation": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }


def final_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True,
        "securityGroupAbsenceRead": True,
        "vpcAbsenceRead": True,
        "s3ObjectHistoryRead": True,
        "terraformVersionRead": True,
        "terraformStateRead": True,
        "terraformExactSavedPlanApply": True,
        "terraformInit": False,
        "terraformPlan": False,
        "terraformUnsavedDestroy": False,
        "statePush": False,
        "directAwsMutation": False,
        "directS3Mutation": False,
        "forceUnlock": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }


def recovery_boundary() -> dict[str, Any]:
    return {
        "recoveryControlPlaneCommit": RECOVERY_CONTROL_PLANE_COMMIT,
        "privateRecoveryRequestSha256": RECOVERY_REQUEST_SHA256,
        "privateRecoveryEvidenceSha256": RECOVERY_EVIDENCE_SHA256,
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "vpcOnlyStateSha256": VPC_ONLY_STATE_SHA256,
        "stateAddressInventorySha256": VPC_ONLY_INVENTORY_SHA256,
        "managedStateAddressCount": 1,
        "dataStateAddressCount": 0,
        "totalStateAddressCount": 1,
        "securityGroupEvidenceSha256": SG_STDOUT_SHA256,
        "securityGroupInventorySha256": SG_INVENTORY_SHA256,
        "targetSecurityGroupIdSha256": SG_ID_SHA256,
        "targetSecurityGroupNameSha256": SG_NAME_SHA256,
        "targetSecurityGroupDescriptionSha256": SG_DESCRIPTION_SHA256,
        "vpcIdSha256": VPC_ID_SHA256,
        "targetOwnerMatchesAccount": True,
        "targetIsEksClusterSecurityGroup": True,
        "targetMatchesFormerEniSecurityGroup": True,
        "targetTagCount": 3,
        "targetIngressRuleCount": 0,
        "targetEgressRuleCount": 1,
        "targetSelfReferenceCount": 0,
        "targetReferencesOtherGroupCount": 0,
        "targetReferencedByDefaultCount": 0,
        "targetCidrRuleCount": 1,
        "networkInterfaceCount": 0,
        "subnetCount": 0,
        "dependencyClassification": "non-default-security-group",
    }


def validate_prepare_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateRecoveryRequestPath",
        "privateRecoveryOutputDirectory", "privatePrepareOutputDirectory",
        "recoveryBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Prepare request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-prepare-request-v1", "Prepare schema changed")
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
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-apply-request-v1", "Final schema changed")
    require(value["operation"] == FINAL_CONFIRMATION, "Final operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    boundary = value["planBoundary"]
    keys = {"privatePrepareRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256", "managedDeleteCount", "dataChangeCount", "resourceDriftCount", "importCount", "humanReviewed", "orphanSecurityGroupDeleted", "planReviewExpiresAtUtc"}
    require(isinstance(boundary, dict) and set(boundary) == keys, "Plan boundary fields changed")
    for key in ("privatePrepareRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256"):
        require(isinstance(boundary[key], str) and SHA_RE.fullmatch(boundary[key]), f"Invalid digest: {key}")
    require(boundary["managedDeleteCount"] == 1 and boundary["dataChangeCount"] == 0 and boundary["resourceDriftCount"] == 0 and boundary["importCount"] == 0, "Final plan count boundary changed")
    require(boundary["humanReviewed"] is True and boundary["orphanSecurityGroupDeleted"] is True, "Final human review or SG deletion boundary changed")
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


def validate_security_group(value: dict[str, Any], expected_account: str) -> dict[str, Any]:
    groups = value.get("SecurityGroups")
    require(isinstance(groups, list) and len(groups) == 1 and isinstance(groups[0], dict), "Bound security-group count changed")
    group = groups[0]
    group_id = group.get("GroupId")
    require(text_sha256(group_id) == SG_ID_SHA256, "Bound security-group identity changed")
    require(text_sha256(group.get("GroupName", "")) == SG_NAME_SHA256 and text_sha256(group.get("Description", "")) == SG_DESCRIPTION_SHA256, "Bound security-group description changed")
    require(text_sha256(group.get("VpcId")) == VPC_ID_SHA256 and group.get("OwnerId") == expected_account, "Bound security-group VPC or owner changed")
    combined = f"{group.get('GroupName', '')}\n{group.get('Description', '')}".lower()
    require(any(marker in combined for marker in ("eks-cluster-sg", "eks created security group", "amazon eks")), "Bound security group is not classified as EKS-created")
    tags = {str(item.get("Key")): str(item.get("Value")) for item in group.get("Tags", []) if isinstance(item, dict)}
    require(len(tags) == 3 and ("aws:eks:cluster-name" in tags or any(key.startswith("kubernetes.io/cluster/") for key in tags)), "Bound EKS security-group tags changed")
    ingress = group.get("IpPermissions")
    egress = group.get("IpPermissionsEgress")
    require(isinstance(ingress, list) and not ingress and isinstance(egress, list) and len(egress) == 1, "Bound security-group rule counts changed")
    all_rules = ingress + egress
    require(all(isinstance(rule, dict) for rule in all_rules), "Bound security-group rule shape changed")
    group_pairs = [pair for rule in all_rules for pair in rule.get("UserIdGroupPairs", []) if isinstance(pair, dict)]
    cidrs = [entry for rule in all_rules for entry in rule.get("IpRanges", []) if isinstance(entry, dict)]
    ipv6 = [entry for rule in all_rules for entry in rule.get("Ipv6Ranges", []) if isinstance(entry, dict)]
    prefixes = [entry for rule in all_rules for entry in rule.get("PrefixListIds", []) if isinstance(entry, dict)]
    require(not group_pairs and len(cidrs) == 1 and not ipv6 and not prefixes, "Bound security-group rule shape changed")
    require(lines_sha256([group_id]) == FORMER_ENI_SG_INVENTORY_SHA256, "Bound security group no longer matches former ENI evidence")
    return group


def validate_recovery(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    recovery_request_path = require_private_file(Path(request["privateRecoveryRequestPath"]), "VPC-only recovery request")
    require(file_sha256(recovery_request_path) == RECOVERY_REQUEST_SHA256, "VPC-only recovery request digest changed")
    recovery_request = VPC_RECOVERY.validate_request(load_json(recovery_request_path, "VPC-only recovery request"))
    require(recovery_request["expectedMainCommit"] == RECOVERY_CONTROL_PLANE_COMMIT, "Recovery control-plane commit changed")
    require(recovery_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and recovery_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Recovery runtime target changed")
    incident = VPC_RECOVERY.validate_incident(recovery_request, repository_root)
    output = require_private_directory(Path(request["privateRecoveryOutputDirectory"]), "VPC-only recovery output")
    require(str(output) == recovery_request["privateRecoveryOutputDirectory"], "VPC-only recovery output path changed")
    evidence_path = require_private_file(output / "aws-dev-vpc-only-recovery-evidence.json", "VPC-only recovery evidence")
    result_path = require_private_file(output / "aws-dev-vpc-only-recovery-result.json", "VPC-only recovery result")
    state_path = require_private_file(output / "aws-dev-state-vpc-only-recovery.json", "VPC-only recovery state")
    sg_path = require_private_file(output / "security-groups-vpc-only-recovery.stdout", "VPC-only security-group evidence")
    sg_stderr = require_private_file(output / "security-groups-vpc-only-recovery.stderr", "VPC-only security-group stderr")
    require(file_sha256(evidence_path) == RECOVERY_EVIDENCE_SHA256 and file_sha256(result_path) == RECOVERY_RESULT_SHA256, "VPC-only recovery result evidence changed")
    require(file_sha256(state_path) == VPC_ONLY_STATE_SHA256, "VPC-only recovery state changed")
    require(file_sha256(sg_path) == SG_STDOUT_SHA256 and file_sha256(sg_stderr) == EMPTY_SHA256, "VPC-only security-group evidence changed")
    result = load_json(result_path, "VPC-only recovery result")
    require(result.get("status") == "aws-dev-vpc-only-read-only-recovery-completed" and result.get("managed_state_address_count") == 1 and result.get("data_state_address_count") == 0 and result.get("state_address_inventory_sha256") == VPC_ONLY_INVENTORY_SHA256, "VPC-only state boundary changed")
    require(result.get("dependency_classifications") == ["non-default-security-group"] and result.get("non_default_security_group_count") == 1 and result.get("network_interface_count") == 0 and result.get("subnet_count") == 0, "VPC-only dependency boundary changed")
    groups_document = load_json(sg_path, "VPC-only security-group evidence")
    all_groups = groups_document.get("SecurityGroups")
    require(isinstance(all_groups, list) and len(all_groups) == 2, "VPC security-group inventory changed")
    require(lines_sha256([item.get("GroupId") for item in all_groups if isinstance(item, dict)]) == SG_INVENTORY_SHA256, "VPC security-group inventory digest changed")
    target = [item for item in all_groups if isinstance(item, dict) and item.get("GroupName") != "default"]
    defaults = [item for item in all_groups if isinstance(item, dict) and item.get("GroupName") == "default"]
    require(len(target) == 1 and len(defaults) == 1, "Default/non-default security-group split changed")
    validate_security_group({"SecurityGroups": target}, request["expectedAwsAccountId"])
    target_id = target[0].get("GroupId")
    default_rules = defaults[0].get("IpPermissions", []) + defaults[0].get("IpPermissionsEgress", [])
    require(all(isinstance(rule, dict) for rule in default_rules), "Default security-group rule shape changed")
    default_pairs = [pair for rule in default_rules for pair in rule.get("UserIdGroupPairs", []) if isinstance(pair, dict)]
    require(all(pair.get("GroupId") != target_id for pair in default_pairs), "Default security group now references cleanup target")
    return {"request_path": recovery_request_path, "request": recovery_request, "incident": incident, "output": output, "state": load_json(state_path, "VPC-only state"), "state_path": state_path, "target": target[0], "sg_path": sg_path}


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
    private_request = require_private_file(request_path, "Private EKS-SG cleanup prepare request")
    require(not is_within(private_request, repository_root), "Prepare request must remain outside repository")
    request = validate_prepare_request(load_json(private_request, "Prepare request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = active_window(request, current, "Prepare approval")
    clean_main(request, git_runner, "EKS-SG VPC cleanup prepare")
    recovery = validate_recovery(request, repository_root)
    output = require_new_private_directory(Path(request["privatePrepareOutputDirectory"]), "Private prepare output")
    require(not is_within(output, repository_root), "Prepare output must remain outside repository")
    return {"request": request, "request_path": private_request, "recovery": recovery, "output": output, "remaining": remaining}


def redacted_prepare_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-eks-sg-vpc-cleanup-prepare-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_prepare_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "private_recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "vpc_only_state_sha256": VPC_ONLY_STATE_SHA256,
        "managed_state_address_count": 1,
        "non_default_security_group_count": 1,
        "target_security_group_id_sha256": SG_ID_SHA256,
        "security_group_deletion_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "remaining_prepare_approval_seconds": context["remaining"],
        "next_action": "obtain-separate-orphan-eks-security-group-delete-and-vpc-plan-approval",
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


def vpc_plan_gate(document: dict[str, Any]) -> dict[str, Any]:
    require(document.get("complete") is True and document.get("errored") is False and document.get("applyable") is True, "VPC saved plan is not complete and applyable")
    drift = document.get("resource_drift", [])
    require(isinstance(drift, list) and not drift, "VPC saved plan contains resource drift")
    changes = document.get("resource_changes")
    require(isinstance(changes, list), "VPC plan changes are missing")
    managed: list[str] = []
    data: list[str] = []
    for item in changes:
        require(isinstance(item, dict), "VPC plan resource change shape changed")
        change = item.get("change", {})
        require(isinstance(change, dict), "VPC plan resource action shape changed")
        require(change.get("importing") is None, "VPC plan contains import")
        if item.get("mode") == "managed":
            require(change.get("actions") == ["delete"], f"VPC managed action is not delete-only: {item.get('address')}")
            managed.append(item.get("address"))
        elif item.get("mode") == "data":
            require(change.get("actions") in (["read"], ["no-op"], ["delete"]), "VPC data action changed")
            data.append(item.get("address"))
        else:
            raise CleanupError("Unsupported VPC plan resource mode")
    require(managed == [VPC_ADDRESS] and not data, "VPC plan is not the exact one-resource cleanup")
    outputs = document.get("output_changes", {})
    require(isinstance(outputs, dict) and all(isinstance(item, dict) and item.get("actions") in (["delete"], ["no-op"]) for item in outputs.values()), "VPC plan output action changed")
    return {"schemaVersion": "v0.12.4.1.5.0.7.1.5-private-vpc-plan-address-inventory-v1", "managedDeleteAddresses": managed, "dataChangeAddresses": [], "managedDeleteCount": 1, "dataChangeCount": 0, "resourceDriftCount": 0, "importCount": 0}


def prepare_plan_evidence(recovery: dict[str, Any]) -> dict[str, Any]:
    return recovery["incident"]["recovery"]["incident"]["recovery"]["plan_evidence"]


def execute_prepare(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_prepare(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_PREPARE") == PREPARE_CONFIRMATION, f"Set CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_PREPARE={PREPARE_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_APPLY", "CONFIRM_AWS_DEV_VPC_ONLY_RECOVERY", "CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY", "CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH")
    require(all(not os.environ.get(name) for name in forbidden), "Other mutation confirmations must be unset")
    request = context["request"]
    recovery = context["recovery"]
    plan_evidence = prepare_plan_evidence(recovery)
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    tfvars = require_private_file(plan_evidence["output"] / "terraform.tfvars.private", "Private Terraform tfvars")
    group_id = recovery["target"]["GroupId"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-eks-sg-prepare", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-eks-sg-prepare", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = parse_json_bytes(run_logged(output, "terraform-state-pull-eks-sg-prepare", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live VPC-only state")
    require(FINAL_13.semantic_partial_state(pulled) == FINAL_13.semantic_partial_state(recovery["state"]), "Live state changed since VPC-only recovery")
    require(TEARDOWN.state_list(run_logged(output, "terraform-state-list-eks-sg-prepare", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == PENDING_ADDRESSES, "Live state is not the exact VPC-only inventory")
    live_group = parse_json_bytes(run_logged(output, "security-group-before-delete", ["aws", "ec2", "describe-security-groups", "--region", TEARDOWN.AWS_REGION, "--group-ids", group_id, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Live bound security group")
    validate_security_group(live_group, request["expectedAwsAccountId"])
    before_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-before-vpc-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before VPC plan"))
    TEARDOWN.require_clean_lock(before_history)
    deleted = run_logged(output, "delete-bound-orphan-eks-security-group", ["aws", "ec2", "delete-security-group", "--region", TEARDOWN.AWS_REGION, "--group-id", group_id], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner)
    require(deleted.stdout == b"", "Security-group delete returned unexpected stdout")
    run_expected_missing(output, "security-group-after-delete", ["aws", "ec2", "describe-security-groups", "--region", TEARDOWN.AWS_REGION, "--group-ids", group_id, "--output", "json"], b"InvalidGroup.NotFound", environment, repository_root, runner)

    binary = output / "aws-dev-vpc-final-cleanup.tfplan"
    cidr = plan_evidence["recovery_request"]["privateManagementCidr"]
    cidr_argument = "-var=eks_public_access_cidrs=" + json.dumps([cidr], separators=(",", ":"))
    run_logged(output, "terraform-plan-vpc-final-cleanup", ["terraform", "plan", "-destroy", "-input=false", "-lock=true", "-lock-timeout=0s", f"-var-file={tfvars}", cidr_argument, f"-out={binary}"], environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(binary.is_file() and not binary.is_symlink(), "Terraform did not create VPC saved plan")
    binary.chmod(0o600)
    shown_json = run_logged(output, "terraform-show-vpc-final-plan-json", ["terraform", "show", "-json", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    plan_json = output / "aws-dev-vpc-final-cleanup-plan.json"
    write_private(plan_json, shown_json.stdout)
    inventory = vpc_plan_gate(parse_json_bytes(shown_json.stdout, "VPC saved plan"))
    inventory_path = output / "vpc-final-cleanup-address-inventory.json"
    write_private_json(inventory_path, inventory)
    shown_text = run_logged(output, "terraform-show-vpc-final-plan-text", ["terraform", "show", "-no-color", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(shown_text.stdout, "VPC human-readable plan is empty")
    plan_text = output / "aws-dev-vpc-final-cleanup-plan.txt"
    write_private(plan_text, shown_text.stdout)
    after_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-after-vpc-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after VPC plan"))
    require(after_history["stateVersions"] == before_history["stateVersions"] and after_history["stateDeleteMarkers"] == 0, "VPC plan changed remote state")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "VPC plan lock lifecycle changed")
    TEARDOWN.require_clean_lock(after_history)
    record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5-aws-dev-vpc-final-cleanup-plan-record-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "createdAtUtc": utc_text(current),
        "planReviewExpiresAtUtc": request["approval"]["planReviewExpiresAtUtc"],
        "privatePrepareRequestSha256": file_sha256(context["request_path"]),
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "securityGroupEvidenceSha256": SG_STDOUT_SHA256,
        "securityGroupIdSha256": SG_ID_SHA256,
        "orphanSecurityGroupDeleted": True,
        "binaryPlanSha256": file_sha256(binary),
        "planJsonSha256": file_sha256(plan_json),
        "planTextSha256": file_sha256(plan_text),
        "addressInventorySha256": file_sha256(inventory_path),
        "managedDeleteCount": 1,
        "dataChangeCount": 0,
        "resourceDriftCount": 0,
        "importCount": 0,
        "humanReviewed": False,
        "terraformInitExecuted": False,
        "terraformApplyExecuted": False,
        "stateObjectVersionDelta": 0,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
    }
    record_path = output / "vpc-final-cleanup-plan-record.json"
    write_private_json(record_path, record)
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-prepare-result-v1",
        "status": "aws-dev-orphan-eks-security-group-deleted-and-vpc-plan-awaiting-review",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_prepare_request_sha256": record["privatePrepareRequestSha256"],
        "target_security_group_id_sha256": SG_ID_SHA256,
        "orphan_security_group_deleted": True,
        "binary_plan_sha256": record["binaryPlanSha256"],
        "plan_json_sha256": record["planJsonSha256"],
        "plan_text_sha256": record["planTextSha256"],
        "address_inventory_sha256": record["addressInventorySha256"],
        "plan_record_sha256": file_sha256(record_path),
        "managed_delete_count": 1,
        "data_change_count": 0,
        "resource_drift_count": 0,
        "import_count": 0,
        "human_reviewed": False,
        "terraform_apply_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "review-private-vpc-plan-then-create-separate-final-apply-request",
    }


def validate_prepare_evidence(request: dict[str, Any], repository_root: Path, now: datetime) -> dict[str, Any]:
    prepare_request_path = require_private_file(Path(request["privatePrepareRequestPath"]), "Private prepare request")
    require(file_sha256(prepare_request_path) == request["planBoundary"]["privatePrepareRequestSha256"], "Prepare request digest changed")
    prepare_request = validate_prepare_request(load_json(prepare_request_path, "Prepare request"))
    require(prepare_request["expectedMainCommit"] == request["expectedMainCommit"] and prepare_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and prepare_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Prepare and final targets differ")
    recovery = validate_recovery(prepare_request, repository_root)
    output = require_private_directory(Path(request["privatePrepareOutputDirectory"]), "Private prepare output")
    require(str(output) == prepare_request["privatePrepareOutputDirectory"], "Prepare output path changed")
    names = {"binary": "aws-dev-vpc-final-cleanup.tfplan", "json": "aws-dev-vpc-final-cleanup-plan.json", "text": "aws-dev-vpc-final-cleanup-plan.txt", "inventory": "vpc-final-cleanup-address-inventory.json", "record": "vpc-final-cleanup-plan-record.json"}
    digest_keys = {"binary": "binaryPlanSha256", "json": "planJsonSha256", "text": "planTextSha256", "inventory": "addressInventorySha256", "record": "planRecordSha256"}
    artifacts: dict[str, Path] = {}
    for key, name in names.items():
        path = require_private_file(output / name, f"Prepare artifact {name}")
        require(file_sha256(path) == request["planBoundary"][digest_keys[key]], f"Prepare artifact digest changed: {name}")
        artifacts[key] = path
    boundary = request["planBoundary"]
    record = load_json(artifacts["record"], "VPC plan record")
    for record_key, boundary_key in (("privatePrepareRequestSha256", "privatePrepareRequestSha256"), ("binaryPlanSha256", "binaryPlanSha256"), ("planJsonSha256", "planJsonSha256"), ("planTextSha256", "planTextSha256"), ("addressInventorySha256", "addressInventorySha256"), ("managedDeleteCount", "managedDeleteCount"), ("dataChangeCount", "dataChangeCount"), ("resourceDriftCount", "resourceDriftCount"), ("importCount", "importCount"), ("orphanSecurityGroupDeleted", "orphanSecurityGroupDeleted"), ("planReviewExpiresAtUtc", "planReviewExpiresAtUtc")):
        require(record.get(record_key) == boundary[boundary_key], f"VPC plan record changed: {record_key}")
    require(record.get("humanReviewed") is False and boundary["humanReviewed"] is True, "Separate VPC plan review was not declared")
    inventory = load_json(artifacts["inventory"], "VPC plan inventory")
    require(vpc_plan_gate(load_json(artifacts["json"], "VPC plan JSON")) == inventory, "VPC plan inventory changed")
    require(now < utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry"), "Final reviewed VPC plan expired")
    return {"prepare_request": prepare_request, "request_path": prepare_request_path, "recovery": recovery, "output": output, "artifacts": artifacts, "record": record, "inventory": inventory}


def verify_final(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private final VPC apply request")
    require(not is_within(private_request, repository_root), "Final request must remain outside repository")
    request = validate_final_request(load_json(private_request, "Final request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = active_window(request, current, "Final approval")
    clean_main(request, git_runner, "Final VPC cleanup apply")
    evidence = validate_prepare_evidence(request, repository_root, current)
    output = require_new_private_directory(Path(request["privateFinalOutputDirectory"]), "Private final output")
    require(not is_within(output, repository_root), "Final output must remain outside repository")
    return {"request": request, "request_path": private_request, "evidence": evidence, "output": output, "remaining": remaining}


def redacted_final_verification(context: dict[str, Any]) -> dict[str, Any]:
    boundary = context["request"]["planBoundary"]
    return {
        "status": "aws-dev-vpc-final-apply-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_final_request_sha256": file_sha256(context["request_path"]),
        "private_prepare_request_sha256": boundary["privatePrepareRequestSha256"],
        "binary_plan_sha256": boundary["binaryPlanSha256"],
        "managed_delete_count": 1,
        "human_review_verified": True,
        "orphan_security_group_deleted": True,
        "operational_commands_executed": [],
        "terraform_init_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "state_push_authorized": False,
        "remaining_final_approval_seconds": context["remaining"],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-vpc-final-apply-approval",
    }


def execute_final(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_final(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_APPLY") == FINAL_CONFIRMATION, f"Set CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_APPLY={FINAL_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_PREPARE", "CONFIRM_AWS_DEV_VPC_ONLY_RECOVERY", "CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY", "CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH")
    require(all(not os.environ.get(name) for name in forbidden), "Other mutation confirmations must be unset")
    request = context["request"]
    evidence = context["evidence"]
    recovery = evidence["recovery"]
    plan_evidence = prepare_plan_evidence(recovery)
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    group_id = recovery["target"]["GroupId"]
    vpc_id = RECOVERY_12.raw_attribute(recovery["state"], "module.vpc", "aws_vpc", "this", None, "id")
    binary = evidence["artifacts"]["binary"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-before-vpc-final-apply", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-before-vpc-final-apply", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = parse_json_bytes(run_logged(output, "terraform-state-pull-before-vpc-final-apply", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live state before VPC apply")
    require(FINAL_13.semantic_partial_state(pulled) == FINAL_13.semantic_partial_state(recovery["state"]), "Live state changed since VPC plan")
    require(TEARDOWN.state_list(run_logged(output, "terraform-state-list-before-vpc-final-apply", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == PENDING_ADDRESSES, "Final live state inventory changed")
    run_expected_missing(output, "security-group-before-vpc-final-apply", ["aws", "ec2", "describe-security-groups", "--region", TEARDOWN.AWS_REGION, "--group-ids", group_id, "--output", "json"], b"InvalidGroup.NotFound", environment, repository_root, runner)
    shown = run_logged(output, "terraform-show-reviewed-vpc-final-plan-json", ["terraform", "show", "-json", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(hashlib.sha256(shown.stdout).hexdigest() == request["planBoundary"]["planJsonSha256"], "Reviewed VPC plan JSON changed")
    vpc_plan_gate(parse_json_bytes(shown.stdout, "Reviewed VPC plan"))
    before_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-before-vpc-final-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before VPC apply"))
    TEARDOWN.require_clean_lock(before_history)
    applied = run_logged(output, "terraform-apply-reviewed-vpc-final-plan", ["terraform", "apply", "-input=false", "-auto-approve", str(binary)], environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    summary = re.search(rb"Apply complete! Resources: ([0-9]+) added, ([0-9]+) changed, ([0-9]+) destroyed\.", applied.stdout)
    require(summary is not None and tuple(map(int, summary.groups())) == (0, 0, 1), "Final VPC apply summary changed")
    after_pull = run_logged(output, "terraform-state-pull-after-vpc-final-apply", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-after-vpc-final-cleanup.json"
    write_private(state_path, after_pull.stdout)
    state = parse_json_bytes(after_pull.stdout, "Final empty state")
    require(PRIOR.state_instance_counts(state) == (0, 0), "Final remote state is not empty")
    require(TEARDOWN.state_list(run_logged(output, "terraform-state-list-after-vpc-final-apply", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == set(), "Final state list is not empty")
    after_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-after-vpc-final-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after VPC apply"))
    state_delta = after_history["stateVersions"] - before_history["stateVersions"]
    require(1 <= state_delta <= 3 and after_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Final VPC state object lifecycle changed")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Final VPC lock lifecycle changed")
    TEARDOWN.require_clean_lock(after_history)
    run_expected_missing(output, "vpc-after-vpc-final-apply", ["aws", "ec2", "describe-vpcs", "--region", TEARDOWN.AWS_REGION, "--vpc-ids", vpc_id, "--output", "json"], b"InvalidVpcID.NotFound", environment, repository_root, runner)
    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "completedAtUtc": utc_text(current),
        "privateFinalRequestSha256": file_sha256(context["request_path"]),
        "binaryPlanSha256": request["planBoundary"]["binaryPlanSha256"],
        "orphanSecurityGroupDeleted": True,
        "managedDestroyedCount": 1,
        "managedStateAddressCount": 0,
        "dataStateAddressCount": 0,
        "stateAddressCount": 0,
        "stateAddressInventorySha256": address_digest(set()),
        "finalStateSha256": file_sha256(state_path),
        "vpcAbsent": True,
        "stateObjectVersionDelta": state_delta,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
        "lockObjectAbsent": True,
        "terraformInitExecuted": False,
        "terraformPlanExecutedByFinalApply": False,
        "exactSavedPlanApplied": True,
        "automaticRetryPerformed": False,
        "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-eks-sg-vpc-cleanup-evidence.json"
    write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-result-v1",
        "status": "aws-dev-eks-sg-vpc-cleanup-completed",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_final_request_sha256": evidence_record["privateFinalRequestSha256"],
        "binary_plan_sha256": evidence_record["binaryPlanSha256"],
        "final_cleanup_evidence_sha256": file_sha256(evidence_path),
        "orphan_security_group_deleted": True,
        "managed_destroyed_count": 1,
        "managed_state_address_count": 0,
        "data_state_address_count": 0,
        "total_state_address_count": 0,
        "state_address_inventory_sha256": evidence_record["stateAddressInventorySha256"],
        "final_state_sha256": evidence_record["finalStateSha256"],
        "vpc_absent": True,
        "state_object_version_delta": state_delta,
        "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1,
        "lock_object_absent": True,
        "terraform_init_executed": False,
        "terraform_plan_executed_by_final_apply": False,
        "exact_saved_plan_applied": True,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "record-private-final-cleanup-evidence-and-stop-aws-dev-work",
    }
    result_path = output / "aws-dev-eks-sg-vpc-cleanup-result.json"
    write_private_json(result_path, result)
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
        parser.exit(1, f"AWS-dev EKS-SG/VPC cleanup stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

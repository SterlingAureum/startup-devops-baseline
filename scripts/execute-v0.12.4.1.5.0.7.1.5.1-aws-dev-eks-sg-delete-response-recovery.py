#!/usr/bin/env python3
"""Resume VPC-only planning after the bound EKS-SG delete returned success JSON."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py"
RECOVERY_CONFIRMATION = "verify-deleted-eks-security-group-and-plan-vpc-destroy"
FINAL_CONFIRMATION = "apply-reviewed-vpc-only-recovery-plan"
INCIDENT_CONTROL_PLANE_COMMIT = "2366976f4a40fc397bf45e0d71f7be0a9ce72d5f"
INCIDENT_PREPARE_REQUEST_SHA256 = "15e178bf565b80c50e441829955291bedcf430035c01b8e94d843731e729b625"
IDENTITY_STDOUT_SHA256 = "96f07df216dfe7b89b6bf4194d7939fffe813df5d6ad18e0bc04cee4458a7c77"
TERRAFORM_VERSION_STDOUT_SHA256 = "b8b71532b158676046596265d7f7b92de62474f9307086aee6a97c0f46089026"
STATE_PULL_STDOUT_SHA256 = "0b6c70b0df67dfaab60c6e15cab920b9dabbae032287e8f2258e6116cf1cfa43"
STATE_LIST_STDOUT_SHA256 = "1be0314b76ccf644267ad1c6b18b06d9b42b815b1c3f0d1b3e54aa8ee4be297f"
SG_BEFORE_DELETE_STDOUT_SHA256 = "5016252e638c4da2f696eed09c8db8adc753ab4adcfc3596bc5cb693956c1c83"
S3_HISTORY_BEFORE_STDOUT_SHA256 = "72771d6b8cdc8abaee8600010148b64589907d4a3651e7ec6e43a4a476125086"
DELETE_STDOUT_SHA256 = "fe1cb2564af4e2ea11993e6a2608d1bbcda6c1006bf5d4a15fb9809a25fe03f3"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
MAXIMUM_RECOVERY_WINDOW_SECONDS = 3600
MAXIMUM_FINAL_WINDOW_SECONDS = 10800
MAXIMUM_REVIEW_LIFETIME_SECONDS = 14400
MINIMUM_REMAINING_SECONDS = 900
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_module(BASE_PATH, "eks_sg_vpc_cleanup_incident_dependency")
RecoveryError = BASE.CleanupError
CommandFailure = BASE.CommandFailure
GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def utc_timestamp(value: Any, label: str) -> datetime:
    return BASE.utc_timestamp(value, label)


def utc_text(value: datetime) -> str:
    return BASE.utc_text(value)


def incident_boundary() -> dict[str, Any]:
    return {
        "incidentControlPlaneCommit": INCIDENT_CONTROL_PLANE_COMMIT,
        "privateIncidentPrepareRequestSha256": INCIDENT_PREPARE_REQUEST_SHA256,
        "awsIdentityStdoutSha256": IDENTITY_STDOUT_SHA256,
        "terraformVersionStdoutSha256": TERRAFORM_VERSION_STDOUT_SHA256,
        "statePullStdoutSha256": STATE_PULL_STDOUT_SHA256,
        "stateListStdoutSha256": STATE_LIST_STDOUT_SHA256,
        "securityGroupBeforeDeleteStdoutSha256": SG_BEFORE_DELETE_STDOUT_SHA256,
        "s3HistoryBeforePlanStdoutSha256": S3_HISTORY_BEFORE_STDOUT_SHA256,
        "deleteSecurityGroupStdoutSha256": DELETE_STDOUT_SHA256,
        "deleteSecurityGroupStderrSha256": EMPTY_SHA256,
        "targetSecurityGroupIdSha256": BASE.SG_ID_SHA256,
        "deleteReturn": True,
        "deleteResponseGroupIdBound": True,
        "postDeleteAbsenceEvidenceCreated": False,
        "vpcSavedPlanCreated": False,
    }


def recovery_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True,
        "securityGroupAbsenceRead": True,
        "s3ObjectHistoryRead": True,
        "terraformVersionRead": True,
        "terraformStateRead": True,
        "terraformSavedDestroyPlan": True,
        "securityGroupDelete": False,
        "otherAwsMutation": False,
        "terraformInit": False,
        "terraformApply": False,
        "terraformUnsavedDestroy": False,
        "statePush": False,
        "directS3Mutation": False,
        "forceUnlock": False,
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
        "securityGroupDelete": False,
        "otherAwsMutation": False,
        "terraformInit": False,
        "terraformPlan": False,
        "terraformUnsavedDestroy": False,
        "statePush": False,
        "directS3Mutation": False,
        "forceUnlock": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }


def validate_recovery_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateIncidentPrepareRequestPath",
        "privateIncidentPrepareOutputDirectory", "privateRecoveryOutputDirectory",
        "incidentBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.5.1-aws-dev-eks-sg-delete-response-recovery-request-v1", "Recovery schema changed")
    require(value["operation"] == RECOVERY_CONFIRMATION, "Recovery operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateIncidentPrepareRequestPath", "privateIncidentPrepareOutputDirectory", "privateRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["incidentBoundary"] == incident_boundary(), "Incident boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc", "planReviewExpiresAtUtc"}, "Recovery approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Recovery approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Recovery approval expiry")
    review = utc_timestamp(approval["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_RECOVERY_WINDOW_SECONDS), "Recovery approval must be positive and at most one hour")
    require(review > expiry and review - start <= timedelta(seconds=MAXIMUM_REVIEW_LIFETIME_SECONDS), "Plan review must end after recovery and within four hours")
    require(value["executionBoundary"] == recovery_execution_boundary(), "Recovery execution boundary changed")
    return value


def validate_final_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateRecoveryRequestPath",
        "privateRecoveryOutputDirectory", "privateFinalOutputDirectory", "planBoundary",
        "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Final request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-apply-request-v1", "Final schema changed")
    require(value["operation"] == FINAL_CONFIRMATION, "Final operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateRecoveryRequestPath", "privateRecoveryOutputDirectory", "privateFinalOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    boundary = value["planBoundary"]
    keys = {
        "privateRecoveryRequestSha256", "binaryPlanSha256", "planJsonSha256",
        "planTextSha256", "addressInventorySha256", "planRecordSha256",
        "recoveryResultSha256", "managedDeleteCount", "dataChangeCount",
        "resourceDriftCount", "importCount", "humanReviewed",
        "orphanSecurityGroupAbsenceVerified", "planReviewExpiresAtUtc",
    }
    require(isinstance(boundary, dict) and set(boundary) == keys, "Plan boundary fields changed")
    for key in ("privateRecoveryRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256", "recoveryResultSha256"):
        require(isinstance(boundary[key], str) and SHA_RE.fullmatch(boundary[key]), f"Invalid digest: {key}")
    require(boundary["managedDeleteCount"] == 1 and boundary["dataChangeCount"] == 0 and boundary["resourceDriftCount"] == 0 and boundary["importCount"] == 0, "Final plan count boundary changed")
    require(boundary["humanReviewed"] is True and boundary["orphanSecurityGroupAbsenceVerified"] is True, "Final review or SG absence boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Final approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Final approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Final approval expiry")
    review = utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_FINAL_WINDOW_SECONDS), "Final approval must be positive and at most three hours")
    require(expiry <= review, "Final approval exceeds plan review lifetime")
    require(value["executionBoundary"] == final_execution_boundary(), "Final execution boundary changed")
    return value


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


def require_artifact(output: Path, name: str, digest: str) -> Path:
    path = BASE.require_private_file(output / name, f"Incident artifact {name}")
    require(BASE.file_sha256(path) == digest, f"Incident artifact digest changed: {name}")
    return path


def validate_incident(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    prepare_request_path = BASE.require_private_file(Path(request["privateIncidentPrepareRequestPath"]), "Incident prepare request")
    require(BASE.file_sha256(prepare_request_path) == INCIDENT_PREPARE_REQUEST_SHA256, "Incident prepare request digest changed")
    prepare_request = BASE.validate_prepare_request(BASE.load_json(prepare_request_path, "Incident prepare request"))
    require(prepare_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT, "Incident control-plane commit changed")
    require(prepare_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and prepare_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Incident runtime target changed")
    recovery = BASE.validate_recovery(prepare_request, repository_root)
    output = BASE.require_private_directory(Path(request["privateIncidentPrepareOutputDirectory"]), "Incident prepare output")
    require(str(output) == prepare_request["privatePrepareOutputDirectory"], "Incident prepare output path changed")
    artifacts = {
        "identity": require_artifact(output, "aws-identity-eks-sg-prepare.stdout", IDENTITY_STDOUT_SHA256),
        "version": require_artifact(output, "terraform-version-eks-sg-prepare.stdout", TERRAFORM_VERSION_STDOUT_SHA256),
        "state": require_artifact(output, "terraform-state-pull-eks-sg-prepare.stdout", STATE_PULL_STDOUT_SHA256),
        "state_list": require_artifact(output, "terraform-state-list-eks-sg-prepare.stdout", STATE_LIST_STDOUT_SHA256),
        "sg_before": require_artifact(output, "security-group-before-delete.stdout", SG_BEFORE_DELETE_STDOUT_SHA256),
        "history": require_artifact(output, "s3-object-history-before-vpc-plan.stdout", S3_HISTORY_BEFORE_STDOUT_SHA256),
        "delete": require_artifact(output, "delete-bound-orphan-eks-security-group.stdout", DELETE_STDOUT_SHA256),
        "delete_stderr": require_artifact(output, "delete-bound-orphan-eks-security-group.stderr", EMPTY_SHA256),
    }
    empty_artifacts = ("aws-identity-eks-sg-prepare.stderr", "terraform-version-eks-sg-prepare.stderr", "terraform-state-pull-eks-sg-prepare.stderr", "terraform-state-list-eks-sg-prepare.stderr", "security-group-before-delete.stderr", "s3-object-history-before-vpc-plan.stderr")
    for name in empty_artifacts:
        require_artifact(output, name, EMPTY_SHA256)
    expected_names = {
        "aws-identity-eks-sg-prepare.stdout", "terraform-version-eks-sg-prepare.stdout",
        "terraform-state-pull-eks-sg-prepare.stdout", "terraform-state-list-eks-sg-prepare.stdout",
        "security-group-before-delete.stdout", "s3-object-history-before-vpc-plan.stdout",
        "delete-bound-orphan-eks-security-group.stdout", "delete-bound-orphan-eks-security-group.stderr",
        *empty_artifacts,
    }
    require({path.name for path in output.iterdir()} == expected_names, "Incident output artifact inventory changed")
    identity = BASE.load_json(artifacts["identity"], "Incident AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "Incident AWS account changed")
    version = BASE.load_json(artifacts["version"], "Incident Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Incident Terraform version changed")
    state = BASE.load_json(artifacts["state"], "Incident state")
    require(BASE.FINAL_13.semantic_partial_state(state) == BASE.FINAL_13.semantic_partial_state(recovery["state"]), "Incident state changed")
    require(BASE.TEARDOWN.state_list(artifacts["state_list"].read_bytes()) == BASE.PENDING_ADDRESSES, "Incident state inventory changed")
    BASE.validate_security_group(BASE.load_json(artifacts["sg_before"], "Incident security group"), request["expectedAwsAccountId"])
    delete_response = BASE.validate_delete_security_group_response(artifacts["delete"].read_bytes())
    require(delete_response["responseShape"] == "json" and delete_response["return"] is True and delete_response["groupIdBound"] is True, "Incident delete success response changed")
    before_history = BASE.TEARDOWN.history_counts(BASE.load_json(artifacts["history"], "Incident S3 history"))
    BASE.TEARDOWN.require_clean_lock(before_history)
    for name in ("security-group-after-delete.stdout", "security-group-after-delete.stderr", "aws-dev-vpc-final-cleanup.tfplan", "aws-dev-vpc-final-cleanup-plan.json", "aws-dev-vpc-final-cleanup-plan.txt", "vpc-final-cleanup-address-inventory.json", "vpc-final-cleanup-plan-record.json"):
        require(not (output / name).exists(), f"Incident unexpectedly produced {name}")
    return {
        "prepare_request_path": prepare_request_path,
        "prepare_request": prepare_request,
        "recovery": recovery,
        "output": output,
        "state": state,
        "before_history": before_history,
        "target": recovery["target"],
    }


def verify_recovery(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = BASE.run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = BASE.require_private_file(request_path, "Private delete-response recovery request")
    require(not BASE.is_within(private_request, repository_root), "Recovery request must remain outside repository")
    request = validate_recovery_request(BASE.load_json(private_request, "Recovery request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = active_window(request, current, "Recovery approval")
    clean_main(request, git_runner, "Delete-response recovery")
    incident = validate_incident(request, repository_root)
    output = BASE.require_new_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(not BASE.is_within(output, repository_root), "Recovery output must remain outside repository")
    require(not BASE.is_within(output, incident["output"]) and not BASE.is_within(incident["output"], output), "Recovery output must not overlap incident evidence")
    return {"request": request, "request_path": private_request, "incident": incident, "output": output, "remaining": remaining}


def redacted_recovery_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-eks-sg-delete-response-recovery-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": BASE.file_sha256(context["request_path"]),
        "private_incident_prepare_request_sha256": INCIDENT_PREPARE_REQUEST_SHA256,
        "delete_security_group_stdout_sha256": DELETE_STDOUT_SHA256,
        "delete_return_verified": True,
        "delete_response_group_id_bound": True,
        "post_delete_absence_evidence_present": False,
        "vpc_saved_plan_present": False,
        "security_group_delete_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "operational_commands_executed": [],
        "remaining_recovery_approval_seconds": context["remaining"],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-sg-absence-verification-and-vpc-plan-approval",
    }


def execute_recovery(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = BASE.run_git, runner: CommandRunner = BASE.run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_recovery(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_EKS_SG_DELETE_RESPONSE_RECOVERY") == RECOVERY_CONFIRMATION, f"Set CONFIRM_AWS_DEV_EKS_SG_DELETE_RESPONSE_RECOVERY={RECOVERY_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_PREPARE", "CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_APPLY", "CONFIRM_AWS_DEV_VPC_ONLY_RECOVERY", "CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY", "CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH")
    require(all(not os.environ.get(name) for name in forbidden), "Other mutation confirmations must be unset")
    request = context["request"]
    incident = context["incident"]
    recovery = incident["recovery"]
    plan_evidence = BASE.prepare_plan_evidence(recovery)
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    tfvars = BASE.require_private_file(plan_evidence["output"] / "terraform.tfvars.private", "Private Terraform tfvars")
    group_id = incident["target"]["GroupId"]

    identity = BASE.parse_json_bytes(BASE.run_logged(output, "aws-identity-delete-response-recovery", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = BASE.parse_json_bytes(BASE.run_logged(output, "terraform-version-delete-response-recovery", ["terraform", "version", "-json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = BASE.parse_json_bytes(BASE.run_logged(output, "terraform-state-pull-delete-response-recovery", ["terraform", "state", "pull"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live VPC-only state")
    require(BASE.FINAL_13.semantic_partial_state(pulled) == BASE.FINAL_13.semantic_partial_state(incident["state"]), "Live state changed since failed prepare")
    require(BASE.TEARDOWN.state_list(BASE.run_logged(output, "terraform-state-list-delete-response-recovery", ["terraform", "state", "list"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == BASE.PENDING_ADDRESSES, "Live state is not the exact VPC-only inventory")
    BASE.run_expected_missing(output, "security-group-after-delete-response-recovery", ["aws", "ec2", "describe-security-groups", "--region", BASE.TEARDOWN.AWS_REGION, "--group-ids", group_id, "--output", "json"], b"InvalidGroup.NotFound", environment, repository_root, runner)
    before_history = BASE.TEARDOWN.history_counts(BASE.parse_json_bytes(BASE.run_logged(output, "s3-object-history-before-recovered-vpc-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", BASE.TEARDOWN.STATE_KEY, "--output", "json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before recovered VPC plan"))
    BASE.TEARDOWN.require_clean_lock(before_history)
    require(before_history == incident["before_history"], "State or lock history changed since the stopped prepare")

    binary = output / "aws-dev-vpc-final-cleanup-recovered.tfplan"
    cidr = plan_evidence["recovery_request"]["privateManagementCidr"]
    cidr_argument = "-var=eks_public_access_cidrs=" + json.dumps([cidr], separators=(",", ":"))
    BASE.run_logged(output, "terraform-plan-recovered-vpc-final-cleanup", ["terraform", "plan", "-destroy", "-input=false", "-lock=true", "-lock-timeout=0s", f"-var-file={tfvars}", cidr_argument, f"-out={binary}"], environment, BASE.TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(binary.is_file() and not binary.is_symlink(), "Terraform did not create recovered VPC saved plan")
    binary.chmod(0o600)
    shown_json = BASE.run_logged(output, "terraform-show-recovered-vpc-final-plan-json", ["terraform", "show", "-json", str(binary)], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    plan_json = output / "aws-dev-vpc-final-cleanup-recovered-plan.json"
    BASE.write_private(plan_json, shown_json.stdout)
    inventory = BASE.vpc_plan_gate(BASE.parse_json_bytes(shown_json.stdout, "Recovered VPC saved plan"))
    inventory_path = output / "recovered-vpc-final-cleanup-address-inventory.json"
    BASE.write_private_json(inventory_path, inventory)
    shown_text = BASE.run_logged(output, "terraform-show-recovered-vpc-final-plan-text", ["terraform", "show", "-no-color", str(binary)], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(shown_text.stdout, "Recovered VPC human-readable plan is empty")
    plan_text = output / "aws-dev-vpc-final-cleanup-recovered-plan.txt"
    BASE.write_private(plan_text, shown_text.stdout)
    after_history = BASE.TEARDOWN.history_counts(BASE.parse_json_bytes(BASE.run_logged(output, "s3-object-history-after-recovered-vpc-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", BASE.TEARDOWN.STATE_KEY, "--output", "json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after recovered VPC plan"))
    require(after_history["stateVersions"] == before_history["stateVersions"] and after_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Recovered VPC plan changed remote state")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Recovered VPC plan lock lifecycle changed")
    BASE.TEARDOWN.require_clean_lock(after_history)
    record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5.1-aws-dev-recovered-vpc-plan-record-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "createdAtUtc": utc_text(current),
        "planReviewExpiresAtUtc": request["approval"]["planReviewExpiresAtUtc"],
        "privateRecoveryRequestSha256": BASE.file_sha256(context["request_path"]),
        "incidentPrepareRequestSha256": INCIDENT_PREPARE_REQUEST_SHA256,
        "deleteSecurityGroupStdoutSha256": DELETE_STDOUT_SHA256,
        "orphanSecurityGroupAbsenceVerified": True,
        "binaryPlanSha256": BASE.file_sha256(binary),
        "planJsonSha256": BASE.file_sha256(plan_json),
        "planTextSha256": BASE.file_sha256(plan_text),
        "addressInventorySha256": BASE.file_sha256(inventory_path),
        "managedDeleteCount": 1,
        "dataChangeCount": 0,
        "resourceDriftCount": 0,
        "importCount": 0,
        "humanReviewed": False,
        "securityGroupDeleteRetried": False,
        "terraformInitExecuted": False,
        "terraformApplyExecuted": False,
        "stateObjectVersionDelta": 0,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
    }
    record_path = output / "recovered-vpc-final-cleanup-plan-record.json"
    BASE.write_private_json(record_path, record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5.1-aws-dev-eks-sg-delete-response-recovery-result-v1",
        "status": "aws-dev-eks-sg-absence-verified-and-recovered-vpc-plan-awaiting-review",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_recovery_request_sha256": record["privateRecoveryRequestSha256"],
        "private_incident_prepare_request_sha256": INCIDENT_PREPARE_REQUEST_SHA256,
        "delete_security_group_stdout_sha256": DELETE_STDOUT_SHA256,
        "delete_return_verified": True,
        "delete_response_group_id_bound": True,
        "orphan_security_group_absence_verified": True,
        "security_group_delete_retried": False,
        "binary_plan_sha256": record["binaryPlanSha256"],
        "plan_json_sha256": record["planJsonSha256"],
        "plan_text_sha256": record["planTextSha256"],
        "address_inventory_sha256": record["addressInventorySha256"],
        "plan_record_sha256": BASE.file_sha256(record_path),
        "managed_delete_count": 1,
        "data_change_count": 0,
        "resource_drift_count": 0,
        "import_count": 0,
        "human_reviewed": False,
        "terraform_apply_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "review-private-recovered-vpc-plan-then-create-separate-final-apply-request",
    }
    result_path = output / "aws-dev-eks-sg-delete-response-recovery-result.json"
    BASE.write_private_json(result_path, result)
    result["recovery_result_sha256"] = BASE.file_sha256(result_path)
    return result


def validate_recovery_evidence(request: dict[str, Any], repository_root: Path, now: datetime) -> dict[str, Any]:
    recovery_request_path = BASE.require_private_file(Path(request["privateRecoveryRequestPath"]), "Private recovery request")
    boundary = request["planBoundary"]
    require(BASE.file_sha256(recovery_request_path) == boundary["privateRecoveryRequestSha256"], "Recovery request digest changed")
    recovery_request = validate_recovery_request(BASE.load_json(recovery_request_path, "Recovery request"))
    require(recovery_request["expectedMainCommit"] == request["expectedMainCommit"] and recovery_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and recovery_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Recovery and final targets differ")
    incident = validate_incident(recovery_request, repository_root)
    output = BASE.require_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(str(output) == recovery_request["privateRecoveryOutputDirectory"], "Recovery output path changed")
    names = {
        "binary": "aws-dev-vpc-final-cleanup-recovered.tfplan",
        "json": "aws-dev-vpc-final-cleanup-recovered-plan.json",
        "text": "aws-dev-vpc-final-cleanup-recovered-plan.txt",
        "inventory": "recovered-vpc-final-cleanup-address-inventory.json",
        "record": "recovered-vpc-final-cleanup-plan-record.json",
        "result": "aws-dev-eks-sg-delete-response-recovery-result.json",
    }
    digest_keys = {"binary": "binaryPlanSha256", "json": "planJsonSha256", "text": "planTextSha256", "inventory": "addressInventorySha256", "record": "planRecordSha256", "result": "recoveryResultSha256"}
    artifacts: dict[str, Path] = {}
    for key, name in names.items():
        path = BASE.require_private_file(output / name, f"Recovery artifact {name}")
        require(BASE.file_sha256(path) == boundary[digest_keys[key]], f"Recovery artifact digest changed: {name}")
        artifacts[key] = path
    record = BASE.load_json(artifacts["record"], "Recovered VPC plan record")
    for record_key, boundary_key in (("privateRecoveryRequestSha256", "privateRecoveryRequestSha256"), ("binaryPlanSha256", "binaryPlanSha256"), ("planJsonSha256", "planJsonSha256"), ("planTextSha256", "planTextSha256"), ("addressInventorySha256", "addressInventorySha256"), ("managedDeleteCount", "managedDeleteCount"), ("dataChangeCount", "dataChangeCount"), ("resourceDriftCount", "resourceDriftCount"), ("importCount", "importCount"), ("orphanSecurityGroupAbsenceVerified", "orphanSecurityGroupAbsenceVerified"), ("planReviewExpiresAtUtc", "planReviewExpiresAtUtc")):
        require(record.get(record_key) == boundary[boundary_key], f"Recovered VPC plan record changed: {record_key}")
    require(record.get("humanReviewed") is False and boundary["humanReviewed"] is True and record.get("securityGroupDeleteRetried") is False, "Separate recovered-plan review was not declared")
    result = BASE.load_json(artifacts["result"], "Delete-response recovery result")
    require(result.get("status") == "aws-dev-eks-sg-absence-verified-and-recovered-vpc-plan-awaiting-review" and result.get("security_group_delete_retried") is False and result.get("orphan_security_group_absence_verified") is True, "Recovery result boundary changed")
    inventory = BASE.load_json(artifacts["inventory"], "Recovered VPC plan inventory")
    require(BASE.vpc_plan_gate(BASE.load_json(artifacts["json"], "Recovered VPC plan JSON")) == inventory, "Recovered VPC plan inventory changed")
    require(now < utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry"), "Reviewed recovered VPC plan expired")
    return {"recovery_request": recovery_request, "request_path": recovery_request_path, "incident": incident, "output": output, "artifacts": artifacts, "record": record, "inventory": inventory}


def verify_final(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = BASE.run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = BASE.require_private_file(request_path, "Private recovered-plan final request")
    require(not BASE.is_within(private_request, repository_root), "Final request must remain outside repository")
    request = validate_final_request(BASE.load_json(private_request, "Final request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = active_window(request, current, "Final approval")
    clean_main(request, git_runner, "Recovered VPC final apply")
    evidence = validate_recovery_evidence(request, repository_root, current)
    output = BASE.require_new_private_directory(Path(request["privateFinalOutputDirectory"]), "Private final output")
    require(not BASE.is_within(output, repository_root), "Final output must remain outside repository")
    return {"request": request, "request_path": private_request, "evidence": evidence, "output": output, "remaining": remaining}


def redacted_final_verification(context: dict[str, Any]) -> dict[str, Any]:
    boundary = context["request"]["planBoundary"]
    return {
        "status": "aws-dev-recovered-vpc-final-apply-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_final_request_sha256": BASE.file_sha256(context["request_path"]),
        "private_recovery_request_sha256": boundary["privateRecoveryRequestSha256"],
        "binary_plan_sha256": boundary["binaryPlanSha256"],
        "managed_delete_count": 1,
        "human_review_verified": True,
        "orphan_security_group_absence_verified": True,
        "security_group_delete_authorized": False,
        "operational_commands_executed": [],
        "terraform_init_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "state_push_authorized": False,
        "remaining_final_approval_seconds": context["remaining"],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-recovered-vpc-plan-apply-approval",
    }


def execute_final(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = BASE.run_git, runner: CommandRunner = BASE.run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_final(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_RECOVERED_VPC_FINAL_APPLY") == FINAL_CONFIRMATION, f"Set CONFIRM_AWS_DEV_RECOVERED_VPC_FINAL_APPLY={FINAL_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_EKS_SG_DELETE_RESPONSE_RECOVERY", "CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_PREPARE", "CONFIRM_AWS_DEV_EKS_SG_VPC_CLEANUP_APPLY", "CONFIRM_AWS_DEV_VPC_ONLY_RECOVERY", "CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY", "CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH")
    require(all(not os.environ.get(name) for name in forbidden), "Other mutation confirmations must be unset")
    request = context["request"]
    evidence = context["evidence"]
    incident = evidence["incident"]
    recovery = incident["recovery"]
    plan_evidence = BASE.prepare_plan_evidence(recovery)
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    group_id = incident["target"]["GroupId"]
    vpc_id = BASE.RECOVERY_12.raw_attribute(incident["state"], "module.vpc", "aws_vpc", "this", None, "id")
    binary = evidence["artifacts"]["binary"]

    identity = BASE.parse_json_bytes(BASE.run_logged(output, "aws-identity-before-recovered-vpc-final-apply", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = BASE.parse_json_bytes(BASE.run_logged(output, "terraform-version-before-recovered-vpc-final-apply", ["terraform", "version", "-json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = BASE.parse_json_bytes(BASE.run_logged(output, "terraform-state-pull-before-recovered-vpc-final-apply", ["terraform", "state", "pull"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live state before final apply")
    require(BASE.FINAL_13.semantic_partial_state(pulled) == BASE.FINAL_13.semantic_partial_state(incident["state"]), "Live state changed since recovered VPC plan")
    require(BASE.TEARDOWN.state_list(BASE.run_logged(output, "terraform-state-list-before-recovered-vpc-final-apply", ["terraform", "state", "list"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == BASE.PENDING_ADDRESSES, "Final live state inventory changed")
    BASE.run_expected_missing(output, "security-group-before-recovered-vpc-final-apply", ["aws", "ec2", "describe-security-groups", "--region", BASE.TEARDOWN.AWS_REGION, "--group-ids", group_id, "--output", "json"], b"InvalidGroup.NotFound", environment, repository_root, runner)
    shown = BASE.run_logged(output, "terraform-show-reviewed-recovered-vpc-final-plan-json", ["terraform", "show", "-json", str(binary)], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(hashlib.sha256(shown.stdout).hexdigest() == request["planBoundary"]["planJsonSha256"], "Reviewed recovered VPC plan JSON changed")
    BASE.vpc_plan_gate(BASE.parse_json_bytes(shown.stdout, "Reviewed recovered VPC plan"))
    before_history = BASE.TEARDOWN.history_counts(BASE.parse_json_bytes(BASE.run_logged(output, "s3-object-history-before-recovered-vpc-final-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", BASE.TEARDOWN.STATE_KEY, "--output", "json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before final apply"))
    BASE.TEARDOWN.require_clean_lock(before_history)
    applied = BASE.run_logged(output, "terraform-apply-reviewed-recovered-vpc-final-plan", ["terraform", "apply", "-input=false", "-auto-approve", str(binary)], environment, BASE.TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    summary = re.search(rb"Apply complete! Resources: ([0-9]+) added, ([0-9]+) changed, ([0-9]+) destroyed\.", applied.stdout)
    require(summary is not None and tuple(map(int, summary.groups())) == (0, 0, 1), "Final recovered VPC apply summary changed")
    after_pull = BASE.run_logged(output, "terraform-state-pull-after-recovered-vpc-final-apply", ["terraform", "state", "pull"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-after-recovered-vpc-final-cleanup.json"
    BASE.write_private(state_path, after_pull.stdout)
    state = BASE.parse_json_bytes(after_pull.stdout, "Final empty state")
    require(BASE.PRIOR.state_instance_counts(state) == (0, 0), "Final remote state is not empty")
    require(BASE.TEARDOWN.state_list(BASE.run_logged(output, "terraform-state-list-after-recovered-vpc-final-apply", ["terraform", "state", "list"], environment, BASE.COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout) == set(), "Final state list is not empty")
    after_history = BASE.TEARDOWN.history_counts(BASE.parse_json_bytes(BASE.run_logged(output, "s3-object-history-after-recovered-vpc-final-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", BASE.TEARDOWN.STATE_KEY, "--output", "json"], environment, BASE.COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after final apply"))
    state_delta = after_history["stateVersions"] - before_history["stateVersions"]
    require(1 <= state_delta <= 3 and after_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Final VPC state object lifecycle changed")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Final VPC lock lifecycle changed")
    BASE.TEARDOWN.require_clean_lock(after_history)
    BASE.run_expected_missing(output, "vpc-after-recovered-vpc-final-apply", ["aws", "ec2", "describe-vpcs", "--region", BASE.TEARDOWN.AWS_REGION, "--vpc-ids", vpc_id, "--output", "json"], b"InvalidVpcID.NotFound", environment, repository_root, runner)
    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-cleanup-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "completedAtUtc": utc_text(current),
        "privateFinalRequestSha256": BASE.file_sha256(context["request_path"]),
        "binaryPlanSha256": request["planBoundary"]["binaryPlanSha256"],
        "orphanSecurityGroupAbsenceVerified": True,
        "securityGroupDeleteRetried": False,
        "managedDestroyedCount": 1,
        "managedStateAddressCount": 0,
        "dataStateAddressCount": 0,
        "stateAddressCount": 0,
        "stateAddressInventorySha256": BASE.address_digest(set()),
        "finalStateSha256": BASE.file_sha256(state_path),
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
    evidence_path = output / "aws-dev-recovered-vpc-final-cleanup-evidence.json"
    BASE.write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-cleanup-result-v1",
        "status": "aws-dev-recovered-vpc-final-cleanup-completed",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_final_request_sha256": evidence_record["privateFinalRequestSha256"],
        "binary_plan_sha256": evidence_record["binaryPlanSha256"],
        "final_cleanup_evidence_sha256": BASE.file_sha256(evidence_path),
        "orphan_security_group_absence_verified": True,
        "security_group_delete_retried": False,
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
    result_path = output / "aws-dev-recovered-vpc-final-cleanup-result.json"
    BASE.write_private_json(result_path, result)
    result["final_cleanup_result_sha256"] = BASE.file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify-recovery", "recovery", "verify-final", "final"))
    parser.add_argument("--private-recovery-request", type=Path)
    parser.add_argument("--private-final-request", type=Path)
    args = parser.parse_args()
    try:
        if args.phase in {"verify-recovery", "recovery"}:
            require(args.private_recovery_request is not None and args.private_final_request is None, "Recovery phase requires only --private-recovery-request")
            context = verify_recovery(args.private_recovery_request)
            result = redacted_recovery_verification(context) if args.phase == "verify-recovery" else execute_recovery(args.private_recovery_request)
        else:
            require(args.private_final_request is not None and args.private_recovery_request is None, "Final phase requires only --private-final-request")
            context = verify_final(args.private_final_request)
            result = redacted_final_verification(context) if args.phase == "verify-final" else execute_final(args.private_final_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, RecoveryError) as error:
        parser.exit(1, f"AWS-dev EKS-SG delete-response recovery stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create, verify, and apply one exact saved aws-dev destroy plan."""

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
SEMANTIC_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.py"
QUALIFICATION_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.py"
PLAN_CONFIRMATION = "plan-reviewed-aws-dev-remote-state-teardown"
DESTROY_CONFIRMATION = "destroy-reviewed-aws-dev-with-exact-saved-plan"
RECOVERY_REQUEST_SHA256 = "d20b549187fb360ac4b9ad45d0233bc1657b43b84cb0b2915e29d3ec7d552d4e"
RECOVERY_EVIDENCE_SHA256 = "e064b6ce9460e3f9e0a0d87bfc5b1622f3a18b828c9b27fb93dffac8b492d0d1"
RECOVERY_RESULT_SHA256 = "9006818a0806e5c9693c9766a2ec73c814e7038bdfa0707e2531d0a13bec18c6"
LIVE_STATE_SHA256 = "0de88b8e306055c714fdd92c2192b575055bde56e0dc7b96c2de6a0c164b7bf9"
STATE_INVENTORY_SHA256 = "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691"
NORMALIZED_CHECKS_SHA256 = "cce879cf1dc7519f44b5a75d6802b9ef517712c1483688c0fc98184266ce11a1"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
STATE_KEY = "environments/dev/terraform.tfstate"
MANAGED_COUNT = 90
DATA_COUNT = 13
TOTAL_COUNT = 103
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 300
TERRAFORM_TIMEOUT_SECONDS = 7200
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class TeardownError(ValueError):
    pass


class CommandFailure(TeardownError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TeardownError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEMANTIC = load_module(SEMANTIC_PATH, "aws_dev_semantic_recovery_teardown_dependency")
QUALIFICATION = load_module(QUALIFICATION_PATH, "aws_dev_post_create_qualification_teardown_dependency")
PRIOR = SEMANTIC.PRIOR
APPLY = SEMANTIC.APPLY
BASE = SEMANTIC.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TeardownError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def address_digest(addresses: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(addresses)) + ("\n" if addresses else "")).encode()).hexdigest()


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise TeardownError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise TeardownError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def write_private(path: Path, value: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(value)
    path.chmod(0o600)


def write_private_json(path: Path, value: Any) -> None:
    write_private(path, canonical_json(value))


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise TeardownError(f"{label} must be a valid UTC timestamp") from error
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
        "recoveryControlPlaneCommit": QUALIFICATION.RECOVERY_CONTROL_PLANE_COMMIT,
        "privateRecoveryRequestSha256": RECOVERY_REQUEST_SHA256,
        "privateRecoveryEvidenceSha256": RECOVERY_EVIDENCE_SHA256,
        "privateRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "liveStateSha256": LIVE_STATE_SHA256,
        "stateAddressInventorySha256": STATE_INVENTORY_SHA256,
        "normalizedCheckResultsSha256": NORMALIZED_CHECKS_SHA256,
        "stateSerial": 9,
        "managedStateAddressCount": MANAGED_COUNT,
        "dataStateAddressCount": DATA_COUNT,
        "totalStateAddressCount": TOTAL_COUNT,
        "semanticStateEqual": True,
        "environmentCreated": True,
        "unexplainedAddressCount": 0,
    }


def plan_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True, "s3ObjectHistoryRead": True,
        "terraformVersionRead": True, "terraformStateRead": True,
        "terraformSavedDestroyPlan": True, "terraformInit": False,
        "terraformApply": False, "terraformUnsavedDestroy": False,
        "statePush": False, "directS3Mutation": False, "forceUnlock": False,
        "kubernetesCommand": False, "secretValueRead": False,
        "automaticRetry": False, "automaticRollback": False,
    }


def destroy_execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True, "eksAbsenceRead": True, "vpcAbsenceRead": True,
        "s3ObjectHistoryRead": True, "terraformVersionRead": True,
        "terraformStateRead": True, "terraformExactSavedPlanApply": True,
        "terraformInit": False, "terraformPlan": False,
        "terraformUnsavedDestroy": False, "statePush": False,
        "directS3Mutation": False, "forceUnlock": False,
        "kubernetesCommand": False, "secretValueRead": False,
        "automaticRetry": False, "automaticRollback": False,
    }


def validate_plan_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateSemanticRecoveryRequestPath",
        "privateSemanticRecoveryOutputDirectory", "privateTeardownPlanOutputDirectory",
        "recoveryBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Teardown plan request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1-aws-dev-teardown-plan-request-v1", "Plan request schema changed")
    require(value["operation"] == PLAN_CONFIRMATION, "Plan request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateSemanticRecoveryRequestPath", "privateSemanticRecoveryOutputDirectory", "privateTeardownPlanOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["recoveryBoundary"] == recovery_boundary(), "Recovery boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc", "planReviewExpiresAtUtc"}, "Plan approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Plan approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Plan approval expiry")
    review = utc_timestamp(approval["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(hours=1), "Plan approval window must be positive and at most one hour")
    require(review > expiry and review - start <= timedelta(hours=4), "Plan review window must end after planning and within four hours")
    require(value["executionBoundary"] == plan_execution_boundary(), "Plan execution boundary changed")
    return value


def validate_destroy_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateTeardownPlanRequestPath",
        "privateTeardownPlanOutputDirectory", "privateDestroyOutputDirectory",
        "planBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Destroy request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1-aws-dev-teardown-destroy-request-v1", "Destroy request schema changed")
    require(value["operation"] == DESTROY_CONFIRMATION, "Destroy request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateTeardownPlanRequestPath", "privateTeardownPlanOutputDirectory", "privateDestroyOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    boundary = value["planBoundary"]
    expected_keys = {"privatePlanRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256", "managedDeleteCount", "dataChangeCount", "resourceDriftCount", "importCount", "humanReviewed", "planReviewExpiresAtUtc"}
    require(isinstance(boundary, dict) and set(boundary) == expected_keys, "Destroy plan boundary fields changed")
    for key in ("privatePlanRequestSha256", "binaryPlanSha256", "planJsonSha256", "planTextSha256", "addressInventorySha256", "planRecordSha256"):
        require(isinstance(boundary[key], str) and SHA_RE.fullmatch(boundary[key]), f"Invalid digest: {key}")
    require(boundary["managedDeleteCount"] == MANAGED_COUNT and isinstance(boundary["dataChangeCount"], int) and 0 <= boundary["dataChangeCount"] <= DATA_COUNT, "Plan address counts changed")
    require(boundary["resourceDriftCount"] == 0 and boundary["importCount"] == 0 and boundary["humanReviewed"] is True, "Plan review boundary changed")
    utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Destroy approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Destroy approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Destroy approval expiry")
    require(expiry > start and expiry - start <= timedelta(hours=3), "Destroy approval window must be positive and at most three hours")
    require(expiry <= utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry"), "Destroy approval exceeds plan review lifetime")
    require(value["executionBoundary"] == destroy_execution_boundary(), "Destroy execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise TeardownError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def require_clean_main(request: dict[str, Any], git_runner: GitRunner, operation: str) -> None:
    expected = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", f"{operation} must run from main")
    require(git_runner(["status", "--porcelain"]) == "", f"{operation} requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected and git_runner(["rev-parse", "origin/main"]) == expected, "HEAD and origin/main must equal reviewed main")


def require_active_approval(request: dict[str, Any], now: datetime, prefix: str) -> int:
    start = utc_timestamp(request["approval"]["notBeforeUtc"], f"{prefix} approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], f"{prefix} approval expiry")
    require(start <= now < expiry, f"{prefix} approval is not currently active")
    remaining = int((expiry - now).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, f"{prefix} approval has less than 15 minutes remaining")
    return remaining


def validate_recovery_chain(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    recovery_request_path = require_private_file(Path(request["privateSemanticRecoveryRequestPath"]), "Semantic recovery request")
    require(not is_within(recovery_request_path, repository_root), "Semantic recovery request must remain outside the repository")
    require(file_sha256(recovery_request_path) == RECOVERY_REQUEST_SHA256, "Semantic recovery request digest changed")
    recovery_request = SEMANTIC.validate_request(load_json(recovery_request_path, "Semantic recovery request"))
    require(recovery_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "AWS account changed since semantic recovery")
    require(recovery_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Terraform version changed since semantic recovery")
    prior = SEMANTIC.validate_prior_incident(recovery_request, repository_root)
    output = require_private_directory(Path(request["privateSemanticRecoveryOutputDirectory"]), "Semantic recovery output")
    require(str(output) == recovery_request["privateRecoveryOutputDirectory"], "Semantic recovery output path changed")
    require(not is_within(output, repository_root), "Semantic recovery output must remain outside the repository")
    evidence = require_private_file(output / "aws-dev-semantic-state-recovery-evidence.json", "Semantic recovery evidence")
    result = require_private_file(output / "aws-dev-semantic-state-recovery-result.json", "Semantic recovery result")
    state = require_private_file(output / "aws-dev-state-semantic-recovery.json", "Semantic recovery state")
    require(file_sha256(evidence) == RECOVERY_EVIDENCE_SHA256, "Semantic recovery evidence digest changed")
    require(file_sha256(result) == RECOVERY_RESULT_SHA256, "Semantic recovery result digest changed")
    require(file_sha256(state) == LIVE_STATE_SHA256, "Semantic recovery state digest changed")
    QUALIFICATION.validate_recovery_evidence(load_json(evidence, "Semantic recovery evidence"))
    QUALIFICATION.validate_recovery_result(load_json(result, "Semantic recovery result"))
    state_document = load_json(state, "Semantic recovery state")
    require(SEMANTIC.semantic_state(state_document) == SEMANTIC.semantic_state(prior["prior_state"]), "Recovered state semantic identity changed")
    plan_evidence = prior["incident"]["plan_evidence"]
    return {"request_path": recovery_request_path, "request": recovery_request, "output": output, "state": state_document, "state_path": state, "prior": prior, "plan_evidence": plan_evidence}


def verify_plan_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private teardown plan request")
    require(not is_within(private_request, repository_root), "Teardown plan request must remain outside the repository")
    request = validate_plan_request(load_json(private_request, "Private teardown plan request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = require_active_approval(request, current, "Teardown plan")
    require_clean_main(request, git_runner, "Teardown planning")
    recovery = validate_recovery_chain(request, repository_root)
    output = require_new_private_directory(Path(request["privateTeardownPlanOutputDirectory"]), "Private teardown plan output")
    require(not is_within(output, repository_root), "Teardown plan output must remain outside the repository")
    for protected in (recovery["output"], recovery["plan_evidence"]["source"], recovery["plan_evidence"]["output"]):
        require(not is_within(output, protected) and not is_within(protected, output), "Teardown output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "recovery": recovery, "output": output, "remaining": remaining}


def redacted_plan_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-guarded-teardown-plan-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_plan_request_sha256": file_sha256(context["request_path"]),
        "semantic_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "semantic_recovery_evidence_sha256": RECOVERY_EVIDENCE_SHA256,
        "semantic_recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "managed_state_address_count": MANAGED_COUNT, "data_state_address_count": DATA_COUNT,
        "total_state_address_count": TOTAL_COUNT, "state_address_inventory_sha256": STATE_INVENTORY_SHA256,
        "remaining_plan_approval_seconds": context["remaining"],
        "operational_commands_executed": [], "terraform_init_authorized": False,
        "terraform_plan_authorized": False, "terraform_apply_authorized": False,
        "unsaved_destroy_authorized": False, "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-aws-dev-saved-destroy-plan-approval",
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


def state_list(value: bytes) -> set[str]:
    return {line.strip() for line in value.decode().splitlines() if line.strip()}


def destroy_plan_gate(document: dict[str, Any], expected_managed: set[str]) -> dict[str, Any]:
    require(document.get("complete") is True and document.get("errored") is False and document.get("applyable") is True, "Saved destroy plan is not complete and applyable")
    require(document.get("resource_drift") == [], "Saved destroy plan contains resource drift")
    changes = document.get("resource_changes")
    require(isinstance(changes, list) and changes, "Saved destroy plan has no resource changes")
    managed: set[str] = set()
    data: set[str] = set()
    for item in changes:
        require(isinstance(item, dict) and isinstance(item.get("address"), str), "Plan resource change shape changed")
        change = item.get("change")
        require(isinstance(change, dict) and isinstance(change.get("actions"), list), "Plan action shape changed")
        require(change.get("importing") is None, "Saved destroy plan contains import")
        if item.get("mode") == "managed":
            require(change["actions"] == ["delete"], f"Managed action is not delete-only: {item['address']}")
            managed.add(item["address"])
        elif item.get("mode") == "data":
            require(change["actions"] in (["read"], ["no-op"], ["delete"]), f"Data action changed: {item['address']}")
            data.add(item["address"])
        else:
            raise TeardownError(f"Unsupported resource mode: {item.get('mode')}")
    require(managed == expected_managed and len(managed) == MANAGED_COUNT, "Managed delete inventory differs from the reviewed create inventory")
    require(len(data) <= DATA_COUNT, "Destroy plan data change count exceeds the bound state")
    output_changes = document.get("output_changes", {})
    require(isinstance(output_changes, dict), "Plan output changes shape changed")
    require(all(isinstance(item, dict) and item.get("actions") in (["delete"], ["no-op"]) for item in output_changes.values()), "Destroy plan output action changed")
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1-private-destroy-plan-address-inventory-v1",
        "managedDeleteAddresses": sorted(managed), "dataChangeAddresses": sorted(data),
        "managedDeleteCount": len(managed), "dataChangeCount": len(data),
        "resourceDriftCount": 0, "importCount": 0,
    }


def history_counts(value: dict[str, Any]) -> dict[str, int]:
    return BASE.history_counts(value)


def require_clean_lock(counts: dict[str, int]) -> None:
    require(counts["lockLatestVersions"] == 0 and counts["lockLatestDeleteMarkers"] == 1, "Terraform native lock is not cleanly released")
    require(counts["stateDeleteMarkers"] == 0, "Canonical remote state has a delete marker")


def execute_plan(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_plan_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_TEARDOWN_PLAN") == PLAN_CONFIRMATION, f"Set CONFIRM_AWS_DEV_TEARDOWN_PLAN={PLAN_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION")
    require(all(not os.environ.get(name) for name in forbidden), "Destroy or state-mutation confirmations must be unset")
    request = context["request"]
    recovery = context["recovery"]
    plan_evidence = recovery["plan_evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    tfvars = require_private_file(plan_evidence["output"] / "terraform.tfvars.private", "Private Terraform tfvars")
    expected_addresses = recovery["prior"]["incident"]["expected_addresses"]
    expected_managed = set(plan_evidence["inventory"]["managedCreateAddresses"])

    identity = parse_json_bytes(run_logged(output, "aws-identity-before-destroy-plan", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-before-destroy-plan", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = run_logged(output, "terraform-state-pull-before-destroy-plan", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    live_state = parse_json_bytes(pulled.stdout, "Live remote state")
    require(SEMANTIC.semantic_state(live_state) == SEMANTIC.semantic_state(recovery["state"]), "Live remote state differs from the recovered semantic state")
    listed = state_list(run_logged(output, "terraform-state-list-before-destroy-plan", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout)
    require(listed == expected_addresses and address_digest(listed) == STATE_INVENTORY_SHA256, "Live state address inventory changed")
    before_history = history_counts(parse_json_bytes(run_logged(output, "s3-object-history-before-destroy-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before destroy plan"))
    require_clean_lock(before_history)

    binary = output / "aws-dev-destroy.tfplan"
    cidr = plan_evidence["recovery_request"]["privateManagementCidr"]
    cidr_argument = "-var=eks_public_access_cidrs=" + json.dumps([cidr], separators=(",", ":"))
    plan = ["terraform", "plan", "-destroy", "-input=false", "-lock=true", "-lock-timeout=0s", f"-var-file={tfvars}", cidr_argument, f"-out={binary}"]
    run_logged(output, "terraform-plan-destroy", plan, environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(binary.is_file() and not binary.is_symlink(), "Terraform did not create a regular saved destroy plan")
    binary.chmod(0o600)
    shown_json = run_logged(output, "terraform-show-destroy-plan-json", ["terraform", "show", "-json", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    plan_json = output / "aws-dev-destroy-plan.json"
    write_private(plan_json, shown_json.stdout)
    inventory = destroy_plan_gate(parse_json_bytes(shown_json.stdout, "Saved destroy plan"), expected_managed)
    inventory_path = output / "destroy-plan-address-inventory.json"
    write_private_json(inventory_path, inventory)
    shown_text = run_logged(output, "terraform-show-destroy-plan-text", ["terraform", "show", "-no-color", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(shown_text.stdout, "Human-readable destroy plan is empty")
    plan_text = output / "aws-dev-destroy-plan.txt"
    write_private(plan_text, shown_text.stdout)
    after_history = history_counts(parse_json_bytes(run_logged(output, "s3-object-history-after-destroy-plan", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after destroy plan"))
    require(after_history["stateVersions"] == before_history["stateVersions"] and after_history["stateDeleteMarkers"] == 0, "Destroy planning changed canonical state history")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Destroy plan lock lifecycle changed")
    require_clean_lock(after_history)
    record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1-aws-dev-destroy-plan-record-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "createdAtUtc": utc_text(current),
        "planReviewExpiresAtUtc": request["approval"]["planReviewExpiresAtUtc"],
        "privatePlanRequestSha256": file_sha256(context["request_path"]),
        "semanticRecoveryResultSha256": RECOVERY_RESULT_SHA256,
        "sourceManifestSha256": plan_evidence["incident"]["failed_request"]["sourceManifestSha256"],
        "providerLockfileSha256": file_sha256(plan_evidence["lockfile"]),
        "binaryPlanSha256": file_sha256(binary), "planJsonSha256": file_sha256(plan_json),
        "planTextSha256": file_sha256(plan_text), "addressInventorySha256": file_sha256(inventory_path),
        "managedDeleteCount": MANAGED_COUNT, "dataChangeCount": inventory["dataChangeCount"],
        "resourceDriftCount": 0, "importCount": 0, "humanReviewed": False,
        "terraformInitExecuted": False, "terraformApplyExecuted": False,
        "stateObjectVersionDelta": 0, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1,
    }
    record_path = output / "destroy-plan-record.json"
    write_private_json(record_path, record)
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1-aws-dev-destroy-plan-result-v1",
        "status": "aws-dev-saved-destroy-plan-produced-awaiting-human-review",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "private_plan_request_sha256": record["privatePlanRequestSha256"],
        "binary_plan_sha256": record["binaryPlanSha256"], "plan_json_sha256": record["planJsonSha256"],
        "plan_text_sha256": record["planTextSha256"], "address_inventory_sha256": record["addressInventorySha256"],
        "plan_record_sha256": file_sha256(record_path), "managed_delete_count": MANAGED_COUNT,
        "data_change_count": inventory["dataChangeCount"], "resource_drift_count": 0, "import_count": 0,
        "human_reviewed": False, "terraform_init_executed": False, "terraform_apply_executed": False,
        "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "review-private-destroy-plan-then-create-separate-destroy-request",
    }


def validate_plan_evidence(request: dict[str, Any], repository_root: Path, now: datetime) -> dict[str, Any]:
    plan_request_path = require_private_file(Path(request["privateTeardownPlanRequestPath"]), "Private teardown plan request")
    require(not is_within(plan_request_path, repository_root), "Teardown plan request must remain outside the repository")
    require(file_sha256(plan_request_path) == request["planBoundary"]["privatePlanRequestSha256"], "Teardown plan request digest changed")
    plan_request = validate_plan_request(load_json(plan_request_path, "Private teardown plan request"))
    require(plan_request["expectedMainCommit"] == request["expectedMainCommit"], "Plan and destroy commits differ")
    require(plan_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] and plan_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Plan and destroy runtime targets differ")
    output = require_private_directory(Path(request["privateTeardownPlanOutputDirectory"]), "Private teardown plan output")
    require(str(output) == plan_request["privateTeardownPlanOutputDirectory"], "Teardown plan output path changed")
    artifacts = {
        "binary": output / "aws-dev-destroy.tfplan", "json": output / "aws-dev-destroy-plan.json",
        "text": output / "aws-dev-destroy-plan.txt", "inventory": output / "destroy-plan-address-inventory.json",
        "record": output / "destroy-plan-record.json",
    }
    digest_keys = {"binary": "binaryPlanSha256", "json": "planJsonSha256", "text": "planTextSha256", "inventory": "addressInventorySha256", "record": "planRecordSha256"}
    for name, path in artifacts.items():
        artifacts[name] = require_private_file(path, f"Teardown plan artifact {name}")
        require(file_sha256(artifacts[name]) == request["planBoundary"][digest_keys[name]], f"Teardown plan artifact digest changed: {name}")
    record = load_json(artifacts["record"], "Destroy plan record")
    inventory = load_json(artifacts["inventory"], "Destroy plan inventory")
    boundary = request["planBoundary"]
    for record_key, boundary_key in (("privatePlanRequestSha256", "privatePlanRequestSha256"), ("binaryPlanSha256", "binaryPlanSha256"), ("planJsonSha256", "planJsonSha256"), ("planTextSha256", "planTextSha256"), ("addressInventorySha256", "addressInventorySha256"), ("managedDeleteCount", "managedDeleteCount"), ("dataChangeCount", "dataChangeCount"), ("resourceDriftCount", "resourceDriftCount"), ("importCount", "importCount"), ("planReviewExpiresAtUtc", "planReviewExpiresAtUtc")):
        require(record.get(record_key) == boundary[boundary_key], f"Destroy plan record changed: {record_key}")
    require(record.get("humanReviewed") is False and boundary["humanReviewed"] is True, "Separate human review was not declared")
    require(inventory.get("managedDeleteCount") == MANAGED_COUNT and inventory.get("managedDeleteAddresses") and len(inventory["managedDeleteAddresses"]) == MANAGED_COUNT, "Destroy inventory managed count changed")
    require(inventory.get("dataChangeCount") == boundary["dataChangeCount"] and inventory.get("resourceDriftCount") == 0 and inventory.get("importCount") == 0, "Destroy inventory boundary changed")
    require(now < utc_timestamp(boundary["planReviewExpiresAtUtc"], "Plan review expiry"), "Reviewed destroy plan has expired")
    recovery = validate_recovery_chain(plan_request, repository_root)
    document = load_json(artifacts["json"], "Destroy plan JSON")
    gated = destroy_plan_gate(document, set(recovery["plan_evidence"]["inventory"]["managedCreateAddresses"]))
    require(gated["managedDeleteAddresses"] == inventory["managedDeleteAddresses"] and gated["dataChangeAddresses"] == inventory["dataChangeAddresses"], "Destroy plan inventory differs from saved JSON")
    return {"plan_request": plan_request, "request_path": plan_request_path, "output": output, "artifacts": artifacts, "record": record, "inventory": inventory, "recovery": recovery}


def verify_destroy_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private destroy request")
    require(not is_within(private_request, repository_root), "Destroy request must remain outside the repository")
    request = validate_destroy_request(load_json(private_request, "Private destroy request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    remaining = require_active_approval(request, current, "Destroy")
    require_clean_main(request, git_runner, "Destroy")
    evidence = validate_plan_evidence(request, repository_root, current)
    output = require_new_private_directory(Path(request["privateDestroyOutputDirectory"]), "Private destroy output")
    require(not is_within(output, repository_root), "Destroy output must remain outside the repository")
    for protected in (evidence["output"], evidence["recovery"]["output"], evidence["recovery"]["plan_evidence"]["source"]):
        require(not is_within(output, protected) and not is_within(protected, output), "Destroy output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "evidence": evidence, "output": output, "remaining": remaining}


def redacted_destroy_verification(context: dict[str, Any]) -> dict[str, Any]:
    boundary = context["request"]["planBoundary"]
    return {
        "status": "aws-dev-reviewed-saved-destroy-plan-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_destroy_request_sha256": file_sha256(context["request_path"]),
        "private_plan_request_sha256": boundary["privatePlanRequestSha256"],
        "binary_plan_sha256": boundary["binaryPlanSha256"], "plan_json_sha256": boundary["planJsonSha256"],
        "plan_record_sha256": boundary["planRecordSha256"], "managed_delete_count": MANAGED_COUNT,
        "data_change_count": boundary["dataChangeCount"], "human_review_verified": True,
        "remaining_destroy_approval_seconds": context["remaining"], "operational_commands_executed": [],
        "terraform_init_authorized": False, "terraform_plan_authorized": False,
        "terraform_apply_authorized": False, "unsaved_destroy_authorized": False,
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-saved-destroy-plan-apply-approval",
    }


def run_expected_absent(output: Path, label: str, arguments: list[str], allowed_codes: set[bytes], environment: dict[str, str], cwd: Path, runner: CommandRunner) -> None:
    try:
        result = runner(arguments, environment, COMMAND_TIMEOUT_SECONDS, cwd)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    record_result(output, label, result)
    if result.returncode == 0:
        value = parse_json_bytes(result.stdout, label)
        require(value.get("Vpcs") == [], f"{label} unexpectedly found a resource")
        return
    require(result.stdout == b"" and any(code in result.stderr for code in allowed_codes), f"{label} absence response changed")


def state_output(state: dict[str, Any], name: str) -> Any:
    output = state.get("outputs", {}).get(name)
    require(isinstance(output, dict) and "value" in output, f"Recovered state output missing: {name}")
    return output["value"]


def execute_destroy(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_destroy_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_TEARDOWN_DESTROY") == DESTROY_CONFIRMATION, f"Set CONFIRM_AWS_DEV_TEARDOWN_DESTROY={DESTROY_CONFIRMATION}")
    forbidden = ("CONFIRM_AWS_DEV_TEARDOWN_PLAN", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION")
    require(all(not os.environ.get(name) for name in forbidden), "Other plan, destroy, or state-mutation confirmations must be unset")
    request = context["request"]
    evidence = context["evidence"]
    recovery = evidence["recovery"]
    plan_evidence = recovery["plan_evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    binary = evidence["artifacts"]["binary"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-before-destroy", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-before-destroy", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = parse_json_bytes(run_logged(output, "terraform-state-pull-before-destroy", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Live remote state")
    require(SEMANTIC.semantic_state(pulled) == SEMANTIC.semantic_state(recovery["state"]), "Live state changed after destroy planning")
    listed = state_list(run_logged(output, "terraform-state-list-before-destroy", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout)
    require(listed == recovery["prior"]["incident"]["expected_addresses"], "Live address inventory changed after destroy planning")
    shown = run_logged(output, "terraform-show-reviewed-destroy-plan-json", ["terraform", "show", "-json", str(binary)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(hashlib.sha256(shown.stdout).hexdigest() == request["planBoundary"]["planJsonSha256"], "Reviewed destroy plan JSON changed before apply")
    gated = destroy_plan_gate(parse_json_bytes(shown.stdout, "Reviewed destroy plan"), set(plan_evidence["inventory"]["managedCreateAddresses"]))
    require(gated["managedDeleteAddresses"] == evidence["inventory"]["managedDeleteAddresses"], "Reviewed managed-delete inventory changed")
    before_history = history_counts(parse_json_bytes(run_logged(output, "s3-object-history-before-destroy", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before destroy"))
    require_clean_lock(before_history)

    applied = run_logged(output, "terraform-apply-reviewed-destroy-plan", ["terraform", "apply", "-input=false", "-auto-approve", str(binary)], environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    summary = re.search(rb"Apply complete! Resources: ([0-9]+) added, ([0-9]+) changed, ([0-9]+) destroyed\.", applied.stdout)
    require(summary is not None and tuple(map(int, summary.groups())) == (0, 0, MANAGED_COUNT), "Terraform destroy summary changed")

    after_pull = run_logged(output, "terraform-state-pull-after-destroy", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    after_state_path = output / "aws-dev-state-after-destroy.json"
    write_private(after_state_path, after_pull.stdout)
    after_state = parse_json_bytes(after_pull.stdout, "State after destroy")
    managed_instances, data_instances = PRIOR.state_instance_counts(after_state)
    require(managed_instances == 0 and 0 <= data_instances <= DATA_COUNT, "Post-destroy state still contains managed resources or unexpected data")
    after_list = state_list(run_logged(output, "terraform-state-list-after-destroy", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout)
    require(after_list.issubset(recovery["prior"]["incident"]["expected_addresses"]) and not (after_list & set(plan_evidence["inventory"]["managedCreateAddresses"])), "Post-destroy address inventory contains a managed or new address")
    after_history = history_counts(parse_json_bytes(run_logged(output, "s3-object-history-after-destroy", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after destroy"))
    state_delta = after_history["stateVersions"] - before_history["stateVersions"]
    require(1 <= state_delta <= MANAGED_COUNT + 1 and after_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Destroy state object lifecycle changed")
    require(after_history["lockVersions"] - before_history["lockVersions"] == 1 and after_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Destroy lock lifecycle changed")
    require_clean_lock(after_history)
    run_expected_absent(output, "eks-cluster-after-destroy", ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"], {b"ResourceNotFoundException"}, environment, repository_root, runner)
    vpc_id = state_output(recovery["state"], "vpc_id")
    require(isinstance(vpc_id, str) and vpc_id.startswith("vpc-"), "Recovered VPC identity changed")
    run_expected_absent(output, "vpc-after-destroy", ["aws", "ec2", "describe-vpcs", "--region", AWS_REGION, "--vpc-ids", vpc_id, "--output", "json"], {b"InvalidVpcID.NotFound"}, environment, repository_root, runner)
    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.7.1-aws-dev-teardown-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "completedAtUtc": utc_text(current),
        "privateDestroyRequestSha256": file_sha256(context["request_path"]),
        "binaryPlanSha256": request["planBoundary"]["binaryPlanSha256"],
        "managedDestroyedCount": MANAGED_COUNT, "managedStateAddressCount": 0,
        "remainingDataStateAddressCount": len(after_list), "postDestroyStateSha256": file_sha256(after_state_path),
        "postDestroyAddressInventorySha256": address_digest(after_list),
        "stateObjectVersionDelta": state_delta, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
        "eksClusterAbsent": True, "vpcAbsent": True, "terraformInitExecuted": False,
        "terraformPlanExecutedByDestroy": False, "exactSavedPlanApplied": True,
        "automaticRetryPerformed": False, "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-teardown-evidence.json"
    write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1-aws-dev-teardown-result-v1",
        "status": "aws-dev-guarded-teardown-completed",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "private_destroy_request_sha256": evidence_record["privateDestroyRequestSha256"],
        "binary_plan_sha256": evidence_record["binaryPlanSha256"],
        "teardown_evidence_sha256": file_sha256(evidence_path),
        "managed_destroyed_count": MANAGED_COUNT, "managed_state_address_count": 0,
        "remaining_data_state_address_count": len(after_list),
        "post_destroy_state_sha256": evidence_record["postDestroyStateSha256"],
        "post_destroy_address_inventory_sha256": evidence_record["postDestroyAddressInventorySha256"],
        "state_object_version_delta": state_delta, "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1, "lock_delete_marker_delta": 1, "lock_object_absent": True,
        "eks_cluster_absent": True, "vpc_absent": True, "exact_saved_plan_applied": True,
        "terraform_init_executed": False, "terraform_plan_executed_by_destroy": False,
        "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False, "private_object_version_id_emitted": False,
        "next_action": "record-private-teardown-evidence-and-stop-aws-dev-work",
    }
    result_path = output / "aws-dev-teardown-result.json"
    write_private_json(result_path, result)
    result["teardown_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify-plan", "plan", "verify-destroy", "destroy"))
    parser.add_argument("--private-teardown-plan-request", type=Path)
    parser.add_argument("--private-destroy-request", type=Path)
    args = parser.parse_args()
    try:
        if args.phase in {"verify-plan", "plan"}:
            require(args.private_teardown_plan_request is not None and args.private_destroy_request is None, "Plan phase requires only --private-teardown-plan-request")
            context = verify_plan_inputs(args.private_teardown_plan_request)
            result = redacted_plan_verification(context) if args.phase == "verify-plan" else execute_plan(args.private_teardown_plan_request)
        else:
            require(args.private_destroy_request is not None and args.private_teardown_plan_request is None, "Destroy phase requires only --private-destroy-request")
            context = verify_destroy_inputs(args.private_destroy_request)
            result = redacted_destroy_verification(context) if args.phase == "verify-destroy" else execute_destroy(args.private_destroy_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, TeardownError) as error:
        parser.exit(1, f"AWS-dev guarded teardown stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

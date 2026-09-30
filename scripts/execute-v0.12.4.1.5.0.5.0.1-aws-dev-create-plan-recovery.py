#!/usr/bin/env python3
"""Recover the failed aws-dev create-plan attempt with one private /32."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BASE_EXECUTOR = ROOT / "scripts/execute-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py"
CONFIRMATION = "recover-aws-dev-create-plan-with-reviewed-management-cidr"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
STATE_KEY = "environments/dev/terraform.tfstate"
LOCK_KEY = STATE_KEY + ".tflock"
INCIDENT_COMMIT = "4d4d3db2fe6e6e194e979131799ddfff5b1b7487"
FAILED_REQUEST_SHA256 = "5d915fac07cbcc4ea0bfd763b1a78230ac66bc969c623498d1a4056868d0c151"
FAILED_ARTIFACTS = {
    "aws-identity.stdout": "b2e7ee5c1961bbb26b31ed08586888d7c98cb39da6001812dec7ddfe9a9e99fa",
    "s3-object-history-before-plan.stdout": "ccbdb79421b226d279de576d0e370de8d2de02f98a5e14652e846174459c0ac6",
    "terraform-version.stdout": "de6e7b4887d277af1b8349359a892133db8d2c5954dc8d7d69cdbbff6c492aeb",
    "terraform-init-reconfigure.stdout": "9ed3c5c1a292c0dd899dd126752b183692bdfd23841f6bdff071498dbad2c88b",
    "terraform-init-reconfigure.stderr": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "terraform-plan-create.stdout": "7816eeb8d982b4e96c0bdea007a6212a61258ca7f80d32588b47a08c5fc01507",
    "terraform-plan-create.stderr": "df1e2e6084fc655c5528258fa9ec9460a648eb2e68b7b0286011b56e22e948a0",
    "aws-dev-create.tfplan": "bc99d8d8d1c2a5b8f163f983e953b1fd64d3f03ed44fd86c90bf120b08e2d781",
}
FAILED_LOCKFILE_SHA256 = "a824bda667aac25533101eb99e1b5c6ec5415cc5f2e773793f7b1699b453fd6f"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 7200
MAXIMUM_PLAN_REVIEW_LIFETIME_SECONDS = 28800
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 180
TERRAFORM_TIMEOUT_SECONDS = 2400
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class RecoveryError(ValueError):
    pass


class CommandFailure(RecoveryError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RecoveryError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_module(BASE_EXECUTOR, "aws_dev_saved_create_plan_dependency")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_private(path: Path, value: bytes, mode: int = 0o600) -> None:
    with path.open("xb") as destination:
        destination.write(value)
    path.chmod(mode)


def write_private_json(path: Path, value: Any) -> None:
    write_private(path, canonical_json(value))


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise RecoveryError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise RecoveryError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise RecoveryError(f"{label} must be a valid UTC timestamp") from error
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


def validate_management_cidr(value: Any) -> str:
    require(isinstance(value, str), "Private management CIDR must be a string")
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as error:
        raise RecoveryError("Private management CIDR is invalid") from error
    require(network.version == 4 and network.prefixlen == 32, "Private management CIDR must be one IPv4 /32")
    require(network.network_address.is_global, "Private management CIDR must be globally routable")
    require(str(network) == value, "Private management CIDR must use canonical form")
    return value


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "incidentControlPlaneCommit",
        "expectedMainCommit", "expectedAwsAccountId", "expectedAwsRegion", "expectedClusterName",
        "expectedTerraformVersion", "privateFailedPlanRequestPath", "privateFailedPlanRequestSha256",
        "privateFailedPlanSourceDirectory", "privateFailedPlanOutputDirectory", "failedArtifactSha256s",
        "failedProviderLockfileSha256", "privateManagementCidr", "privateRecoveryPlanSourceDirectory",
        "privateRecoveryPlanOutputDirectory", "humanReview", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(value["incidentControlPlaneCommit"] == INCIDENT_COMMIT, "Incident commit changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]) is not None, "Expected AWS account is invalid")
    require(value["expectedAwsRegion"] == AWS_REGION and value["expectedClusterName"] == CLUSTER_NAME, "AWS target changed")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]) is not None, "Terraform version is invalid")
    require(value["privateFailedPlanRequestSha256"] == FAILED_REQUEST_SHA256, "Failed request digest changed")
    require(value["failedArtifactSha256s"] == FAILED_ARTIFACTS, "Failed artifact digest inventory changed")
    require(value["failedProviderLockfileSha256"] == FAILED_LOCKFILE_SHA256, "Failed provider lockfile digest changed")
    validate_management_cidr(value["privateManagementCidr"])
    for key in (
        "privateFailedPlanRequestPath", "privateFailedPlanSourceDirectory", "privateFailedPlanOutputDirectory",
        "privateRecoveryPlanSourceDirectory", "privateRecoveryPlanOutputDirectory",
    ):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["humanReview"] == {
        "failedAttemptReviewed": True,
        "failureCause": "eks-public-endpoint-missing-restricted-cidr",
        "managementCidrPrivatelyValidated": True,
        "reviewedMaximumBudgetUsd": 50,
    }, "Human review boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc", "planReviewExpiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    review_expiry = utc_timestamp(approval["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most two hours")
    require(review_expiry >= expiry and review_expiry - start <= timedelta(seconds=MAXIMUM_PLAN_REVIEW_LIFETIME_SECONDS), "Plan review window must include execution and be at most eight hours")
    require(value["executionBoundary"] == {
        "awsReadOnlyValidation": True, "localPrivateSourceCopy": True,
        "terraformInitReconfigureReadonlyLockfile": True, "terraformSavedPlan": True,
        "terraformShow": True, "terraformApply": False, "stateMigration": False,
        "statePush": False, "destroy": False, "iamPolicyAttachment": False,
        "kubernetesCommand": False, "secretValueRead": False, "directS3Mutation": False,
        "forceUnlock": False, "automaticRetry": False, "automaticRollback": False,
    }, "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RecoveryError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def validate_failed_attempt(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    failed_request_path = require_private_file(Path(request["privateFailedPlanRequestPath"]), "Failed plan request")
    require(not is_within(failed_request_path, repository_root), "Failed request must remain outside the repository")
    require(file_sha256(failed_request_path) == FAILED_REQUEST_SHA256, "Failed request digest changed")
    failed_request = BASE.validate_request(load_json(failed_request_path, "Failed plan request"))
    require(failed_request["expectedMainCommit"] == INCIDENT_COMMIT, "Failed request incident commit changed")
    require(failed_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Failed request AWS account changed")
    require(failed_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Failed request Terraform version changed")
    chain = BASE.validate_preflight_chain(failed_request, repository_root)

    failed_source = require_private_directory(Path(request["privateFailedPlanSourceDirectory"]), "Failed plan source")
    failed_output = require_private_directory(Path(request["privateFailedPlanOutputDirectory"]), "Failed plan output")
    require(str(failed_source) == failed_request["privatePlanSourceDirectory"], "Failed plan source path changed")
    require(str(failed_output) == failed_request["privatePlanOutputDirectory"], "Failed plan output path changed")
    require(not is_within(failed_source, repository_root) and not is_within(failed_output, repository_root), "Failed attempt must remain outside the repository")
    for name, digest in FAILED_ARTIFACTS.items():
        path = require_private_file(failed_output / name, f"Failed artifact {name}")
        require(file_sha256(path) == digest, f"Failed artifact digest changed: {name}")
    failed_lockfile = require_private_file(failed_source / "environments/dev/.terraform.lock.hcl", "Failed provider lockfile")
    require(file_sha256(failed_lockfile) == FAILED_LOCKFILE_SHA256, "Failed provider lockfile digest changed")
    require((failed_output / "terraform-init-reconfigure.stderr").read_bytes() == b"", "Failed init stderr is not empty")
    stderr = (failed_output / "terraform-plan-create.stderr").read_text(errors="replace")
    require("Resource precondition failed" in stderr, "Failed plan error class changed")
    require("at least one restricted CIDR" in stderr, "Failed plan CIDR error changed")
    require("0.0.0.0/0" in stderr, "Failed plan open-CIDR guard evidence changed")
    prior_history = parse_json_bytes((failed_output / "s3-object-history-before-plan.stdout").read_bytes(), "Failed pre-plan object history")
    BASE.validate_empty_history(BASE.history_counts(prior_history))
    require(not (failed_output / "terraform-show-create-json.stdout").exists(), "Failed plan unexpectedly reached terraform show")

    expected_files = set()
    for entry in chain["entries"]:
        relative = Path(entry["path"]).relative_to("infra/terraform/aws")
        current = repository_root / "infra/terraform/aws" / relative
        require(current.is_file() and not current.is_symlink(), f"Current Terraform source missing: {relative}")
        require(file_sha256(current) == entry["sha256"], f"Current Terraform source changed: {relative}")
        expected_files.add(relative.as_posix())
    return {
        "failed_request_path": failed_request_path, "failed_request": failed_request,
        "failed_source": failed_source, "failed_output": failed_output,
        "failed_lockfile": failed_lockfile, "chain": chain, "expected_files": expected_files,
    }


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private recovery request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Recovery approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Recovery approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Recovery must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Recovery requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")
    incident = validate_failed_attempt(request, repository_root)
    plan_source = require_new_private_directory(Path(request["privateRecoveryPlanSourceDirectory"]), "Recovery plan source")
    output = require_new_private_directory(Path(request["privateRecoveryPlanOutputDirectory"]), "Recovery plan output")
    require(not is_within(plan_source, repository_root) and not is_within(output, repository_root), "Recovery directories must remain outside the repository")
    require(plan_source != output and not is_within(plan_source, output) and not is_within(output, plan_source), "Recovery directories must be distinct")
    for protected in (incident["failed_source"], incident["failed_output"], incident["chain"]["staging"]):
        require(not is_within(plan_source, protected) and not is_within(output, protected), "Recovery directories must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "incident": incident, "plan_source": plan_source, "output": output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "aws-dev-create-plan-recovery-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_failed_plan_request_sha256": FAILED_REQUEST_SHA256,
        "failed_binary_plan_sha256": FAILED_ARTIFACTS["aws-dev-create.tfplan"],
        "failed_provider_lockfile_sha256": FAILED_LOCKFILE_SHA256,
        "failed_plan_is_apply_eligible": False,
        "management_cidr_privately_validated": True,
        "management_cidr_emitted": False,
        "remaining_recovery_approval_seconds": context["remaining"],
        "recovery_plan_execution_authorized": False,
        "terraform_apply_authorized": False,
        "state_push_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-aws-dev-create-plan-recovery-approval",
    }


def safe_environment(terraform_data: Path) -> dict[str, str]:
    return BASE.safe_environment(terraform_data)


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


def copy_recovery_source(context: dict[str, Any]) -> Path:
    destination: Path = context["plan_source"]
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    chain = context["incident"]["chain"]
    for entry in chain["entries"]:
        relative = Path(entry["path"]).relative_to("infra/terraform/aws")
        source = chain["staging"] / relative
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        write_private(target, source.read_bytes(), 0o700 if entry["gitMode"] == "100755" else 0o600)
        require(file_sha256(target) == entry["sha256"], f"Recovery source digest changed: {relative}")
    lockfile = destination / "environments/dev/.terraform.lock.hcl"
    write_private(lockfile, context["incident"]["failed_lockfile"].read_bytes())
    require(file_sha256(lockfile) == FAILED_LOCKFILE_SHA256, "Copied provider lockfile digest changed")
    return lockfile


def validate_incident_history(counts: dict[str, int]) -> None:
    require(counts["stateVersions"] == 0 and counts["stateDeleteMarkers"] == 0, "Remote dev state history is no longer empty")
    require(counts["lockVersions"] == 1 and counts["lockDeleteMarkers"] == 1, "Failed attempt lock history changed")
    require(counts["lockLatestVersions"] == 0 and counts["lockLatestDeleteMarkers"] == 1, "Failed attempt lock was not cleanly released")


def validate_recovery_history(before: dict[str, int], after: dict[str, int]) -> None:
    require(after["stateVersions"] == 0 and after["stateDeleteMarkers"] == 0, "Recovery plan wrote remote state")
    require(after["lockVersions"] - before["lockVersions"] == 1, "Recovery plan lock object-version delta changed")
    require(after["lockDeleteMarkers"] - before["lockDeleteMarkers"] == 1, "Recovery plan lock delete-marker delta changed")
    require(after["lockLatestVersions"] == 0 and after["lockLatestDeleteMarkers"] == 1, "Recovery plan lock was not cleanly released")


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN", "CONFIRM_AWS_DEV_APPLY", "CONFIRM_AWS_DEV_DESTROY",
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
        "CONFIRM_STATE_MIGRATION", "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN", "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Other operation confirmations must be unset")
    request = context["request"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    lockfile = copy_recovery_source(context)
    chain = context["incident"]["chain"]
    backend_copy = output / "dev.s3.tfbackend"
    tfvars_copy = output / "terraform.tfvars.private"
    write_private(backend_copy, chain["paths"]["backend"].read_bytes())
    write_private(tfvars_copy, chain["paths"]["tfvars"].read_bytes())
    terraform_data = output / "terraform-data"
    terraform_data.mkdir(mode=0o700)
    terraform_data.chmod(0o700)
    environment = safe_environment(terraform_data)
    dev_root = context["plan_source"] / "environments/dev"

    identity = parse_json_bytes(run_logged(output, "aws-identity", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    BASE.run_expected_missing_eks(output, "eks-cluster-before-recovery-plan", environment, repository_root, runner)
    before_value = parse_json_bytes(run_logged(output, "s3-object-history-before-recovery-plan", ["aws", "s3api", "list-object-versions", "--bucket", chain["backend"]["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before recovery plan")
    before_counts = BASE.history_counts(before_value)
    validate_incident_history(before_counts)

    version = parse_json_bytes(run_logged(output, "terraform-version", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    init = ["terraform", "init", "-input=false", "-reconfigure", "-lockfile=readonly", f"-backend-config={backend_copy}"]
    run_logged(output, "terraform-init-reconfigure-readonly-lockfile", init, environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(file_sha256(lockfile) == FAILED_LOCKFILE_SHA256, "Provider lockfile changed during readonly init")

    binary_plan = output / "aws-dev-create-recovery.tfplan"
    cidr_argument = "-var=eks_public_access_cidrs=" + json.dumps([request["privateManagementCidr"]], separators=(",", ":"))
    plan = ["terraform", "plan", "-input=false", "-lock=true", "-lock-timeout=0s", f"-var-file={tfvars_copy}", cidr_argument, f"-out={binary_plan}"]
    run_logged(output, "terraform-plan-create-recovery", plan, environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(binary_plan.is_file() and not binary_plan.is_symlink(), "Terraform did not create a regular recovery saved plan")
    binary_plan.chmod(0o600)
    show_json = run_logged(output, "terraform-show-create-recovery-json", ["terraform", "show", "-json", str(binary_plan)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    plan_json_path = output / "aws-dev-create-recovery-plan.json"
    write_private(plan_json_path, show_json.stdout)
    document = parse_json_bytes(show_json.stdout, "Terraform recovery saved plan")
    inventory = BASE.plan_gate(document)
    inventory["schemaVersion"] = "v0.12.4.1.5.0.5.0.1-private-create-plan-recovery-address-inventory-v1"
    inventory_path = output / "create-plan-recovery-address-inventory.json"
    write_private_json(inventory_path, inventory)
    show_text = run_logged(output, "terraform-show-create-recovery-text", ["terraform", "show", "-no-color", str(binary_plan)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(show_text.stdout, "Terraform recovery human-readable plan is empty")
    plan_text_path = output / "aws-dev-create-recovery-plan.txt"
    write_private(plan_text_path, show_text.stdout)

    BASE.run_expected_missing_eks(output, "eks-cluster-after-recovery-plan", environment, repository_root, runner)
    after_value = parse_json_bytes(run_logged(output, "s3-object-history-after-recovery-plan", ["aws", "s3api", "list-object-versions", "--bucket", chain["backend"]["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after recovery plan")
    after_counts = BASE.history_counts(after_value)
    validate_recovery_history(before_counts, after_counts)
    require(file_sha256(chain["paths"]["backend"]) == context["incident"]["failed_request"]["privateBackendConfigSha256"], "Backend config changed during recovery planning")
    require(file_sha256(chain["paths"]["tfvars"]) == context["incident"]["failed_request"]["privateTerraformTfvarsSha256"], "Terraform tfvars changed during recovery planning")

    record = {
        "schemaVersion": "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-record-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "incidentControlPlaneCommit": INCIDENT_COMMIT,
        "createdAtUtc": utc_text(current), "planReviewExpiresAtUtc": request["approval"]["planReviewExpiresAtUtc"],
        "privateRecoveryRequestSha256": file_sha256(context["request_path"]),
        "privateFailedPlanRequestSha256": FAILED_REQUEST_SHA256,
        "failedBinaryPlanSha256": FAILED_ARTIFACTS["aws-dev-create.tfplan"],
        "failedPlanApplyEligible": False, "managementCidrBoundByPrivateRequest": True,
        "providerLockfileSha256": file_sha256(lockfile), "binaryPlanSha256": file_sha256(binary_plan),
        "planJsonSha256": file_sha256(plan_json_path), "planTextSha256": file_sha256(plan_text_path),
        "addressInventorySha256": file_sha256(inventory_path), "managedCreateCount": inventory["managedCreateCount"],
        "dataChangeCount": inventory["dataChangeCount"], "resourceDriftCount": 0, "importCount": 0,
        "stateObjectVersionCount": 0, "stateDeleteMarkerCount": 0,
        "priorFailedLockObjectVersionCount": before_counts["lockVersions"],
        "priorFailedLockDeleteMarkerCount": before_counts["lockDeleteMarkers"],
        "recoveryLockObjectVersionDelta": after_counts["lockVersions"] - before_counts["lockVersions"],
        "recoveryLockDeleteMarkerDelta": after_counts["lockDeleteMarkers"] - before_counts["lockDeleteMarkers"],
        "terraformApplyExecuted": False, "environmentCreated": False,
    }
    record_path = output / "create-plan-recovery-record.json"
    write_private_json(record_path, record)
    return {
        "schemaVersion": "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-result-v1",
        "status": "aws-dev-create-plan-recovered-awaiting-separate-apply-review",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_COMMIT, "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_failed_plan_request_sha256": FAILED_REQUEST_SHA256,
        "failed_binary_plan_sha256": FAILED_ARTIFACTS["aws-dev-create.tfplan"], "failed_plan_is_apply_eligible": False,
        "provider_lockfile_sha256": record["providerLockfileSha256"], "binary_plan_sha256": record["binaryPlanSha256"],
        "terraform_plan_json_sha256": record["planJsonSha256"], "terraform_plan_text_sha256": record["planTextSha256"],
        "address_inventory_sha256": record["addressInventorySha256"], "plan_record_sha256": file_sha256(record_path),
        "managed_create_count": inventory["managedCreateCount"], "data_change_count": inventory["dataChangeCount"],
        "resource_drift_count": 0, "import_count": 0, "remote_state_object_version_count": 0,
        "remote_state_delete_marker_count": 0, "prior_failed_lock_object_version_count": 1,
        "prior_failed_lock_delete_marker_count": 1, "recovery_lock_object_version_delta": 1,
        "recovery_lock_delete_marker_delta": 1, "lock_object_absent": True,
        "management_cidr_privately_bound": True, "management_cidr_emitted": False,
        "plan_review_expires_at_utc": request["approval"]["planReviewExpiresAtUtc"],
        "terraform_init_executed": True, "terraform_plan_executed": True, "terraform_apply_executed": False,
        "state_migration_executed": False, "state_push_executed": False, "environment_created": False,
        "automatic_retry_performed": False, "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "human-review-private-recovery-create-plan-before-v0.12.4.1.5.0.6-exact-apply",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-recovery-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        context = verify_inputs(args.private_recovery_request)
        result = redacted_verification(context) if args.phase == "verify" else execute(args.private_recovery_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, RecoveryError) as error:
        parser.exit(1, f"AWS-dev create-plan recovery stopped: {error}; preserve private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

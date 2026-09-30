#!/usr/bin/env python3
"""Apply the exact human-reviewed aws-dev recovery saved plan once."""

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
RECOVERY_EXECUTOR = ROOT / "scripts/execute-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"
CONFIRMATION = "apply-reviewed-aws-dev-recovery-saved-create-plan"
RECOVERY_CONTROL_PLANE_COMMIT = "a20fba2eac0b4642b239193730ed72402065c1b5"
RECOVERY_REQUEST_SHA256 = "d77abf17613dd5b9d311292a3404a1799efe4f0468d920f95f3ead586193895d"
PROVIDER_LOCKFILE_SHA256 = "a824bda667aac25533101eb99e1b5c6ec5415cc5f2e773793f7b1699b453fd6f"
PLAN_REVIEW_EXPIRES_AT = "2026-09-30T20:31:00Z"
REVIEWED_ARTIFACTS = {
    "aws-dev-create-recovery.tfplan": "4e69241462430992203d79674a2eefa70c309eb756b33a6874a8b8b38ee71a1b",
    "aws-dev-create-recovery-plan.json": "5f2de857159c042e8588b743ca66364015496dc16f78e215bee5c3da525ed3de",
    "aws-dev-create-recovery-plan.txt": "cc96ec46c0b8184bd47eff6dae5f968f83d2502bef1df8e2b782e8643c0ff02e",
    "create-plan-recovery-address-inventory.json": "8ee52b515704cf5e6e4a3824c06da83c7b639b52f6320c852f20d53ca99ead81",
    "create-plan-recovery-record.json": "b0ac35c31977cc87f88ee3c568b6e76878bf21765ffe6be507ad9ae1401c57df",
}
MANAGED_CREATE_COUNT = 90
DATA_CHANGE_COUNT = 6
EXPECTED_STATE_ADDRESS_COUNT = MANAGED_CREATE_COUNT + DATA_CHANGE_COUNT
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
STATE_KEY = "environments/dev/terraform.tfstate"
LOCK_KEY = STATE_KEY + ".tflock"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 10800
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 180
TERRAFORM_APPLY_TIMEOUT_SECONDS = 9000
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SECRET_READ_FIELD = "".join(("secret", "ValueRead"))


class ApplyError(ValueError):
    pass


class CommandFailure(ApplyError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ApplyError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY = load_module(RECOVERY_EXECUTOR, "aws_dev_create_plan_recovery_apply_dependency")
BASE = RECOVERY.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ApplyError(message)


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
        raise ApplyError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ApplyError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ApplyError(f"{label} must be a valid UTC timestamp") from error
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


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "recoveryControlPlaneCommit",
        "expectedMainCommit", "expectedAwsAccountId", "expectedAwsRegion", "expectedClusterName",
        "expectedTerraformVersion", "privateRecoveryRequestPath", "privateRecoveryRequestSha256",
        "privateRecoveryPlanSourceDirectory", "privateRecoveryPlanOutputDirectory",
        "reviewedArtifactSha256s", "reviewedProviderLockfileSha256",
        "privateApplyOutputDirectory", "humanReview", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Apply request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(value["recoveryControlPlaneCommit"] == RECOVERY_CONTROL_PLANE_COMMIT, "Recovery control-plane commit changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]) is not None, "Expected AWS account is invalid")
    require(value["expectedAwsRegion"] == AWS_REGION and value["expectedClusterName"] == CLUSTER_NAME, "AWS target changed")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]) is not None, "Terraform version is invalid")
    require(value["privateRecoveryRequestSha256"] == RECOVERY_REQUEST_SHA256, "Recovery request digest changed")
    require(value["reviewedArtifactSha256s"] == REVIEWED_ARTIFACTS, "Reviewed artifact digest inventory changed")
    require(value["reviewedProviderLockfileSha256"] == PROVIDER_LOCKFILE_SHA256, "Provider lockfile digest changed")
    for key in ("privateRecoveryRequestPath", "privateRecoveryPlanSourceDirectory", "privateRecoveryPlanOutputDirectory", "privateApplyOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["humanReview"] == {
        "recoveryPlanReviewed": True, "managedCreateCount": MANAGED_CREATE_COUNT,
        "dataReadOrNoopCount": DATA_CHANGE_COUNT, "resourceDriftCount": 0, "importCount": 0,
        "unexpectedResourceMutationFound": False, "unexpectedIamAttachmentFound": False,
        "unexplainedStderrFound": False, "reviewedMaximumBudgetUsd": 50,
    }, "Human review boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc", "planReviewExpiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    review_expiry = utc_timestamp(approval["planReviewExpiresAtUtc"], "Plan review expiry")
    require(approval["planReviewExpiresAtUtc"] == PLAN_REVIEW_EXPIRES_AT, "Reviewed plan expiry changed")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Apply approval window must be positive and at most three hours")
    require(expiry <= review_expiry, "Apply approval extends beyond the reviewed plan")
    expected_boundary = {
        "awsReadOnlyValidation": True, "terraformShowExistingPlan": True,
        "exactSavedPlanApply": True, "terraformStateRead": True,
        "terraformInit": False, "terraformPlan": False, "unsavedApply": False,
        "stateMigration": False, "statePush": False, "destroy": False,
        "iamPolicyAttachment": False, "kubernetesCommand": False,
        SECRET_READ_FIELD: False, "directS3Mutation": False, "forceUnlock": False,
        "automaticRetry": False, "automaticRollback": False,
    }
    require(value["executionBoundary"] == expected_boundary, "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ApplyError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def validate_plan_evidence(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    recovery_request_path = require_private_file(Path(request["privateRecoveryRequestPath"]), "Recovery request")
    require(not is_within(recovery_request_path, repository_root), "Recovery request must remain outside the repository")
    require(file_sha256(recovery_request_path) == RECOVERY_REQUEST_SHA256, "Recovery request digest changed")
    recovery_request = RECOVERY.validate_request(load_json(recovery_request_path, "Recovery request"))
    require(recovery_request["expectedMainCommit"] == RECOVERY_CONTROL_PLANE_COMMIT, "Recovery request commit changed")
    require(recovery_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Recovery AWS account changed")
    require(recovery_request["expectedAwsRegion"] == request["expectedAwsRegion"], "Recovery AWS region changed")
    require(recovery_request["expectedClusterName"] == request["expectedClusterName"], "Recovery cluster changed")
    require(recovery_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Recovery Terraform version changed")
    incident = RECOVERY.validate_failed_attempt(recovery_request, repository_root)

    source = require_private_directory(Path(request["privateRecoveryPlanSourceDirectory"]), "Recovery plan source")
    output = require_private_directory(Path(request["privateRecoveryPlanOutputDirectory"]), "Recovery plan output")
    require(str(source) == recovery_request["privateRecoveryPlanSourceDirectory"], "Recovery plan source path changed")
    require(str(output) == recovery_request["privateRecoveryPlanOutputDirectory"], "Recovery plan output path changed")
    require(not is_within(source, repository_root) and not is_within(output, repository_root), "Recovery evidence must remain outside the repository")
    for entry in incident["chain"]["entries"]:
        relative = Path(entry["path"]).relative_to("infra/terraform/aws")
        source_file = source / relative
        require(source_file.is_file() and not source_file.is_symlink(), f"Recovery source missing: {relative}")
        require(file_sha256(source_file) == entry["sha256"], f"Recovery source digest changed: {relative}")
    lockfile = require_private_file(source / "environments/dev/.terraform.lock.hcl", "Recovery provider lockfile")
    require(file_sha256(lockfile) == PROVIDER_LOCKFILE_SHA256, "Recovery provider lockfile changed")
    artifacts: dict[str, Path] = {}
    for name, digest in REVIEWED_ARTIFACTS.items():
        path = require_private_file(output / name, f"Reviewed artifact {name}")
        require(file_sha256(path) == digest, f"Reviewed artifact digest changed: {name}")
        artifacts[name] = path
    plan_document = load_json(artifacts["aws-dev-create-recovery-plan.json"], "Reviewed plan JSON")
    inventory = BASE.plan_gate(plan_document)
    require(inventory["managedCreateCount"] == MANAGED_CREATE_COUNT, "Reviewed managed-create count changed")
    require(inventory["dataChangeCount"] == DATA_CHANGE_COUNT, "Reviewed data change count changed")
    reviewed_inventory = load_json(artifacts["create-plan-recovery-address-inventory.json"], "Reviewed address inventory")
    for key in ("managedCreateAddresses", "dataReadOrNoopAddresses", "managedCreateCount", "dataChangeCount", "resourceDriftCount", "importCount"):
        require(reviewed_inventory.get(key) == inventory.get(key), f"Reviewed address inventory changed: {key}")
    record = load_json(artifacts["create-plan-recovery-record.json"], "Reviewed plan record")
    expected_record = {
        "controlPlaneCommit": RECOVERY_CONTROL_PLANE_COMMIT,
        "privateRecoveryRequestSha256": RECOVERY_REQUEST_SHA256,
        "providerLockfileSha256": PROVIDER_LOCKFILE_SHA256,
        "binaryPlanSha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery.tfplan"],
        "planJsonSha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery-plan.json"],
        "planTextSha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery-plan.txt"],
        "addressInventorySha256": REVIEWED_ARTIFACTS["create-plan-recovery-address-inventory.json"],
        "managedCreateCount": MANAGED_CREATE_COUNT, "dataChangeCount": DATA_CHANGE_COUNT,
        "resourceDriftCount": 0, "importCount": 0, "stateObjectVersionCount": 0,
        "stateDeleteMarkerCount": 0, "terraformApplyExecuted": False, "environmentCreated": False,
        "planReviewExpiresAtUtc": PLAN_REVIEW_EXPIRES_AT,
    }
    for key, expected in expected_record.items():
        require(record.get(key) == expected, f"Reviewed plan record changed: {key}")
    terraform_data = require_private_directory(output / "terraform-data", "Recovery Terraform data")
    return {
        "recovery_request_path": recovery_request_path, "recovery_request": recovery_request,
        "incident": incident, "source": source, "output": output, "lockfile": lockfile,
        "artifacts": artifacts, "plan_document": plan_document, "inventory": reviewed_inventory,
        "record": record, "terraform_data": terraform_data,
    }


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private apply request")
    require(not is_within(private_request, repository_root), "Apply request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private apply request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    review_expiry = utc_timestamp(PLAN_REVIEW_EXPIRES_AT, "Plan review expiry")
    require(start <= current < expiry, "Apply approval is not currently active")
    require(current < review_expiry, "Reviewed plan has expired")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Apply approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Apply must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Apply requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")
    evidence = validate_plan_evidence(request, repository_root)
    apply_output = require_new_private_directory(Path(request["privateApplyOutputDirectory"]), "Private apply output")
    require(not is_within(apply_output, repository_root), "Apply output must remain outside the repository")
    for protected in (evidence["source"], evidence["output"], evidence["incident"]["failed_source"], evidence["incident"]["failed_output"]):
        require(not is_within(apply_output, protected) and not is_within(protected, apply_output), "Apply output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "evidence": evidence, "output": apply_output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "aws-dev-recovery-saved-plan-apply-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "recovery_control_plane_commit": RECOVERY_CONTROL_PLANE_COMMIT,
        "private_apply_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "binary_plan_sha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery.tfplan"],
        "plan_json_sha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery-plan.json"],
        "plan_record_sha256": REVIEWED_ARTIFACTS["create-plan-recovery-record.json"],
        "managed_create_count": MANAGED_CREATE_COUNT, "data_change_count": DATA_CHANGE_COUNT,
        "resource_drift_count": 0, "import_count": 0,
        "human_review_verified": True, "remaining_apply_approval_seconds": context["remaining"],
        "apply_execution_authorized": False, "terraform_init_authorized": False,
        "terraform_plan_authorized": False, "unsaved_apply_authorized": False,
        "state_push_authorized": False, "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-recovery-saved-plan-apply-approval",
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


def history_counts(value: dict[str, Any]) -> dict[str, int]:
    return BASE.history_counts(value)


def validate_before_apply_history(counts: dict[str, int]) -> None:
    require(counts["stateVersions"] == 0 and counts["stateDeleteMarkers"] == 0, "Remote dev state is no longer empty")
    require(counts["lockVersions"] == 2 and counts["lockDeleteMarkers"] == 2, "Reviewed plan lock history changed")
    require(counts["lockLatestVersions"] == 0 and counts["lockLatestDeleteMarkers"] == 1, "Reviewed plan lock is not cleanly released")


def validate_after_apply_history(before: dict[str, int], after: dict[str, int], value: dict[str, Any]) -> int:
    delta = after["stateVersions"] - before["stateVersions"]
    require(1 <= delta <= EXPECTED_STATE_ADDRESS_COUNT + 1, "Apply state object-version delta is outside the reviewed bound")
    require(after["stateDeleteMarkers"] == before["stateDeleteMarkers"] == 0, "Apply created a state delete marker")
    require(after["lockVersions"] - before["lockVersions"] == 1, "Apply lock object-version delta changed")
    require(after["lockDeleteMarkers"] - before["lockDeleteMarkers"] == 1, "Apply lock delete-marker delta changed")
    require(after["lockLatestVersions"] == 0 and after["lockLatestDeleteMarkers"] == 1, "Apply lock was not cleanly released")
    versions = value.get("Versions", [])
    markers = value.get("DeleteMarkers", [])
    require(sum(item.get("Key") == STATE_KEY and item.get("IsLatest") is True for item in versions) == 1, "Canonical state latest-version marker changed")
    require(not any(item.get("Key") == STATE_KEY and item.get("IsLatest") is True for item in markers), "Canonical state latest object is a delete marker")
    return delta


def state_list_addresses(value: bytes) -> set[str]:
    addresses = {line.strip() for line in value.decode().splitlines() if line.strip()}
    require(len(addresses) == EXPECTED_STATE_ADDRESS_COUNT, "Terraform state address count changed")
    return addresses


def show_state_addresses(document: dict[str, Any]) -> set[str]:
    values = document.get("values")
    require(isinstance(values, dict), "Terraform state show values are missing")
    root = values.get("root_module")
    require(isinstance(root, dict), "Terraform state show root module is missing")
    addresses: set[str] = set()

    def visit(module: dict[str, Any]) -> None:
        resources = module.get("resources", [])
        require(isinstance(resources, list), "Terraform state show resource shape changed")
        for resource in resources:
            require(isinstance(resource, dict) and isinstance(resource.get("address"), str), "Terraform state show address changed")
            addresses.add(resource["address"])
        children = module.get("child_modules", [])
        require(isinstance(children, list), "Terraform state show child-module shape changed")
        for child in children:
            require(isinstance(child, dict), "Terraform state show child module changed")
            visit(child)

    visit(root)
    return addresses


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN", "CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY",
        "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY",
        "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION", "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN",
        "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Other operation confirmations must be unset")
    request = context["request"]
    evidence = context["evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(evidence["terraform_data"])
    dev_root = evidence["source"] / "environments/dev"
    binary_plan = evidence["artifacts"]["aws-dev-create-recovery.tfplan"]
    backend = evidence["incident"]["chain"]["backend"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-before-apply", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    RECOVERY.BASE.run_expected_missing_eks(output, "eks-cluster-before-apply", environment, repository_root, runner)
    before_value = parse_json_bytes(run_logged(output, "s3-object-history-before-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before apply")
    before_counts = history_counts(before_value)
    validate_before_apply_history(before_counts)
    version = parse_json_bytes(run_logged(output, "terraform-version-before-apply", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    shown_json = run_logged(output, "terraform-show-reviewed-plan-json", ["terraform", "show", "-json", str(binary_plan)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(hashlib.sha256(shown_json.stdout).hexdigest() == REVIEWED_ARTIFACTS["aws-dev-create-recovery-plan.json"], "Reviewed plan JSON changed before apply")
    gate = BASE.plan_gate(parse_json_bytes(shown_json.stdout, "Reviewed plan before apply"))
    require(gate["managedCreateAddresses"] == evidence["inventory"]["managedCreateAddresses"], "Reviewed managed inventory changed before apply")
    require(gate["dataReadOrNoopAddresses"] == evidence["inventory"]["dataReadOrNoopAddresses"], "Reviewed data inventory changed before apply")
    shown_text = run_logged(output, "terraform-show-reviewed-plan-text", ["terraform", "show", "-no-color", str(binary_plan)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(hashlib.sha256(shown_text.stdout).hexdigest() == REVIEWED_ARTIFACTS["aws-dev-create-recovery-plan.txt"], "Reviewed plan text changed before apply")
    require(file_sha256(binary_plan) == REVIEWED_ARTIFACTS["aws-dev-create-recovery.tfplan"], "Reviewed binary plan changed before apply")
    require(file_sha256(evidence["lockfile"]) == PROVIDER_LOCKFILE_SHA256, "Provider lockfile changed before apply")

    apply_result = run_logged(output, "terraform-apply-reviewed-recovery-plan", ["terraform", "apply", "-input=false", "-auto-approve", str(binary_plan)], environment, TERRAFORM_APPLY_TIMEOUT_SECONDS, dev_root, runner)
    require(re.search(rb"Apply complete! Resources: 90 added, 0 changed, 0 destroyed\.", apply_result.stdout) is not None, "Terraform apply completion summary changed")

    state_pull = run_logged(output, "terraform-state-pull-after-apply", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-after-apply.json"
    write_private(state_path, state_pull.stdout)
    state_document = parse_json_bytes(state_pull.stdout, "Terraform state after apply")
    require(isinstance(state_document.get("lineage"), str) and state_document["lineage"], "Terraform state lineage is missing")
    require(isinstance(state_document.get("serial"), int) and state_document["serial"] >= 1, "Terraform state serial is invalid")
    state_list = run_logged(output, "terraform-state-list-after-apply", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    listed = state_list_addresses(state_list.stdout)
    expected_addresses = set(evidence["inventory"]["managedCreateAddresses"]) | set(evidence["inventory"]["dataReadOrNoopAddresses"])
    require(listed == expected_addresses, "Terraform state address inventory differs from reviewed plan")
    state_show = run_logged(output, "terraform-show-state-after-apply", ["terraform", "show", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_show_path = output / "aws-dev-state-show-after-apply.json"
    write_private(state_show_path, state_show.stdout)
    require(show_state_addresses(parse_json_bytes(state_show.stdout, "Terraform state show after apply")) == expected_addresses, "Terraform state show address inventory differs from reviewed plan")
    cluster = parse_json_bytes(run_logged(output, "eks-cluster-after-apply", ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "EKS cluster after apply")
    require(isinstance(cluster.get("cluster"), dict) and cluster["cluster"].get("name") == CLUSTER_NAME and cluster["cluster"].get("status") == "ACTIVE", "EKS cluster is not ACTIVE after apply")
    after_value = parse_json_bytes(run_logged(output, "s3-object-history-after-apply", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after apply")
    after_counts = history_counts(after_value)
    state_version_delta = validate_after_apply_history(before_counts, after_counts, after_value)
    require(file_sha256(binary_plan) == REVIEWED_ARTIFACTS["aws-dev-create-recovery.tfplan"], "Reviewed binary plan changed during apply")
    require(file_sha256(evidence["lockfile"]) == PROVIDER_LOCKFILE_SHA256, "Provider lockfile changed during apply")

    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "recoveryControlPlaneCommit": RECOVERY_CONTROL_PLANE_COMMIT,
        "completedAtUtc": utc_text(current), "privateApplyRequestSha256": file_sha256(context["request_path"]),
        "privateRecoveryRequestSha256": RECOVERY_REQUEST_SHA256,
        "binaryPlanSha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery.tfplan"],
        "planJsonSha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery-plan.json"],
        "planRecordSha256": REVIEWED_ARTIFACTS["create-plan-recovery-record.json"],
        "managedStateAddressCount": MANAGED_CREATE_COUNT, "dataStateAddressCount": DATA_CHANGE_COUNT,
        "stateSha256": file_sha256(state_path), "stateShowSha256": file_sha256(state_show_path),
        "stateLineageSha256": hashlib.sha256(state_document["lineage"].encode()).hexdigest(),
        "stateSerial": state_document["serial"], "stateObjectVersionDelta": state_version_delta,
        "stateDeleteMarkerDelta": 0, "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1,
        "lockObjectAbsent": True, "eksClusterActive": True, "terraformApplyExecuted": True,
        "terraformInitExecuted": False, "terraformPlanExecuted": False,
        "statePushExecuted": False, "automaticRetryPerformed": False, "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-recovery-saved-plan-apply-evidence.json"
    write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-result-v1",
        "status": "aws-dev-recovery-saved-plan-applied-and-read-only-validated",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "recovery_control_plane_commit": RECOVERY_CONTROL_PLANE_COMMIT,
        "private_apply_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "binary_plan_sha256": REVIEWED_ARTIFACTS["aws-dev-create-recovery.tfplan"],
        "plan_record_sha256": REVIEWED_ARTIFACTS["create-plan-recovery-record.json"],
        "managed_state_address_count": MANAGED_CREATE_COUNT, "data_state_address_count": DATA_CHANGE_COUNT,
        "remote_state_sha256": evidence_record["stateSha256"], "state_serial": state_document["serial"],
        "state_object_version_delta": state_version_delta, "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1, "lock_delete_marker_delta": 1, "lock_object_absent": True,
        "eks_cluster_active": True, "environment_created": True,
        "terraform_apply_executed": True, "terraform_init_executed": False,
        "terraform_plan_executed": False, "state_push_executed": False,
        "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "apply_evidence_sha256": file_sha256(evidence_path),
        "private_resource_identity_emitted": False, "private_object_version_id_emitted": False,
        "next_action": "record-private-apply-evidence-before-v0.12.4.1.5.0.7-post-create-qualification",
    }
    result_path = output / "aws-dev-recovery-saved-plan-apply-result.json"
    write_private_json(result_path, result)
    result["apply_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-apply-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        context = verify_inputs(args.private_apply_request)
        result = redacted_verification(context) if args.phase == "verify" else execute(args.private_apply_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, ApplyError) as error:
        parser.exit(1, f"AWS-dev recovery saved-plan apply stopped: {error}; preserve private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

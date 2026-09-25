#!/usr/bin/env python3
"""Verify or execute the guarded bootstrap-state migration preflight."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.1.2.0.1-state-bootstrap-recovery.py"
CONFIRMATION = "prepare-reviewed-bootstrap-state-migration"
AWS_REGION = "us-east-1"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
EXPECTED_PLAN_REQUEST_SHA256 = "9f041fa9b98c15b7309df8b87af79bb50d3871eb0501b9977bbdb772c41a326b"
EXPECTED_APPLY_REQUEST_SHA256 = "91406ddbac3f75415c383da3b369070ec93c0c8874a11023ee1a7b50e307de07"
EXPECTED_RECOVERY_REQUEST_SHA256 = "cd31e26adc15932215985f27db865717a674382d22b34d8f0d2327e977a6c7a7"
EXPECTED_STATE_SHA256 = "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995"
EXPECTED_RECOVERY_RESULT_SHA256 = "c65f405bdb67779af4a9b074e5760ba62b2aff78f075ff10985108ba70ba4365"
EXPECTED_LIVE_VALIDATION_SHA256 = "6f929213b687c44652c5f265f577767dcc422ab363f4cb598ed1c68395c1c091"
EXPECTED_BACKEND_BLOCK = '''terraform {
  backend "s3" {}

  # This root must create the S3/KMS backend before that backend can be used.
  # v0.12.2.1 only declares this partial backend and prepares a separately
  # reviewed command plan. The state remains local until v0.12.2.2 executes
  # the exact approved terraform init -migrate-state boundary.
}
'''


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RECOVERY_EXECUTOR = load_module(RECOVERY_EXECUTOR_PATH, "bootstrap_recovery_for_migration_preflight")
APPLY_EXECUTOR = RECOVERY_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = RECOVERY_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = RECOVERY_EXECUTOR.PLAN_GATE

GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"{label} is invalid") from error


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        result = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError(f"{label} must be a valid UTC timestamp") from error
    require(result.tzinfo == timezone.utc, f"{label} must be UTC")
    return result


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
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a directory")
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
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "privatePlanRequestPath", "privatePlanRequestSha256",
        "privateApplyRequestPath", "privateApplyRequestSha256", "privateRecoveryRequestPath",
        "privateRecoveryRequestSha256", "privatePlanBundleDirectory", "privateApplyOutputDirectory",
        "privateRecoveryOutputDirectory", "appliedStateSha256", "recoveryResultSha256",
        "liveValidationSha256", "privateBackendConfigPath", "privateBackendConfigSha256",
        "privatePreflightOutputDirectory", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Preflight request fields changed")
    require(value["schemaVersion"] == "v0.12.2.1-bootstrap-migration-preflight-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Expected main is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    exact_hashes = {
        "privatePlanRequestSha256": EXPECTED_PLAN_REQUEST_SHA256,
        "privateApplyRequestSha256": EXPECTED_APPLY_REQUEST_SHA256,
        "privateRecoveryRequestSha256": EXPECTED_RECOVERY_REQUEST_SHA256,
        "appliedStateSha256": EXPECTED_STATE_SHA256,
        "recoveryResultSha256": EXPECTED_RECOVERY_RESULT_SHA256,
        "liveValidationSha256": EXPECTED_LIVE_VALIDATION_SHA256,
    }
    for key, expected in exact_hashes.items():
        require(value[key] == expected, f"Reviewed digest changed: {key}")
    require(isinstance(value["privateBackendConfigSha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["privateBackendConfigSha256"]) is not None, "Backend-config digest is invalid")
    for key in (
        "privatePlanRequestPath", "privateApplyRequestPath", "privateRecoveryRequestPath",
        "privatePlanBundleDirectory", "privateApplyOutputDirectory", "privateRecoveryOutputDirectory",
        "privateBackendConfigPath", "privatePreflightOutputDirectory",
    ):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "terraformInit": False, "terraformPlan": False, "terraformApply": False,
        "stateMigration": False, "statePush": False, "destroy": False,
        "awsReadOnlyValidation": True, "localPrivateBackup": True,
    }, "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def parse_backend_config(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z_]+)\s*=\s*(.+)", line)
        require(match is not None, "Backend config contains unsupported syntax")
        key, encoded = match.groups()
        require(key not in values, f"Duplicate backend config key: {key}")
        if encoded in {"true", "false"}:
            values[key] = encoded == "true"
        else:
            require(re.fullmatch(r'"[^"\\]*"', encoded) is not None, f"Backend config value is invalid: {key}")
            values[key] = encoded[1:-1]
    require(set(values) == {"bucket", "key", "region", "encrypt", "kms_key_id", "use_lockfile"}, "Backend config fields changed")
    return values


def resource_identity_digest(state: dict[str, Any]) -> str:
    resources = state.get("resources")
    require(isinstance(resources, list), "State resources are invalid")
    return hashlib.sha256(canonical_json(resources)).hexdigest()


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request_path = require_private_file(request_path, "Private preflight request")
    require(not is_within(private_request_path, repository_root), "Preflight request must remain outside the repository")
    request = validate_request(load_json(private_request_path, "Private preflight request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Preflight approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Preflight approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Preflight must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Preflight requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    plan_path = require_private_file(Path(request["privatePlanRequestPath"]), "Private plan request")
    apply_path = require_private_file(Path(request["privateApplyRequestPath"]), "Private apply request")
    recovery_path = require_private_file(Path(request["privateRecoveryRequestPath"]), "Private recovery request")
    for path, key in ((plan_path, "privatePlanRequestSha256"), (apply_path, "privateApplyRequestSha256"), (recovery_path, "privateRecoveryRequestSha256")):
        require(not is_within(path, repository_root), "Prior private request must remain outside repository")
        require(file_sha256(path) == request[key], f"Prior private request changed: {key}")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_path, "Private plan request"))
    apply_request = APPLY_EXECUTOR.validate_apply_request(load_json(apply_path, "Private apply request"))
    recovery_request = RECOVERY_EXECUTOR.validate_request(load_json(recovery_path, "Private recovery request"))
    require(apply_request["privatePlanRequestSha256"] == request["privatePlanRequestSha256"], "Apply/plan chain changed")
    require(recovery_request["privateApplyRequestSha256"] == request["privateApplyRequestSha256"], "Recovery/apply chain changed")
    require(plan_request["expectedAwsAccountId"] == request["expectedAwsAccountId"] == apply_request["expectedAwsAccountId"] == recovery_request["expectedAwsAccountId"], "AWS account chain changed")

    bundle = require_private_directory(Path(request["privatePlanBundleDirectory"]), "Private plan bundle")
    apply_output = require_private_directory(Path(request["privateApplyOutputDirectory"]), "Private apply output")
    recovery_output = require_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(bundle == Path(plan_request["privateOutputDirectory"]).resolve(strict=True) == Path(apply_request["privatePlanBundleDirectory"]).resolve(strict=True) == Path(recovery_request["privatePlanBundleDirectory"]).resolve(strict=True), "Private plan bundle chain changed")
    require(apply_output == Path(apply_request["privateApplyOutputDirectory"]).resolve(strict=True) == Path(recovery_request["privateFailedApplyOutputDirectory"]).resolve(strict=True), "Private apply output chain changed")
    require(recovery_output == Path(recovery_request["privateRecoveryOutputDirectory"]).resolve(strict=True), "Private recovery output chain changed")

    canonical_state = require_private_file(bundle / "source/terraform.tfstate", "Canonical applied state")
    preserved_state = require_private_file(apply_output / "state-bootstrap.tfstate.applied", "Preserved applied state")
    require(file_sha256(canonical_state) == request["appliedStateSha256"] == file_sha256(preserved_state), "Applied-state digest changed")
    require(canonical_state.read_bytes() == preserved_state.read_bytes(), "Applied-state copies are not byte-identical")
    state = load_json(canonical_state, "Canonical applied state")
    managed, data = RECOVERY_EXECUTOR.state_addresses(state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES, "Managed state inventory changed")
    require(data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES, "Unreviewed data state address found")
    identities = APPLY_EXECUTOR.validate_outputs(state.get("outputs"), plan_request)

    recovery_result_path = require_private_file(recovery_output / "recovery-result.json", "Recovery result")
    live_validation_path = require_private_file(recovery_output / "live-validation.json", "Live validation")
    require(file_sha256(recovery_result_path) == request["recoveryResultSha256"], "Recovery result changed")
    require(file_sha256(live_validation_path) == request["liveValidationSha256"], "Live validation changed")
    recovery_result = load_json(recovery_result_path, "Recovery result")
    require(recovery_result.get("status") == "state-backend-foundation-post-apply-recovered-and-live-validated", "Recovery did not reach terminal success")
    require(recovery_result.get("applied_state_sha256") == request["appliedStateSha256"], "Recovery state binding changed")
    require(recovery_result.get("state_migration_executed") is False and recovery_result.get("terraform_init_executed") is False, "Prior recovery already migrated state")

    source = bundle / "source"
    old_manifest = load_json(bundle / "source-manifest.json", "Original source manifest")
    require(old_manifest == PLAN_EXECUTOR.source_manifest(source), "Original staged source changed")
    current_root = repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE
    current_manifest = PLAN_EXECUTOR.source_manifest(current_root)
    for name in PLAN_EXECUTOR.TERRAFORM_SOURCE_FILES:
        if name != "backend.tf":
            require(old_manifest[name] == current_manifest[name], f"Unreviewed Terraform source drift: {name}")
    require((current_root / "backend.tf").read_text() == EXPECTED_BACKEND_BLOCK, "Partial S3 backend declaration changed")

    backend_path = require_private_file(Path(request["privateBackendConfigPath"]), "Private backend config")
    require(not is_within(backend_path, repository_root), "Backend config must remain outside repository")
    require(file_sha256(backend_path) == request["privateBackendConfigSha256"], "Backend config changed")
    backend = parse_backend_config(backend_path)
    expected_backend = {
        "bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION,
        "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True,
    }
    require(backend == expected_backend, "Backend config does not match applied-state outputs")
    output = require_new_private_directory(Path(request["privatePreflightOutputDirectory"]), "Private preflight output")
    require(not is_within(output, repository_root), "Preflight output must remain outside repository")
    return {
        "request": request, "request_path": private_request_path, "plan_request": plan_request,
        "bundle": bundle, "apply_output": apply_output, "recovery_output": recovery_output,
        "canonical_state": canonical_state, "preserved_state": preserved_state, "state": state,
        "managed": managed, "data": data, "identities": identities, "backend_path": backend_path,
        "backend": backend, "output": output, "current_manifest": current_manifest,
        "remaining": remaining,
    }


def safe_environment(plan_request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    environment = APPLY_EXECUTOR.safe_environment(plan_request, terraform_data)
    for key in list(environment):
        if key.startswith("TF_CLI_ARGS") or key.startswith("TF_VAR_") or key.startswith("CONFIRM_"):
            del environment[key]
    return environment


def execute(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT") == CONFIRMATION, f"Set CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT={CONFIRMATION}")
    for forbidden in ("CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_MIGRATION"):
        require(not os.environ.get(forbidden), "Plan, apply, destroy and migration confirmations must be unset")

    output = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    terraform_data = output / "terraform-data"
    terraform_data.mkdir(mode=0o700)
    staged = PLAN_EXECUTOR.stage_source(repository_root, output / "migration-source", context["current_manifest"])
    staged_state = staged / "terraform.tfstate"
    backup = output / "bootstrap-state.pre-migration.backup"
    shutil.copyfile(context["canonical_state"], staged_state)
    staged_state.chmod(0o600)
    shutil.copyfile(context["canonical_state"], backup)
    backup.chmod(0o600)
    for path in (staged_state, backup):
        require(file_sha256(path) == context["request"]["appliedStateSha256"], "Private state copy changed")

    environment = safe_environment(context["plan_request"], terraform_data)
    version = APPLY_EXECUTOR.run_logged(output, "terraform-version", ["terraform", "version", "-json"], environment, 30, runner, repository_root)
    terraform_version = PLAN_EXECUTOR.parse_terraform_version(version.stdout)
    identity_result = APPLY_EXECUTOR.run_logged(output, "aws-identity", ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = APPLY_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")
    live = APPLY_EXECUTOR.validate_live_foundation(output, context["identities"], environment, runner, repository_root)
    require(live["s3_object_version_count"] == 0 and live["attached_root_state_policy_count"] == 0, "Live preflight boundary changed")

    inventory = {
        "schemaVersion": "v0.12.2.1-bootstrap-state-inventory-v1",
        "appliedStateSha256": context["request"]["appliedStateSha256"],
        "lineage": context["state"].get("lineage"), "serial": context["state"].get("serial"),
        "managedAddressCount": len(context["managed"]), "dataAddressCount": len(context["data"]),
        "managedAddresses": sorted(context["managed"]), "dataAddresses": sorted(context["data"]),
        "resourceIdentitySha256": resource_identity_digest(context["state"]),
    }
    require(isinstance(inventory["lineage"], str) and inventory["lineage"], "State lineage is missing")
    require(isinstance(inventory["serial"], int) and inventory["serial"] >= 1, "State serial is invalid")
    inventory_path = output / "state-inventory.json"
    APPLY_EXECUTOR.write_private(inventory_path, canonical_json(inventory))
    manifest_path = output / "migration-source-manifest.json"
    APPLY_EXECUTOR.write_private(manifest_path, canonical_json(context["current_manifest"]))
    live_path = output / "live-validation.json"
    APPLY_EXECUTOR.write_private(live_path, canonical_json(live))
    command_plan = {
        "schemaVersion": "v0.12.2.1-bootstrap-migration-command-plan-v1",
        "workingDirectory": str(staged),
        "backendConfigPath": str(context["backend_path"]),
        "command": ["terraform", f"-chdir={staged}", "init", "-input=false", "-migrate-state", "-force-copy", f"-backend-config={context['backend_path']}"],
        "expectedRemoteKey": "bootstrap/terraform.tfstate",
        "expectedManagedAddressCount": 13,
        "requiresSeparateV01222Approval": True,
        "executedByThisPreflight": False,
    }
    command_path = output / "migration-command-plan.json"
    APPLY_EXECUTOR.write_private(command_path, canonical_json(command_plan))
    result = {
        "schemaVersion": "v0.12.2.1-bootstrap-migration-preflight-result-v1",
        "status": "bootstrap-migration-preflight-complete-awaiting-separate-migration-approval",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_preflight_request_sha256": file_sha256(context["request_path"]),
        "applied_state_sha256": context["request"]["appliedStateSha256"],
        "immutable_backup_sha256": file_sha256(backup),
        "state_inventory_sha256": file_sha256(inventory_path),
        "resource_identity_sha256": inventory["resourceIdentitySha256"],
        "migration_source_manifest_sha256": file_sha256(manifest_path),
        "migration_command_plan_sha256": file_sha256(command_path),
        "live_validation_sha256": file_sha256(live_path),
        "managed_state_address_count": len(context["managed"]),
        "remote_state_object_version_count": live["s3_object_version_count"],
        "terraform_version": ".".join(str(item) for item in terraform_version),
        "terraform_init_executed": False, "terraform_plan_executed": False,
        "terraform_apply_executed": False, "state_migration_executed": False,
        "state_push_executed": False, "destroy_executed": False,
        "private_resource_identity_emitted": False,
        "next_action": "human-review-private-preflight-before-v0.12.2.2-migration-request",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "preflight-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["preflight_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "bootstrap-migration-preflight-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_preflight_request_sha256": file_sha256(context["request_path"]),
        "private_plan_request_sha256": context["request"]["privatePlanRequestSha256"],
        "private_apply_request_sha256": context["request"]["privateApplyRequestSha256"],
        "private_recovery_request_sha256": context["request"]["privateRecoveryRequestSha256"],
        "applied_state_sha256": context["request"]["appliedStateSha256"],
        "managed_state_address_count": len(context["managed"]),
        "state_copies_byte_identical": True,
        "backend_config_matches_applied_outputs": True,
        "remaining_preflight_approval_seconds": context["remaining"],
        "preflight_execution_authorized": False,
        "state_migration_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-bootstrap-migration-preflight-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-preflight-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_preflight_request)) if args.phase == "verify" else execute(args.private_preflight_request)
    except (APPLY_EXECUTOR.CommandFailure, PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        parser.exit(1, f"Bootstrap migration preflight stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

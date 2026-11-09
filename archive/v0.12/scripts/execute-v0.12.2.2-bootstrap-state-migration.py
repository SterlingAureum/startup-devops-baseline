#!/usr/bin/env python3
"""Verify or execute the exact reviewed bootstrap local-to-S3 state migration."""

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
PREFLIGHT_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.1-bootstrap-migration-preflight.py"
CONFIRMATION = "migrate-reviewed-bootstrap-state-to-s3"
AWS_REGION = "us-east-1"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
EXPECTED_PREFLIGHT_REQUEST_SHA256 = "1ac1f2be621fd5c5b9da05b82f1bc43eac3b10b0bf4d351179f6905096a77204"
EXPECTED_PREFLIGHT_RESULT_SHA256 = "4e5a060e9a8ce7660ce56033b0b29153ae6a37c52a4a5501d8c46921e185add9"
EXPECTED_STATE_INVENTORY_SHA256 = "fc25de78ab8d6e86b65a26a4bbbc992e1c631c46623e3dd81925c0d69d1829ff"
EXPECTED_SOURCE_MANIFEST_SHA256 = "8c9ef5076aeea7ef2cb617faf080f24db24839caf3a134129800ac9b4c3ce9e3"
EXPECTED_COMMAND_PLAN_SHA256 = "16e56fcbf1d59c20bb273291719bf7f24d4d0144da1ba52bce9c17b9c8ddbaab"
EXPECTED_STATE_SHA256 = "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995"
EXPECTED_RESOURCE_IDENTITY_SHA256 = "c59b979c1449d5212ceb72319995fbd01da9715c3dbf99ef9ca08d0bc8e282c4"
EXPECTED_PREFLIGHT_LIVE_SHA256 = "6f929213b687c44652c5f265f577767dcc422ab363f4cb598ed1c68395c1c091"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT_EXECUTOR = load_module(PREFLIGHT_EXECUTOR_PATH, "bootstrap_migration_preflight_for_execution")
RECOVERY_EXECUTOR = PREFLIGHT_EXECUTOR.RECOVERY_EXECUTOR
APPLY_EXECUTOR = PREFLIGHT_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = PREFLIGHT_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = PREFLIGHT_EXECUTOR.PLAN_GATE

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
        "expectedAwsAccountId", "privatePreflightRequestPath", "privatePreflightRequestSha256",
        "privatePreflightOutputDirectory", "preflightResultSha256", "stateInventorySha256",
        "migrationSourceManifestSha256", "migrationCommandPlanSha256", "immutableBackupSha256",
        "resourceIdentitySha256", "preflightLiveValidationSha256", "privateMigrationOutputDirectory",
        "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Migration request fields changed")
    require(value["schemaVersion"] == "v0.12.2.2-bootstrap-state-migration-request-v1", "Migration request schema changed")
    require(value["operation"] == CONFIRMATION, "Migration operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Expected main is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    exact = {
        "privatePreflightRequestSha256": EXPECTED_PREFLIGHT_REQUEST_SHA256,
        "preflightResultSha256": EXPECTED_PREFLIGHT_RESULT_SHA256,
        "stateInventorySha256": EXPECTED_STATE_INVENTORY_SHA256,
        "migrationSourceManifestSha256": EXPECTED_SOURCE_MANIFEST_SHA256,
        "migrationCommandPlanSha256": EXPECTED_COMMAND_PLAN_SHA256,
        "immutableBackupSha256": EXPECTED_STATE_SHA256,
        "resourceIdentitySha256": EXPECTED_RESOURCE_IDENTITY_SHA256,
        "preflightLiveValidationSha256": EXPECTED_PREFLIGHT_LIVE_SHA256,
    }
    for key, expected in exact.items():
        require(value[key] == expected, f"Reviewed preflight digest changed: {key}")
    for key in ("privatePreflightRequestPath", "privatePreflightOutputDirectory", "privateMigrationOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "terraformInitMigrateState": True, "terraformPlan": False, "terraformApply": False,
        "stateMigration": True, "statePush": False, "destroy": False,
        "iamPolicyAttachment": False, "automaticRetry": False, "localBackupDeletion": False,
    }, "Migration execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def exact_command_plan(plan: Any, working: Path, backend: Path) -> list[str]:
    require(isinstance(plan, dict), "Migration command plan must be an object")
    expected = [
        "terraform", f"-chdir={working}", "init", "-input=false", "-migrate-state",
        "-force-copy", f"-backend-config={backend}",
    ]
    require(plan.get("schemaVersion") == "v0.12.2.1-bootstrap-migration-command-plan-v1", "Command-plan schema changed")
    require(plan.get("workingDirectory") == str(working), "Command-plan working directory changed")
    require(plan.get("backendConfigPath") == str(backend), "Command-plan backend config changed")
    require(plan.get("command") == expected, "Reviewed migration command changed")
    require(plan.get("expectedRemoteKey") == "bootstrap/terraform.tfstate", "Remote state key changed")
    require(plan.get("expectedManagedAddressCount") == 13, "Command-plan address count changed")
    require(plan.get("requiresSeparateV01222Approval") is True, "Separate migration approval missing")
    require(plan.get("executedByThisPreflight") is False, "Preflight already reports command execution")
    return expected


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request_path = require_private_file(request_path, "Private migration request")
    require(not is_within(private_request_path, repository_root), "Migration request must remain outside repository")
    request = validate_request(load_json(private_request_path, "Private migration request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Migration approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Migration approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Migration must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Migration requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    preflight_request_path = require_private_file(Path(request["privatePreflightRequestPath"]), "Private preflight request")
    require(file_sha256(preflight_request_path) == request["privatePreflightRequestSha256"], "Preflight request changed")
    preflight_request = PREFLIGHT_EXECUTOR.validate_request(load_json(preflight_request_path, "Private preflight request"))
    require(preflight_request["expectedMainCommit"] == "33734683159315171e8de9d524691b94806dbc15", "Preflight control plane changed")
    require(preflight_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Preflight account changed")
    preflight_output = require_private_directory(Path(request["privatePreflightOutputDirectory"]), "Private preflight output")
    require(preflight_output == Path(preflight_request["privatePreflightOutputDirectory"]).resolve(strict=True), "Preflight output path changed")

    artifacts = {
        "preflight-result.json": "preflightResultSha256",
        "state-inventory.json": "stateInventorySha256",
        "migration-source-manifest.json": "migrationSourceManifestSha256",
        "migration-command-plan.json": "migrationCommandPlanSha256",
        "live-validation.json": "preflightLiveValidationSha256",
    }
    for name, field in artifacts.items():
        path = require_private_file(preflight_output / name, f"Preflight artifact {name}")
        require(file_sha256(path) == request[field], f"Preflight artifact changed: {name}")
    backup = require_private_file(preflight_output / "bootstrap-state.pre-migration.backup", "Immutable migration backup")
    require(file_sha256(backup) == request["immutableBackupSha256"], "Immutable backup changed")
    inventory = load_json(preflight_output / "state-inventory.json", "State inventory")
    require(inventory.get("managedAddressCount") == 13 and len(inventory.get("managedAddresses", [])) == 13, "State inventory changed")
    require(inventory.get("resourceIdentitySha256") == request["resourceIdentitySha256"], "Resource identity changed")
    require(isinstance(inventory.get("lineage"), str) and inventory["lineage"], "State lineage missing")
    require(isinstance(inventory.get("serial"), int) and inventory["serial"] >= 1, "State serial invalid")
    preflight_result = load_json(preflight_output / "preflight-result.json", "Preflight result")
    require(preflight_result.get("status") == "bootstrap-migration-preflight-complete-awaiting-separate-migration-approval", "Preflight did not complete")
    require(preflight_result.get("state_migration_executed") is False and preflight_result.get("terraform_init_executed") is False, "Preflight already migrated state")

    working = require_private_directory(preflight_output / "migration-source", "Private migration source")
    working_state = require_private_file(working / "terraform.tfstate", "Reviewed migration-source state")
    require(file_sha256(working_state) == request["immutableBackupSha256"], "Migration-source state changed")
    require(working_state.read_bytes() == backup.read_bytes(), "Migration source and backup differ")
    source_manifest = load_json(preflight_output / "migration-source-manifest.json", "Migration source manifest")
    require(PLAN_EXECUTOR.source_manifest(working) == source_manifest, "Migration source changed")
    require(PLAN_EXECUTOR.source_manifest(repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE) == source_manifest, "Repository migration source changed")

    backend = require_private_file(Path(preflight_request["privateBackendConfigPath"]), "Private backend config")
    require(file_sha256(backend) == preflight_request["privateBackendConfigSha256"], "Backend config changed")
    backend_values = PREFLIGHT_EXECUTOR.parse_backend_config(backend)
    plan_request_path = require_private_file(Path(preflight_request["privatePlanRequestPath"]), "Private plan request")
    require(file_sha256(plan_request_path) == preflight_request["privatePlanRequestSha256"], "Private plan request changed")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Private plan request"))
    state = load_json(backup, "Immutable migration backup")
    managed, data = RECOVERY_EXECUTOR.state_addresses(state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES and data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES, "Backup state inventory changed")
    require(PREFLIGHT_EXECUTOR.resource_identity_digest(state) == request["resourceIdentitySha256"], "Backup resource identity changed")
    identities = APPLY_EXECUTOR.validate_outputs(state.get("outputs"), plan_request)
    require(backend_values == {
        "bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION,
        "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True,
    }, "Backend config no longer matches state outputs")
    command_plan = load_json(preflight_output / "migration-command-plan.json", "Migration command plan")
    command = exact_command_plan(command_plan, working, backend)
    migration_output = require_new_private_directory(Path(request["privateMigrationOutputDirectory"]), "Private migration output")
    require(not is_within(migration_output, repository_root), "Migration output must remain outside repository")
    return {
        "request": request, "request_path": private_request_path, "preflight_request": preflight_request,
        "preflight_output": preflight_output, "migration_output": migration_output,
        "working": working, "working_state": working_state, "backup": backup, "inventory": inventory,
        "state": state, "managed": managed, "data": data, "identities": identities,
        "plan_request": plan_request, "backend": backend, "backend_values": backend_values,
        "command": command, "remaining": remaining,
    }


def safe_environment(plan_request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    environment = APPLY_EXECUTOR.safe_environment(plan_request, terraform_data)
    for key in list(environment):
        if key.startswith("TF_CLI_ARGS") or key.startswith("TF_VAR_") or key.startswith("CONFIRM_"):
            del environment[key]
    return environment


def parse_state_list(stdout: bytes) -> set[str]:
    try:
        lines = stdout.decode().splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("Terraform state list is not UTF-8") from error
    require(all(line and line.strip() == line for line in lines), "Terraform state list is invalid")
    return set(lines)


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
    require(os.environ.get("CONFIRM_STATE_BOOTSTRAP_MIGRATION") == CONFIRMATION, f"Set CONFIRM_STATE_BOOTSTRAP_MIGRATION={CONFIRMATION}")
    for forbidden in ("CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY", "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY"):
        require(not os.environ.get(forbidden), "Plan, apply, destroy and preflight confirmations must be unset")

    output = context["migration_output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    terraform_data = output / "terraform-data"
    terraform_data.mkdir(mode=0o700)
    environment = safe_environment(context["plan_request"], terraform_data)
    identity_result = APPLY_EXECUTOR.run_logged(output, "aws-identity", ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = APPLY_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")
    before = APPLY_EXECUTOR.validate_live_foundation(output, context["identities"], environment, runner, repository_root)
    require(before["s3_object_version_count"] == 0, "Remote backend is no longer empty")
    APPLY_EXECUTOR.write_private(output / "pre-migration-live-validation.json", canonical_json(before))

    APPLY_EXECUTOR.run_logged(output, "terraform-init-migrate-state", context["command"], environment, 600, runner, repository_root)
    for path in (
        context["backup"],
        Path(context["preflight_request"]["privatePlanBundleDirectory"]) / "source/terraform.tfstate",
        Path(context["preflight_request"]["privateApplyOutputDirectory"]) / "state-bootstrap.tfstate.applied",
    ):
        require(
            file_sha256(path) == context["request"]["immutableBackupSha256"],
            "Preserved local state changed after migration",
        )

    pull = APPLY_EXECUTOR.run_logged(output, "terraform-state-pull", ["terraform", f"-chdir={context['working']}", "state", "pull"], environment, 180, runner, repository_root)
    remote_state_path = output / "remote-state-pulled.json"
    APPLY_EXECUTOR.write_private(remote_state_path, pull.stdout)
    remote_state = load_json(remote_state_path, "Pulled remote state")
    remote_managed, remote_data = RECOVERY_EXECUTOR.state_addresses(remote_state)
    require(remote_managed == context["managed"] and remote_data == context["data"], "Remote state address inventory changed")
    require(remote_state.get("lineage") == context["inventory"]["lineage"], "Remote state lineage changed")
    require(isinstance(remote_state.get("serial"), int) and remote_state["serial"] >= context["inventory"]["serial"], "Remote state serial regressed")
    remote_resource_digest = PREFLIGHT_EXECUTOR.resource_identity_digest(remote_state)
    require(remote_resource_digest == context["request"]["resourceIdentitySha256"], "Remote resource identity changed")
    APPLY_EXECUTOR.validate_outputs(remote_state.get("outputs"), context["plan_request"])

    listed = APPLY_EXECUTOR.run_logged(output, "terraform-state-list", ["terraform", f"-chdir={context['working']}", "state", "list"], environment, 180, runner, repository_root)
    require(parse_state_list(listed.stdout) == context["managed"] | context["data"], "Terraform remote state list changed")
    bucket = context["identities"]["bucket"]
    key = context["backend_values"]["key"]
    head_result = APPLY_EXECUTOR.run_logged(output, "s3-state-head", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", key, "--output", "json"], environment, 120, runner, repository_root)
    head = APPLY_EXECUTOR.parse_json_result(head_result, "S3 state head")
    require(head.get("ServerSideEncryption") == "aws:kms", "Remote state is not SSE-KMS encrypted")
    require(head.get("SSEKMSKeyId") == context["identities"]["kms_arn"], "Remote state KMS identity changed")
    require(head.get("BucketKeyEnabled") is True, "Remote state S3 Bucket Key is disabled")
    version_id = head.get("VersionId")
    require(isinstance(version_id, str) and version_id, "Remote state object version is missing")
    versions_result = APPLY_EXECUTOR.run_logged(output, "s3-state-versions", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", key, "--output", "json"], environment, 120, runner, repository_root)
    versions = APPLY_EXECUTOR.parse_json_result(versions_result, "S3 state versions")
    exact_versions = [item for item in versions.get("Versions", []) if item.get("Key") == key]
    exact_markers = [item for item in versions.get("DeleteMarkers", []) if item.get("Key") == key]
    require(len(exact_versions) == 1 and exact_versions[0].get("VersionId") == version_id and exact_versions[0].get("IsLatest") is True, "Remote state version inventory changed")
    require(exact_markers == [], "Remote state has a delete marker")

    validation = {
        "schemaVersion": "v0.12.2.2-bootstrap-migration-validation-v1",
        "remoteStateSha256": file_sha256(remote_state_path),
        "lineage": remote_state["lineage"], "serial": remote_state["serial"],
        "managedAddressCount": len(remote_managed), "dataAddressCount": len(remote_data),
        "resourceIdentitySha256": remote_resource_digest,
        "stateObjectVersionId": version_id,
        "stateObjectVersionCount": len(exact_versions), "stateObjectDeleteMarkerCount": len(exact_markers),
        "sseKmsValidated": True, "bucketKeyValidated": True,
    }
    validation_path = output / "migration-validation.json"
    APPLY_EXECUTOR.write_private(validation_path, canonical_json(validation))
    result = {
        "schemaVersion": "v0.12.2.2-bootstrap-state-migration-result-v1",
        "status": "bootstrap-state-migrated-to-s3-awaiting-v0.12.2.3-proof",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_migration_request_sha256": file_sha256(context["request_path"]),
        "private_preflight_request_sha256": context["request"]["privatePreflightRequestSha256"],
        "preflight_result_sha256": context["request"]["preflightResultSha256"],
        "immutable_backup_sha256": context["request"]["immutableBackupSha256"],
        "remote_state_sha256": validation["remoteStateSha256"],
        "resource_identity_sha256": remote_resource_digest,
        "migration_validation_sha256": file_sha256(validation_path),
        "managed_state_address_count": len(remote_managed),
        "remote_state_object_version_count": len(exact_versions),
        "remote_state_delete_marker_count": len(exact_markers),
        "terraform_init_executed": True, "state_migration_executed": True,
        "terraform_plan_executed": False, "terraform_apply_executed": False,
        "state_push_executed": False, "destroy_executed": False,
        "iam_policy_attachment_executed": False, "automatic_retry_performed": False,
        "local_backup_deleted": False, "private_state_object_version_id_emitted": False,
        "next_action": "preserve-private-evidence-and-build-v0.12.2.3-post-migration-proof",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "migration-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["migration_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "bootstrap-state-migration-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_migration_request_sha256": file_sha256(context["request_path"]),
        "private_preflight_request_sha256": context["request"]["privatePreflightRequestSha256"],
        "preflight_result_sha256": context["request"]["preflightResultSha256"],
        "immutable_backup_sha256": context["request"]["immutableBackupSha256"],
        "resource_identity_sha256": context["request"]["resourceIdentitySha256"],
        "managed_state_address_count": len(context["managed"]),
        "reviewed_command_exact": True, "remote_key_expected_absent": True,
        "remaining_migration_approval_seconds": context["remaining"],
        "migration_execution_authorized": False,
        "terraform_apply_authorized": False, "state_push_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-bootstrap-state-migration-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-migration-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_migration_request)) if args.phase == "verify" else execute(args.private_migration_request)
    except (APPLY_EXECUTOR.CommandFailure, PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        parser.exit(1, f"Bootstrap state migration stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

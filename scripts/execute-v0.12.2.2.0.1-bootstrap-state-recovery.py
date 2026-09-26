#!/usr/bin/env python3
"""Complete read-only recovery after the v0.12.2.2 state identity rebase."""

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
MIGRATION_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.2-bootstrap-state-migration.py"
RECOVERY_CONFIRMATION = "complete-read-only-bootstrap-state-identity-rebase-recovery"
INCIDENT_MAIN_COMMIT = "5e10d0edbca3be5e87fdc5446f03e6d5c4c374f5"
MIGRATION_REQUEST_SHA256 = "dbf011baaf96661f4317da1edcbbca0b3f84596c15965d1edd9c038b1e5a6467"
BACKUP_STATE_SHA256 = "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995"
REMOTE_STATE_SHA256 = "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
OLD_LINEAGE_SHA256 = "0bacf9c12fd5f2485d1b2acac980b6295a0f612335533b6abe7d1d03e3f7dc90"
NEW_LINEAGE_SHA256 = "4f42afe2b009593773f37059419ca3ea4e87ca89d4ef1a7ff1278d60f2ed2fab"
RESOURCES_SHA256 = "9ae208cbf85c37a2b9820e41be80b852efcc3cbdade7d9caa7e425784be0556e"
OUTPUTS_SHA256 = "695a5087bac5068c4a7ae30ac5d3edc5cb09e28bd8cfe591d11a0c2d0aca8b2b"
BACKUP_CHECK_RESULTS_SHA256 = "5edcc426d374ea432c4c8509b9a7e3060908f8b2bdaf754255934e05792134a8"
REMOTE_CHECK_RESULTS_SHA256 = "9e28019a03a22863c8ed4d06f2c57a1cf26e7634b3f6a3735c9f680fc17277ec"
SEMANTIC_PROJECTION_SHA256 = "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d"
AWS_IDENTITY_STDOUT_SHA256 = "a4ae772e487ab1ff50e89e58de4b5b8d5de619abbdb9f0f7ae87e9189d570732"
PRE_MIGRATION_LIVE_SHA256 = "6f929213b687c44652c5f265f577767dcc422ab363f4cb598ed1c68395c1c091"
INIT_STDOUT_SHA256 = "74bc49dd83ef1bb9e141b35689c96099136294a6a7c89014d24569f1203b916e"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
AWS_REGION = "us-east-1"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION_EXECUTOR = load_module(MIGRATION_EXECUTOR_PATH, "bootstrap_state_migration_for_recovery")
PREFLIGHT_EXECUTOR = MIGRATION_EXECUTOR.PREFLIGHT_EXECUTOR
APPLY_EXECUTOR = MIGRATION_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = MIGRATION_EXECUTOR.PLAN_EXECUTOR
RECOVERY_EXECUTOR = MIGRATION_EXECUTOR.RECOVERY_EXECUTOR
PLAN_GATE = MIGRATION_EXECUTOR.PLAN_GATE

GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_digest(value: Any) -> str:
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(encoded).hexdigest()


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
        "schemaVersion", "operation", "repository", "trustedRef",
        "expectedRecoveryMainCommit", "incidentControlPlaneCommit", "expectedAwsAccountId",
        "privateMigrationRequestPath", "privateMigrationRequestSha256",
        "privateMigrationOutputDirectory", "privateRecoveryOutputDirectory",
        "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.2.2.0.1-bootstrap-state-recovery-request-v1", "Recovery request schema changed")
    require(value["operation"] == RECOVERY_CONFIRMATION, "Recovery operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    for key in ("expectedRecoveryMainCommit", "incidentControlPlaneCommit"):
        require(isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{40}", value[key]) is not None, f"Invalid commit: {key}")
    require(value["incidentControlPlaneCommit"] == INCIDENT_MAIN_COMMIT, "Incident control plane changed")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    require(value["privateMigrationRequestSha256"] == MIGRATION_REQUEST_SHA256, "Migration request digest changed")
    for key in ("privateMigrationRequestPath", "privateMigrationOutputDirectory", "privateRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsReadOnlyValidation": True, "terraformStatePull": True, "terraformStateList": True,
        "s3ObjectRead": True, "terraformInit": False, "terraformPlan": False,
        "terraformApply": False, "stateMigration": False, "statePush": False,
        "destroy": False, "iamPolicyAttachment": False, "automaticRetry": False,
        "automaticRollback": False,
    }, "Recovery execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def lineage_digest(value: Any) -> str:
    require(isinstance(value, str) and value, "State lineage is invalid")
    return hashlib.sha256(value.encode()).hexdigest()


def semantic_projection(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state[key] for key in ("version", "outputs", "resources")}


def validate_identity_rebase(backup: Any, remote: Any) -> dict[str, Any]:
    require(isinstance(backup, dict) and isinstance(remote, dict), "State documents must be objects")
    expected_keys = {"version", "terraform_version", "serial", "lineage", "outputs", "resources", "check_results"}
    require(set(backup) == expected_keys and set(remote) == expected_keys, "State top-level keys changed")
    require(backup["version"] == remote["version"] == 4, "State format version changed")
    require(backup["terraform_version"] == remote["terraform_version"] == "1.14.5", "Terraform state writer version changed")
    old_lineage = lineage_digest(backup["lineage"])
    new_lineage = lineage_digest(remote["lineage"])
    require(old_lineage == OLD_LINEAGE_SHA256 and new_lineage == NEW_LINEAGE_SHA256 and old_lineage != new_lineage, "Observed lineage rebase changed")
    require(backup["serial"] == 20 and remote["serial"] == 1, "Observed serial rebase changed")
    managed_before, data_before = RECOVERY_EXECUTOR.state_addresses(backup)
    managed_after, data_after = RECOVERY_EXECUTOR.state_addresses(remote)
    require(managed_before == managed_after == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES, "Managed state addresses changed")
    require(data_before == data_after and data_before <= PLAN_GATE.ALLOWED_DATA_ADDRESSES and len(data_before) == 9, "Data state addresses changed")
    require(backup["resources"] == remote["resources"], "State resources changed")
    require(compact_digest(backup["resources"]) == compact_digest(remote["resources"]) == RESOURCES_SHA256, "State resources digest changed")
    require(backup["outputs"] == remote["outputs"], "State outputs changed")
    require(compact_digest(backup["outputs"]) == compact_digest(remote["outputs"]) == OUTPUTS_SHA256, "State outputs digest changed")
    require(isinstance(backup["check_results"], list) and len(backup["check_results"]) == 2, "Backup check results changed")
    require(isinstance(remote["check_results"], list) and len(remote["check_results"]) == 2, "Remote check results changed")
    require(compact_digest(backup["check_results"]) == BACKUP_CHECK_RESULTS_SHA256, "Backup check-results digest changed")
    require(compact_digest(remote["check_results"]) == REMOTE_CHECK_RESULTS_SHA256, "Remote check-results digest changed")
    before_projection = semantic_projection(backup)
    after_projection = semantic_projection(remote)
    require(before_projection == after_projection, "State semantic projection changed")
    require(compact_digest(before_projection) == compact_digest(after_projection) == SEMANTIC_PROJECTION_SHA256, "State semantic projection digest changed")
    return {
        "old_lineage_sha256": old_lineage, "new_lineage_sha256": new_lineage,
        "old_serial": backup["serial"], "new_serial": remote["serial"],
        "managed": managed_after, "data": data_after,
        "resources_sha256": RESOURCES_SHA256, "outputs_sha256": OUTPUTS_SHA256,
        "semantic_projection_sha256": SEMANTIC_PROJECTION_SHA256,
        "remote_check_results_sha256": REMOTE_CHECK_RESULTS_SHA256,
    }


def require_artifact(path: Path, label: str, expected_sha256: str, expected_size: int | None = None) -> Path:
    result = require_private_file(path, label)
    require(file_sha256(result) == expected_sha256, f"{label} digest changed")
    if expected_size is not None:
        require(result.stat().st_size == expected_size, f"{label} size changed")
    return result


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside repository")
    request = validate_request(load_json(private_request, "Private recovery request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Recovery approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Recovery approval has less than 15 minutes remaining")
    expected_main = request["expectedRecoveryMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Recovery must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Recovery requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal recovery main")

    migration_request_path = require_private_file(Path(request["privateMigrationRequestPath"]), "Private migration request")
    require(file_sha256(migration_request_path) == MIGRATION_REQUEST_SHA256, "Private migration request changed")
    migration_request = MIGRATION_EXECUTOR.validate_request(load_json(migration_request_path, "Private migration request"))
    require(migration_request["expectedMainCommit"] == INCIDENT_MAIN_COMMIT, "Migration incident commit changed")
    require(migration_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Migration account changed")
    migration_output = require_private_directory(Path(request["privateMigrationOutputDirectory"]), "Private migration output")
    require(migration_output == Path(migration_request["privateMigrationOutputDirectory"]).resolve(strict=True), "Migration output path changed")
    require(not is_within(migration_output, repository_root), "Migration output must remain outside repository")

    preflight_request_path = require_private_file(Path(migration_request["privatePreflightRequestPath"]), "Private preflight request")
    require(file_sha256(preflight_request_path) == MIGRATION_EXECUTOR.EXPECTED_PREFLIGHT_REQUEST_SHA256, "Preflight request changed")
    preflight_request = PREFLIGHT_EXECUTOR.validate_request(load_json(preflight_request_path, "Private preflight request"))
    preflight_output = require_private_directory(Path(migration_request["privatePreflightOutputDirectory"]), "Private preflight output")
    require(preflight_output == Path(preflight_request["privatePreflightOutputDirectory"]).resolve(strict=True), "Preflight output path changed")
    plan_request_path = require_private_file(Path(preflight_request["privatePlanRequestPath"]), "Private plan request")
    require(file_sha256(plan_request_path) == preflight_request["privatePlanRequestSha256"], "Private plan request changed")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Private plan request"))

    incident_artifacts = {
        "aws-identity.stdout": (AWS_IDENTITY_STDOUT_SHA256, 197),
        "aws-identity.stderr": (EMPTY_SHA256, 0),
        "pre-migration-live-validation.json": (PRE_MIGRATION_LIVE_SHA256, 377),
        "terraform-init-migrate-state.stdout": (INIT_STDOUT_SHA256, 839),
        "terraform-init-migrate-state.stderr": (EMPTY_SHA256, 0),
        "terraform-state-pull.stdout": (REMOTE_STATE_SHA256, 69929),
        "terraform-state-pull.stderr": (EMPTY_SHA256, 0),
        "remote-state-pulled.json": (REMOTE_STATE_SHA256, 69929),
    }
    for name, (digest, size) in incident_artifacts.items():
        require_artifact(migration_output / name, f"Migration incident artifact {name}", digest, size)
    require((migration_output / "terraform-state-pull.stdout").read_bytes() == (migration_output / "remote-state-pulled.json").read_bytes(), "Pulled state copies differ")
    init_text = (migration_output / "terraform-init-migrate-state.stdout").read_text(errors="strict")
    require("Successfully configured the backend" in init_text and "Terraform has been successfully initialized" in init_text, "Terraform migration success markers changed")
    for name in ("migration-result.json", "migration-validation.json", "terraform-state-list.stdout", "terraform-state-list.stderr", "s3-state-head.stdout", "s3-state-versions.stdout"):
        require(not (migration_output / name).exists() and not (migration_output / name).is_symlink(), f"Unexpected post-migration artifact exists: {name}")

    backup = require_artifact(preflight_output / "bootstrap-state.pre-migration.backup", "Immutable migration backup", BACKUP_STATE_SHA256)
    plan_state = require_artifact(Path(preflight_request["privatePlanBundleDirectory"]) / "source/terraform.tfstate", "Preserved plan state", BACKUP_STATE_SHA256)
    apply_state = require_artifact(Path(preflight_request["privateApplyOutputDirectory"]) / "state-bootstrap.tfstate.applied", "Preserved apply state", BACKUP_STATE_SHA256)
    require(backup.read_bytes() == plan_state.read_bytes() == apply_state.read_bytes(), "Preserved state copies differ")
    working = require_private_directory(preflight_output / "migration-source", "Private migration source")
    working_state = require_artifact(working / "terraform.tfstate", "Post-migration local working state", EMPTY_SHA256, 0)
    terraform_data = require_private_directory(migration_output / "terraform-data", "Existing migrated Terraform data")

    backup_state = load_json(backup, "Immutable migration backup")
    remote_state_path = migration_output / "remote-state-pulled.json"
    remote_state = load_json(remote_state_path, "Pulled remote state")
    transition = validate_identity_rebase(backup_state, remote_state)
    identities = APPLY_EXECUTOR.validate_outputs(remote_state.get("outputs"), plan_request)
    backend = require_private_file(Path(preflight_request["privateBackendConfigPath"]), "Private backend config")
    backend_values = PREFLIGHT_EXECUTOR.parse_backend_config(backend)
    require(backend_values == {
        "bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION,
        "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True,
    }, "Backend config no longer matches migrated state outputs")

    recovery_output = require_new_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(not is_within(recovery_output, repository_root), "Recovery output must remain outside repository")
    return {
        "request": request, "request_path": private_request,
        "migration_request": migration_request, "migration_request_path": migration_request_path,
        "migration_output": migration_output, "preflight_request": preflight_request,
        "preflight_output": preflight_output, "plan_request": plan_request,
        "working": working, "working_state": working_state, "terraform_data": terraform_data,
        "backup": backup, "remote_state_path": remote_state_path, "remote_state": remote_state,
        "transition": transition, "identities": identities, "backend_values": backend_values,
        "recovery_output": recovery_output, "remaining": remaining,
    }


def safe_environment(plan_request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    return MIGRATION_EXECUTOR.safe_environment(plan_request, terraform_data)


def exact_state_versions(value: Any, key: str, version_id: str) -> tuple[list[Any], list[Any]]:
    require(isinstance(value, dict), "S3 version inventory must be an object")
    versions = value.get("Versions", [])
    markers = value.get("DeleteMarkers", [])
    require(isinstance(versions, list) and isinstance(markers, list), "S3 version inventory changed")
    exact_versions = [item for item in versions if isinstance(item, dict) and item.get("Key") == key]
    exact_markers = [item for item in markers if isinstance(item, dict) and item.get("Key") == key]
    require(len(exact_versions) == 1, "Expected exactly one remote state object version")
    require(exact_versions[0].get("VersionId") == version_id and exact_versions[0].get("IsLatest") is True, "Current remote state version changed")
    require(exact_markers == [], "Remote state has a delete marker")
    return exact_versions, exact_markers


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
    require(os.environ.get("CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY") == RECOVERY_CONFIRMATION, f"Set CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY={RECOVERY_CONFIRMATION}")
    forbidden = (
        "CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT", "CONFIRM_STATE_BOOTSTRAP_MIGRATION",
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Migration, apply, destroy and state-push confirmations must be unset")

    output = context["recovery_output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = safe_environment(context["plan_request"], context["terraform_data"])
    identity_result = APPLY_EXECUTOR.run_logged(output, "aws-identity", ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = APPLY_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")

    pull = APPLY_EXECUTOR.run_logged(output, "terraform-state-pull", ["terraform", f"-chdir={context['working']}", "state", "pull"], environment, 180, runner, repository_root)
    remote_path = output / "remote-state-revalidated.json"
    APPLY_EXECUTOR.write_private(remote_path, pull.stdout)
    require(file_sha256(remote_path) == REMOTE_STATE_SHA256, "Revalidated remote state bytes changed")
    remote_state = load_json(remote_path, "Revalidated remote state")
    transition = validate_identity_rebase(load_json(context["backup"], "Immutable migration backup"), remote_state)

    listed = APPLY_EXECUTOR.run_logged(output, "terraform-state-list", ["terraform", f"-chdir={context['working']}", "state", "list"], environment, 180, runner, repository_root)
    require(MIGRATION_EXECUTOR.parse_state_list(listed.stdout) == transition["managed"] | transition["data"], "Terraform remote state list changed")
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
    exact_versions, exact_markers = exact_state_versions(versions, key, version_id)

    validation = {
        "schemaVersion": "v0.12.2.2.0.1-bootstrap-state-identity-rebase-validation-v1",
        "incidentRemoteStateSha256": REMOTE_STATE_SHA256,
        "revalidatedRemoteStateSha256": file_sha256(remote_path),
        "oldLineageSha256": transition["old_lineage_sha256"],
        "newLineageSha256": transition["new_lineage_sha256"],
        "oldSerial": transition["old_serial"], "newSerial": transition["new_serial"],
        "managedAddressCount": len(transition["managed"]), "dataAddressCount": len(transition["data"]),
        "resourcesSha256": transition["resources_sha256"], "outputsSha256": transition["outputs_sha256"],
        "semanticProjectionSha256": transition["semantic_projection_sha256"],
        "remoteCheckResultsSha256": transition["remote_check_results_sha256"],
        "stateObjectVersionId": version_id, "stateObjectVersionCount": len(exact_versions),
        "stateObjectDeleteMarkerCount": len(exact_markers), "sseKmsValidated": True,
        "bucketKeyValidated": True, "stateListValidated": True,
    }
    validation_path = output / "identity-rebase-validation.json"
    APPLY_EXECUTOR.write_private(validation_path, canonical_json(validation))
    result = {
        "schemaVersion": "v0.12.2.2.0.1-bootstrap-state-recovery-result-v1",
        "status": "bootstrap-state-migration-recovered-with-validated-identity-rebase",
        "incident_control_plane_commit": INCIDENT_MAIN_COMMIT,
        "recovery_control_plane_commit": context["request"]["expectedRecoveryMainCommit"],
        "private_migration_request_sha256": MIGRATION_REQUEST_SHA256,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "immutable_backup_sha256": BACKUP_STATE_SHA256,
        "remote_state_sha256": REMOTE_STATE_SHA256,
        "old_lineage_sha256": transition["old_lineage_sha256"],
        "new_lineage_sha256": transition["new_lineage_sha256"],
        "old_serial": transition["old_serial"], "new_serial": transition["new_serial"],
        "semantic_projection_sha256": transition["semantic_projection_sha256"],
        "managed_state_address_count": len(transition["managed"]),
        "data_state_address_count": len(transition["data"]),
        "remote_state_object_version_count": len(exact_versions),
        "remote_state_delete_marker_count": len(exact_markers),
        "identity_rebase_validation_sha256": file_sha256(validation_path),
        "prior_terraform_init_succeeded": True, "terraform_init_reexecuted": False,
        "state_migration_reexecuted": False, "terraform_plan_executed": False,
        "terraform_apply_executed": False, "state_push_executed": False,
        "destroy_executed": False, "iam_policy_attachment_executed": False,
        "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "private_state_object_version_id_emitted": False, "private_resource_identity_emitted": False,
        "next_action": "record-recovery-evidence-and-build-v0.12.2.3-remote-state-proof",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "identity-rebase-recovery-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["recovery_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    transition = context["transition"]
    return {
        "status": "bootstrap-state-identity-rebase-recovery-inputs-verified",
        "incident_control_plane_commit": INCIDENT_MAIN_COMMIT,
        "recovery_control_plane_commit": context["request"]["expectedRecoveryMainCommit"],
        "private_migration_request_sha256": MIGRATION_REQUEST_SHA256,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "immutable_backup_sha256": BACKUP_STATE_SHA256, "remote_state_sha256": REMOTE_STATE_SHA256,
        "old_lineage_sha256": transition["old_lineage_sha256"],
        "new_lineage_sha256": transition["new_lineage_sha256"],
        "old_serial": transition["old_serial"], "new_serial": transition["new_serial"],
        "semantic_projection_sha256": transition["semantic_projection_sha256"],
        "managed_state_address_count": len(transition["managed"]),
        "data_state_address_count": len(transition["data"]),
        "remaining_recovery_approval_seconds": context["remaining"],
        "recovery_execution_authorized": False, "terraform_init_authorized": False,
        "state_migration_authorized": False, "state_push_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-read-only-identity-rebase-recovery-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-recovery-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_recovery_request)) if args.phase == "verify" else execute(args.private_recovery_request)
    except (APPLY_EXECUTOR.CommandFailure, PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"Bootstrap state identity-rebase recovery stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

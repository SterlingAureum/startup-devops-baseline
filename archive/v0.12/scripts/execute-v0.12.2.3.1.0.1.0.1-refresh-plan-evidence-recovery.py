#!/usr/bin/env python3
"""Complete read-only recovery of the existing refresh-only plan evidence."""

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
REFRESH_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py"
CONFIRMATION = "complete-read-only-refresh-plan-evidence-recovery"
INCIDENT_MAIN_COMMIT = "be27ef4aa9a6825473084bd48ff9a29cbd8f9909"
REFRESH_REQUEST_SHA256 = "d856dd8a88485a3a816e79c411e6551e2335bd435ffa61d05adc41e2622c6f3a"
BINARY_PLAN_SHA256 = "25e0d13ea279af093fc138c9f6d946694e3e399df5c5c6c2648e401ce789f74c"
PLAN_JSON_SHA256 = "b89d89f3590f8cf7aab5bab15fa5d0dc2e522cb8d9c56098bcb6ea02a11887ad"
PLAN_TEXT_SHA256 = "746ef94f5ddb6bd3630006011745bf2f67d8ce7a43eff54642d7d54193e67d98"
RESOURCE_DRIFT_SHA256 = "cda2f5fefc620e11747c88e38db673e906fb7c4a29a5a5c886a5f7ec0140ab7a"
REMOTE_STATE_SHA256 = "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
AWS_REGION = "us-east-1"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REFRESH_EXECUTOR = load_module(REFRESH_EXECUTOR_PATH, "refresh_only_plan_for_evidence_recovery")
PROOF_EXECUTOR = REFRESH_EXECUTOR.PROOF_EXECUTOR
RECOVERY_EXECUTOR = REFRESH_EXECUTOR.RECOVERY_EXECUTOR
MIGRATION_EXECUTOR = REFRESH_EXECUTOR.MIGRATION_EXECUTOR
PREFLIGHT_EXECUTOR = REFRESH_EXECUTOR.PREFLIGHT_EXECUTOR
APPLY_EXECUTOR = REFRESH_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = REFRESH_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = REFRESH_EXECUTOR.PLAN_GATE

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


def require_artifact(path: Path, label: str, digest: str, size: int | None = None) -> Path:
    artifact = require_private_file(path, label)
    require(file_sha256(artifact) == digest, f"{label} digest changed")
    if size is not None:
        require(artifact.stat().st_size == size, f"{label} size changed")
    return artifact


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedRecoveryMainCommit",
        "expectedAwsAccountId", "privateFailedRefreshPlanRequestPath", "privateFailedRefreshPlanRequestSha256",
        "privateFailedRefreshPlanOutputDirectory", "binaryRefreshPlanSha256", "refreshPlanJsonSha256",
        "refreshPlanTextSha256", "resourceDriftSha256", "canonicalRemoteStateSha256",
        "privateRecoveryOutputDirectory", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery-request-v1", "Recovery request schema changed")
    require(value["operation"] == CONFIRMATION, "Recovery operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedRecoveryMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedRecoveryMainCommit"]) is not None, "Recovery main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    for key in ("privateFailedRefreshPlanRequestPath", "privateFailedRefreshPlanOutputDirectory", "privateRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    expected = {
        "privateFailedRefreshPlanRequestSha256": REFRESH_REQUEST_SHA256,
        "binaryRefreshPlanSha256": BINARY_PLAN_SHA256,
        "refreshPlanJsonSha256": PLAN_JSON_SHA256,
        "refreshPlanTextSha256": PLAN_TEXT_SHA256,
        "resourceDriftSha256": RESOURCE_DRIFT_SHA256,
        "canonicalRemoteStateSha256": REMOTE_STATE_SHA256,
    }
    require(all(value[key] == digest for key, digest in expected.items()), "Reviewed refresh-plan incident digest changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsIdentityRead": True, "terraformStatePull": True, "terraformStateList": True,
        "s3StateAndLockRead": True, "terraformInit": False, "terraformPlan": False,
        "terraformApply": False, "statePush": False, "destroy": False,
        "iamPolicyAttachment": False, "directLockWrite": False, "forceUnlock": False,
        "automaticRetry": False,
    }, "Recovery execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def verify_inputs(
    request_path: Path, *, repository_root: Path = ROOT,
    git_runner: GitRunner = run_git, now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private plan-evidence recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside repository")
    request = validate_request(load_json(private_request, "Private plan-evidence recovery request"))
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

    failed_request_path = require_private_file(Path(request["privateFailedRefreshPlanRequestPath"]), "Failed refresh-plan request")
    require(file_sha256(failed_request_path) == REFRESH_REQUEST_SHA256, "Failed refresh-plan request changed")
    failed_request = REFRESH_EXECUTOR.validate_request(load_json(failed_request_path, "Failed refresh-plan request"))
    require(failed_request["expectedMainCommit"] == INCIDENT_MAIN_COMMIT, "Incident control plane changed")
    require(failed_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Incident account changed")
    failed_output = require_private_directory(Path(request["privateFailedRefreshPlanOutputDirectory"]), "Failed refresh-plan output")
    require(failed_output == Path(failed_request["privateRefreshPlanOutputDirectory"]).resolve(strict=True), "Failed refresh-plan output path changed")
    require(not is_within(failed_output, repository_root), "Failed output must remain outside repository")

    artifacts = {
        "terraform-state-pull-before.stdout": (REMOTE_STATE_SHA256, 69929),
        "terraform-state-list-before.stdout": ("099466efe2fc456d759a813278ffd8c4d0f5bf2bfb997bcea4e7c7f3dbbf73f6", 897),
        "s3-lock-head-before.stderr": ("6b4ced3a96731d6fa121bee840a1ff6909200bfe3cd115aaef2c7f75aee03bef", 74),
        "terraform-plan-refresh-only.stdout": ("3e399ae58d8d9bb4a726c805d3ece36341f15566073f65583ade87f24de04531", 7313),
        "terraform-plan-refresh-only.stderr": (EMPTY_SHA256, 0),
        "bootstrap-refresh-only.tfplan": (BINARY_PLAN_SHA256, 18581),
        "terraform-show-refresh-only-json.stdout": (PLAN_JSON_SHA256, 100175),
        "terraform-show-refresh-only-json.stderr": (EMPTY_SHA256, 0),
        "terraform-show-refresh-only-text.stdout": (PLAN_TEXT_SHA256, 4260),
        "terraform-show-refresh-only-text.stderr": (EMPTY_SHA256, 0),
    }
    for name, (digest, size) in artifacts.items():
        require_artifact(failed_output / name, f"Refresh-plan incident artifact {name}", digest, size)
    require(not (failed_output / "refresh-only-plan-result.json").exists(), "Unexpected refresh-plan result exists")
    plan = load_json(failed_output / "terraform-show-refresh-only-json.stdout", "Existing refresh-only plan JSON")
    require(plan.get("applyable") is True, "Existing refresh-only plan is not applyable")
    REFRESH_EXECUTOR.validate_reviewed_drift(plan, refresh_only=True)

    proof_request_path = require_private_file(Path(failed_request["privateFailedProofRequestPath"]), "Failed proof request")
    require(file_sha256(proof_request_path) == REFRESH_EXECUTOR.PROOF_REQUEST_SHA256, "Failed proof request changed")
    proof_request = PROOF_EXECUTOR.validate_request(load_json(proof_request_path, "Failed proof request"))
    recovery_request_path = require_private_file(Path(proof_request["privateRecoveryRequestPath"]), "Private identity recovery request")
    require(file_sha256(recovery_request_path) == PROOF_EXECUTOR.RECOVERY_REQUEST_SHA256, "Identity recovery request changed")
    recovery_request = RECOVERY_EXECUTOR.validate_request(load_json(recovery_request_path, "Private identity recovery request"))
    migration_request_path = require_private_file(Path(recovery_request["privateMigrationRequestPath"]), "Private migration request")
    require(file_sha256(migration_request_path) == RECOVERY_EXECUTOR.MIGRATION_REQUEST_SHA256, "Migration request changed")
    migration_request = MIGRATION_EXECUTOR.validate_request(load_json(migration_request_path, "Private migration request"))
    preflight_request_path = require_private_file(Path(migration_request["privatePreflightRequestPath"]), "Private preflight request")
    require(file_sha256(preflight_request_path) == MIGRATION_EXECUTOR.EXPECTED_PREFLIGHT_REQUEST_SHA256, "Preflight request changed")
    preflight_request = PREFLIGHT_EXECUTOR.validate_request(load_json(preflight_request_path, "Private preflight request"))
    preflight_output = require_private_directory(Path(migration_request["privatePreflightOutputDirectory"]), "Private preflight output")
    working = require_private_directory(preflight_output / "migration-source", "Private migration source")
    source_manifest = load_json(preflight_output / "migration-source-manifest.json", "Migration source manifest")
    require(PLAN_EXECUTOR.source_manifest(working) == source_manifest, "Staged source changed")
    require(PLAN_EXECUTOR.source_manifest(repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE) == source_manifest, "Repository source changed")
    migration_output = require_private_directory(Path(recovery_request["privateMigrationOutputDirectory"]), "Private migration output")
    terraform_data = require_private_directory(migration_output / "terraform-data", "Existing migrated Terraform data")
    original_plan_request_path = require_private_file(Path(preflight_request["privatePlanRequestPath"]), "Private original plan request")
    require(file_sha256(original_plan_request_path) == preflight_request["privatePlanRequestSha256"], "Original plan request changed")
    original_plan_request = PLAN_EXECUTOR.validate_request(load_json(original_plan_request_path, "Private original plan request"))
    tfvars = require_private_file(Path(original_plan_request["privateTfvarsPath"]), "Private tfvars")
    require(file_sha256(tfvars) == original_plan_request["privateTfvarsSha256"], "Private tfvars changed")
    state = load_json(failed_output / "terraform-state-pull-before.stdout", "Canonical state before refresh plan")
    managed, data = RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES and data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES and len(data) == 9, "State address inventory changed")
    identities = APPLY_EXECUTOR.validate_outputs(state.get("outputs"), original_plan_request)
    backend = require_private_file(Path(preflight_request["privateBackendConfigPath"]), "Private backend config")
    backend_values = PREFLIGHT_EXECUTOR.parse_backend_config(backend)
    require(backend_values == {"bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION, "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True}, "Backend config changed")

    before_head_path = require_private_file(failed_output / "s3-state-head-before.stdout", "Incident state head")
    before_head = load_json(before_head_path, "Incident state head")
    state_version_id = PROOF_EXECUTOR.validate_state_head(before_head, identities)
    before_versions_path = require_private_file(failed_output / "s3-object-versions-before.stdout", "Incident object versions")
    before_versions = load_json(before_versions_path, "Incident object versions")
    state_key = backend_values["key"]
    lock_key = state_key + ".tflock"
    state_versions_before, state_markers_before = PROOF_EXECUTOR.exact_history(before_versions, state_key)
    lock_versions_before, lock_markers_before = PROOF_EXECUTOR.exact_history(before_versions, lock_key)
    require(len(state_versions_before) == 1 and state_versions_before[0].get("VersionId") == state_version_id and state_markers_before == [], "Incident state object history changed")
    output = require_new_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(not is_within(output, repository_root), "Recovery output must remain outside repository")
    return {
        "request": request, "request_path": private_request, "failed_request": failed_request,
        "failed_request_path": failed_request_path, "failed_output": failed_output,
        "working": working, "terraform_data": terraform_data, "original_plan_request": original_plan_request,
        "managed": managed, "data": data, "identities": identities, "backend_values": backend_values,
        "state_versions_before": state_versions_before, "state_markers_before": state_markers_before,
        "lock_versions_before": lock_versions_before, "lock_markers_before": lock_markers_before,
        "output": output, "remaining": remaining,
    }


def execute(
    request_path: Path, *, repository_root: Path = ROOT,
    git_runner: GitRunner = run_git, runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_REFRESH_PLAN_EVIDENCE_RECOVERY") == CONFIRMATION, f"Set CONFIRM_REFRESH_PLAN_EVIDENCE_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN", "CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF",
        "CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY",
        "CONFIRM_STATE_BOOTSTRAP_RECOVERY", "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION", "CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY",
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Plan, proof, migration, apply, destroy and state-push confirmations must be unset")
    output = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = PROOF_EXECUTOR.safe_environment(context["original_plan_request"], context["terraform_data"])
    record = PROOF_EXECUTOR.run_recorded
    identity_result = record(output, "aws-identity", ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = PROOF_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")
    prefix = ["terraform", f"-chdir={context['working']}"]
    pull = record(output, "terraform-state-pull", [*prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull.returncode == 0 and hashlib.sha256(pull.stdout).hexdigest() == REMOTE_STATE_SHA256, "Canonical state bytes changed")
    listed = record(output, "terraform-state-list", [*prefix, "state", "list"], environment, 180, runner, repository_root)
    require(listed.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(listed.stdout) == context["managed"] | context["data"], "State address inventory changed")
    bucket = context["identities"]["bucket"]
    state_key = context["backend_values"]["key"]
    lock_key = state_key + ".tflock"
    head_result = record(output, "s3-state-head", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", state_key, "--output", "json"], environment, 120, runner, repository_root)
    state_version_id = PROOF_EXECUTOR.validate_state_head(PROOF_EXECUTOR.parse_json_result(head_result, "State head"), context["identities"])
    versions_result = record(output, "s3-object-versions", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions = PROOF_EXECUTOR.parse_json_result(versions_result, "Object versions")
    state_versions, state_markers = PROOF_EXECUTOR.exact_history(versions, state_key)
    lock_versions, lock_markers = PROOF_EXECUTOR.exact_history(versions, lock_key)
    require(state_versions == context["state_versions_before"] and state_markers == context["state_markers_before"], "State object history changed")
    require(len(state_versions) == 1 and state_versions[0].get("VersionId") == state_version_id and state_versions[0].get("IsLatest") is True, "Current state version changed")
    require(len(lock_versions) - len(context["lock_versions_before"]) == 1, "Refresh plan lock version delta changed")
    require(len(lock_markers) - len(context["lock_markers_before"]) == 1, "Refresh plan lock delete-marker delta changed")
    lock_result = record(output, "s3-lock-head", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(PROOF_EXECUTOR.is_not_found(lock_result), "Lock object remains after refresh-only plan")

    validation = {
        "schemaVersion": "v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-validation-v1",
        "canonicalStateSha256": hashlib.sha256(pull.stdout).hexdigest(),
        "binaryRefreshPlanSha256": BINARY_PLAN_SHA256, "refreshPlanJsonSha256": PLAN_JSON_SHA256,
        "refreshPlanTextSha256": PLAN_TEXT_SHA256, "resourceDriftSha256": RESOURCE_DRIFT_SHA256,
        "resourceDriftCount": 7, "resourceChangeCount": 0, "outputChangeCount": 7,
        "managedAddressCount": len(context["managed"]), "dataAddressCount": len(context["data"]),
        "stateObjectVersionIds": [item.get("VersionId") for item in state_versions],
        "lockObjectVersionIds": [item.get("VersionId") for item in lock_versions],
        "lockObjectDeleteMarkerIds": [item.get("VersionId") for item in lock_markers],
        "stateObjectHistoryChanged": False, "refreshPlanLockVersionDelta": 1,
        "refreshPlanLockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
    }
    validation_path = output / "refresh-plan-evidence-validation.json"
    APPLY_EXECUTOR.write_private(validation_path, canonical_json(validation))
    result = {
        "schemaVersion": "v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery-result-v1",
        "status": "refresh-only-plan-evidence-recovered-awaiting-separate-state-reconciliation-review",
        "incident_control_plane_commit": INCIDENT_MAIN_COMMIT,
        "recovery_control_plane_commit": context["request"]["expectedRecoveryMainCommit"],
        "private_failed_refresh_plan_request_sha256": REFRESH_REQUEST_SHA256,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "canonical_remote_state_sha256": REMOTE_STATE_SHA256,
        "binary_refresh_plan_sha256": BINARY_PLAN_SHA256,
        "refresh_plan_json_sha256": PLAN_JSON_SHA256,
        "refresh_plan_text_sha256": PLAN_TEXT_SHA256,
        "resource_drift_sha256": RESOURCE_DRIFT_SHA256,
        "validation_sha256": file_sha256(validation_path),
        "resource_drift_count": 7, "resource_change_count": 0,
        "output_change_count": 7, "managed_state_address_count": len(context["managed"]),
        "data_state_address_count": len(context["data"]), "plan_applyable": True,
        "state_content_mutated": False, "state_object_history_changed": False,
        "refresh_plan_reexecuted": False, "terraform_init_executed": False,
        "terraform_apply_executed": False, "state_push_executed": False,
        "destroy_executed": False, "iam_policy_attachment_executed": False,
        "direct_lock_write_executed": False, "force_unlock_executed": False,
        "automatic_retry_performed": False, "lock_object_absent": True,
        "refresh_plan_lock_version_delta": 1, "refresh_plan_lock_delete_marker_delta": 1,
        "private_resource_identity_emitted": False, "private_object_version_id_emitted": False,
        "next_action": "human-review-existing-refresh-only-plan-before-v0.12.2.3.1.0.2",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "refresh-plan-evidence-recovery-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["recovery_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "refresh-only-plan-evidence-recovery-inputs-verified",
        "incident_control_plane_commit": INCIDENT_MAIN_COMMIT,
        "recovery_control_plane_commit": context["request"]["expectedRecoveryMainCommit"],
        "private_failed_refresh_plan_request_sha256": REFRESH_REQUEST_SHA256,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "canonical_remote_state_sha256": REMOTE_STATE_SHA256,
        "binary_refresh_plan_sha256": BINARY_PLAN_SHA256,
        "refresh_plan_json_sha256": PLAN_JSON_SHA256,
        "refresh_plan_text_sha256": PLAN_TEXT_SHA256,
        "resource_drift_sha256": RESOURCE_DRIFT_SHA256,
        "resource_drift_count": 7, "resource_change_count": 0, "output_change_count": 7,
        "managed_state_address_count": len(context["managed"]), "data_state_address_count": len(context["data"]),
        "plan_applyable": True, "remaining_recovery_approval_seconds": context["remaining"],
        "recovery_execution_authorized": False, "terraform_plan_authorized": False,
        "terraform_apply_authorized": False, "state_content_mutation_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-read-only-refresh-plan-evidence-recovery-approval",
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
        parser.exit(1, f"Refresh-only plan evidence recovery stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

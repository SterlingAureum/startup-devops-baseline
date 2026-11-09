#!/usr/bin/env python3
"""Prove real S3 lock contention and produce a zero-change saved plan."""

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
import time
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.2.0.1-bootstrap-state-recovery.py"
CONFIRMATION = "prove-bootstrap-lock-and-zero-change"
REQUEST_OPERATION = "prove-bootstrap-remote-state-lock-and-zero-change"
EXPECTED_MAIN_COMMIT = "297a82b526ea9a137704ce4ba81fdfa35e16860f"
RECOVERY_REQUEST_SHA256 = "e4c3f713fb00387dfbeb82e81d528b7eb0b262afe8d45fa9010fbb0b84d68612"
RECOVERY_RESULT_SHA256 = "adeb7145db9751f3eabd47b8379173acffff666590079edc189eb75db56e66f2"
IDENTITY_VALIDATION_SHA256 = "c6a560147ee4cd7c5fd787e9a895ebb90efd29cf2cbb23dae6a7943dd03d93b5"
REMOTE_STATE_SHA256 = "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139"
SEMANTIC_PROJECTION_SHA256 = "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d"
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


RECOVERY_EXECUTOR = load_module(RECOVERY_EXECUTOR_PATH, "identity_rebase_recovery_for_proof")
MIGRATION_EXECUTOR = RECOVERY_EXECUTOR.MIGRATION_EXECUTOR
PREFLIGHT_EXECUTOR = RECOVERY_EXECUTOR.PREFLIGHT_EXECUTOR
APPLY_EXECUTOR = RECOVERY_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = RECOVERY_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = RECOVERY_EXECUTOR.PLAN_GATE

GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]
Sleeper = Callable[[float], None]


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
        "expectedAwsAccountId", "privateRecoveryRequestPath", "privateRecoveryRequestSha256",
        "privateRecoveryOutputDirectory", "recoveryResultSha256", "identityValidationSha256",
        "remoteStateSha256", "semanticProjectionSha256", "privateProofOutputDirectory",
        "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Proof request fields changed")
    require(value["schemaVersion"] == "v0.12.2.3.1-bootstrap-remote-state-proof-request-v1", "Proof request schema changed")
    require(value["operation"] == REQUEST_OPERATION, "Proof operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    for key in ("privateRecoveryRequestPath", "privateRecoveryOutputDirectory", "privateProofOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["privateRecoveryRequestSha256"] == RECOVERY_REQUEST_SHA256, "Recovery request digest changed")
    require(value["recoveryResultSha256"] == RECOVERY_RESULT_SHA256, "Recovery result digest changed")
    require(value["identityValidationSha256"] == IDENTITY_VALIDATION_SHA256, "Identity validation digest changed")
    require(value["remoteStateSha256"] == REMOTE_STATE_SHA256, "Remote state digest changed")
    require(value["semanticProjectionSha256"] == SEMANTIC_PROJECTION_SHA256, "Semantic projection digest changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsReadOnlyValidation": True, "terraformConsoleLockHolder": True,
        "terraformPlanLockContender": True, "terraformZeroChangeSavedPlan": True,
        "transientLockMutation": True, "stateContentMutation": False,
        "terraformInit": False, "terraformApply": False, "statePush": False,
        "destroy": False, "iamPolicyAttachment": False, "directLockWrite": False,
        "forceUnlock": False, "objectVersionRecovery": False, "automaticRetry": False,
    }, "Proof execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private proof request")
    require(not is_within(private_request, repository_root), "Proof request must remain outside repository")
    request = validate_request(load_json(private_request, "Private proof request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Proof approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Proof approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Proof must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Proof requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    recovery_request_path = require_private_file(Path(request["privateRecoveryRequestPath"]), "Private recovery request")
    require(file_sha256(recovery_request_path) == RECOVERY_REQUEST_SHA256, "Private recovery request changed")
    recovery_request = RECOVERY_EXECUTOR.validate_request(load_json(recovery_request_path, "Private recovery request"))
    require(recovery_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Recovery account changed")
    recovery_output = require_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(recovery_output == Path(recovery_request["privateRecoveryOutputDirectory"]).resolve(strict=True), "Recovery output path changed")
    require(not is_within(recovery_output, repository_root), "Recovery output must remain outside repository")
    result_path = require_private_file(recovery_output / "identity-rebase-recovery-result.json", "Recovery result")
    validation_path = require_private_file(recovery_output / "identity-rebase-validation.json", "Identity validation")
    remote_path = require_private_file(recovery_output / "remote-state-revalidated.json", "Revalidated remote state")
    require(file_sha256(result_path) == RECOVERY_RESULT_SHA256, "Recovery result changed")
    require(file_sha256(validation_path) == IDENTITY_VALIDATION_SHA256, "Identity validation changed")
    require(file_sha256(remote_path) == REMOTE_STATE_SHA256, "Revalidated remote state changed")
    result = load_json(result_path, "Recovery result")
    require(result.get("status") == "bootstrap-state-migration-recovered-with-validated-identity-rebase", "Recovery did not reach terminal success")
    require(result.get("remote_state_sha256") == REMOTE_STATE_SHA256, "Recovery state binding changed")
    require(result.get("semantic_projection_sha256") == SEMANTIC_PROJECTION_SHA256, "Recovery semantic binding changed")
    require(result.get("managed_state_address_count") == 13 and result.get("data_state_address_count") == 9, "Recovery address counts changed")
    for key in ("terraform_init_reexecuted", "state_migration_reexecuted", "terraform_plan_executed", "terraform_apply_executed", "state_push_executed", "automatic_retry_performed"):
        require(result.get(key) is False, f"Recovery mutation boundary changed: {key}")

    migration_request_path = require_private_file(Path(recovery_request["privateMigrationRequestPath"]), "Private migration request")
    require(file_sha256(migration_request_path) == RECOVERY_EXECUTOR.MIGRATION_REQUEST_SHA256, "Migration request changed")
    migration_request = MIGRATION_EXECUTOR.validate_request(load_json(migration_request_path, "Private migration request"))
    preflight_request_path = require_private_file(Path(migration_request["privatePreflightRequestPath"]), "Private preflight request")
    require(file_sha256(preflight_request_path) == MIGRATION_EXECUTOR.EXPECTED_PREFLIGHT_REQUEST_SHA256, "Preflight request changed")
    preflight_request = PREFLIGHT_EXECUTOR.validate_request(load_json(preflight_request_path, "Private preflight request"))
    preflight_output = require_private_directory(Path(migration_request["privatePreflightOutputDirectory"]), "Private preflight output")
    working = require_private_directory(preflight_output / "migration-source", "Private migration source")
    source_manifest = load_json(preflight_output / "migration-source-manifest.json", "Migration source manifest")
    require(PLAN_EXECUTOR.source_manifest(working) == source_manifest, "Staged migration source changed")
    require(PLAN_EXECUTOR.source_manifest(repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE) == source_manifest, "Repository Terraform source changed")
    migration_output = require_private_directory(Path(recovery_request["privateMigrationOutputDirectory"]), "Private migration output")
    terraform_data = require_private_directory(migration_output / "terraform-data", "Existing migrated Terraform data")
    plan_request_path = require_private_file(Path(preflight_request["privatePlanRequestPath"]), "Private plan request")
    require(file_sha256(plan_request_path) == preflight_request["privatePlanRequestSha256"], "Private plan request changed")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Private plan request"))
    tfvars = require_private_file(Path(plan_request["privateTfvarsPath"]), "Private tfvars")
    require(file_sha256(tfvars) == plan_request["privateTfvarsSha256"], "Private tfvars changed")
    require(not is_within(tfvars, repository_root), "Private tfvars must remain outside repository")
    remote_state = load_json(remote_path, "Revalidated remote state")
    managed, data = RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(remote_state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES and data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES and len(data) == 9, "Remote state address inventory changed")
    identities = APPLY_EXECUTOR.validate_outputs(remote_state.get("outputs"), plan_request)
    backend = require_private_file(Path(preflight_request["privateBackendConfigPath"]), "Private backend config")
    backend_values = PREFLIGHT_EXECUTOR.parse_backend_config(backend)
    require(backend_values == {
        "bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION,
        "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True,
    }, "Backend config no longer matches remote state")
    proof_output = require_new_private_directory(Path(request["privateProofOutputDirectory"]), "Private proof output")
    require(not is_within(proof_output, repository_root), "Proof output must remain outside repository")
    return {
        "request": request, "request_path": private_request, "recovery_request": recovery_request,
        "recovery_output": recovery_output, "remote_path": remote_path, "remote_state": remote_state,
        "migration_request": migration_request, "preflight_request": preflight_request,
        "preflight_output": preflight_output, "working": working, "terraform_data": terraform_data,
        "plan_request": plan_request, "tfvars": tfvars, "managed": managed, "data": data,
        "identities": identities, "backend_values": backend_values, "proof_output": proof_output,
        "remaining": remaining,
    }


def safe_environment(plan_request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    return MIGRATION_EXECUTOR.safe_environment(plan_request, terraform_data)


def write_private(path: Path, content: bytes) -> None:
    APPLY_EXECUTOR.write_private(path, content)


def run_recorded(output: Path, label: str, arguments: list[str], environment: dict[str, str], timeout: int, runner: CommandRunner, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    result = runner(arguments, environment, timeout, cwd)
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)
    return result


def parse_json_result(result: subprocess.CompletedProcess[bytes], label: str) -> Any:
    require(result.returncode == 0, f"{label} command failed")
    try:
        return json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} returned invalid JSON") from error


def is_not_found(result: subprocess.CompletedProcess[bytes]) -> bool:
    text = (result.stdout + b"\n" + result.stderr).decode(errors="replace")
    return result.returncode != 0 and any(token in text for token in ("Not Found", "NotFound", "404"))


def exact_history(value: Any, key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    require(isinstance(value, dict), "S3 version inventory must be an object")
    versions = value.get("Versions", [])
    markers = value.get("DeleteMarkers", [])
    require(isinstance(versions, list) and isinstance(markers, list), "S3 version inventory changed")
    return (
        [item for item in versions if isinstance(item, dict) and item.get("Key") == key],
        [item for item in markers if isinstance(item, dict) and item.get("Key") == key],
    )


def lock_error_only(result: subprocess.CompletedProcess[bytes]) -> bool:
    text = (result.stdout + b"\n" + result.stderr).decode(errors="replace")
    headings = re.findall(r"^Error:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    return (
        result.returncode == 1
        and headings != []
        and all(heading == "Error acquiring the state lock" for heading in headings)
    )


def validate_zero_change_plan(value: Any) -> dict[str, int]:
    require(isinstance(value, dict), "Terraform plan JSON must be an object")
    require(value.get("terraform_version") == "1.14.5", "Terraform plan version changed")
    require(value.get("errored", False) is False, "Terraform plan is errored")
    require(value.get("complete", True) is True, "Terraform plan is incomplete")
    require(value.get("resource_drift", []) == [], "Terraform plan contains resource drift")
    counts = {key: 0 for key in ("create", "update", "delete", "replace", "import")}
    for change in value.get("resource_changes", []):
        require(isinstance(change, dict) and isinstance(change.get("change"), dict), "Resource change is invalid")
        actions = change["change"].get("actions")
        require(actions == ["no-op"], "Terraform plan contains a managed-resource change")
        require("importing" not in change["change"], "Terraform plan contains an import")
    outputs = value.get("output_changes", {})
    require(isinstance(outputs, dict), "Output changes are invalid")
    for change in outputs.values():
        require(isinstance(change, dict) and change.get("actions") == ["no-op"], "Terraform plan contains an output change")
    return counts


class ConsoleSession:
    def __init__(self, process: subprocess.Popen[bytes], stdout_handle: Any, stderr_handle: Any):
        self.process = process
        self.stdout_handle = stdout_handle
        self.stderr_handle = stderr_handle

    def poll(self) -> int | None:
        return self.process.poll()

    def finish(self, timeout: int = 30) -> int:
        try:
            self.process.communicate(input=b"exit\n", timeout=timeout)
        finally:
            self.stdout_handle.close()
            self.stderr_handle.close()
        return int(self.process.returncode)


def start_console(arguments: list[str], environment: dict[str, str], cwd: Path, output: Path) -> ConsoleSession:
    stdout_path = output / "terraform-console-lock-holder.stdout"
    stderr_path = output / "terraform-console-lock-holder.stderr"
    stdout_handle = stdout_path.open("xb")
    stderr_handle = stderr_path.open("xb")
    stdout_path.chmod(0o600)
    stderr_path.chmod(0o600)
    try:
        process = subprocess.Popen(arguments, cwd=cwd, env=environment, stdin=subprocess.PIPE, stdout=stdout_handle, stderr=stderr_handle)
    except BaseException:
        stdout_handle.close()
        stderr_handle.close()
        raise
    return ConsoleSession(process, stdout_handle, stderr_handle)


def wait_for_lock(
    *, present: bool, session: Any | None, output: Path, label: str, bucket: str, key: str,
    environment: dict[str, str], runner: CommandRunner, cwd: Path, sleeper: Sleeper,
) -> dict[str, Any] | None:
    last: subprocess.CompletedProcess[bytes] | None = None
    for _ in range(120):
        if present and session is not None:
            require(session.poll() is None, "Terraform console lock holder exited before lock observation")
        last = runner(["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", key, "--output", "json"], environment, 30, cwd)
        if present and last.returncode == 0:
            write_private(output / f"{label}.stdout", last.stdout)
            write_private(output / f"{label}.stderr", last.stderr)
            return parse_json_result(last, "Lock head")
        if not present and is_not_found(last):
            write_private(output / f"{label}.stdout", last.stdout)
            write_private(output / f"{label}.stderr", last.stderr)
            return None
        sleeper(0.25)
    if last is not None:
        write_private(output / f"{label}.stdout", last.stdout)
        write_private(output / f"{label}.stderr", last.stderr)
    raise ValueError("Lock object did not reach the required presence state")


def validate_state_head(head: Any, identities: dict[str, str]) -> str:
    require(isinstance(head, dict), "State head is invalid")
    require(head.get("ServerSideEncryption") == "aws:kms", "Remote state is not SSE-KMS encrypted")
    require(head.get("SSEKMSKeyId") == identities["kms_arn"], "Remote state KMS identity changed")
    require(head.get("BucketKeyEnabled") is True, "Remote state S3 Bucket Key is disabled")
    version_id = head.get("VersionId")
    require(isinstance(version_id, str) and version_id, "Remote state version is missing")
    return version_id


def execute(
    request_path: Path,
    *, repository_root: Path = ROOT, git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command, console_starter: Callable[..., Any] = start_console,
    sleeper: Sleeper = time.sleep, now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF") == CONFIRMATION, f"Set CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF={CONFIRMATION}")
    forbidden = (
        "CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT", "CONFIRM_STATE_BOOTSTRAP_MIGRATION",
        "CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "All migration, recovery, apply, destroy and state-push confirmations must be unset")
    output = context["proof_output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = safe_environment(context["plan_request"], context["terraform_data"])
    identity_result = run_recorded(output, "aws-identity", ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")
    working = context["working"]
    terraform_prefix = ["terraform", f"-chdir={working}"]
    pull = run_recorded(output, "terraform-state-pull-before", [*terraform_prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull.returncode == 0 and hashlib.sha256(pull.stdout).hexdigest() == REMOTE_STATE_SHA256, "Canonical remote state bytes changed")
    write_private(output / "remote-state-before.json", pull.stdout)
    before_state = load_json(output / "remote-state-before.json", "Remote state before proof")
    require(RECOVERY_EXECUTOR.semantic_projection(before_state) == RECOVERY_EXECUTOR.semantic_projection(context["remote_state"]), "Remote state semantic projection changed")
    listed = run_recorded(output, "terraform-state-list-before", [*terraform_prefix, "state", "list"], environment, 180, runner, repository_root)
    require(listed.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(listed.stdout) == context["managed"] | context["data"], "Remote state list changed")
    bucket = context["identities"]["bucket"]
    state_key = context["backend_values"]["key"]
    lock_key = state_key + ".tflock"
    state_head_result = run_recorded(output, "s3-state-head-before", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", state_key, "--output", "json"], environment, 120, runner, repository_root)
    state_version_id = validate_state_head(parse_json_result(state_head_result, "State head"), context["identities"])
    versions_before_result = run_recorded(output, "s3-object-versions-before", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions_before = parse_json_result(versions_before_result, "Object versions before proof")
    state_versions_before, state_markers_before = exact_history(versions_before, state_key)
    lock_versions_before, lock_markers_before = exact_history(versions_before, lock_key)
    require(len(state_versions_before) == 1 and state_versions_before[0].get("VersionId") == state_version_id and state_versions_before[0].get("IsLatest") is True and state_markers_before == [], "Canonical state version inventory changed")
    lock_absent = run_recorded(output, "s3-lock-head-before", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(is_not_found(lock_absent), "Lock object already exists before proof")

    console_arguments = [*terraform_prefix, "console", f"-var-file={context['tfvars']}"]
    session = console_starter(console_arguments, environment, repository_root, output)
    holder_finished = False
    cleanup_attempted = False
    try:
        wait_for_lock(present=True, session=session, output=output, label="s3-lock-head-during-holder", bucket=bucket, key=lock_key, environment=environment, runner=runner, cwd=repository_root, sleeper=sleeper)
        contender = run_recorded(output, "terraform-plan-lock-contender", [*terraform_prefix, "plan", "-input=false", "-lock=true", "-lock-timeout=0s", "-detailed-exitcode", "-no-color", f"-var-file={context['tfvars']}"], environment, 300, runner, repository_root)
        require(lock_error_only(contender), "Contender did not fail exclusively on state lock acquisition")
        cleanup_attempted = True
        require(session.finish() == 0, "Terraform console lock holder did not exit cleanly")
        holder_finished = True
        wait_for_lock(present=False, session=None, output=output, label="s3-lock-head-after-holder", bucket=bucket, key=lock_key, environment=environment, runner=runner, cwd=repository_root, sleeper=sleeper)
    finally:
        if not holder_finished and not cleanup_attempted:
            cleanup_attempted = True
            require(session.finish() == 0, "Terraform console cleanup was ambiguous")
            wait_for_lock(present=False, session=None, output=output, label="s3-lock-head-after-failure", bucket=bucket, key=lock_key, environment=environment, runner=runner, cwd=repository_root, sleeper=sleeper)

    binary_plan = output / "bootstrap-zero-change.tfplan"
    plan = run_recorded(output, "terraform-plan-zero-change", [*terraform_prefix, "plan", "-input=false", "-lock=true", "-lock-timeout=60s", "-detailed-exitcode", "-no-color", f"-out={binary_plan}", f"-var-file={context['tfvars']}"], environment, 600, runner, repository_root)
    require(plan.returncode == 0, "Zero-change Terraform plan did not return exit code 0")
    binary_plan = require_private_file(binary_plan, "Saved zero-change binary plan")
    show_json = run_recorded(output, "terraform-show-zero-change-json", [*terraform_prefix, "show", "-json", str(binary_plan)], environment, 180, runner, repository_root)
    show_text = run_recorded(output, "terraform-show-zero-change-text", [*terraform_prefix, "show", "-no-color", str(binary_plan)], environment, 180, runner, repository_root)
    plan_json = parse_json_result(show_json, "Terraform show JSON")
    counts = validate_zero_change_plan(plan_json)
    require(show_text.returncode == 0, "Terraform show text failed")
    pull_after = run_recorded(output, "terraform-state-pull-after", [*terraform_prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull_after.returncode == 0 and hashlib.sha256(pull_after.stdout).hexdigest() == REMOTE_STATE_SHA256, "Remote state bytes changed during proof")
    listed_after = run_recorded(output, "terraform-state-list-after", [*terraform_prefix, "state", "list"], environment, 180, runner, repository_root)
    require(listed_after.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(listed_after.stdout) == context["managed"] | context["data"], "Remote state list changed after proof")
    versions_after_result = run_recorded(output, "s3-object-versions-after", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions_after = parse_json_result(versions_after_result, "Object versions after proof")
    state_versions_after, state_markers_after = exact_history(versions_after, state_key)
    lock_versions_after, lock_markers_after = exact_history(versions_after, lock_key)
    require(state_versions_after == state_versions_before and state_markers_after == state_markers_before, "Canonical state object history changed")
    require(len(lock_versions_after) - len(lock_versions_before) == 2, "Unexpected lock object version delta")
    require(len(lock_markers_after) - len(lock_markers_before) == 2, "Unexpected lock delete-marker delta")
    final_lock = run_recorded(output, "s3-lock-head-final", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(is_not_found(final_lock), "Lock object remains after zero-change plan")
    proof = {
        "schemaVersion": "v0.12.2.3.1-bootstrap-remote-state-proof-v1",
        "remoteStateSha256": REMOTE_STATE_SHA256,
        "managedAddressCount": len(context["managed"]), "dataAddressCount": len(context["data"]),
        "binaryPlanSha256": file_sha256(binary_plan),
        "planJsonSha256": hashlib.sha256(show_json.stdout).hexdigest(),
        "planTextSha256": hashlib.sha256(show_text.stdout).hexdigest(),
        "changeCounts": counts, "resourceDriftCount": 0,
        "stateObjectVersionCountBefore": len(state_versions_before),
        "stateObjectVersionCountAfter": len(state_versions_after),
        "lockObjectVersionDelta": 2, "lockObjectDeleteMarkerDelta": 2,
        "lockContenderExitCode": contender.returncode, "zeroChangePlanExitCode": plan.returncode,
        "stateObjectVersionIds": [item.get("VersionId") for item in state_versions_after],
        "lockObjectVersionIds": [item.get("VersionId") for item in lock_versions_after],
        "lockObjectDeleteMarkerIds": [item.get("VersionId") for item in lock_markers_after],
    }
    proof_path = output / "remote-state-proof.json"
    write_private(proof_path, canonical_json(proof))
    result = {
        "schemaVersion": "v0.12.2.3.1-bootstrap-remote-state-proof-result-v1",
        "status": "bootstrap-remote-state-lock-contention-and-zero-change-plan-produced-awaiting-human-review",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_proof_request_sha256": file_sha256(context["request_path"]),
        "recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "remote_state_sha256": REMOTE_STATE_SHA256,
        "semantic_projection_sha256": SEMANTIC_PROJECTION_SHA256,
        "managed_state_address_count": len(context["managed"]), "data_state_address_count": len(context["data"]),
        "binary_plan_sha256": proof["binaryPlanSha256"], "terraform_plan_json_sha256": proof["planJsonSha256"],
        "terraform_plan_text_sha256": proof["planTextSha256"], "proof_sha256": file_sha256(proof_path),
        "managed_create_count": 0, "managed_update_count": 0, "managed_delete_count": 0,
        "managed_replace_count": 0, "import_count": 0, "resource_drift_count": 0,
        "lock_object_version_delta": 2, "lock_object_delete_marker_delta": 2,
        "terraform_console_executed": True, "lock_contention_observed": True,
        "zero_change_saved_plan_produced": True, "state_content_mutated": False,
        "terraform_init_executed": False, "terraform_apply_executed": False,
        "state_push_executed": False, "destroy_executed": False,
        "iam_policy_attachment_executed": False, "direct_lock_write_executed": False,
        "force_unlock_executed": False, "automatic_retry_performed": False,
        "private_resource_identity_emitted": False, "private_state_object_version_id_emitted": False,
        "next_action": "human-review-private-lock-and-zero-change-proof-before-v0.12.2.3.2",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "remote-state-proof-result.json"
    write_private(result_path, canonical_json(result))
    result["proof_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "bootstrap-remote-state-proof-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_proof_request_sha256": file_sha256(context["request_path"]),
        "private_recovery_request_sha256": RECOVERY_REQUEST_SHA256,
        "recovery_result_sha256": RECOVERY_RESULT_SHA256,
        "remote_state_sha256": REMOTE_STATE_SHA256,
        "semantic_projection_sha256": SEMANTIC_PROJECTION_SHA256,
        "managed_state_address_count": len(context["managed"]), "data_state_address_count": len(context["data"]),
        "remaining_proof_approval_seconds": context["remaining"],
        "proof_execution_authorized": False, "terraform_apply_authorized": False,
        "state_push_authorized": False, "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-bootstrap-remote-state-proof-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-proof-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_proof_request)) if args.phase == "verify" else execute(args.private_proof_request)
    except (APPLY_EXECUTOR.CommandFailure, PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"Bootstrap remote-state proof stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Apply the exact reviewed refresh-only saved plan once and validate state."""

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
EVIDENCE_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py"
CONFIRMATION = "apply-exact-reviewed-refresh-only-plan-once"
EVIDENCE_CONTROL_PLANE_COMMIT = "eb6af48ca1e50c64e0db7e54a6bdee62c220fe2f"
EVIDENCE_REQUEST_SHA256 = "c1348c8aa3da406109534cdb1faffcd99ec065fd2ab184f72d435b576a7962b5"
EVIDENCE_RESULT_SHA256 = "737211cfbf8331bcfc79e8d768f6e911dd4caf7c17a1749f31b6e0071b91cee9"
EVIDENCE_VALIDATION_SHA256 = "8776a11aba093bca353de48f0b2b9aff1b1bf8730dc43af9f2a2850766931611"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVIDENCE_EXECUTOR = load_module(EVIDENCE_EXECUTOR_PATH, "refresh_plan_evidence_for_state_reconciliation")
REFRESH_EXECUTOR = EVIDENCE_EXECUTOR.REFRESH_EXECUTOR
PROOF_EXECUTOR = EVIDENCE_EXECUTOR.PROOF_EXECUTOR
RECOVERY_EXECUTOR = EVIDENCE_EXECUTOR.RECOVERY_EXECUTOR
MIGRATION_EXECUTOR = EVIDENCE_EXECUTOR.MIGRATION_EXECUTOR
PREFLIGHT_EXECUTOR = EVIDENCE_EXECUTOR.PREFLIGHT_EXECUTOR
APPLY_EXECUTOR = EVIDENCE_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = EVIDENCE_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = EVIDENCE_EXECUTOR.PLAN_GATE
AWS_REGION = EVIDENCE_EXECUTOR.AWS_REGION
BINARY_PLAN_SHA256 = EVIDENCE_EXECUTOR.BINARY_PLAN_SHA256
PLAN_JSON_SHA256 = EVIDENCE_EXECUTOR.PLAN_JSON_SHA256
PLAN_TEXT_SHA256 = EVIDENCE_EXECUTOR.PLAN_TEXT_SHA256
RESOURCE_DRIFT_SHA256 = EVIDENCE_EXECUTOR.RESOURCE_DRIFT_SHA256
REMOTE_STATE_SHA256 = EVIDENCE_EXECUTOR.REMOTE_STATE_SHA256
REFRESH_REQUEST_SHA256 = EVIDENCE_EXECUTOR.REFRESH_REQUEST_SHA256

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


def require_artifact(path: Path, label: str, digest: str) -> Path:
    artifact = require_private_file(path, label)
    require(file_sha256(artifact) == digest, f"{label} digest changed")
    return artifact


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "privateEvidenceRecoveryRequestPath", "privateEvidenceRecoveryRequestSha256",
        "privateEvidenceRecoveryOutputDirectory", "evidenceRecoveryResultSha256", "evidenceValidationSha256",
        "recoveryStateHeadSha256", "recoveryObjectVersionsSha256", "privateRefreshPlanRequestPath",
        "privateRefreshPlanRequestSha256", "privateRefreshPlanOutputDirectory", "binaryRefreshPlanSha256",
        "refreshPlanJsonSha256", "refreshPlanTextSha256", "resourceDriftSha256",
        "canonicalRemoteStateSha256", "privateApplyOutputDirectory", "humanReview", "approval",
        "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Apply request fields changed")
    require(value["schemaVersion"] == "v0.12.2.3.1.0.2-refresh-only-state-reconciliation-request-v1", "Apply request schema changed")
    require(value["operation"] == CONFIRMATION, "Apply operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    for key in ("privateEvidenceRecoveryRequestPath", "privateEvidenceRecoveryOutputDirectory", "privateRefreshPlanRequestPath", "privateRefreshPlanOutputDirectory", "privateApplyOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    exact = {
        "privateEvidenceRecoveryRequestSha256": EVIDENCE_REQUEST_SHA256,
        "evidenceRecoveryResultSha256": EVIDENCE_RESULT_SHA256,
        "evidenceValidationSha256": EVIDENCE_VALIDATION_SHA256,
        "privateRefreshPlanRequestSha256": REFRESH_REQUEST_SHA256,
        "binaryRefreshPlanSha256": BINARY_PLAN_SHA256,
        "refreshPlanJsonSha256": PLAN_JSON_SHA256,
        "refreshPlanTextSha256": PLAN_TEXT_SHA256,
        "resourceDriftSha256": RESOURCE_DRIFT_SHA256,
        "canonicalRemoteStateSha256": REMOTE_STATE_SHA256,
    }
    require(all(value[key] == digest for key, digest in exact.items()), "Reviewed evidence digest changed")
    for key in ("recoveryStateHeadSha256", "recoveryObjectVersionsSha256"):
        require(isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None, f"Invalid digest: {key}")
    review = value["humanReview"]
    review_fields = {"reviewedAtUtc", "exactSevenStateRefreshes", "resourceChangesEmpty", "allSevenOutputsNoOp", "noImports", "noRemoteResourceActions", "noUnexpectedResourcesOrIamAttachments", "noUnexplainedWarnings"}
    require(isinstance(review, dict) and set(review) == review_fields, "Human-review fields changed")
    utc_timestamp(review["reviewedAtUtc"], "Human review timestamp")
    require(all(review[key] is True for key in review_fields - {"reviewedAtUtc"}), "Human review is incomplete")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(utc_timestamp(review["reviewedAtUtc"], "Human review timestamp") <= start, "Human review must precede approval")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsIdentityAndS3Read": True, "terraformStatePullAndList": True,
        "exactSavedRefreshPlanApply": True, "terraformInit": False, "terraformPlan": False,
        "unsavedApply": False, "statePush": False, "destroy": False,
        "iamPolicyAttachment": False, "directS3Mutation": False, "forceUnlock": False,
        "automaticRetry": False, "automaticRollback": False,
    }, "Apply execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private reconciliation request")
    require(not is_within(private_request, repository_root), "Reconciliation request must remain outside repository")
    request = validate_request(load_json(private_request, "Private reconciliation request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Apply approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Apply approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Apply must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Apply requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    evidence_request_path = require_artifact(Path(request["privateEvidenceRecoveryRequestPath"]), "Evidence-recovery request", EVIDENCE_REQUEST_SHA256)
    evidence_request = EVIDENCE_EXECUTOR.validate_request(load_json(evidence_request_path, "Evidence-recovery request"))
    require(evidence_request["expectedRecoveryMainCommit"] == EVIDENCE_CONTROL_PLANE_COMMIT, "Evidence control plane changed")
    require(evidence_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Evidence account changed")
    evidence_output = require_private_directory(Path(request["privateEvidenceRecoveryOutputDirectory"]), "Evidence-recovery output")
    require(evidence_output == Path(evidence_request["privateRecoveryOutputDirectory"]).resolve(strict=True), "Evidence output path changed")
    result_path = require_artifact(evidence_output / "refresh-plan-evidence-recovery-result.json", "Evidence-recovery result", EVIDENCE_RESULT_SHA256)
    validation_path = require_artifact(evidence_output / "refresh-plan-evidence-validation.json", "Evidence validation", EVIDENCE_VALIDATION_SHA256)
    result = load_json(result_path, "Evidence-recovery result")
    validation = load_json(validation_path, "Evidence validation")
    require(result.get("status") == "refresh-only-plan-evidence-recovered-awaiting-separate-state-reconciliation-review", "Evidence result status changed")
    require(result.get("recovery_control_plane_commit") == EVIDENCE_CONTROL_PLANE_COMMIT and result.get("state_content_mutated") is False and result.get("refresh_plan_reexecuted") is False, "Evidence recovery boundary changed")
    require(result.get("binary_refresh_plan_sha256") == BINARY_PLAN_SHA256 and result.get("refresh_plan_json_sha256") == PLAN_JSON_SHA256 and result.get("validation_sha256") == EVIDENCE_VALIDATION_SHA256, "Evidence result digest chain changed")
    require(validation.get("resourceDriftCount") == 7 and validation.get("resourceChangeCount") == 0 and validation.get("outputChangeCount") == 7, "Evidence plan shape changed")
    require(validation.get("stateObjectHistoryChanged") is False and validation.get("lockObjectAbsent") is True, "Evidence state/lock gate changed")

    refresh_request_path = require_artifact(Path(request["privateRefreshPlanRequestPath"]), "Refresh-plan request", REFRESH_REQUEST_SHA256)
    require(refresh_request_path == Path(evidence_request["privateFailedRefreshPlanRequestPath"]).resolve(strict=True), "Refresh-plan request path changed")
    refresh_request = REFRESH_EXECUTOR.validate_request(load_json(refresh_request_path, "Refresh-plan request"))
    require(refresh_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Refresh-plan account changed")
    refresh_output = require_private_directory(Path(request["privateRefreshPlanOutputDirectory"]), "Refresh-plan output")
    require(refresh_output == Path(refresh_request["privateRefreshPlanOutputDirectory"]).resolve(strict=True), "Refresh-plan output path changed")
    binary = require_artifact(refresh_output / "bootstrap-refresh-only.tfplan", "Saved refresh-only plan", BINARY_PLAN_SHA256)
    plan_json_path = require_artifact(refresh_output / "terraform-show-refresh-only-json.stdout", "Refresh-plan JSON", PLAN_JSON_SHA256)
    require_artifact(refresh_output / "terraform-show-refresh-only-text.stdout", "Refresh-plan text", PLAN_TEXT_SHA256)
    refresh_stderr = require_private_file(refresh_output / "terraform-plan-refresh-only.stderr", "Refresh-plan stderr")
    require(refresh_stderr.read_bytes() == b"", "Refresh-plan stderr changed")
    plan = load_json(plan_json_path, "Refresh-plan JSON")
    require(plan.get("applyable") is True, "Saved refresh-only plan is not applyable")
    REFRESH_EXECUTOR.validate_reviewed_drift(plan, refresh_only=True)

    proof_request_path = require_private_file(Path(refresh_request["privateFailedProofRequestPath"]), "Failed proof request")
    require(file_sha256(proof_request_path) == REFRESH_EXECUTOR.PROOF_REQUEST_SHA256, "Failed proof request changed")
    proof_request = PROOF_EXECUTOR.validate_request(load_json(proof_request_path, "Failed proof request"))
    identity_request_path = require_private_file(Path(proof_request["privateRecoveryRequestPath"]), "Identity recovery request")
    require(file_sha256(identity_request_path) == PROOF_EXECUTOR.RECOVERY_REQUEST_SHA256, "Identity recovery request changed")
    identity_request = RECOVERY_EXECUTOR.validate_request(load_json(identity_request_path, "Identity recovery request"))
    migration_request_path = require_private_file(Path(identity_request["privateMigrationRequestPath"]), "Migration request")
    require(file_sha256(migration_request_path) == RECOVERY_EXECUTOR.MIGRATION_REQUEST_SHA256, "Migration request changed")
    migration_request = MIGRATION_EXECUTOR.validate_request(load_json(migration_request_path, "Migration request"))
    preflight_request_path = require_private_file(Path(migration_request["privatePreflightRequestPath"]), "Preflight request")
    require(file_sha256(preflight_request_path) == MIGRATION_EXECUTOR.EXPECTED_PREFLIGHT_REQUEST_SHA256, "Preflight request changed")
    preflight_request = PREFLIGHT_EXECUTOR.validate_request(load_json(preflight_request_path, "Preflight request"))
    preflight_output = require_private_directory(Path(migration_request["privatePreflightOutputDirectory"]), "Preflight output")
    working = require_private_directory(preflight_output / "migration-source", "Migration source")
    source_manifest = load_json(preflight_output / "migration-source-manifest.json", "Migration source manifest")
    require(PLAN_EXECUTOR.source_manifest(working) == source_manifest, "Staged source changed")
    require(PLAN_EXECUTOR.source_manifest(repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE) == source_manifest, "Repository source changed")
    migration_output = require_private_directory(Path(identity_request["privateMigrationOutputDirectory"]), "Migration output")
    terraform_data = require_private_directory(migration_output / "terraform-data", "Migrated Terraform data")
    plan_request_path = require_private_file(Path(preflight_request["privatePlanRequestPath"]), "Original plan request")
    require(file_sha256(plan_request_path) == preflight_request["privatePlanRequestSha256"], "Original plan request changed")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Original plan request"))

    before_state_path = require_artifact(evidence_output / "terraform-state-pull.stdout", "Recovered canonical state", REMOTE_STATE_SHA256)
    before_state = load_json(before_state_path, "Recovered canonical state")
    managed, data = RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(before_state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES and data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES and len(data) == 9, "Canonical state addresses changed")
    identities = APPLY_EXECUTOR.validate_outputs(before_state.get("outputs"), plan_request)
    backend = require_private_file(Path(preflight_request["privateBackendConfigPath"]), "Backend config")
    backend_values = PREFLIGHT_EXECUTOR.parse_backend_config(backend)
    require(backend_values == {"bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION, "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True}, "Backend config changed")
    head_path = require_artifact(evidence_output / "s3-state-head.stdout", "Recovered state head", request["recoveryStateHeadSha256"])
    history_path = require_artifact(evidence_output / "s3-object-versions.stdout", "Recovered object history", request["recoveryObjectVersionsSha256"])
    state_version_id = PROOF_EXECUTOR.validate_state_head(load_json(head_path, "Recovered state head"), identities)
    history = load_json(history_path, "Recovered object history")
    state_key = backend_values["key"]
    lock_key = state_key + ".tflock"
    state_versions, state_markers = PROOF_EXECUTOR.exact_history(history, state_key)
    lock_versions, lock_markers = PROOF_EXECUTOR.exact_history(history, lock_key)
    require(len(state_versions) == 1 and state_versions[0].get("VersionId") == state_version_id and state_versions[0].get("IsLatest") is True and state_markers == [], "Recovered state history changed")
    output = require_new_private_directory(Path(request["privateApplyOutputDirectory"]), "Private reconciliation output")
    require(not is_within(output, repository_root), "Reconciliation output must remain outside repository")
    return {
        "request": request, "request_path": private_request, "output": output,
        "refresh_output": refresh_output, "binary": binary, "plan": plan,
        "working": working, "terraform_data": terraform_data, "plan_request": plan_request,
        "before_state": before_state, "managed": managed, "data": data,
        "identities": identities, "backend_values": backend_values,
        "state_versions_before": state_versions, "state_markers_before": state_markers,
        "lock_versions_before": lock_versions, "lock_markers_before": lock_markers,
        "remaining": remaining,
    }


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION") == CONFIRMATION, f"Set CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION={CONFIRMATION}")
    forbidden = (
        "CONFIRM_REFRESH_PLAN_EVIDENCE_RECOVERY", "CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN",
        "CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF", "CONFIRM_STATE_BOOTSTRAP_PLAN",
        "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT", "CONFIRM_STATE_BOOTSTRAP_MIGRATION",
        "CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "All prior, unsaved apply, destroy and state-push confirmations must be unset")
    output = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = PROOF_EXECUTOR.safe_environment(context["plan_request"], context["terraform_data"])
    record = PROOF_EXECUTOR.run_recorded
    identity_result = record(output, "aws-identity", ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"], environment, 90, runner, repository_root)
    identity = PROOF_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")
    prefix = ["terraform", f"-chdir={context['working']}"]
    pull_before = record(output, "terraform-state-pull-before", [*prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull_before.returncode == 0 and hashlib.sha256(pull_before.stdout).hexdigest() == REMOTE_STATE_SHA256, "Canonical state bytes changed before apply")
    list_before = record(output, "terraform-state-list-before", [*prefix, "state", "list"], environment, 180, runner, repository_root)
    require(list_before.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(list_before.stdout) == context["managed"] | context["data"], "State address inventory changed before apply")
    bucket = context["identities"]["bucket"]
    state_key = context["backend_values"]["key"]
    lock_key = state_key + ".tflock"
    head_before_result = record(output, "s3-state-head-before", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", state_key, "--output", "json"], environment, 120, runner, repository_root)
    state_version_before = PROOF_EXECUTOR.validate_state_head(PROOF_EXECUTOR.parse_json_result(head_before_result, "State head before apply"), context["identities"])
    versions_before_result = record(output, "s3-object-versions-before", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions_before = PROOF_EXECUTOR.parse_json_result(versions_before_result, "Object versions before apply")
    state_versions_before, state_markers_before = PROOF_EXECUTOR.exact_history(versions_before, state_key)
    lock_versions_before, lock_markers_before = PROOF_EXECUTOR.exact_history(versions_before, lock_key)
    require(state_versions_before == context["state_versions_before"] and state_markers_before == context["state_markers_before"], "State history changed before apply")
    require(lock_versions_before == context["lock_versions_before"] and lock_markers_before == context["lock_markers_before"], "Lock history changed before apply")
    require(state_versions_before[0].get("VersionId") == state_version_before, "Current state version changed before apply")
    lock_before = record(output, "s3-lock-head-before", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(PROOF_EXECUTOR.is_not_found(lock_before), "Lock object exists before apply")

    apply_result = record(output, "terraform-apply-reviewed-refresh-only-plan", [*prefix, "apply", "-input=false", "-lock=true", "-lock-timeout=60s", "-no-color", str(context["binary"])], environment, 600, runner, repository_root)
    require(apply_result.returncode == 0, "Exact saved refresh-only plan apply failed")
    require(apply_result.stderr == b"", "Exact saved refresh-only plan apply emitted stderr")
    require(b"Apply complete! Resources: 0 added, 0 changed, 0 destroyed." in apply_result.stdout, "Apply completion summary changed")

    pull_after = record(output, "terraform-state-pull-after", [*prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull_after.returncode == 0, "State pull failed after apply")
    after_state = json.loads(pull_after.stdout)
    before_state = context["before_state"]
    require(after_state.get("version") == before_state.get("version") == 4 and after_state.get("terraform_version") == "1.14.5", "State format changed")
    require(after_state.get("lineage") == before_state.get("lineage"), "State lineage changed")
    require(after_state.get("serial") == before_state.get("serial") + 1, "State serial did not advance exactly once")
    managed_after, data_after = RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(after_state)
    require(managed_after == context["managed"] and data_after == context["data"], "State address inventory changed after apply")
    list_after = record(output, "terraform-state-list-after", [*prefix, "state", "list"], environment, 180, runner, repository_root)
    require(list_after.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(list_after.stdout) == managed_after | data_after, "State list changed after apply")
    show_after = record(output, "terraform-show-state-after", [*prefix, "show", "-json"], environment, 180, runner, repository_root)
    state_show = PROOF_EXECUTOR.parse_json_result(show_after, "State JSON after apply")
    require(state_show.get("values") == context["plan"].get("planned_values"), "Persisted state values do not equal the reviewed refresh-only plan")

    head_after_result = record(output, "s3-state-head-after", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", state_key, "--output", "json"], environment, 120, runner, repository_root)
    state_version_after = PROOF_EXECUTOR.validate_state_head(PROOF_EXECUTOR.parse_json_result(head_after_result, "State head after apply"), context["identities"])
    require(state_version_after != state_version_before, "State object version did not advance")
    versions_after_result = record(output, "s3-object-versions-after", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions_after = PROOF_EXECUTOR.parse_json_result(versions_after_result, "Object versions after apply")
    state_versions_after, state_markers_after = PROOF_EXECUTOR.exact_history(versions_after, state_key)
    lock_versions_after, lock_markers_after = PROOF_EXECUTOR.exact_history(versions_after, lock_key)
    require(len(state_versions_after) - len(state_versions_before) == 1 and state_markers_after == state_markers_before, "State object history delta changed")
    require(state_versions_after[0].get("VersionId") == state_version_after and state_versions_after[0].get("IsLatest") is True, "New state object version is not current")
    require(len(lock_versions_after) - len(lock_versions_before) == 1, "Apply lock version delta changed")
    require(len(lock_markers_after) - len(lock_markers_before) == 1, "Apply lock delete-marker delta changed")
    lock_after = record(output, "s3-lock-head-after", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(PROOF_EXECUTOR.is_not_found(lock_after), "Lock object remains after apply")

    after_sha = hashlib.sha256(pull_after.stdout).hexdigest()
    evidence = {
        "schemaVersion": "v0.12.2.3.1.0.2-refresh-only-state-reconciliation-evidence-v1",
        "priorStateSha256": REMOTE_STATE_SHA256, "reconciledStateSha256": after_sha,
        "binaryRefreshPlanSha256": BINARY_PLAN_SHA256, "refreshPlanJsonSha256": PLAN_JSON_SHA256,
        "resourceDriftSha256": RESOURCE_DRIFT_SHA256, "priorSerial": before_state["serial"],
        "reconciledSerial": after_state["serial"], "lineageUnchanged": True,
        "plannedValuesExactlyPersisted": True, "managedAddressCount": len(managed_after),
        "dataAddressCount": len(data_after), "stateObjectVersionDelta": 1,
        "stateDeleteMarkerDelta": 0, "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
        "stateObjectVersionIds": [item.get("VersionId") for item in state_versions_after],
        "lockObjectVersionIds": [item.get("VersionId") for item in lock_versions_after],
        "lockObjectDeleteMarkerIds": [item.get("VersionId") for item in lock_markers_after],
    }
    evidence_path = output / "refresh-only-state-reconciliation-evidence.json"
    APPLY_EXECUTOR.write_private(evidence_path, canonical_json(evidence))
    result = {
        "schemaVersion": "v0.12.2.3.1.0.2-refresh-only-state-reconciliation-result-v1",
        "status": "bootstrap-refresh-only-state-reconciled-awaiting-post-reconciliation-review",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "private_apply_request_sha256": file_sha256(context["request_path"]),
        "evidence_recovery_request_sha256": EVIDENCE_REQUEST_SHA256,
        "evidence_recovery_result_sha256": EVIDENCE_RESULT_SHA256,
        "binary_refresh_plan_sha256": BINARY_PLAN_SHA256,
        "refresh_plan_json_sha256": PLAN_JSON_SHA256,
        "resource_drift_sha256": RESOURCE_DRIFT_SHA256,
        "prior_state_sha256": REMOTE_STATE_SHA256, "reconciled_state_sha256": after_sha,
        "reconciliation_evidence_sha256": file_sha256(evidence_path),
        "prior_serial": before_state["serial"], "reconciled_serial": after_state["serial"],
        "state_lineage_unchanged": True, "planned_values_exactly_persisted": True,
        "managed_state_address_count": len(managed_after), "data_state_address_count": len(data_after),
        "remote_resource_action_count": 0, "state_object_version_delta": 1,
        "state_delete_marker_delta": 0, "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1, "lock_object_absent": True,
        "terraform_init_executed": False, "terraform_plan_executed": False,
        "exact_saved_refresh_plan_applied_once": True, "unsaved_apply_executed": False,
        "state_push_executed": False, "destroy_executed": False,
        "iam_policy_attachment_executed": False, "direct_s3_mutation_executed": False,
        "force_unlock_executed": False, "automatic_retry_performed": False,
        "automatic_rollback_performed": False, "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "human-review-state-reconciliation-before-new-zero-change-proof",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "refresh-only-state-reconciliation-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["reconciliation_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "refresh-only-state-reconciliation-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "evidence_control_plane_commit": EVIDENCE_CONTROL_PLANE_COMMIT,
        "private_apply_request_sha256": file_sha256(context["request_path"]),
        "evidence_recovery_request_sha256": EVIDENCE_REQUEST_SHA256,
        "evidence_recovery_result_sha256": EVIDENCE_RESULT_SHA256,
        "binary_refresh_plan_sha256": BINARY_PLAN_SHA256,
        "refresh_plan_json_sha256": PLAN_JSON_SHA256,
        "resource_drift_sha256": RESOURCE_DRIFT_SHA256,
        "canonical_remote_state_sha256": REMOTE_STATE_SHA256,
        "resource_drift_count": 7, "resource_change_count": 0, "output_change_count": 7,
        "managed_state_address_count": len(context["managed"]), "data_state_address_count": len(context["data"]),
        "human_review_verified": True, "remaining_apply_approval_seconds": context["remaining"],
        "apply_execution_authorized": False, "terraform_plan_authorized": False,
        "unsaved_apply_authorized": False, "state_push_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-saved-refresh-plan-apply-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-apply-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_apply_request)) if args.phase == "verify" else execute(args.private_apply_request)
    except (APPLY_EXECUTOR.CommandFailure, PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"Refresh-only state reconciliation stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

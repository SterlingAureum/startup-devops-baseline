#!/usr/bin/env python3
"""Resume the reviewed refresh-only reconciliation after one exact state-pull normalization."""

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
BASE_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py"
CONFIRMATION = "apply-exact-reviewed-refresh-only-plan-after-validated-check-results-normalization"
INCIDENT_CONTROL_PLANE_COMMIT = "ab126f6bf7bff021b8821c0e0951d739c635aa49"
FAILED_APPLY_REQUEST_SHA256 = "a58ea364097505b798771eae726c147e906cd365fa7d9c6c4525c30bec31274f"
FAILED_IDENTITY_STDOUT_SHA256 = "972b1b4b008369972374b6a8bdeded41cf2df5347e0b0cea93e5c8777518d6be"
NORMALIZED_STATE_SHA256 = "5ff0cb562fa7bf6d99cd2068c373646fca50f06cbaa08f3f5a3e3392bf2c55e1"
NORMALIZED_STATE_SIZE = 69929
NORMALIZED_CHECK_RESULTS_SHA256 = "5edcc426d374ea432c4c8509b9a7e3060908f8b2bdaf754255934e05792134a8"
SEMANTIC_PROJECTION_SHA256 = "1d21a9edbfe82d1d1496b312c8a31996c20f9f4bf8505604a277cbdede2f8d15"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load_module(BASE_PATH, "reviewed_refresh_only_state_reconciliation")
GitRunner = Callable[[list[str]], str]
CommandRunner = BASE.CommandRunner


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "privateFailedApplyRequestPath", "privateFailedApplyRequestSha256",
        "privateFailedApplyOutputDirectory", "failedIdentityStdoutSha256", "failedStatePullSha256",
        "failedStatePullSize", "normalizedCheckResultsSha256", "semanticProjectionSha256",
        "privateApplyOutputDirectory", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Normalization-repair request fields changed")
    require(value["schemaVersion"] == "v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-request-v1", "Normalization-repair request schema changed")
    require(value["operation"] == CONFIRMATION, "Normalization-repair operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    for key in ("privateFailedApplyRequestPath", "privateFailedApplyOutputDirectory", "privateApplyOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    exact = {
        "privateFailedApplyRequestSha256": FAILED_APPLY_REQUEST_SHA256,
        "failedIdentityStdoutSha256": FAILED_IDENTITY_STDOUT_SHA256,
        "failedStatePullSha256": NORMALIZED_STATE_SHA256,
        "failedStatePullSize": NORMALIZED_STATE_SIZE,
        "normalizedCheckResultsSha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "semanticProjectionSha256": SEMANTIC_PROJECTION_SHA256,
    }
    require(all(value[key] == expected for key, expected in exact.items()), "Observed normalization evidence changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = BASE.utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = BASE.utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=BASE.MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsIdentityAndS3Read": True, "terraformStatePullAndList": True,
        "exactSavedRefreshPlanApply": True, "acceptExactCheckResultsNormalization": True,
        "terraformInit": False, "terraformPlan": False, "unsavedApply": False,
        "statePush": False, "destroy": False, "iamPolicyAttachment": False,
        "directS3Mutation": False, "forceUnlock": False,
        "automaticRetry": False, "automaticRollback": False,
    }, "Normalization-repair execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def historical_git(arguments: list[str]) -> str:
    if arguments == ["branch", "--show-current"]:
        return "main"
    if arguments == ["status", "--porcelain"]:
        return ""
    if arguments in (["rev-parse", "HEAD"], ["rev-parse", "origin/main"]):
        return INCIDENT_CONTROL_PLANE_COMMIT
    raise ValueError("Unexpected historical Git check")


def exact_failed_artifact(path: Path, label: str, digest: str, size: int | None = None) -> Path:
    artifact = BASE.require_artifact(path, label, digest)
    if size is not None:
        require(artifact.stat().st_size == size, f"{label} size changed")
    return artifact


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = BASE.require_private_file(request_path, "Private normalization-repair request")
    require(not BASE.is_within(private_request, repository_root), "Normalization-repair request must remain outside repository")
    request = validate_request(BASE.load_json(private_request, "Private normalization-repair request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = BASE.utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = BASE.utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Normalization-repair approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= BASE.MINIMUM_REMAINING_SECONDS, "Normalization-repair approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Normalization repair must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Normalization repair requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    failed_request_path = exact_failed_artifact(
        Path(request["privateFailedApplyRequestPath"]),
        "Failed reconciliation request",
        FAILED_APPLY_REQUEST_SHA256,
    )
    failed_request = BASE.validate_request(BASE.load_json(failed_request_path, "Failed reconciliation request"))
    require(failed_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT, "Incident control plane changed")
    require(failed_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Incident AWS account changed")
    historical_start = BASE.utc_timestamp(failed_request["approval"]["notBeforeUtc"], "Historical approval start")
    historical_expiry = BASE.utc_timestamp(failed_request["approval"]["expiresAtUtc"], "Historical approval expiry")
    historical_now = historical_start + (historical_expiry - historical_start) / 2
    context = BASE.verify_inputs(
        failed_request_path,
        repository_root=repository_root,
        git_runner=historical_git,
        now=historical_now,
        allow_existing_output=True,
    )
    failed_output = BASE.require_private_directory(Path(request["privateFailedApplyOutputDirectory"]), "Failed reconciliation output")
    require(failed_output == context["output"], "Failed reconciliation output path changed")
    require({item.name for item in failed_output.iterdir()} == {
        "aws-identity.stdout", "aws-identity.stderr",
        "terraform-state-pull-before.stdout", "terraform-state-pull-before.stderr",
    }, "Failed reconciliation artifact inventory changed")
    exact_failed_artifact(failed_output / "aws-identity.stdout", "Failed identity stdout", FAILED_IDENTITY_STDOUT_SHA256, 197)
    require(exact_failed_artifact(failed_output / "aws-identity.stderr", "Failed identity stderr", hashlib.sha256(b"").hexdigest(), 0).read_bytes() == b"", "Failed identity stderr changed")
    normalized_path = exact_failed_artifact(failed_output / "terraform-state-pull-before.stdout", "Failed state pull stdout", NORMALIZED_STATE_SHA256, NORMALIZED_STATE_SIZE)
    require(exact_failed_artifact(failed_output / "terraform-state-pull-before.stderr", "Failed state pull stderr", hashlib.sha256(b"").hexdigest(), 0).read_bytes() == b"", "Failed state pull stderr changed")
    normalized_state = BASE.validate_check_results_normalization(
        context["before_state"],
        normalized_path.read_bytes(),
        observed_state_sha256=NORMALIZED_STATE_SHA256,
        observed_check_results_sha256=NORMALIZED_CHECK_RESULTS_SHA256,
        semantic_projection_sha256=SEMANTIC_PROJECTION_SHA256,
    )
    managed, data = BASE.RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(normalized_state)
    require(managed == context["managed"] and data == context["data"], "Normalized state address inventory changed")
    new_output = BASE.require_new_private_directory(Path(request["privateApplyOutputDirectory"]), "Private normalization-repair output")
    require(not BASE.is_within(new_output, repository_root), "Normalization-repair output must remain outside repository")
    context.update({
        "request": request,
        "request_path": private_request,
        "output": new_output,
        "reviewed_before_state": context["before_state"],
        "before_state": normalized_state,
        "managed": managed,
        "data": data,
        "pre_apply_state_sha256": NORMALIZED_STATE_SHA256,
        "check_results_normalization": {
            "check_results_sha256": NORMALIZED_CHECK_RESULTS_SHA256,
            "semantic_projection_sha256": SEMANTIC_PROJECTION_SHA256,
        },
        "remaining": remaining,
        "evidence_schema": "v0.12.2.3.1.0.2.0.1-state-pull-normalization-reconciliation-evidence-v1",
        "result_schema": "v0.12.2.3.1.0.2.0.1-state-pull-normalization-reconciliation-result-v1",
        "result_status": "bootstrap-refresh-only-state-reconciled-after-validated-check-results-normalization",
        "evidence_filename": "state-pull-normalization-reconciliation-evidence.json",
        "result_filename": "state-pull-normalization-reconciliation-result.json",
        "next_action": "human-review-state-reconciliation-before-new-zero-change-proof",
    })
    return context


def execute(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = BASE.run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION_NORMALIZATION") == CONFIRMATION, f"Set CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION_NORMALIZATION={CONFIRMATION}")
    forbidden = (
        "CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION", "CONFIRM_REFRESH_PLAN_EVIDENCE_RECOVERY",
        "CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN", "CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF",
        "CONFIRM_STATE_BOOTSTRAP_PLAN", "CONFIRM_STATE_BOOTSTRAP_APPLY",
        "CONFIRM_STATE_BOOTSTRAP_RECOVERY", "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION", "CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY",
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "All prior, unsaved apply, destroy and state-push confirmations must be unset")
    return BASE.execute_verified(context, repository_root=repository_root, runner=runner, current=current)


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "state-pull-check-results-normalization-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_failed_apply_request_sha256": FAILED_APPLY_REQUEST_SHA256,
        "private_normalization_repair_request_sha256": BASE.file_sha256(context["request_path"]),
        "reviewed_canonical_state_sha256": BASE.REMOTE_STATE_SHA256,
        "normalized_pre_apply_state_sha256": NORMALIZED_STATE_SHA256,
        "normalized_check_results_sha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "semantic_projection_sha256": SEMANTIC_PROJECTION_SHA256,
        "managed_state_address_count": len(context["managed"]),
        "data_state_address_count": len(context["data"]),
        "prior_apply_executed": False,
        "normalization_exactly_validated": True,
        "apply_execution_authorized": False,
        "terraform_plan_authorized": False,
        "unsaved_apply_authorized": False,
        "state_push_authorized": False,
        "remaining_apply_approval_seconds": context["remaining"],
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-exact-saved-refresh-plan-apply-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-repair-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_repair_request)) if args.phase == "verify" else execute(args.private_repair_request)
    except (BASE.APPLY_EXECUTOR.CommandFailure, BASE.PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"State-pull normalization reconciliation stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

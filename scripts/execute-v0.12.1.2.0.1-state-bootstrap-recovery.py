#!/usr/bin/env python3
"""Verify or execute read-only recovery after the reviewed state-bootstrap apply."""

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
APPLY_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.1.2-state-bootstrap-apply.py"
RECOVERY_CONFIRMATION = "complete-read-only-state-bootstrap-post-apply-validation"
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


APPLY_EXECUTOR = load_module(APPLY_EXECUTOR_PATH, "state_bootstrap_apply_executor_v01212_recovery")
PLAN_EXECUTOR = APPLY_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = APPLY_EXECUTOR.PLAN_GATE

GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[
    [list[str], dict[str, str], int, Path],
    subprocess.CompletedProcess[bytes],
]


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
    parent = require_private_directory(path.parent, f"{label} parent")
    return parent / path.name


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "operation",
        "repository",
        "trustedRef",
        "expectedRecoveryMainCommit",
        "incidentControlPlaneCommit",
        "expectedAwsAccountId",
        "privateApplyRequestPath",
        "privateApplyRequestSha256",
        "privatePlanBundleDirectory",
        "planRecordSha256",
        "binaryPlanSha256",
        "privateFailedApplyOutputDirectory",
        "failedKmsRotationStderrSha256",
        "appliedStateSha256",
        "privateRecoveryOutputDirectory",
        "approval",
        "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(
        value["schemaVersion"] == "v0.12.1.2.0.1-state-bootstrap-recovery-request-v1",
        "Recovery request schema changed",
    )
    require(value["operation"] == RECOVERY_CONFIRMATION, "Recovery request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    for key in ("expectedRecoveryMainCommit", "incidentControlPlaneCommit"):
        require(
            isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{40}", value[key]) is not None,
            f"Invalid commit: {key}",
        )
    require(
        isinstance(value["expectedAwsAccountId"], str)
        and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None,
        "Expected AWS account ID is invalid",
    )
    for key in (
        "privateApplyRequestSha256",
        "planRecordSha256",
        "binaryPlanSha256",
        "failedKmsRotationStderrSha256",
        "appliedStateSha256",
    ):
        require(
            isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None,
            f"Invalid SHA-256: {key}",
        )
    for key in (
        "privateApplyRequestPath",
        "privatePlanBundleDirectory",
        "privateFailedApplyOutputDirectory",
        "privateRecoveryOutputDirectory",
    ):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    approval = value["approval"]
    require(
        isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"},
        "Recovery approval fields changed",
    )
    start = utc_timestamp(approval["notBeforeUtc"], "Recovery approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Recovery approval expiry")
    require(expiry > start, "Recovery approval expiry must follow its start")
    require(expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Recovery window exceeds one hour")
    require(
        value["executionBoundary"]
        == {
            "terraformApply": False,
            "terraformPlan": False,
            "terraformInit": False,
            "stateMigration": False,
            "destroy": False,
            "awsReadOnlyLiveValidation": True,
        },
        "Recovery execution boundary changed",
    )
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("Git identity check failed")
    return result.stdout.strip()


def run_command(
    arguments: list[str],
    environment: dict[str, str],
    timeout: int,
    cwd: Path,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def state_addresses(state: Any) -> tuple[set[str], set[str]]:
    require(isinstance(state, dict) and state.get("version") == 4, "Applied state must use version 4")
    resources = state.get("resources")
    require(isinstance(resources, list), "Applied state resources are invalid")
    managed: set[str] = set()
    data: set[str] = set()
    for resource in resources:
        require(isinstance(resource, dict), "Applied state resource is invalid")
        mode = resource.get("mode", "managed")
        require(mode in {"managed", "data"}, "Applied state resource mode is invalid")
        resource_type = resource.get("type")
        name = resource.get("name")
        module = resource.get("module")
        instances = resource.get("instances")
        require(isinstance(resource_type, str) and resource_type, "Applied state resource type is invalid")
        require(isinstance(name, str) and name, "Applied state resource name is invalid")
        require(module is None or isinstance(module, str), "Applied state module is invalid")
        require(isinstance(instances, list) and instances, "Applied state instances are invalid")
        prefix = f"{module}." if module else ""
        if mode == "data":
            prefix += "data."
        base = f"{prefix}{resource_type}.{name}"
        destination = managed if mode == "managed" else data
        for instance in instances:
            require(isinstance(instance, dict), "Applied state instance is invalid")
            if "index_key" not in instance:
                destination.add(base)
                continue
            key = instance["index_key"]
            if isinstance(key, str):
                destination.add(f"{base}[{json.dumps(key)}]")
            elif isinstance(key, int) and not isinstance(key, bool):
                destination.add(f"{base}[{key}]")
            else:
                raise ValueError("Applied state index key is invalid")
    return managed, data


def require_plan_bundle(
    bundle: Path,
    apply_request: dict[str, Any],
    plan_request: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    require(file_sha256(bundle / "plan-record.json") == apply_request["planRecordSha256"], "Plan record changed")
    record = load_json(bundle / "plan-record.json", "Plan record")
    require(record.get("controlPlaneCommit") == apply_request["expectedMainCommit"], "Plan main changed")
    require(record.get("privateRequestSha256") == apply_request["privatePlanRequestSha256"], "Plan request changed")
    require(record.get("managedCreateCount") == 13, "Managed create count changed")
    require(record.get("terraformPlanExecuted") is True, "Plan was not executed")
    require(record.get("terraformApplyExecuted") is False, "Plan record already reports apply")
    for field, name in APPLY_EXECUTOR.PLAN_ARTIFACTS.items():
        digest = file_sha256(bundle / name)
        require(apply_request[field] == digest, f"Apply request artifact changed: {name}")
        if field != "terraformVersionJsonSha256":
            require(record.get(field) == digest, f"Plan record artifact changed: {name}")
    expected = plan_request["expectedInputs"]
    plan_document = load_json(bundle / "terraform-plan.json", "Terraform plan JSON")
    gate = PLAN_GATE.validate(
        plan_document,
        expected_bucket_name=expected["stateBucketName"],
        expected_kms_alias=expected["stateKmsAlias"],
        expected_additional_tags=expected["additionalTags"],
    )
    require(gate == load_json(bundle / "plan-gate.json", "Plan gate"), "Plan gate changed")
    require(gate["managed_create_count"] == 13, "Plan no longer contains 13 creates")
    return record, gate


def error_code(stderr: bytes) -> str:
    text = stderr.decode(errors="replace")
    match = re.search(r"An error occurred \(([^)]+)\)", text)
    require(match is not None, "KMS rotation failure code is missing")
    return match.group(1)


def verify_inputs(
    private_recovery_request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    request_path = require_private_file(private_recovery_request_path, "Private recovery request")
    require(not is_within(request_path, repository_root), "Recovery request must remain outside the repository")
    request = validate_request(load_json(request_path, "Private recovery request"))

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Recovery approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Recovery approval expiry")
    require(start <= current < expiry, "Recovery approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Recovery approval has less than 15 minutes remaining")

    expected_main = request["expectedRecoveryMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Recovery must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Recovery requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_main
        and git_runner(["rev-parse", "origin/main"]) == expected_main,
        "HEAD and origin/main must equal the reviewed recovery commit",
    )

    apply_path = require_private_file(Path(request["privateApplyRequestPath"]), "Private apply request")
    require(not is_within(apply_path, repository_root), "Apply request must remain outside the repository")
    require(file_sha256(apply_path) == request["privateApplyRequestSha256"], "Apply request changed")
    apply_request = APPLY_EXECUTOR.validate_apply_request(load_json(apply_path, "Private apply request"))
    require(apply_request["expectedMainCommit"] == request["incidentControlPlaneCommit"], "Incident main changed")
    require(apply_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Incident account changed")
    require(apply_request["planRecordSha256"] == request["planRecordSha256"], "Plan record binding changed")
    require(apply_request["binaryPlanSha256"] == request["binaryPlanSha256"], "Binary plan binding changed")

    plan_request_path = require_private_file(Path(apply_request["privatePlanRequestPath"]), "Private plan request")
    require(file_sha256(plan_request_path) == apply_request["privatePlanRequestSha256"], "Plan request changed")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Private plan request"))
    require(plan_request["expectedMainCommit"] == request["incidentControlPlaneCommit"], "Plan incident main changed")
    require(plan_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Plan account changed")

    bundle = require_private_directory(Path(request["privatePlanBundleDirectory"]), "Private plan bundle")
    require(bundle == Path(apply_request["privatePlanBundleDirectory"]).resolve(strict=True), "Plan bundle changed")
    require(bundle == Path(plan_request["privateOutputDirectory"]).resolve(strict=True), "Plan output changed")
    record, gate = require_plan_bundle(bundle, apply_request, plan_request)
    source_manifest = load_json(bundle / "source-manifest.json", "Source manifest")
    source = bundle / "source"
    require(source.is_dir() and not source.is_symlink(), "Staged Terraform source is invalid")
    require(source_manifest == PLAN_EXECUTOR.source_manifest(source), "Staged Terraform source changed")
    require(
        source_manifest == PLAN_EXECUTOR.source_manifest(repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE),
        "Repository Terraform source changed after the incident",
    )

    failed_output = require_private_directory(
        Path(request["privateFailedApplyOutputDirectory"]),
        "Private failed-apply output",
    )
    require(
        failed_output == Path(apply_request["privateApplyOutputDirectory"]).resolve(strict=True),
        "Failed-apply output changed",
    )
    recovery_output = require_new_private_directory(
        Path(request["privateRecoveryOutputDirectory"]),
        "Private recovery output",
    )
    require(not is_within(recovery_output, repository_root), "Recovery output must remain outside the repository")

    state_copy = require_private_file(failed_output / "state-bootstrap.tfstate.applied", "Applied state copy")
    working_state = source / "terraform.tfstate"
    require(working_state.is_file() and not working_state.is_symlink(), "Working applied state is missing")
    require(stat.S_IMODE(working_state.stat().st_mode) == 0o600, "Working applied state mode must be 0600")
    require(file_sha256(state_copy) == request["appliedStateSha256"], "Applied state copy changed")
    require(file_sha256(working_state) == request["appliedStateSha256"], "Working applied state changed")
    state = load_json(state_copy, "Applied state")
    managed, data = state_addresses(state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES, "Applied managed state inventory changed")
    require(data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES, "Applied state contains unreviewed data addresses")
    identities = APPLY_EXECUTOR.validate_outputs(state.get("outputs"), plan_request)

    captured_outputs_path = require_private_file(failed_output / "terraform-output.stdout", "Captured Terraform output")
    captured_identities = APPLY_EXECUTOR.validate_outputs(
        load_json(captured_outputs_path, "Captured Terraform output"),
        plan_request,
    )
    require(captured_identities == identities, "Captured Terraform output differs from applied state")
    require_private_file(failed_output / "terraform-apply.stdout", "Captured Terraform apply stdout")
    require_private_file(failed_output / "terraform-apply.stderr", "Captured Terraform apply stderr")
    require_private_file(failed_output / "terraform-state-list.stdout", "Captured Terraform state list")

    kms_stderr = require_private_file(failed_output / "kms-rotation.stderr", "KMS rotation stderr")
    kms_stdout = require_private_file(failed_output / "kms-rotation.stdout", "KMS rotation stdout")
    require(file_sha256(kms_stderr) == request["failedKmsRotationStderrSha256"], "KMS failure evidence changed")
    require(kms_stdout.read_bytes() == b"", "Failed KMS rotation stdout must be empty")
    require(error_code(kms_stderr.read_bytes()) == "InvalidArnException", "Unexpected recovery incident reason")
    require(not (failed_output / "live-validation.json").exists(), "Prior live validation unexpectedly completed")
    require(not (failed_output / "apply-result.json").exists(), "Prior apply result unexpectedly completed")

    return {
        "request": request,
        "request_path": request_path,
        "apply_request": apply_request,
        "apply_request_path": apply_path,
        "plan_request": plan_request,
        "bundle": bundle,
        "failed_output": failed_output,
        "recovery_output": recovery_output,
        "state_copy": state_copy,
        "identities": identities,
        "record": record,
        "gate": gate,
        "remaining": remaining,
    }


def safe_environment(plan_request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    environment = APPLY_EXECUTOR.safe_environment(plan_request, terraform_data)
    for key in list(environment):
        if key.startswith("TF_CLI_ARGS") or key.startswith("TF_VAR_") or key.startswith("CONFIRM_"):
            del environment[key]
    return environment


def execute(
    private_recovery_request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    context = verify_inputs(
        private_recovery_request_path,
        repository_root=repository_root,
        git_runner=git_runner,
        now=now,
    )
    require(
        os.environ.get("CONFIRM_STATE_BOOTSTRAP_RECOVERY") == RECOVERY_CONFIRMATION,
        f"Set CONFIRM_STATE_BOOTSTRAP_RECOVERY={RECOVERY_CONFIRMATION}",
    )
    for forbidden in (
        "CONFIRM_STATE_BOOTSTRAP_PLAN",
        "CONFIRM_STATE_BOOTSTRAP_APPLY",
        "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY",
        "CONFIRM_STATE_MIGRATION",
    ):
        require(not os.environ.get(forbidden), "Plan, apply, destroy and migration confirmations must be unset")

    output = context["recovery_output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = safe_environment(context["plan_request"], context["failed_output"] / "terraform-data")

    identity_result = APPLY_EXECUTOR.run_logged(
        output,
        "aws-identity",
        ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"],
        environment,
        90,
        runner,
        repository_root,
    )
    identity = APPLY_EXECUTOR.parse_json_result(identity_result, "AWS identity")
    require(identity.get("Account") == context["request"]["expectedAwsAccountId"], "AWS account changed")

    live = APPLY_EXECUTOR.validate_live_foundation(
        output,
        context["identities"],
        environment,
        runner,
        repository_root,
    )
    live_path = output / "live-validation.json"
    APPLY_EXECUTOR.write_private(live_path, canonical_json(live))
    result = {
        "status": "state-backend-foundation-post-apply-recovered-and-live-validated",
        "recovery_control_plane_commit": context["request"]["expectedRecoveryMainCommit"],
        "incident_control_plane_commit": context["request"]["incidentControlPlaneCommit"],
        "prior_apply_request_sha256": context["request"]["privateApplyRequestSha256"],
        "plan_record_sha256": context["request"]["planRecordSha256"],
        "binary_plan_sha256": context["request"]["binaryPlanSha256"],
        "applied_state_sha256": context["request"]["appliedStateSha256"],
        "managed_state_address_count": len(PLAN_GATE.EXPECTED_MANAGED_ADDRESSES),
        "root_state_policy_count": live["root_state_policy_count"],
        "attached_root_state_policy_count": live["attached_root_state_policy_count"],
        "state_bucket_object_version_count": live["s3_object_version_count"],
        "prior_terraform_apply_succeeded": True,
        "terraform_apply_reexecuted": False,
        "terraform_plan_executed": False,
        "terraform_init_executed": False,
        "state_migration_executed": False,
        "iam_policy_attachment_executed": False,
        "destroy_executed": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "live_validation_sha256": file_sha256(live_path),
        "next_action": "record-redacted-v0.12.1.2.1-execution-evidence-before-v0.12.2",
    }
    result_path = output / "recovery-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["recovery_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "state-bootstrap-post-apply-recovery-inputs-verified",
        "recovery_control_plane_commit": context["request"]["expectedRecoveryMainCommit"],
        "incident_control_plane_commit": context["request"]["incidentControlPlaneCommit"],
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_apply_request_sha256": context["request"]["privateApplyRequestSha256"],
        "plan_record_sha256": context["request"]["planRecordSha256"],
        "binary_plan_sha256": context["request"]["binaryPlanSha256"],
        "applied_state_sha256": context["request"]["appliedStateSha256"],
        "managed_state_address_count": len(PLAN_GATE.EXPECTED_MANAGED_ADDRESSES),
        "prior_apply_evidence_verified": True,
        "remaining_recovery_approval_seconds": context["remaining"],
        "recovery_execution_authorized": False,
        "terraform_apply_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-read-only-state-bootstrap-recovery-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-recovery-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            result = redacted_verification(verify_inputs(args.private_recovery_request))
        else:
            result = execute(args.private_recovery_request)
    except (
        APPLY_EXECUTOR.CommandFailure,
        PLAN_EXECUTOR.CommandFailure,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as error:
        parser.exit(1, f"State-bootstrap post-apply recovery stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

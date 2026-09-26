#!/usr/bin/env python3
"""Recover the failed proof and produce an exact reviewed refresh-only plan."""

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
PROOF_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1-bootstrap-remote-state-proof.py"
CONFIRMATION = "produce-reviewed-bootstrap-refresh-only-plan"
INCIDENT_MAIN_COMMIT = "a80400593fce7cd40a90a0d5649f31d4e1d85d1a"
PROOF_REQUEST_SHA256 = "b9c6a1a5499e9aad31d0482981d5c97a783e5bcac0ec567a9e886a929f0b7730"
REMOTE_STATE_SHA256 = "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139"
BINARY_PLAN_SHA256 = "5dfe31147df6f7d6b02acb5631ab0f5a06552459286931b5b6e3804ac0940d8a"
PLAN_JSON_SHA256 = "51625bf05e06b4fee6260e2acb2a23765707f6dac045adb0661361fc97dd3bfc"
PLAN_TEXT_SHA256 = "f13fa1c59cb83003176963af0243b3b94ed2c419d81a47f11b76028513cad939"
RESOURCE_DRIFT_SHA256 = "cda2f5fefc620e11747c88e38db673e906fb7c4a29a5a5c886a5f7ec0140ab7a"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
AWS_REGION = "us-east-1"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900

EXPECTED_DRIFT_PATHS = {
    'aws_iam_policy.root_state_access["bootstrap"]': ("tags",),
    'aws_iam_policy.root_state_access["dev"]': ("tags",),
    'aws_iam_policy.root_state_access["prod"]': ("tags",),
    'aws_iam_policy.root_state_access["runtime-identities"]': ("tags",),
    'aws_iam_policy.root_state_access["test"]': ("tags",),
    "aws_kms_key.state": ("tags",),
    "aws_s3_bucket.state": (
        "policy",
        "server_side_encryption_configuration.[0].rule.[0].apply_server_side_encryption_by_default.[0].kms_master_key_id",
        "server_side_encryption_configuration.[0].rule.[0].apply_server_side_encryption_by_default.[0].sse_algorithm",
        "server_side_encryption_configuration.[0].rule.[0].bucket_key_enabled",
        "tags",
        "versioning.[0].enabled",
    ),
}
EXPECTED_REFRESH_OUTPUTS = {
    "backend_configuration",
    "root_state_access_policy_arns",
    "state_bucket_arn",
    "state_bucket_name",
    "state_keys",
    "state_kms_alias",
    "state_kms_key_arn",
}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROOF_EXECUTOR = load_module(PROOF_EXECUTOR_PATH, "remote_state_proof_for_refresh_recovery")
RECOVERY_EXECUTOR = PROOF_EXECUTOR.RECOVERY_EXECUTOR
MIGRATION_EXECUTOR = PROOF_EXECUTOR.MIGRATION_EXECUTOR
PREFLIGHT_EXECUTOR = PROOF_EXECUTOR.PREFLIGHT_EXECUTOR
APPLY_EXECUTOR = PROOF_EXECUTOR.APPLY_EXECUTOR
PLAN_EXECUTOR = PROOF_EXECUTOR.PLAN_EXECUTOR
PLAN_GATE = PROOF_EXECUTOR.PLAN_GATE

GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def compact_digest(value: Any) -> str:
    return hashlib.sha256((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()


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


def require_artifact(path: Path, label: str, expected_sha256: str, expected_size: int | None = None) -> Path:
    artifact = require_private_file(path, label)
    require(file_sha256(artifact) == expected_sha256, f"{label} digest changed")
    if expected_size is not None:
        require(artifact.stat().st_size == expected_size, f"{label} size changed")
    return artifact


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "privateFailedProofRequestPath", "privateFailedProofRequestSha256",
        "privateFailedProofOutputDirectory", "failedBinaryPlanSha256", "failedPlanJsonSha256",
        "failedPlanTextSha256", "resourceDriftSha256", "canonicalRemoteStateSha256",
        "privateRefreshPlanOutputDirectory", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Refresh-plan request fields changed")
    require(value["schemaVersion"] == "v0.12.2.3.1.0.1-bootstrap-refresh-only-plan-request-v1", "Refresh-plan request schema changed")
    require(value["operation"] == CONFIRMATION, "Refresh-plan operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None, "Expected account is invalid")
    for key in ("privateFailedProofRequestPath", "privateFailedProofOutputDirectory", "privateRefreshPlanOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    expected = {
        "privateFailedProofRequestSha256": PROOF_REQUEST_SHA256,
        "failedBinaryPlanSha256": BINARY_PLAN_SHA256,
        "failedPlanJsonSha256": PLAN_JSON_SHA256,
        "failedPlanTextSha256": PLAN_TEXT_SHA256,
        "resourceDriftSha256": RESOURCE_DRIFT_SHA256,
        "canonicalRemoteStateSha256": REMOTE_STATE_SHA256,
    }
    require(all(value[key] == digest for key, digest in expected.items()), "Reviewed incident digest changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsReadOnlyValidation": True, "terraformStatePull": True, "terraformStateList": True,
        "terraformRefreshOnlyPlan": True, "terraformShow": True, "transientLockMutation": True,
        "stateContentMutation": False, "terraformInit": False, "terraformApply": False,
        "ordinaryTerraformPlan": False, "statePush": False, "destroy": False,
        "iamPolicyAttachment": False, "directLockWrite": False, "forceUnlock": False,
        "automaticRetry": False,
    }, "Refresh-plan execution boundary changed")
    return value


def changed_paths(before: Any, after: Any, prefix: tuple[str, ...] = ()) -> list[str]:
    if type(before) is not type(after):
        return [".".join(prefix) or "<root>"]
    if isinstance(before, dict):
        result: list[str] = []
        for key in sorted(set(before) | set(after)):
            path = prefix + (str(key),)
            if key not in before or key not in after:
                result.append(".".join(path))
            else:
                result.extend(changed_paths(before[key], after[key], path))
        return result
    if isinstance(before, list):
        if len(before) != len(after):
            return [".".join(prefix + ("<length>",))]
        result = []
        for index, (left, right) in enumerate(zip(before, after)):
            result.extend(changed_paths(left, right, prefix + (f"[{index}]",)))
        return result
    return [] if before == after else [".".join(prefix) or "<root>"]


def validate_reviewed_drift(plan: Any, *, refresh_only: bool = False) -> dict[str, Any]:
    require(isinstance(plan, dict), "Terraform plan JSON must be an object")
    require(plan.get("terraform_version") == "1.14.5", "Terraform version changed")
    require(plan.get("errored", False) is False and plan.get("complete", True) is True, "Terraform plan is not complete")
    drift = plan.get("resource_drift", [])
    require(isinstance(drift, list) and len(drift) == 7, "Resource drift count changed")
    require(compact_digest(drift) == RESOURCE_DRIFT_SHA256, "Resource drift values changed")
    changes = {item.get("address"): item for item in plan.get("resource_changes", []) if isinstance(item, dict)}
    outputs = plan.get("output_changes", {})
    require(isinstance(outputs, dict) and all(item.get("actions") == ["no-op"] for item in outputs.values()), "Output changes are not all no-op")
    if refresh_only:
        require(changes == {}, "Refresh-only plan unexpectedly contains resource changes")
        require(set(outputs) == EXPECTED_REFRESH_OUTPUTS, "Refresh-only output inventory changed")
    else:
        require(len(changes) == 13 and set(changes) == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES, "Managed resource-change inventory changed")
        require(all(item.get("change", {}).get("actions") == ["no-op"] and "importing" not in item.get("change", {}) for item in changes.values()), "Managed resource changes are not all no-op")
    observed: dict[str, tuple[str, ...]] = {}
    for item in drift:
        address = item.get("address")
        require(address in EXPECTED_DRIFT_PATHS, "Unreviewed drift address found")
        change = item.get("change", {})
        require(change.get("actions") == ["update"] and "importing" not in change, "Drift action changed")
        if not refresh_only:
            expected_change = changes[address].get("change", {})
            require(change.get("after") == expected_change.get("before") == expected_change.get("after"), "Refresh result does not equal no-op planned state")
        paths = tuple(changed_paths(change.get("before"), change.get("after")))
        require(paths == EXPECTED_DRIFT_PATHS[address], f"Drift paths changed: {address}")
        observed[address] = paths
    require(set(observed) == set(EXPECTED_DRIFT_PATHS), "Reviewed drift inventory changed")
    return {"drift": drift, "changes": changes, "outputs": outputs}


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
    private_request = require_private_file(request_path, "Private refresh-plan request")
    require(not is_within(private_request, repository_root), "Refresh-plan request must remain outside repository")
    request = validate_request(load_json(private_request, "Private refresh-plan request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Refresh-plan approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Refresh-plan approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Refresh plan must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Refresh plan requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")

    proof_request_path = require_private_file(Path(request["privateFailedProofRequestPath"]), "Failed proof request")
    require(file_sha256(proof_request_path) == PROOF_REQUEST_SHA256, "Failed proof request changed")
    proof_request = PROOF_EXECUTOR.validate_request(load_json(proof_request_path, "Failed proof request"))
    require(proof_request["expectedMainCommit"] == INCIDENT_MAIN_COMMIT, "Incident control plane changed")
    require(proof_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Incident account changed")
    proof_output = require_private_directory(Path(request["privateFailedProofOutputDirectory"]), "Failed proof output")
    require(proof_output == Path(proof_request["privateProofOutputDirectory"]).resolve(strict=True), "Failed proof output path changed")
    require(not is_within(proof_output, repository_root), "Failed proof output must remain outside repository")

    incident_artifacts = {
        "remote-state-before.json": (REMOTE_STATE_SHA256, 69929),
        "terraform-plan-lock-contender.stderr": ("e571e2c237d67e41627ae7396ca43d210194396c1ea1dc9dd22cfc8f115ca964", 896),
        "terraform-console-lock-holder.stderr": (EMPTY_SHA256, 0),
        "s3-lock-head-after-holder.stderr": ("6b4ced3a96731d6fa121bee840a1ff6909200bfe3cd115aaef2c7f75aee03bef", 74),
        "terraform-plan-zero-change.stdout": ("3c15d54d784be50888414ed4c01e3428ce1094664c4fef2b0f45d420b9be376e", 3241),
        "terraform-plan-zero-change.stderr": (EMPTY_SHA256, 0),
        "bootstrap-zero-change.tfplan": (BINARY_PLAN_SHA256, 19463),
        "terraform-show-zero-change-json.stdout": (PLAN_JSON_SHA256, 155458),
        "terraform-show-zero-change-json.stderr": (EMPTY_SHA256, 0),
        "terraform-show-zero-change-text.stdout": (PLAN_TEXT_SHA256, 188),
        "terraform-show-zero-change-text.stderr": (EMPTY_SHA256, 0),
    }
    for name, (digest, size) in incident_artifacts.items():
        require_artifact(proof_output / name, f"Failed proof artifact {name}", digest, size)
    require(not (proof_output / "remote-state-proof-result.json").exists(), "Unexpected proof result exists")
    contender = (proof_output / "terraform-plan-lock-contender.stderr").read_bytes()
    require(PROOF_EXECUTOR.lock_error_only(subprocess.CompletedProcess([], 1, b"", contender)), "Incident lock contention evidence changed")
    lock_after = (proof_output / "s3-lock-head-after-holder.stderr").read_text(errors="strict")
    require(any(token in lock_after for token in ("404", "Not Found", "NotFound")), "Incident lock-release evidence changed")
    failed_plan = load_json(proof_output / "terraform-show-zero-change-json.stdout", "Failed proof plan JSON")
    validate_reviewed_drift(failed_plan)

    recovery_request_path = require_private_file(Path(proof_request["privateRecoveryRequestPath"]), "Private recovery request")
    require(file_sha256(recovery_request_path) == PROOF_EXECUTOR.RECOVERY_REQUEST_SHA256, "Recovery request changed")
    recovery_request = RECOVERY_EXECUTOR.validate_request(load_json(recovery_request_path, "Private recovery request"))
    recovery_output = require_private_directory(Path(proof_request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(recovery_output == Path(recovery_request["privateRecoveryOutputDirectory"]).resolve(strict=True), "Recovery output path changed")
    require_artifact(recovery_output / "identity-rebase-recovery-result.json", "Recovery result", PROOF_EXECUTOR.RECOVERY_RESULT_SHA256)
    require_artifact(recovery_output / "identity-rebase-validation.json", "Identity validation", PROOF_EXECUTOR.IDENTITY_VALIDATION_SHA256)

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
    plan_request_path = require_private_file(Path(preflight_request["privatePlanRequestPath"]), "Private original plan request")
    require(file_sha256(plan_request_path) == preflight_request["privatePlanRequestSha256"], "Original plan request changed")
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Private original plan request"))
    tfvars = require_private_file(Path(plan_request["privateTfvarsPath"]), "Private tfvars")
    require(file_sha256(tfvars) == plan_request["privateTfvarsSha256"], "Private tfvars changed")
    state = load_json(proof_output / "remote-state-before.json", "Incident canonical state")
    managed, data = RECOVERY_EXECUTOR.RECOVERY_EXECUTOR.state_addresses(state)
    require(managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES and data <= PLAN_GATE.ALLOWED_DATA_ADDRESSES and len(data) == 9, "Canonical state addresses changed")
    identities = APPLY_EXECUTOR.validate_outputs(state.get("outputs"), plan_request)
    backend = require_private_file(Path(preflight_request["privateBackendConfigPath"]), "Private backend config")
    backend_values = PREFLIGHT_EXECUTOR.parse_backend_config(backend)
    require(backend_values == {"bucket": identities["bucket"], "key": "bootstrap/terraform.tfstate", "region": AWS_REGION, "encrypt": True, "kms_key_id": identities["kms_arn"], "use_lockfile": True}, "Backend config changed")
    output = require_new_private_directory(Path(request["privateRefreshPlanOutputDirectory"]), "Private refresh-plan output")
    require(not is_within(output, repository_root), "Refresh-plan output must remain outside repository")
    return {
        "request": request, "request_path": private_request, "proof_request": proof_request,
        "proof_output": proof_output, "working": working, "terraform_data": terraform_data,
        "plan_request": plan_request, "tfvars": tfvars, "state": state, "managed": managed,
        "data": data, "identities": identities, "backend_values": backend_values,
        "output": output, "remaining": remaining,
    }


def exact_history(value: Any, key: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return PROOF_EXECUTOR.exact_history(value, key)


def execute(
    request_path: Path, *, repository_root: Path = ROOT,
    git_runner: GitRunner = run_git, runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN") == CONFIRMATION, f"Set CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN={CONFIRMATION}")
    forbidden = (
        "CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF", "CONFIRM_STATE_BOOTSTRAP_PLAN",
        "CONFIRM_STATE_BOOTSTRAP_APPLY", "CONFIRM_STATE_BOOTSTRAP_RECOVERY",
        "CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT", "CONFIRM_STATE_BOOTSTRAP_MIGRATION",
        "CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Proof, migration, recovery, apply, destroy and state-push confirmations must be unset")
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
    require(pull_before.returncode == 0 and hashlib.sha256(pull_before.stdout).hexdigest() == REMOTE_STATE_SHA256, "Canonical state bytes changed before refresh plan")
    listed_before = record(output, "terraform-state-list-before", [*prefix, "state", "list"], environment, 180, runner, repository_root)
    require(listed_before.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(listed_before.stdout) == context["managed"] | context["data"], "State address inventory changed")
    bucket = context["identities"]["bucket"]
    state_key = context["backend_values"]["key"]
    lock_key = state_key + ".tflock"
    head_result = record(output, "s3-state-head-before", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", state_key, "--output", "json"], environment, 120, runner, repository_root)
    state_version_id = PROOF_EXECUTOR.validate_state_head(PROOF_EXECUTOR.parse_json_result(head_result, "State head"), context["identities"])
    versions_before_result = record(output, "s3-object-versions-before", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions_before = PROOF_EXECUTOR.parse_json_result(versions_before_result, "Object versions before refresh plan")
    state_versions_before, state_markers_before = exact_history(versions_before, state_key)
    lock_versions_before, lock_markers_before = exact_history(versions_before, lock_key)
    require(len(state_versions_before) == 1 and state_versions_before[0].get("VersionId") == state_version_id and state_versions_before[0].get("IsLatest") is True and state_markers_before == [], "Canonical state object history changed")
    lock_before = record(output, "s3-lock-head-before", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(PROOF_EXECUTOR.is_not_found(lock_before), "Lock object exists before refresh plan")

    binary = output / "bootstrap-refresh-only.tfplan"
    plan_result = record(output, "terraform-plan-refresh-only", [*prefix, "plan", "-refresh-only", "-input=false", "-lock=true", "-lock-timeout=60s", "-detailed-exitcode", "-no-color", f"-out={binary}", f"-var-file={context['tfvars']}"], environment, 600, runner, repository_root)
    require(plan_result.returncode == 2, "Refresh-only plan did not return reviewed detailed exit code 2")
    binary = require_private_file(binary, "Saved refresh-only binary plan")
    show_json = record(output, "terraform-show-refresh-only-json", [*prefix, "show", "-json", str(binary)], environment, 180, runner, repository_root)
    show_text = record(output, "terraform-show-refresh-only-text", [*prefix, "show", "-no-color", str(binary)], environment, 180, runner, repository_root)
    plan_json = PROOF_EXECUTOR.parse_json_result(show_json, "Refresh-only plan JSON")
    validate_reviewed_drift(plan_json, refresh_only=True)
    require(show_text.returncode == 0, "Refresh-only plan text rendering failed")

    pull_after = record(output, "terraform-state-pull-after", [*prefix, "state", "pull"], environment, 180, runner, repository_root)
    require(pull_after.returncode == 0 and hashlib.sha256(pull_after.stdout).hexdigest() == REMOTE_STATE_SHA256, "Refresh-only planning changed canonical state bytes")
    listed_after = record(output, "terraform-state-list-after", [*prefix, "state", "list"], environment, 180, runner, repository_root)
    require(listed_after.returncode == 0 and MIGRATION_EXECUTOR.parse_state_list(listed_after.stdout) == context["managed"] | context["data"], "State address inventory changed after refresh plan")
    versions_after_result = record(output, "s3-object-versions-after", ["aws", "--region", AWS_REGION, "s3api", "list-object-versions", "--bucket", bucket, "--prefix", state_key, "--output", "json"], environment, 120, runner, repository_root)
    versions_after = PROOF_EXECUTOR.parse_json_result(versions_after_result, "Object versions after refresh plan")
    state_versions_after, state_markers_after = exact_history(versions_after, state_key)
    lock_versions_after, lock_markers_after = exact_history(versions_after, lock_key)
    require(state_versions_after == state_versions_before and state_markers_after == state_markers_before, "Refresh-only plan changed state object history")
    require(len(lock_versions_after) - len(lock_versions_before) == 1, "Unexpected refresh-plan lock version delta")
    require(len(lock_markers_after) - len(lock_markers_before) == 1, "Unexpected refresh-plan lock delete-marker delta")
    lock_after = record(output, "s3-lock-head-after", ["aws", "--region", AWS_REGION, "s3api", "head-object", "--bucket", bucket, "--key", lock_key, "--output", "json"], environment, 60, runner, repository_root)
    require(PROOF_EXECUTOR.is_not_found(lock_after), "Lock object remains after refresh-only plan")

    evidence = {
        "schemaVersion": "v0.12.2.3.1.0.1-bootstrap-refresh-only-plan-evidence-v1",
        "incidentPlanJsonSha256": PLAN_JSON_SHA256, "incidentResourceDriftSha256": RESOURCE_DRIFT_SHA256,
        "canonicalStateSha256Before": REMOTE_STATE_SHA256, "canonicalStateSha256After": hashlib.sha256(pull_after.stdout).hexdigest(),
        "refreshBinaryPlanSha256": file_sha256(binary), "refreshPlanJsonSha256": hashlib.sha256(show_json.stdout).hexdigest(),
        "refreshPlanTextSha256": hashlib.sha256(show_text.stdout).hexdigest(), "refreshResourceDriftSha256": compact_digest(plan_json["resource_drift"]),
        "resourceDriftCount": 7, "resourceChangeCount": 0, "outputChangeCount": 7,
        "managedAddressCount": len(context["managed"]), "dataAddressCount": len(context["data"]),
        "stateObjectVersionIds": [item.get("VersionId") for item in state_versions_after],
        "lockObjectVersionIds": [item.get("VersionId") for item in lock_versions_after],
        "lockObjectDeleteMarkerIds": [item.get("VersionId") for item in lock_markers_after],
        "stateObjectHistoryChanged": False, "lockObjectVersionDelta": 1, "lockObjectDeleteMarkerDelta": 1,
    }
    evidence_path = output / "refresh-only-plan-evidence.json"
    APPLY_EXECUTOR.write_private(evidence_path, canonical_json(evidence))
    result = {
        "schemaVersion": "v0.12.2.3.1.0.1-bootstrap-refresh-only-plan-result-v1",
        "status": "bootstrap-refresh-only-plan-produced-awaiting-separate-state-reconciliation-review",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_MAIN_COMMIT,
        "private_refresh_plan_request_sha256": file_sha256(context["request_path"]),
        "private_failed_proof_request_sha256": PROOF_REQUEST_SHA256,
        "canonical_remote_state_sha256": REMOTE_STATE_SHA256,
        "incident_plan_json_sha256": PLAN_JSON_SHA256,
        "incident_resource_drift_sha256": RESOURCE_DRIFT_SHA256,
        "refresh_binary_plan_sha256": evidence["refreshBinaryPlanSha256"],
        "refresh_plan_json_sha256": evidence["refreshPlanJsonSha256"],
        "refresh_plan_text_sha256": evidence["refreshPlanTextSha256"],
        "refresh_resource_drift_sha256": evidence["refreshResourceDriftSha256"],
        "refresh_plan_evidence_sha256": file_sha256(evidence_path),
        "resource_drift_count": 7, "managed_resource_change_count": 0,
        "output_change_count": 7,
        "managed_non_noop_change_count": 0, "output_non_noop_change_count": 0,
        "import_count": 0, "managed_state_address_count": len(context["managed"]),
        "data_state_address_count": len(context["data"]), "refresh_plan_exit_code": 2,
        "state_content_mutated": False, "state_object_history_changed": False,
        "lock_object_version_delta": 1, "lock_object_delete_marker_delta": 1,
        "terraform_init_executed": False, "terraform_apply_executed": False,
        "ordinary_terraform_plan_executed": False, "state_push_executed": False,
        "destroy_executed": False, "iam_policy_attachment_executed": False,
        "direct_lock_write_executed": False, "force_unlock_executed": False,
        "automatic_retry_performed": False, "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "human-review-private-refresh-only-plan-before-v0.12.2.3.1.0.2",
        "completed_at_utc": utc_text(current),
    }
    result_path = output / "refresh-only-plan-result.json"
    APPLY_EXECUTOR.write_private(result_path, canonical_json(result))
    result["refresh_plan_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "bootstrap-refresh-only-plan-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_MAIN_COMMIT,
        "private_refresh_plan_request_sha256": file_sha256(context["request_path"]),
        "private_failed_proof_request_sha256": PROOF_REQUEST_SHA256,
        "canonical_remote_state_sha256": REMOTE_STATE_SHA256,
        "incident_plan_json_sha256": PLAN_JSON_SHA256,
        "incident_resource_drift_sha256": RESOURCE_DRIFT_SHA256,
        "resource_drift_count": 7, "managed_resource_change_count": 0,
        "output_change_count": 7,
        "managed_non_noop_change_count": 0, "output_non_noop_change_count": 0,
        "managed_state_address_count": len(context["managed"]), "data_state_address_count": len(context["data"]),
        "remaining_refresh_plan_approval_seconds": context["remaining"],
        "refresh_plan_execution_authorized": False, "terraform_apply_authorized": False,
        "state_content_mutation_authorized": False, "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-bootstrap-refresh-only-plan-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-refresh-plan-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = redacted_verification(verify_inputs(args.private_refresh_plan_request)) if args.phase == "verify" else execute(args.private_refresh_plan_request)
    except (APPLY_EXECUTOR.CommandFailure, PLAN_EXECUTOR.CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError) as error:
        parser.exit(1, f"Bootstrap refresh-only recovery plan stopped: {error}; preserve all private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

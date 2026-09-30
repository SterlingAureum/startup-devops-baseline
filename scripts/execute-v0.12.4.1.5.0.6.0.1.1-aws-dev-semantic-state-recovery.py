#!/usr/bin/env python3
"""Resume aws-dev post-apply reads using exact semantic-state equality."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import copy
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
PRIOR_EXECUTOR = ROOT / "scripts/execute-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"
CONFIRMATION = "recover-aws-dev-post-apply-with-semantic-state-equality"
PRIOR_CONTROL_PLANE_COMMIT = "e7c218b9d11f64f2af419786fd3c45c51ea289b0"
PRIOR_RECOVERY_REQUEST_SHA256 = "66935f15b045fa641334b4ffa4c47abcc6c0b16a5b3fcb7e7d0aee8f3aa65fe9"
PRIOR_PULLED_STATE_SHA256 = "5e227aeae2e3c0f27afb688319252f91f7f56653d4f05535bf6e1b17908bfdee"
NORMALIZED_CHECK_RESULTS_SHA256 = "cce879cf1dc7519f44b5a75d6802b9ef517712c1483688c0fc98184266ce11a1"
CHECK_RESULT_COUNT = 28
CHECK_STATUS_HISTOGRAM = {"pass": 56}
CHECK_OBJECT_KIND_HISTOGRAM = {"resource": 4, "var": 24}
MAXIMUM_APPROVAL_WINDOW_SECONDS = 10800
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 180
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SECRET_READ_FIELD = "".join(("secret", "ValueRead"))


class RecoveryError(ValueError):
    pass


class CommandFailure(RecoveryError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RecoveryError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRIOR = load_module(PRIOR_EXECUTOR, "aws_dev_post_apply_read_only_recovery_dependency")
APPLY = PRIOR.APPLY
BASE = PRIOR.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def compact_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


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
        raise RecoveryError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise RecoveryError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise RecoveryError(f"{label} must be a valid UTC timestamp") from error
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


def normalize_unordered(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize_unordered(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        normalized = [normalize_unordered(item) for item in value]
        return sorted(normalized, key=compact_json)
    return value


def normalized_check_results(document: dict[str, Any]) -> Any:
    checks = document.get("check_results")
    require(isinstance(checks, list), "Terraform check_results must be a list")
    require(len(checks) == CHECK_RESULT_COUNT, "Terraform check_results count changed")
    return normalize_unordered(checks)


def named_values(value: Any, name: str) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == name:
                result.append(str(item))
            result.extend(named_values(item, name))
    elif isinstance(value, list):
        for item in value:
            result.extend(named_values(item, name))
    return result


def validate_check_results(document: dict[str, Any]) -> Any:
    normalized = normalized_check_results(document)
    require(hashlib.sha256(compact_json(normalized)).hexdigest() == NORMALIZED_CHECK_RESULTS_SHA256, "Normalized Terraform check_results changed")
    checks = document["check_results"]
    require(dict(Counter(named_values(checks, "status"))) == CHECK_STATUS_HISTOGRAM, "Terraform check status histogram changed")
    require(dict(Counter(named_values(checks, "object_kind"))) == CHECK_OBJECT_KIND_HISTOGRAM, "Terraform check object-kind histogram changed")
    return normalized


def semantic_state(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["check_results"] = validate_check_results(document)
    return result


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privatePriorRecoveryRequestPath",
        "privatePriorRecoveryOutputDirectory", "privateRecoveryOutputDirectory",
        "evidenceBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privatePriorRecoveryRequestPath", "privatePriorRecoveryOutputDirectory", "privateRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["evidenceBoundary"] == {
        "priorRecoveryControlPlaneCommit": PRIOR_CONTROL_PLANE_COMMIT,
        "privatePriorRecoveryRequestSha256": PRIOR_RECOVERY_REQUEST_SHA256,
        "privateApplyRequestSha256": PRIOR.APPLY_REQUEST_SHA256,
        "preservedStateSha256": PRIOR.STATE_SHA256,
        "priorPulledStateSha256": PRIOR_PULLED_STATE_SHA256,
        "stateLineageSha256": PRIOR.STATE_LINEAGE_SHA256,
        "stateSerial": PRIOR.STATE_SERIAL,
        "managedStateAddressCount": PRIOR.REVIEWED_MANAGED_COUNT,
        "reviewedDataStateAddressCount": PRIOR.REVIEWED_DATA_COUNT,
        "priorStateDataAddressCount": PRIOR.PRIOR_STATE_DATA_COUNT,
        "totalStateAddressCount": PRIOR.TOTAL_STATE_ADDRESS_COUNT,
        "stateAddressInventorySha256": PRIOR.STATE_ADDRESS_INVENTORY_SHA256,
        "normalizedCheckResultsSha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "checkResultCount": CHECK_RESULT_COUNT,
        "checkStatusHistogram": CHECK_STATUS_HISTOGRAM,
        "checkObjectKindHistogram": CHECK_OBJECT_KIND_HISTOGRAM,
        "semanticStateEqual": True,
        "unexplainedAddressCount": 0,
    }, "Evidence boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Recovery approval window must be positive and at most three hours")
    require(value["executionBoundary"] == {
        "awsIdentityRead": True, "eksDescribeCluster": True, "s3ObjectHistoryRead": True,
        "terraformVersionRead": True, "terraformStatePull": True, "terraformStateList": True,
        "terraformShowState": True, "terraformInit": False, "terraformPlan": False,
        "terraformApply": False, "terraformDestroy": False, "statePush": False,
        "stateMigration": False, "directS3Mutation": False, "forceUnlock": False,
        "iamPolicyAttachment": False, "kubernetesCommand": False, SECRET_READ_FIELD: False,
        "automaticRetry": False, "automaticRollback": False,
    }, "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RecoveryError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def validate_prior_incident(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    prior_request_path = require_private_file(Path(request["privatePriorRecoveryRequestPath"]), "Prior recovery request")
    require(not is_within(prior_request_path, repository_root), "Prior recovery request must remain outside the repository")
    require(file_sha256(prior_request_path) == PRIOR_RECOVERY_REQUEST_SHA256, "Prior recovery request digest changed")
    prior_request = PRIOR.validate_request(load_json(prior_request_path, "Prior recovery request"))
    require(prior_request["expectedMainCommit"] == PRIOR_CONTROL_PLANE_COMMIT, "Prior recovery control-plane commit changed")
    require(prior_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "AWS account changed since prior recovery")
    require(prior_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Terraform version changed since prior recovery")
    incident = PRIOR.validate_incident(prior_request, repository_root)
    prior_output = require_private_directory(Path(request["privatePriorRecoveryOutputDirectory"]), "Prior recovery output")
    require(str(prior_output) == prior_request["privatePostApplyRecoveryOutputDirectory"], "Prior recovery output path changed")
    require(not is_within(prior_output, repository_root), "Prior recovery output must remain outside the repository")
    state_stdout = require_private_file(prior_output / "terraform-state-pull-recovery.stdout", "Prior pulled-state stdout")
    state_stderr = require_private_file(prior_output / "terraform-state-pull-recovery.stderr", "Prior pulled-state stderr")
    state_path = require_private_file(prior_output / "aws-dev-state-recovery.json", "Prior pulled state")
    require(file_sha256(state_stderr) == PRIOR.EMPTY_SHA256, "Prior state-pull stderr is not empty")
    require(state_path.read_bytes() == state_stdout.read_bytes(), "Prior pulled-state files differ")
    require(file_sha256(state_path) == PRIOR_PULLED_STATE_SHA256, "Prior pulled-state digest changed")
    prior_state = load_json(state_path, "Prior pulled state")
    preserved_state = incident["state_document"]
    require(semantic_state(prior_state) == semantic_state(preserved_state), "Prior pulled state is not semantically equal to preserved state")
    require(not (prior_output / "terraform-state-list-recovery.stdout").exists(), "Prior recovery advanced beyond the recorded stop point")
    require(not (prior_output / "aws-dev-post-apply-read-only-recovery-result.json").exists(), "Prior recovery result unexpectedly exists")
    for label in ("aws-identity-during-recovery", "terraform-version-during-recovery"):
        require_private_file(prior_output / f"{label}.stdout", f"Prior recovery {label} stdout")
        require(file_sha256(require_private_file(prior_output / f"{label}.stderr", f"Prior recovery {label} stderr")) == PRIOR.EMPTY_SHA256, f"Prior recovery {label} stderr is not empty")
    return {"prior_request": prior_request, "prior_output": prior_output, "incident": incident, "prior_state": prior_state}


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private semantic-state recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private semantic-state recovery request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Recovery approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Recovery approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Recovery must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Recovery requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")
    prior = validate_prior_incident(request, repository_root)
    output = require_new_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private semantic-state recovery output")
    require(not is_within(output, repository_root), "Recovery output must remain outside the repository")
    protected = (prior["prior_output"], prior["incident"]["apply_output"], prior["incident"]["plan_evidence"]["source"], prior["incident"]["plan_evidence"]["output"])
    for path in protected:
        require(not is_within(output, path) and not is_within(path, output), "Recovery output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "prior": prior, "output": output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "aws-dev-semantic-state-recovery-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "prior_recovery_control_plane_commit": PRIOR_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_prior_recovery_request_sha256": PRIOR_RECOVERY_REQUEST_SHA256,
        "prior_recovery_stop_verified": True,
        "semantic_state_equal": True,
        "managed_state_address_count": PRIOR.REVIEWED_MANAGED_COUNT,
        "reviewed_data_state_address_count": PRIOR.REVIEWED_DATA_COUNT,
        "prior_state_data_address_count": PRIOR.PRIOR_STATE_DATA_COUNT,
        "total_state_address_count": PRIOR.TOTAL_STATE_ADDRESS_COUNT,
        "state_address_inventory_sha256": PRIOR.STATE_ADDRESS_INVENTORY_SHA256,
        "normalized_check_results_sha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "check_result_count": CHECK_RESULT_COUNT,
        "check_pass_status_count": CHECK_STATUS_HISTOGRAM["pass"],
        "unexplained_address_count": 0,
        "state_serial": PRIOR.STATE_SERIAL,
        "remaining_recovery_approval_seconds": context["remaining"],
        "terraform_apply_authorized": False, "terraform_init_authorized": False,
        "terraform_plan_authorized": False, "state_push_authorized": False,
        "operational_commands_executed": [], "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-semantic-state-read-only-recovery-approval",
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


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_SEMANTIC_STATE_RECOVERY") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_SEMANTIC_STATE_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY", "CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY",
        "CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN", "CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY",
        "CONFIRM_AWS_DEV_APPLY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION",
        "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN", "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Mutation confirmations must be unset")
    request = context["request"]
    prior = context["prior"]
    incident = prior["incident"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    plan_evidence = incident["plan_evidence"]
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-semantic-recovery", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-semantic-recovery", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    state_pull = run_logged(output, "terraform-state-pull-semantic-recovery", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-semantic-recovery.json"
    write_private(state_path, state_pull.stdout)
    state_document = parse_json_bytes(state_pull.stdout, "Live remote state")
    require(semantic_state(state_document) == semantic_state(prior["prior_state"]), "Live remote state is not semantically equal to the bound post-apply state")
    require(state_document.get("serial") == PRIOR.STATE_SERIAL, "Live state serial changed")
    lineage = state_document.get("lineage")
    require(isinstance(lineage, str) and hashlib.sha256(lineage.encode()).hexdigest() == PRIOR.STATE_LINEAGE_SHA256, "Live state lineage changed")
    require(PRIOR.state_instance_counts(state_document) == (PRIOR.REVIEWED_MANAGED_COUNT, PRIOR.REVIEWED_DATA_COUNT + PRIOR.PRIOR_STATE_DATA_COUNT), "Live state mode counts changed")
    state_list = run_logged(output, "terraform-state-list-semantic-recovery", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    listed = {line.strip() for line in state_list.stdout.decode().splitlines() if line.strip()}
    require(listed == incident["expected_addresses"], "Live state list differs from exact reviewed plus prior-state inventory")
    require(PRIOR.address_digest(listed) == PRIOR.STATE_ADDRESS_INVENTORY_SHA256, "Live state-list digest changed")
    state_show = run_logged(output, "terraform-show-state-semantic-recovery", ["terraform", "show", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_show_path = output / "aws-dev-state-show-semantic-recovery.json"
    write_private(state_show_path, state_show.stdout)
    require(APPLY.show_state_addresses(parse_json_bytes(state_show.stdout, "Live Terraform state show")) == incident["expected_addresses"], "Live state show differs from exact address inventory")
    cluster = parse_json_bytes(run_logged(output, "eks-cluster-semantic-recovery", ["aws", "eks", "describe-cluster", "--region", APPLY.AWS_REGION, "--name", APPLY.CLUSTER_NAME, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "EKS cluster")
    require(isinstance(cluster.get("cluster"), dict) and cluster["cluster"].get("name") == APPLY.CLUSTER_NAME and cluster["cluster"].get("status") == "ACTIVE", "EKS cluster is not ACTIVE")
    history_value = parse_json_bytes(run_logged(output, "s3-object-history-semantic-recovery", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", APPLY.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history")
    state_version_delta = APPLY.validate_after_apply_history(incident["before_counts"], APPLY.history_counts(history_value), history_value)

    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "priorRecoveryControlPlaneCommit": PRIOR_CONTROL_PLANE_COMMIT,
        "completedAtUtc": utc_text(current), "privateRecoveryRequestSha256": file_sha256(context["request_path"]),
        "privatePriorRecoveryRequestSha256": PRIOR_RECOVERY_REQUEST_SHA256,
        "semanticStateEqual": True, "normalizedCheckResultsSha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "checkResultCount": CHECK_RESULT_COUNT, "checkPassStatusCount": CHECK_STATUS_HISTOGRAM["pass"],
        "managedStateAddressCount": PRIOR.REVIEWED_MANAGED_COUNT,
        "reviewedDataStateAddressCount": PRIOR.REVIEWED_DATA_COUNT,
        "priorStateDataAddressCount": PRIOR.PRIOR_STATE_DATA_COUNT,
        "totalStateAddressCount": PRIOR.TOTAL_STATE_ADDRESS_COUNT,
        "stateAddressInventorySha256": PRIOR.STATE_ADDRESS_INVENTORY_SHA256,
        "liveStateSha256": file_sha256(state_path), "stateShowSha256": file_sha256(state_show_path),
        "stateLineageSha256": PRIOR.STATE_LINEAGE_SHA256, "stateSerial": PRIOR.STATE_SERIAL,
        "stateObjectVersionDelta": state_version_delta, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
        "eksClusterActive": True, "priorApplyExecuted": True, "terraformApplyExecutedByRecovery": False,
        "terraformInitExecuted": False, "terraformPlanExecuted": False, "statePushExecuted": False,
        "automaticRetryPerformed": False, "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-semantic-state-recovery-evidence.json"
    write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-result-v1",
        "status": "aws-dev-saved-plan-apply-semantically-validated",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "prior_recovery_control_plane_commit": PRIOR_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_prior_recovery_request_sha256": PRIOR_RECOVERY_REQUEST_SHA256,
        "semantic_state_equal": True, "normalized_check_results_sha256": NORMALIZED_CHECK_RESULTS_SHA256,
        "check_result_count": CHECK_RESULT_COUNT, "check_pass_status_count": CHECK_STATUS_HISTOGRAM["pass"],
        "managed_state_address_count": PRIOR.REVIEWED_MANAGED_COUNT,
        "reviewed_data_state_address_count": PRIOR.REVIEWED_DATA_COUNT,
        "prior_state_data_address_count": PRIOR.PRIOR_STATE_DATA_COUNT,
        "total_state_address_count": PRIOR.TOTAL_STATE_ADDRESS_COUNT,
        "state_address_inventory_sha256": PRIOR.STATE_ADDRESS_INVENTORY_SHA256,
        "unexplained_address_count": 0, "live_state_sha256": file_sha256(state_path),
        "state_serial": PRIOR.STATE_SERIAL, "state_object_version_delta": state_version_delta,
        "state_delete_marker_delta": 0, "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1, "lock_object_absent": True, "eks_cluster_active": True,
        "environment_created": True, "prior_terraform_apply_executed": True,
        "terraform_apply_executed_by_recovery": False, "terraform_init_executed": False,
        "terraform_plan_executed": False, "state_push_executed": False,
        "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "recovery_evidence_sha256": file_sha256(evidence_path),
        "private_resource_identity_emitted": False, "private_object_version_id_emitted": False,
        "next_action": "record-private-recovery-evidence-before-v0.12.4.1.5.0.7-post-create-qualification",
    }
    result_path = output / "aws-dev-semantic-state-recovery-result.json"
    write_private_json(result_path, result)
    result["recovery_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-recovery-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        context = verify_inputs(args.private_recovery_request)
        result = redacted_verification(context) if args.phase == "verify" else execute(args.private_recovery_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, RecoveryError) as error:
        parser.exit(1, f"AWS-dev semantic-state recovery stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

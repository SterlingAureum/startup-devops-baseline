#!/usr/bin/env python3
"""Recover the stopped aws-dev post-apply validation without another apply."""

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
APPLY_EXECUTOR = ROOT / "scripts/execute-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py"
CONFIRMATION = "recover-aws-dev-post-apply-validation-read-only"
APPLY_CONTROL_PLANE_COMMIT = "d5faf42112066831e53fbd761c603f815d06884a"
APPLY_REQUEST_SHA256 = "c8a3e0a33019246ef5a34f9f17024e1f2c4fd095047dc5f38aa6eef616ceca4b"
STATE_SHA256 = "d3960815889c8d192ffc09b19a98a11f965ed660670ce87d07701944bce3e205"
STATE_LINEAGE_SHA256 = "e7607c625b0ce10f80d09715b8bfb43b6e0a251a82aeabe08f52fb4296ed0391"
STATE_SERIAL = 9
REVIEWED_MANAGED_COUNT = 90
REVIEWED_DATA_COUNT = 6
PRIOR_STATE_DATA_COUNT = 7
TOTAL_STATE_ADDRESS_COUNT = 103
PRIOR_STATE_DATA_SHA256 = "3d28dc57ff69f6763bd6aafe3ef78930ee177cc3d1dddc59f49d58f6a4336cb6"
STATE_ADDRESS_INVENTORY_SHA256 = "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
MAXIMUM_APPROVAL_WINDOW_SECONDS = 10800
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 180
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
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


APPLY = load_module(APPLY_EXECUTOR, "aws_dev_saved_plan_apply_recovery_dependency")
BASE = APPLY.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def address_digest(addresses: set[str]) -> str:
    payload = "".join(f"{address}\n" for address in sorted(addresses)).encode()
    return hashlib.sha256(payload).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


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


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateApplyRequestPath",
        "privateRecoveryPlanOutputDirectory", "privateApplyOutputDirectory",
        "privatePostApplyRecoveryOutputDirectory", "expectedIncidentArtifactSha256s",
        "evidenceBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateApplyRequestPath", "privateRecoveryPlanOutputDirectory", "privateApplyOutputDirectory", "privatePostApplyRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    artifacts = value["expectedIncidentArtifactSha256s"]
    expected_artifact_names = {
        "terraform-apply-reviewed-recovery-plan.stdout",
        "s3-object-history-before-apply.stdout",
        "terraform-state-list-after-apply.stdout",
    }
    require(isinstance(artifacts, dict) and set(artifacts) == expected_artifact_names, "Incident artifact inventory changed")
    require(all(isinstance(digest, str) and DIGEST_RE.fullmatch(digest) for digest in artifacts.values()), "Incident artifact digest is invalid")
    require(value["evidenceBoundary"] == {
        "applyControlPlaneCommit": APPLY_CONTROL_PLANE_COMMIT,
        "privateApplyRequestSha256": APPLY_REQUEST_SHA256,
        "applySucceeded": True,
        "applySummary": "90 added, 0 changed, 0 destroyed.",
        "applyStderrSha256": EMPTY_SHA256,
        "stateSha256": STATE_SHA256,
        "stateLineageSha256": STATE_LINEAGE_SHA256,
        "stateSerial": STATE_SERIAL,
        "reviewedManagedAddressCount": REVIEWED_MANAGED_COUNT,
        "reviewedDataAddressCount": REVIEWED_DATA_COUNT,
        "priorStateDataAddressCount": PRIOR_STATE_DATA_COUNT,
        "priorStateDataAddressSha256": PRIOR_STATE_DATA_SHA256,
        "totalStateAddressCount": TOTAL_STATE_ADDRESS_COUNT,
        "totalStateAddressSha256": STATE_ADDRESS_INVENTORY_SHA256,
        "unexplainedAddressCount": 0,
    }, "Evidence boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Recovery approval window must be positive and at most three hours")
    require(value["executionBoundary"] == {
        "awsIdentityRead": True,
        "eksDescribeCluster": True,
        "s3ObjectHistoryRead": True,
        "terraformVersionRead": True,
        "terraformStatePull": True,
        "terraformStateList": True,
        "terraformShowState": True,
        "terraformInit": False,
        "terraformPlan": False,
        "terraformApply": False,
        "terraformDestroy": False,
        "statePush": False,
        "stateMigration": False,
        "directS3Mutation": False,
        "forceUnlock": False,
        "iamPolicyAttachment": False,
        "kubernetesCommand": False,
        SECRET_READ_FIELD: False,
        "automaticRetry": False,
        "automaticRollback": False,
    }, "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RecoveryError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def collect_value_addresses(module: Any) -> tuple[set[str], set[str]]:
    managed: set[str] = set()
    data: set[str] = set()
    require(isinstance(module, dict), "Terraform values module is invalid")
    resources = module.get("resources", [])
    require(isinstance(resources, list), "Terraform values resources changed")
    for resource in resources:
        require(isinstance(resource, dict) and isinstance(resource.get("address"), str), "Terraform values address changed")
        target = data if resource.get("mode", "managed") == "data" else managed
        target.add(resource["address"])
    children = module.get("child_modules", [])
    require(isinstance(children, list), "Terraform child-module shape changed")
    for child in children:
        child_managed, child_data = collect_value_addresses(child)
        managed |= child_managed
        data |= child_data
    return managed, data


def state_instance_counts(document: dict[str, Any]) -> tuple[int, int]:
    managed = 0
    data = 0
    resources = document.get("resources")
    require(isinstance(resources, list), "Raw Terraform state resources changed")
    for resource in resources:
        require(isinstance(resource, dict) and isinstance(resource.get("instances"), list), "Raw Terraform state instance shape changed")
        count = len(resource["instances"])
        if resource.get("mode", "managed") == "data":
            data += count
        else:
            managed += count
    return managed, data


def incident_path(output: Path, name: str) -> Path:
    return require_private_file(output / name, f"Apply incident artifact {name}")


def validate_incident(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    apply_request_path = require_private_file(Path(request["privateApplyRequestPath"]), "Private apply request")
    require(not is_within(apply_request_path, repository_root), "Apply request must remain outside the repository")
    require(file_sha256(apply_request_path) == APPLY_REQUEST_SHA256, "Apply request digest changed")
    apply_request = APPLY.validate_request(load_json(apply_request_path, "Private apply request"))
    require(apply_request["expectedMainCommit"] == APPLY_CONTROL_PLANE_COMMIT, "Apply control-plane commit changed")
    require(apply_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "AWS account changed since apply")
    require(apply_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Terraform version changed since apply")
    plan_evidence = APPLY.validate_plan_evidence(apply_request, repository_root)
    require(str(plan_evidence["output"]) == request["privateRecoveryPlanOutputDirectory"], "Recovery plan output path changed")
    apply_output = require_private_directory(Path(request["privateApplyOutputDirectory"]), "Private apply output")
    require(str(apply_output) == apply_request["privateApplyOutputDirectory"], "Apply output path changed")
    require(not is_within(apply_output, repository_root), "Apply output must remain outside the repository")

    for name, expected_digest in request["expectedIncidentArtifactSha256s"].items():
        require(file_sha256(incident_path(apply_output, name)) == expected_digest, f"Incident artifact digest changed: {name}")
    apply_stdout = incident_path(apply_output, "terraform-apply-reviewed-recovery-plan.stdout")
    apply_stderr = incident_path(apply_output, "terraform-apply-reviewed-recovery-plan.stderr")
    require(file_sha256(apply_stderr) == EMPTY_SHA256, "Apply stderr is not empty")
    require(re.search(rb"Apply complete! Resources: 90 added, 0 changed, 0 destroyed\.", apply_stdout.read_bytes()) is not None, "Successful apply summary is missing")

    state_pull_stdout = incident_path(apply_output, "terraform-state-pull-after-apply.stdout")
    state_pull_stderr = incident_path(apply_output, "terraform-state-pull-after-apply.stderr")
    state_list_stdout = incident_path(apply_output, "terraform-state-list-after-apply.stdout")
    state_list_stderr = incident_path(apply_output, "terraform-state-list-after-apply.stderr")
    state_path = incident_path(apply_output, "aws-dev-state-after-apply.json")
    require(file_sha256(state_pull_stderr) == EMPTY_SHA256 and file_sha256(state_list_stderr) == EMPTY_SHA256, "State-read stderr is not empty")
    require(state_path.read_bytes() == state_pull_stdout.read_bytes(), "Preserved state files differ")
    require(file_sha256(state_path) == STATE_SHA256, "Preserved state digest changed")
    state_document = load_json(state_path, "Preserved post-apply state")
    require(state_document.get("serial") == STATE_SERIAL, "Preserved state serial changed")
    lineage = state_document.get("lineage")
    require(isinstance(lineage, str) and hashlib.sha256(lineage.encode()).hexdigest() == STATE_LINEAGE_SHA256, "Preserved state lineage changed")
    managed_instances, data_instances = state_instance_counts(state_document)
    require(managed_instances == REVIEWED_MANAGED_COUNT and data_instances == REVIEWED_DATA_COUNT + PRIOR_STATE_DATA_COUNT, "Preserved state mode counts changed")

    reviewed_managed = set(plan_evidence["inventory"]["managedCreateAddresses"])
    reviewed_data = set(plan_evidence["inventory"]["dataReadOrNoopAddresses"])
    prior_root = plan_evidence["plan_document"].get("prior_state", {}).get("values", {}).get("root_module")
    require(isinstance(prior_root, dict), "Reviewed plan prior state is missing")
    prior_managed, prior_data = collect_value_addresses(prior_root)
    require(not prior_managed, "Reviewed plan prior state contains managed addresses")
    require(len(prior_data) == PRIOR_STATE_DATA_COUNT and address_digest(prior_data) == PRIOR_STATE_DATA_SHA256, "Reviewed prior-state data inventory changed")
    expected_addresses = reviewed_managed | reviewed_data | prior_data
    require(len(expected_addresses) == TOTAL_STATE_ADDRESS_COUNT, "Expected state address count changed")
    require(address_digest(expected_addresses) == STATE_ADDRESS_INVENTORY_SHA256, "Expected state address inventory changed")
    listed = {line.strip() for line in state_list_stdout.read_text().splitlines() if line.strip()}
    require(listed == expected_addresses, "Preserved state list differs from reviewed plus prior-state inventory")
    require(address_digest(listed) == STATE_ADDRESS_INVENTORY_SHA256, "Preserved state-list digest changed")
    require(not (apply_output / "terraform-show-state-after-apply.stdout").exists(), "Original executor advanced beyond the recorded stop point")
    require(not (apply_output / "aws-dev-recovery-saved-plan-apply-result.json").exists(), "Original apply result unexpectedly exists")

    before_history_path = incident_path(apply_output, "s3-object-history-before-apply.stdout")
    before_history_stderr = incident_path(apply_output, "s3-object-history-before-apply.stderr")
    require(file_sha256(before_history_stderr) == EMPTY_SHA256, "Pre-apply history stderr is not empty")
    before_history = parse_json_bytes(before_history_path.read_bytes(), "Pre-apply S3 history")
    before_counts = APPLY.history_counts(before_history)
    APPLY.validate_before_apply_history(before_counts)
    return {
        "apply_request_path": apply_request_path,
        "apply_request": apply_request,
        "plan_evidence": plan_evidence,
        "apply_output": apply_output,
        "state_path": state_path,
        "state_document": state_document,
        "expected_addresses": expected_addresses,
        "prior_data": prior_data,
        "before_counts": before_counts,
    }


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private post-apply recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private post-apply recovery request"))
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
    incident = validate_incident(request, repository_root)
    recovery_output = require_new_private_directory(Path(request["privatePostApplyRecoveryOutputDirectory"]), "Private post-apply recovery output")
    require(not is_within(recovery_output, repository_root), "Recovery output must remain outside the repository")
    for protected in (incident["apply_output"], incident["plan_evidence"]["source"], incident["plan_evidence"]["output"]):
        require(not is_within(recovery_output, protected) and not is_within(protected, recovery_output), "Recovery output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "incident": incident, "output": recovery_output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "aws-dev-post-apply-read-only-recovery-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "apply_control_plane_commit": APPLY_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_apply_request_sha256": APPLY_REQUEST_SHA256,
        "apply_success_verified": True,
        "managed_state_address_count": REVIEWED_MANAGED_COUNT,
        "reviewed_data_state_address_count": REVIEWED_DATA_COUNT,
        "prior_state_data_address_count": PRIOR_STATE_DATA_COUNT,
        "total_state_address_count": TOTAL_STATE_ADDRESS_COUNT,
        "state_address_inventory_sha256": STATE_ADDRESS_INVENTORY_SHA256,
        "unexplained_address_count": 0,
        "state_sha256": STATE_SHA256,
        "state_serial": STATE_SERIAL,
        "remaining_recovery_approval_seconds": context["remaining"],
        "terraform_apply_authorized": False,
        "terraform_init_authorized": False,
        "terraform_plan_authorized": False,
        "state_push_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-post-apply-read-only-recovery-approval",
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
    require(os.environ.get("CONFIRM_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY", "CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN",
        "CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY", "CONFIRM_AWS_DEV_APPLY", "CONFIRM_AWS_DEV_DESTROY",
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
        "CONFIRM_STATE_MIGRATION", "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN",
        "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Mutation confirmations must be unset")
    request = context["request"]
    incident = context["incident"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    plan_evidence = incident["plan_evidence"]
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-during-recovery", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-during-recovery", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")

    state_pull = run_logged(output, "terraform-state-pull-recovery", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-recovery.json"
    write_private(state_path, state_pull.stdout)
    require(file_sha256(state_path) == STATE_SHA256, "Live remote state differs from preserved post-apply state")
    state_document = parse_json_bytes(state_pull.stdout, "Live remote state")
    require(state_document.get("serial") == STATE_SERIAL, "Live remote state serial changed")
    lineage = state_document.get("lineage")
    require(isinstance(lineage, str) and hashlib.sha256(lineage.encode()).hexdigest() == STATE_LINEAGE_SHA256, "Live remote state lineage changed")
    require(state_instance_counts(state_document) == (REVIEWED_MANAGED_COUNT, REVIEWED_DATA_COUNT + PRIOR_STATE_DATA_COUNT), "Live state mode counts changed")

    state_list = run_logged(output, "terraform-state-list-recovery", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    listed = {line.strip() for line in state_list.stdout.decode().splitlines() if line.strip()}
    require(listed == incident["expected_addresses"], "Live state list differs from exact reviewed plus prior-state inventory")
    require(address_digest(listed) == STATE_ADDRESS_INVENTORY_SHA256, "Live state-list digest changed")
    state_show = run_logged(output, "terraform-show-state-recovery", ["terraform", "show", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_show_path = output / "aws-dev-state-show-recovery.json"
    write_private(state_show_path, state_show.stdout)
    require(APPLY.show_state_addresses(parse_json_bytes(state_show.stdout, "Live Terraform state show")) == incident["expected_addresses"], "Live state show differs from exact address inventory")

    cluster = parse_json_bytes(run_logged(output, "eks-cluster-recovery", ["aws", "eks", "describe-cluster", "--region", APPLY.AWS_REGION, "--name", APPLY.CLUSTER_NAME, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "EKS cluster")
    require(isinstance(cluster.get("cluster"), dict) and cluster["cluster"].get("name") == APPLY.CLUSTER_NAME and cluster["cluster"].get("status") == "ACTIVE", "EKS cluster is not ACTIVE")
    history_value = parse_json_bytes(run_logged(output, "s3-object-history-recovery", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", APPLY.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history")
    after_counts = APPLY.history_counts(history_value)
    state_version_delta = APPLY.validate_after_apply_history(incident["before_counts"], after_counts, history_value)

    evidence_record = {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "applyControlPlaneCommit": APPLY_CONTROL_PLANE_COMMIT,
        "completedAtUtc": utc_text(current),
        "privateRecoveryRequestSha256": file_sha256(context["request_path"]),
        "privateApplyRequestSha256": APPLY_REQUEST_SHA256,
        "priorApplyExecuted": True,
        "terraformApplyExecutedByRecovery": False,
        "managedStateAddressCount": REVIEWED_MANAGED_COUNT,
        "reviewedDataStateAddressCount": REVIEWED_DATA_COUNT,
        "priorStateDataAddressCount": PRIOR_STATE_DATA_COUNT,
        "totalStateAddressCount": TOTAL_STATE_ADDRESS_COUNT,
        "stateAddressInventorySha256": STATE_ADDRESS_INVENTORY_SHA256,
        "stateSha256": file_sha256(state_path),
        "stateShowSha256": file_sha256(state_show_path),
        "stateLineageSha256": STATE_LINEAGE_SHA256,
        "stateSerial": STATE_SERIAL,
        "stateObjectVersionDelta": state_version_delta,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
        "lockObjectAbsent": True,
        "eksClusterActive": True,
        "terraformInitExecuted": False,
        "terraformPlanExecuted": False,
        "statePushExecuted": False,
        "automaticRetryPerformed": False,
        "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-post-apply-read-only-recovery-evidence.json"
    write_private_json(evidence_path, evidence_record)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-result-v1",
        "status": "aws-dev-saved-plan-apply-recovered-and-read-only-validated",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "apply_control_plane_commit": APPLY_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_apply_request_sha256": APPLY_REQUEST_SHA256,
        "managed_state_address_count": REVIEWED_MANAGED_COUNT,
        "reviewed_data_state_address_count": REVIEWED_DATA_COUNT,
        "prior_state_data_address_count": PRIOR_STATE_DATA_COUNT,
        "total_state_address_count": TOTAL_STATE_ADDRESS_COUNT,
        "state_address_inventory_sha256": STATE_ADDRESS_INVENTORY_SHA256,
        "unexplained_address_count": 0,
        "remote_state_sha256": STATE_SHA256,
        "state_serial": STATE_SERIAL,
        "state_object_version_delta": state_version_delta,
        "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1,
        "lock_object_absent": True,
        "eks_cluster_active": True,
        "environment_created": True,
        "prior_terraform_apply_executed": True,
        "terraform_apply_executed_by_recovery": False,
        "terraform_init_executed": False,
        "terraform_plan_executed": False,
        "state_push_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "recovery_evidence_sha256": file_sha256(evidence_path),
        "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "record-private-recovery-evidence-before-v0.12.4.1.5.0.7-post-create-qualification",
    }
    result_path = output / "aws-dev-post-apply-read-only-recovery-result.json"
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
        parser.exit(1, f"AWS-dev post-apply read-only recovery stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify or execute read-only recovery after partial aws-dev teardown."""

from __future__ import annotations

import argparse
from collections import Counter
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
TEARDOWN_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"
CONFIRMATION = "inspect-partial-aws-dev-teardown-read-only"
INCIDENT_CONTROL_PLANE_COMMIT = "8bdb9289a8b612d987dc5a2e555bd16ca4a542b9"
DESTROY_REQUEST_SHA256 = "a41c67a956cd36fabe4730a05c6f67c1e12bfe7ecb788f63e946fd573f4f2d2e"
PLAN_REQUEST_SHA256 = "ee068591265685b66785759ddffad17cdbe7e39b9040d54ddcdd338247a30256"
BINARY_PLAN_SHA256 = "401a1ca3911cc9c48df6e7d05ef7230ac7ed859432fb139e4773876ab0f20b5d"
PLAN_JSON_SHA256 = "1bed4aab69fd9ed5a75a237dc47a586fa63c7bf35b8614b2b748f89a839a9a18"
PLAN_TEXT_SHA256 = "1a173c78a5c49d2351754441df54d9bb0fda45cbefa3b57581e7fa163ffa6725"
INVENTORY_SHA256 = "1eaaf633e69277941618d521cefd2b17b8d4deb905ea7a3485170366ed0df28c"
PLAN_RECORD_SHA256 = "b75bcfaf11982b13ae98c9a7f921681a4d05acec866353a541f15d03ef89dd10"
APPLY_STDOUT_SHA256 = "533d6d9c1be7f4b816e4cf0eff28b918c8c737eda71290d066b38e6523868168"
APPLY_STDERR_SHA256 = "b087c323c60808448c8d3a888034f125690676a2375ed26366248b96c761a324"
STARTED_ADDRESS_SHA256 = "bc1b97b675a856c11041469885e6cd0348ea2061e7b1dd06fee6fca2425e8847"
COMPLETED_ADDRESS_SHA256 = "19d3e297f777ec9427665bfe2755f40b0c93f6212067b00befd3198c54de96e5"
PENDING_ADDRESSES = {
    'module.vpc.aws_subnet.private["us-east-1b"]',
    "module.vpc.aws_vpc.this",
}
FAILED_ADDRESS = 'module.vpc.aws_subnet.private["us-east-1b"]'
MAXIMUM_APPROVAL_WINDOW_SECONDS = 10800
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 300
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


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


TEARDOWN = load_module(TEARDOWN_PATH, "guarded_aws_dev_teardown_recovery_dependency")
SEMANTIC = TEARDOWN.SEMANTIC
PRIOR = TEARDOWN.PRIOR
APPLY = TEARDOWN.APPLY
BASE = TEARDOWN.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def address_digest(addresses: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(addresses)) + ("\n" if addresses else "")).encode()).hexdigest()


def write_private(path: Path, value: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(value)
    path.chmod(0o600)


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


def execution_boundary() -> dict[str, bool]:
    return {
        "awsIdentityRead": True, "eksAbsenceRead": True,
        "ec2VpcRead": True, "ec2SubnetRead": True,
        "ec2NetworkInterfaceRead": True, "ec2InstanceRead": True,
        "ec2NatGatewayRead": True, "ec2RouteTableRead": True,
        "s3ObjectHistoryRead": True, "terraformVersionRead": True,
        "terraformStatePull": True, "terraformStateList": True,
        "terraformShowState": True, "terraformInit": False,
        "terraformPlan": False, "terraformApply": False,
        "terraformDestroy": False, "statePush": False,
        "directAwsMutation": False, "directS3Mutation": False,
        "forceUnlock": False, "kubernetesCommand": False,
        "secretValueRead": False, "automaticRetry": False,
        "automaticRollback": False,
    }


def incident_boundary() -> dict[str, Any]:
    return {
        "incidentControlPlaneCommit": INCIDENT_CONTROL_PLANE_COMMIT,
        "privateDestroyRequestSha256": DESTROY_REQUEST_SHA256,
        "privatePlanRequestSha256": PLAN_REQUEST_SHA256,
        "binaryPlanSha256": BINARY_PLAN_SHA256,
        "planJsonSha256": PLAN_JSON_SHA256,
        "planTextSha256": PLAN_TEXT_SHA256,
        "addressInventorySha256": INVENTORY_SHA256,
        "planRecordSha256": PLAN_RECORD_SHA256,
        "applyStdoutSha256": APPLY_STDOUT_SHA256,
        "applyStderrSha256": APPLY_STDERR_SHA256,
        "plannedManagedDeleteCount": 90,
        "destroyStartedAddressCount": 89,
        "destroyCompletedAddressCount": 88,
        "destroyStartedAddressSha256": STARTED_ADDRESS_SHA256,
        "destroyCompletedAddressSha256": COMPLETED_ADDRESS_SHA256,
        "failedAddress": FAILED_ADDRESS,
        "neverStartedAddress": "module.vpc.aws_vpc.this",
        "failureCode": "DependencyViolation",
        "applyCompleteMarkerPresent": False,
        "teardownResultPresent": False,
        "teardownEvidencePresent": False,
    }


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateDestroyRequestPath",
        "privateDestroyOutputDirectory", "privateRecoveryOutputDirectory",
        "incidentBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateDestroyRequestPath", "privateDestroyOutputDirectory", "privateRecoveryOutputDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["incidentBoundary"] == incident_boundary(), "Incident boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most three hours")
    require(value["executionBoundary"] == execution_boundary(), "Execution boundary changed")
    return value


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RecoveryError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def parse_apply_addresses(stdout: bytes) -> tuple[set[str], set[str]]:
    text = ANSI_RE.sub("", stdout.decode(errors="replace"))
    started: set[str] = set()
    completed: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^(.+?): Destroying\.\.\.", line.strip())
        if match:
            started.add(match.group(1))
        match = re.match(r"^(.+?): Destruction complete after", line.strip())
        if match:
            completed.add(match.group(1))
    return started, completed


def validate_incident(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    destroy_request_path = require_private_file(Path(request["privateDestroyRequestPath"]), "Private destroy request")
    require(not is_within(destroy_request_path, repository_root), "Destroy request must remain outside the repository")
    require(file_sha256(destroy_request_path) == DESTROY_REQUEST_SHA256, "Destroy request digest changed")
    destroy_request = TEARDOWN.validate_destroy_request(load_json(destroy_request_path, "Private destroy request"))
    require(destroy_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT, "Incident control-plane commit changed")
    require(destroy_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "AWS account changed since destroy")
    require(destroy_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Terraform version changed since destroy")
    require(destroy_request["planBoundary"] == {
        "privatePlanRequestSha256": PLAN_REQUEST_SHA256, "binaryPlanSha256": BINARY_PLAN_SHA256,
        "planJsonSha256": PLAN_JSON_SHA256, "planTextSha256": PLAN_TEXT_SHA256,
        "addressInventorySha256": INVENTORY_SHA256, "planRecordSha256": PLAN_RECORD_SHA256,
        "managedDeleteCount": 90, "dataChangeCount": 0, "resourceDriftCount": 0,
        "importCount": 0, "humanReviewed": True,
        "planReviewExpiresAtUtc": "2026-10-01T02:59:15Z",
    }, "Reviewed destroy-plan boundary changed")
    plan_request_path = require_private_file(Path(destroy_request["privateTeardownPlanRequestPath"]), "Private teardown plan request")
    require(file_sha256(plan_request_path) == PLAN_REQUEST_SHA256, "Plan request digest changed")
    plan_request = TEARDOWN.validate_plan_request(load_json(plan_request_path, "Private teardown plan request"))
    require(plan_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT, "Plan control-plane commit changed")
    recovery = TEARDOWN.validate_recovery_chain(plan_request, repository_root)
    plan_output = require_private_directory(Path(destroy_request["privateTeardownPlanOutputDirectory"]), "Private teardown plan output")
    require(str(plan_output) == plan_request["privateTeardownPlanOutputDirectory"], "Plan output path changed")
    artifact_digests = {
        "aws-dev-destroy.tfplan": BINARY_PLAN_SHA256,
        "aws-dev-destroy-plan.json": PLAN_JSON_SHA256,
        "aws-dev-destroy-plan.txt": PLAN_TEXT_SHA256,
        "destroy-plan-address-inventory.json": INVENTORY_SHA256,
        "destroy-plan-record.json": PLAN_RECORD_SHA256,
    }
    artifacts: dict[str, Path] = {}
    for name, digest in artifact_digests.items():
        path = require_private_file(plan_output / name, f"Destroy-plan artifact {name}")
        require(file_sha256(path) == digest, f"Destroy-plan artifact digest changed: {name}")
        artifacts[name] = path
    inventory = load_json(artifacts["destroy-plan-address-inventory.json"], "Destroy-plan inventory")
    planned = set(inventory.get("managedDeleteAddresses", []))
    require(len(planned) == 90 and inventory.get("managedDeleteCount") == 90, "Planned managed-delete inventory changed")
    gated = TEARDOWN.destroy_plan_gate(load_json(artifacts["aws-dev-destroy-plan.json"], "Destroy plan JSON"), set(recovery["plan_evidence"]["inventory"]["managedCreateAddresses"]))
    require(set(gated["managedDeleteAddresses"]) == planned, "Saved destroy plan differs from address inventory")

    destroy_output = require_private_directory(Path(request["privateDestroyOutputDirectory"]), "Private destroy output")
    require(str(destroy_output) == destroy_request["privateDestroyOutputDirectory"], "Destroy output path changed")
    require(not is_within(destroy_output, repository_root), "Destroy output must remain outside the repository")
    stdout_path = require_private_file(destroy_output / "terraform-apply-reviewed-destroy-plan.stdout", "Failed apply stdout")
    stderr_path = require_private_file(destroy_output / "terraform-apply-reviewed-destroy-plan.stderr", "Failed apply stderr")
    require(file_sha256(stdout_path) == APPLY_STDOUT_SHA256 and file_sha256(stderr_path) == APPLY_STDERR_SHA256, "Failed apply logs changed")
    stdout = stdout_path.read_bytes()
    stderr = stderr_path.read_bytes()
    started, completed = parse_apply_addresses(stdout)
    require(len(started) == 89 and address_digest(started) == STARTED_ADDRESS_SHA256, "Started destroy inventory changed")
    require(len(completed) == 88 and address_digest(completed) == COMPLETED_ADDRESS_SHA256, "Completed destroy inventory changed")
    require(started <= planned and completed <= started, "Destroy logs contain an unplanned address")
    require(planned - completed == PENDING_ADDRESSES and started - completed == {FAILED_ADDRESS}, "Pending destroy inventory changed")
    require(b"DependencyViolation" in stderr and b"DeleteSubnet" in stderr, "Destroy failure category changed")
    require(b"Apply complete!" not in stdout, "Failed apply unexpectedly has a success marker")
    require(not (destroy_output / "aws-dev-teardown-result.json").exists(), "Teardown result unexpectedly exists")
    require(not (destroy_output / "aws-dev-teardown-evidence.json").exists(), "Teardown evidence unexpectedly exists")
    before_history_path = require_private_file(destroy_output / "s3-object-history-before-destroy.stdout", "Pre-destroy S3 history")
    require(file_sha256(require_private_file(destroy_output / "s3-object-history-before-destroy.stderr", "Pre-destroy S3 history stderr")) == TEARDOWN.SEMANTIC.PRIOR.EMPTY_SHA256, "Pre-destroy S3 history stderr is not empty")
    before_history = TEARDOWN.history_counts(parse_json_bytes(before_history_path.read_bytes(), "Pre-destroy S3 history"))
    TEARDOWN.require_clean_lock(before_history)
    return {
        "destroy_request_path": destroy_request_path, "destroy_request": destroy_request,
        "plan_request": plan_request, "plan_output": plan_output, "artifacts": artifacts,
        "inventory": inventory, "planned": planned, "started": started, "completed": completed,
        "destroy_output": destroy_output, "before_history": before_history,
        "recovery": recovery,
    }


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private partial-teardown recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private partial-teardown recovery request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Recovery approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Recovery approval has less than 15 minutes remaining")
    expected = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Recovery must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Recovery requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected and git_runner(["rev-parse", "origin/main"]) == expected, "HEAD and origin/main must equal reviewed main")
    incident = validate_incident(request, repository_root)
    output = require_new_private_directory(Path(request["privateRecoveryOutputDirectory"]), "Private recovery output")
    require(not is_within(output, repository_root), "Recovery output must remain outside the repository")
    for protected in (incident["destroy_output"], incident["plan_output"], incident["recovery"]["output"], incident["recovery"]["plan_evidence"]["source"]):
        require(not is_within(output, protected) and not is_within(protected, output), "Recovery output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "incident": incident, "output": output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-partial-teardown-recovery-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_destroy_request_sha256": DESTROY_REQUEST_SHA256,
        "binary_plan_sha256": BINARY_PLAN_SHA256,
        "apply_stdout_sha256": APPLY_STDOUT_SHA256, "apply_stderr_sha256": APPLY_STDERR_SHA256,
        "planned_managed_delete_count": 90, "destroy_started_address_count": 89,
        "destroy_completed_address_count": 88, "pending_managed_address_count": 2,
        "dependency_failure_verified": True, "remaining_recovery_approval_seconds": context["remaining"],
        "operational_commands_executed": [], "terraform_init_authorized": False,
        "terraform_plan_authorized": False, "terraform_apply_authorized": False,
        "terraform_destroy_authorized": False, "state_push_authorized": False,
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-partial-teardown-read-only-recovery-approval",
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


def run_expected_missing_eks(output: Path, environment: dict[str, str], cwd: Path, runner: CommandRunner) -> None:
    arguments = ["aws", "eks", "describe-cluster", "--region", TEARDOWN.AWS_REGION, "--name", TEARDOWN.CLUSTER_NAME, "--output", "json"]
    try:
        result = runner(arguments, environment, COMMAND_TIMEOUT_SECONDS, cwd)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure("eks-cluster-partial-recovery timed out") from error
    record_result(output, "eks-cluster-partial-recovery", result)
    require(result.returncode != 0 and result.stdout == b"" and b"ResourceNotFoundException" in result.stderr, "EKS cluster is not conclusively absent")


def raw_attribute(state: dict[str, Any], module: str, resource_type: str, name: str, index_key: Any, attribute: str) -> Any:
    resources = state.get("resources")
    require(isinstance(resources, list), "Recovered raw state resources changed")
    matches = [item for item in resources if item.get("module") == module and item.get("mode", "managed") == "managed" and item.get("type") == resource_type and item.get("name") == name]
    require(len(matches) == 1, f"Recovered state resource identity changed: {resource_type}.{name}")
    instances = matches[0].get("instances")
    require(isinstance(instances, list), "Recovered state instances changed")
    selected = [item for item in instances if item.get("index_key") == index_key] if index_key is not None else instances
    require(len(selected) == 1 and isinstance(selected[0].get("attributes"), dict), f"Recovered state instance changed: {resource_type}.{name}")
    require(attribute in selected[0]["attributes"], f"Recovered state attribute missing: {attribute}")
    return selected[0]["attributes"][attribute]


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_PARTIAL_TEARDOWN_RECOVERY") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_PARTIAL_TEARDOWN_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_TEARDOWN_PLAN", "CONFIRM_AWS_DEV_TEARDOWN_DESTROY",
        "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY",
        "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Mutation confirmations must be unset")
    request = context["request"]
    incident = context["incident"]
    recovery = incident["recovery"]
    plan_evidence = recovery["plan_evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]

    identity = parse_json_bytes(run_logged(output, "aws-identity-partial-recovery", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-partial-recovery", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = run_logged(output, "terraform-state-pull-partial-recovery", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-partial-recovery.json"
    write_private(state_path, pulled.stdout)
    state = parse_json_bytes(pulled.stdout, "Partial teardown remote state")
    managed_instances, data_instances = PRIOR.state_instance_counts(state)
    require(managed_instances == 2 and 0 <= data_instances <= TEARDOWN.DATA_COUNT, "Partial state mode counts changed")
    listed = TEARDOWN.state_list(run_logged(output, "terraform-state-list-partial-recovery", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout)
    original_managed = set(plan_evidence["inventory"]["managedCreateAddresses"])
    require(listed <= recovery["prior"]["incident"]["expected_addresses"], "Partial state contains a new address")
    require(listed & original_managed == PENDING_ADDRESSES, "Partial state managed inventory differs from the two pending addresses")
    shown = parse_json_bytes(run_logged(output, "terraform-show-state-partial-recovery", ["terraform", "show", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Partial Terraform state show")
    require(APPLY.show_state_addresses(shown) == listed, "Partial state list and show inventories differ")

    original_state = recovery["state"]
    vpc_id = raw_attribute(original_state, "module.vpc", "aws_vpc", "this", None, "id")
    subnet_id = raw_attribute(original_state, "module.vpc", "aws_subnet", "private", "us-east-1b", "id")
    require(isinstance(vpc_id, str) and vpc_id.startswith("vpc-") and isinstance(subnet_id, str) and subnet_id.startswith("subnet-"), "Recovered network identity changed")
    run_expected_missing_eks(output, environment, repository_root, runner)
    vpcs = parse_json_bytes(run_logged(output, "vpc-partial-recovery", ["aws", "ec2", "describe-vpcs", "--region", TEARDOWN.AWS_REGION, "--vpc-ids", vpc_id, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "VPC read").get("Vpcs")
    require(isinstance(vpcs, list) and len(vpcs) == 1 and vpcs[0].get("VpcId") == vpc_id, "Pending VPC is not present exactly once")
    subnets = parse_json_bytes(run_logged(output, "subnet-partial-recovery", ["aws", "ec2", "describe-subnets", "--region", TEARDOWN.AWS_REGION, "--subnet-ids", subnet_id, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Subnet read").get("Subnets")
    require(isinstance(subnets, list) and len(subnets) == 1 and subnets[0].get("VpcId") == vpc_id and subnets[0].get("AvailabilityZone") == "us-east-1b", "Pending subnet identity changed")
    enis = parse_json_bytes(run_logged(output, "network-interfaces-partial-recovery", ["aws", "ec2", "describe-network-interfaces", "--region", TEARDOWN.AWS_REGION, "--filters", f"Name=subnet-id,Values={subnet_id}", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Network-interface read").get("NetworkInterfaces")
    require(isinstance(enis, list), "Network-interface response changed")
    instances_value = parse_json_bytes(run_logged(output, "instances-partial-recovery", ["aws", "ec2", "describe-instances", "--region", TEARDOWN.AWS_REGION, "--filters", f"Name=subnet-id,Values={subnet_id}", "Name=instance-state-name,Values=pending,running,stopping,stopped", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Instance read")
    reservations = instances_value.get("Reservations", [])
    require(isinstance(reservations, list), "Instance response changed")
    instance_count = sum(len(item.get("Instances", [])) for item in reservations if isinstance(item, dict) and isinstance(item.get("Instances", []), list))
    nat_value = parse_json_bytes(run_logged(output, "nat-gateways-partial-recovery", ["aws", "ec2", "describe-nat-gateways", "--region", TEARDOWN.AWS_REGION, "--filter", f"Name=vpc-id,Values={vpc_id}", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "NAT gateway read")
    nat_gateways = nat_value.get("NatGateways", [])
    require(isinstance(nat_gateways, list), "NAT gateway response changed")
    active_nat = [item for item in nat_gateways if item.get("State") not in {"deleted", "failed"}]
    route_value = parse_json_bytes(run_logged(output, "route-tables-partial-recovery", ["aws", "ec2", "describe-route-tables", "--region", TEARDOWN.AWS_REGION, "--filters", f"Name=association.subnet-id,Values={subnet_id}", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Route-table read")
    route_tables = route_value.get("RouteTables", [])
    require(isinstance(route_tables, list), "Route-table response changed")
    interface_types = dict(sorted(Counter(str(item.get("InterfaceType", "unknown")) for item in enis).items()))
    requester_managed_count = sum(item.get("RequesterManaged") is True for item in enis)
    if enis:
        dependency = "network-interface-dependency"
    elif active_nat:
        dependency = "nat-gateway-dependency"
    elif route_tables:
        dependency = "route-table-association-dependency"
    else:
        dependency = "aws-eventual-consistency-or-unclassified-subnet-dependency"

    current_history_value = parse_json_bytes(run_logged(output, "s3-object-history-partial-recovery", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Current S3 history")
    current_history = TEARDOWN.history_counts(current_history_value)
    before_history = incident["before_history"]
    state_delta = current_history["stateVersions"] - before_history["stateVersions"]
    require(1 <= state_delta <= 91, "Partial apply state object-version delta is outside the reviewed bound")
    require(current_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Partial apply created a state delete marker")
    require(current_history["lockVersions"] - before_history["lockVersions"] == 1 and current_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Partial apply lock lifecycle changed")
    TEARDOWN.require_clean_lock(current_history)

    evidence = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"], "incidentControlPlaneCommit": INCIDENT_CONTROL_PLANE_COMMIT,
        "completedAtUtc": utc_text(current), "privateRecoveryRequestSha256": file_sha256(context["request_path"]),
        "privateDestroyRequestSha256": DESTROY_REQUEST_SHA256, "binaryPlanSha256": BINARY_PLAN_SHA256,
        "partialStateSha256": file_sha256(state_path), "stateSerial": state.get("serial"),
        "managedStateAddressCount": 2, "dataStateAddressCount": data_instances,
        "totalStateAddressCount": len(listed), "stateAddressInventorySha256": address_digest(listed),
        "pendingManagedAddressCount": 2, "pendingManagedAddressSha256": address_digest(PENDING_ADDRESSES),
        "eksClusterAbsent": True, "vpcPresent": True, "subnetPresent": True,
        "networkInterfaceCount": len(enis), "networkInterfaceTypeHistogram": interface_types,
        "requesterManagedNetworkInterfaceCount": requester_managed_count,
        "activeInstanceCount": instance_count, "activeNatGatewayCount": len(active_nat),
        "subnetRouteTableAssociationCount": len(route_tables), "dependencyClassification": dependency,
        "stateObjectVersionDelta": state_delta, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1, "lockObjectAbsent": True,
        "terraformInitExecuted": False, "terraformPlanExecuted": False,
        "terraformApplyExecutedByRecovery": False, "terraformDestroyExecutedByRecovery": False,
        "statePushExecuted": False, "automaticRetryPerformed": False, "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-partial-teardown-recovery-evidence.json"
    write_private_json(evidence_path, evidence)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery-result-v1",
        "status": "aws-dev-partial-teardown-read-only-recovery-completed",
        "completed_at_utc": utc_text(current), "control_plane_commit": request["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": evidence["privateRecoveryRequestSha256"],
        "private_destroy_request_sha256": DESTROY_REQUEST_SHA256,
        "recovery_evidence_sha256": file_sha256(evidence_path), "partial_state_sha256": evidence["partialStateSha256"],
        "state_serial": state.get("serial"), "managed_state_address_count": 2,
        "data_state_address_count": data_instances, "total_state_address_count": len(listed),
        "state_address_inventory_sha256": evidence["stateAddressInventorySha256"],
        "pending_managed_address_count": 2, "pending_managed_address_sha256": evidence["pendingManagedAddressSha256"],
        "eks_cluster_absent": True, "vpc_present": True, "subnet_present": True,
        "network_interface_count": len(enis), "network_interface_type_histogram": interface_types,
        "requester_managed_network_interface_count": requester_managed_count,
        "active_instance_count": instance_count, "active_nat_gateway_count": len(active_nat),
        "subnet_route_table_association_count": len(route_tables), "dependency_classification": dependency,
        "state_object_version_delta": state_delta, "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1, "lock_delete_marker_delta": 1, "lock_object_absent": True,
        "terraform_init_executed": False, "terraform_plan_executed": False,
        "terraform_apply_executed_by_recovery": False, "terraform_destroy_executed_by_recovery": False,
        "state_push_executed": False, "automatic_retry_performed": False, "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False, "private_object_version_id_emitted": False,
        "next_action": "design-separately-approved-two-resource-final-cleanup-from-read-only-evidence",
    }
    result_path = output / "aws-dev-partial-teardown-recovery-result.json"
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
        parser.exit(1, f"AWS-dev partial-teardown recovery stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

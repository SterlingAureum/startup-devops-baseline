#!/usr/bin/env python3
"""Verify or execute read-only recovery after the failed final VPC delete."""

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
FINAL_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup.py"
CONFIRMATION = "inspect-failed-vpc-only-final-cleanup-read-only"
INCIDENT_CONTROL_PLANE_COMMIT = "184a892f990c62f61b37ae4266465ff23950f003"
FINAL_REQUEST_SHA256 = "aba7cb60002dbc6a09b38caa3b6633c356df9ee5401e030634bb712ad09c8bf6"
PREPARE_REQUEST_SHA256 = "19e9a2b1d39e8e79d6721563f9f598761a82e045af4ff8309d7e27efa685e847"
BINARY_PLAN_SHA256 = "9e7f4aaab0c4625b88ad588300e7105b65ce58a2939ff079cf24c987f060d321"
PLAN_JSON_SHA256 = "92040c72cb81e8dda766a8719365b977962fa526eea10234ac344ac2dfaf2ddf"
PLAN_TEXT_SHA256 = "e0f8914e2b969279e3271770b356245ca6831e0758ddf4f79d19ffb5fb3ec241"
INVENTORY_SHA256 = "b527d64d7e4cce9cc7bed9a8c2145a96666038a5fa9990394e1a3d235366ed26"
PLAN_RECORD_SHA256 = "6544023dafd586b15790db84f35c47b5f5b33f4a63854d29177c5ab46c082e57"
APPLY_STDOUT_SHA256 = "48aab2cedc8a3249cd03863cd8739f2364bd467355864dceb55e69aad66cec7a"
APPLY_STDERR_SHA256 = "686a2fc7f80bd7c99551340afc7c64ff1e45be88ce760972acc90ccf8f4db0e7"
VPC_ADDRESS = "module.vpc.aws_vpc.this"
SUBNET_ADDRESS = 'module.vpc.aws_subnet.private["us-east-1b"]'
PLANNED_ADDRESSES = {SUBNET_ADDRESS, VPC_ADDRESS}
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


FINAL = load_module(FINAL_PATH, "aws_dev_final_cleanup_vpc_recovery_dependency")
RECOVERY = FINAL.RECOVERY
TEARDOWN = FINAL.TEARDOWN
PRIOR = FINAL.PRIOR
APPLY = FINAL.APPLY
BASE = FINAL.BASE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def lines_sha256(values: set[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(values)) + ("\n" if values else "")).encode()).hexdigest()


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
        "awsIdentityRead": True,
        "terraformVersionRead": True,
        "terraformStateRead": True,
        "s3ObjectHistoryRead": True,
        "ec2VpcDependencyReads": True,
        "elasticLoadBalancingReads": True,
        "terraformInit": False,
        "terraformPlan": False,
        "terraformApply": False,
        "terraformDestroy": False,
        "statePush": False,
        "directAwsMutation": False,
        "directS3Mutation": False,
        "forceUnlock": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }


def incident_boundary() -> dict[str, Any]:
    return {
        "incidentControlPlaneCommit": INCIDENT_CONTROL_PLANE_COMMIT,
        "privateFinalRequestSha256": FINAL_REQUEST_SHA256,
        "privatePrepareRequestSha256": PREPARE_REQUEST_SHA256,
        "binaryPlanSha256": BINARY_PLAN_SHA256,
        "planJsonSha256": PLAN_JSON_SHA256,
        "planTextSha256": PLAN_TEXT_SHA256,
        "addressInventorySha256": INVENTORY_SHA256,
        "planRecordSha256": PLAN_RECORD_SHA256,
        "applyStdoutSha256": APPLY_STDOUT_SHA256,
        "applyStderrSha256": APPLY_STDERR_SHA256,
        "plannedManagedDeleteCount": 2,
        "startedManagedDeleteCount": 2,
        "completedManagedDeleteCount": 1,
        "completedAddress": SUBNET_ADDRESS,
        "pendingAddress": VPC_ADDRESS,
        "failureOperation": "DeleteVpc",
        "failureCode": "DependencyViolation",
        "applyCompleteMarkerPresent": False,
        "finalStateArtifactPresent": False,
        "finalEvidencePresent": False,
        "finalResultPresent": False,
    }


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion", "operation", "repository", "trustedRef", "expectedMainCommit",
        "expectedAwsAccountId", "expectedTerraformVersion", "privateFinalRequestPath",
        "privateFinalApplyOutputDirectory", "privateRecoveryOutputDirectory",
        "incidentBoundary", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Recovery request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline" and value["trustedRef"] == "refs/heads/main", "Repository trust boundary changed")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]), "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]), "Expected AWS account is invalid")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]), "Terraform version is invalid")
    for key in ("privateFinalRequestPath", "privateFinalApplyOutputDirectory", "privateRecoveryOutputDirectory"):
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
        stripped = line.strip()
        destroying = re.match(r"^(.+?): Destroying\.\.\.", stripped)
        destroyed = re.match(r"^(.+?): Destruction complete after", stripped)
        if destroying:
            started.add(destroying.group(1))
        if destroyed:
            completed.add(destroyed.group(1))
    return started, completed


def expected_plan_boundary() -> dict[str, Any]:
    return {
        "privatePrepareRequestSha256": PREPARE_REQUEST_SHA256,
        "binaryPlanSha256": BINARY_PLAN_SHA256,
        "planJsonSha256": PLAN_JSON_SHA256,
        "planTextSha256": PLAN_TEXT_SHA256,
        "addressInventorySha256": INVENTORY_SHA256,
        "planRecordSha256": PLAN_RECORD_SHA256,
        "managedDeleteCount": 2,
        "dataChangeCount": 0,
        "resourceDriftCount": 0,
        "importCount": 0,
        "humanReviewed": True,
        "orphanNetworkInterfaceDeleted": True,
        "planReviewExpiresAtUtc": "2026-10-08T11:29:00Z",
    }


def validate_incident(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    final_request_path = require_private_file(Path(request["privateFinalRequestPath"]), "Private final request")
    require(not is_within(final_request_path, repository_root), "Final request must remain outside the repository")
    require(file_sha256(final_request_path) == FINAL_REQUEST_SHA256, "Final request digest changed")
    final_request = FINAL.validate_final_request(load_json(final_request_path, "Private final request"))
    require(final_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT, "Incident control-plane commit changed")
    require(final_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "AWS account changed since final apply")
    require(final_request["expectedTerraformVersion"] == request["expectedTerraformVersion"], "Terraform version changed since final apply")
    require(final_request["planBoundary"] == expected_plan_boundary(), "Reviewed final-plan boundary changed")

    prepare_request_path = require_private_file(Path(final_request["privatePrepareRequestPath"]), "Private prepare request")
    require(file_sha256(prepare_request_path) == PREPARE_REQUEST_SHA256, "Prepare request digest changed")
    prepare_request = FINAL.validate_prepare_request(load_json(prepare_request_path, "Private prepare request"))
    require(prepare_request["expectedMainCommit"] == INCIDENT_CONTROL_PLANE_COMMIT, "Prepare control-plane commit changed")
    recovery = FINAL.validate_recovery(prepare_request, repository_root)

    prepare_output = require_private_directory(Path(final_request["privatePrepareOutputDirectory"]), "Private prepare output")
    require(str(prepare_output) == prepare_request["privatePrepareOutputDirectory"], "Prepare output path changed")
    artifact_digests = {
        "aws-dev-final-cleanup.tfplan": BINARY_PLAN_SHA256,
        "aws-dev-final-cleanup-plan.json": PLAN_JSON_SHA256,
        "aws-dev-final-cleanup-plan.txt": PLAN_TEXT_SHA256,
        "final-cleanup-address-inventory.json": INVENTORY_SHA256,
        "final-cleanup-plan-record.json": PLAN_RECORD_SHA256,
    }
    for name, digest in artifact_digests.items():
        require(file_sha256(require_private_file(prepare_output / name, f"Final-plan artifact {name}")) == digest, f"Final-plan artifact digest changed: {name}")
    gated = FINAL.final_plan_gate(load_json(prepare_output / "aws-dev-final-cleanup-plan.json", "Final plan JSON"))
    require(set(gated["managedDeleteAddresses"]) == PLANNED_ADDRESSES, "Final plan address inventory changed")

    final_output = require_private_directory(Path(request["privateFinalApplyOutputDirectory"]), "Private final apply output")
    require(str(final_output) == final_request["privateFinalOutputDirectory"], "Final output path changed")
    require(not is_within(final_output, repository_root), "Final output must remain outside repository")
    stdout_path = require_private_file(final_output / "terraform-apply-reviewed-final-plan.stdout", "Failed final apply stdout")
    stderr_path = require_private_file(final_output / "terraform-apply-reviewed-final-plan.stderr", "Failed final apply stderr")
    require(file_sha256(stdout_path) == APPLY_STDOUT_SHA256 and file_sha256(stderr_path) == APPLY_STDERR_SHA256, "Failed final apply logs changed")
    stdout = stdout_path.read_bytes()
    stderr = stderr_path.read_bytes()
    started, completed = parse_apply_addresses(stdout)
    require(started == PLANNED_ADDRESSES and completed == {SUBNET_ADDRESS}, "Failed final apply address inventory changed")
    require(b"DependencyViolation" in stderr and b"DeleteVpc" in stderr, "Final apply failure category changed")
    require(b"Apply complete!" not in stdout, "Failed final apply unexpectedly has a success marker")
    for name in ("aws-dev-state-after-final-cleanup.json", "aws-dev-final-cleanup-evidence.json", "aws-dev-final-cleanup-result.json"):
        require(not (final_output / name).exists(), f"Failed final apply unexpectedly produced {name}")

    eni_stdout = require_private_file(final_output / "network-interface-before-final-apply.stdout", "Pre-apply ENI absence stdout")
    eni_stderr = require_private_file(final_output / "network-interface-before-final-apply.stderr", "Pre-apply ENI absence stderr")
    require(eni_stdout.read_bytes() == b"" and b"InvalidNetworkInterfaceID.NotFound" in eni_stderr.read_bytes(), "Orphan ENI absence proof changed")
    before_history_path = require_private_file(final_output / "s3-object-history-before-final-apply.stdout", "Pre-final-apply S3 history")
    before_history_stderr = require_private_file(final_output / "s3-object-history-before-final-apply.stderr", "Pre-final-apply S3 history stderr")
    require(before_history_stderr.read_bytes() == b"", "Pre-final-apply S3 history produced stderr")
    before_history = TEARDOWN.history_counts(parse_json_bytes(before_history_path.read_bytes(), "Pre-final-apply S3 history"))
    TEARDOWN.require_clean_lock(before_history)
    return {
        "final_request_path": final_request_path,
        "final_request": final_request,
        "prepare_request": prepare_request,
        "prepare_output": prepare_output,
        "recovery": recovery,
        "final_output": final_output,
        "before_history": before_history,
        "started": started,
        "completed": completed,
    }


def verify_inputs(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, now: datetime | None = None) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private VPC-only recovery request")
    require(not is_within(private_request, repository_root), "Recovery request must remain outside repository")
    request = validate_request(load_json(private_request, "Private VPC-only recovery request"))
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
    require(not is_within(output, repository_root), "Recovery output must remain outside repository")
    for protected in (incident["final_output"], incident["prepare_output"], incident["recovery"]["output"]):
        require(not is_within(output, protected) and not is_within(protected, output), "Recovery output must not overlap preserved evidence")
    return {"request": request, "request_path": private_request, "incident": incident, "output": output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-vpc-only-recovery-inputs-verified",
        "control_plane_commit": context["request"]["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": file_sha256(context["request_path"]),
        "private_final_request_sha256": FINAL_REQUEST_SHA256,
        "binary_plan_sha256": BINARY_PLAN_SHA256,
        "apply_stdout_sha256": APPLY_STDOUT_SHA256,
        "apply_stderr_sha256": APPLY_STDERR_SHA256,
        "planned_managed_delete_count": 2,
        "completed_managed_delete_count": 1,
        "pending_managed_address_count": 1,
        "subnet_destroyed": True,
        "vpc_delete_dependency_failure_verified": True,
        "remaining_recovery_approval_seconds": context["remaining"],
        "operational_commands_executed": [],
        "terraform_init_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "terraform_destroy_authorized": False,
        "state_push_authorized": False,
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-vpc-only-read-only-recovery-approval",
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


def collection(value: dict[str, Any], key: str, label: str) -> list[dict[str, Any]]:
    items = value.get(key)
    require(isinstance(items, list) and all(isinstance(item, dict) for item in items), f"{label} response changed")
    return items


def active(items: list[dict[str, Any]], state_key: str = "State", terminal: set[str] | None = None) -> list[dict[str, Any]]:
    # A resource that is still deleting can continue to block DeleteVpc, so it
    # remains part of the dependency inventory until it reaches a terminal
    # absent/failed/rejected state.
    terminal = terminal or {"deleted", "failed", "rejected", "expired"}
    return [item for item in items if str(item.get(state_key, "")).lower() not in terminal]


def classify_dependencies(counts: dict[str, int]) -> list[str]:
    labels = {
        "subnetCount": "subnet",
        "networkInterfaceCount": "network-interface",
        "activeInstanceCount": "instance",
        "activeNatGatewayCount": "nat-gateway",
        "internetGatewayCount": "internet-gateway",
        "egressOnlyInternetGatewayCount": "egress-only-internet-gateway",
        "activeVpcEndpointCount": "vpc-endpoint",
        "nonMainRouteTableCount": "non-main-route-table",
        "nonDefaultSecurityGroupCount": "non-default-security-group",
        "nonDefaultNetworkAclCount": "non-default-network-acl",
        "activeVpcPeeringConnectionCount": "vpc-peering-connection",
        "attachedVpnGatewayCount": "vpn-gateway",
        "activeTransitGatewayAttachmentCount": "transit-gateway-attachment",
        "loadBalancerCount": "load-balancer",
        "classicLoadBalancerCount": "classic-load-balancer",
    }
    return [label for key, label in labels.items() if counts.get(key, 0) > 0]


def execute(request_path: Path, *, repository_root: Path = ROOT, git_runner: GitRunner = run_git, runner: CommandRunner = run_command, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_VPC_ONLY_RECOVERY") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_VPC_ONLY_RECOVERY={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_FINAL_CLEANUP_PREPARE", "CONFIRM_AWS_DEV_FINAL_CLEANUP_APPLY",
        "CONFIRM_AWS_DEV_TEARDOWN_DESTROY", "CONFIRM_AWS_DEV_DESTROY",
        "CONFIRM_TERRAFORM_APPLY", "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Mutation confirmations must be unset")
    request = context["request"]
    incident = context["incident"]
    recovery = incident["recovery"]
    plan_evidence = recovery["incident"]["recovery"]["plan_evidence"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = BASE.safe_environment(plan_evidence["terraform_data"])
    dev_root = plan_evidence["source"] / "environments/dev"
    backend = plan_evidence["incident"]["chain"]["backend"]
    vpc_id = RECOVERY.raw_attribute(recovery["state"], "module.vpc", "aws_vpc", "this", None, "id")
    require(isinstance(vpc_id, str) and vpc_id.startswith("vpc-"), "Recovered VPC identity changed")

    identity = parse_json_bytes(run_logged(output, "aws-identity-vpc-only-recovery", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    version = parse_json_bytes(run_logged(output, "terraform-version-vpc-only-recovery", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    pulled = run_logged(output, "terraform-state-pull-vpc-only-recovery", ["terraform", "state", "pull"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    state_path = output / "aws-dev-state-vpc-only-recovery.json"
    write_private(state_path, pulled.stdout)
    state = parse_json_bytes(pulled.stdout, "VPC-only remote state")
    managed_instances, data_instances = PRIOR.state_instance_counts(state)
    require(managed_instances == 1 and data_instances == 0, "VPC-only state mode counts changed")
    listed = TEARDOWN.state_list(run_logged(output, "terraform-state-list-vpc-only-recovery", ["terraform", "state", "list"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout)
    require(listed == {VPC_ADDRESS}, "Live state is not the exact VPC-only inventory")
    shown = parse_json_bytes(run_logged(output, "terraform-show-state-vpc-only-recovery", ["terraform", "show", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "VPC-only Terraform state show")
    require(APPLY.show_state_addresses(shown) == listed, "VPC-only state list and show inventories differ")
    require(RECOVERY.raw_attribute(state, "module.vpc", "aws_vpc", "this", None, "id") == vpc_id, "Live VPC state identity changed")

    region = TEARDOWN.AWS_REGION
    def aws_read(label: str, arguments: list[str], response_label: str) -> dict[str, Any]:
        return parse_json_bytes(run_logged(output, label, ["aws", *arguments, "--region", region, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, response_label)

    vpcs = collection(aws_read("vpc-vpc-only-recovery", ["ec2", "describe-vpcs", "--vpc-ids", vpc_id], "VPC read"), "Vpcs", "VPC")
    require(len(vpcs) == 1 and vpcs[0].get("VpcId") == vpc_id, "Pending VPC is not present exactly once")
    subnets = collection(aws_read("subnets-vpc-only-recovery", ["ec2", "describe-subnets", "--filters", f"Name=vpc-id,Values={vpc_id}"], "Subnet read"), "Subnets", "Subnet")
    enis = collection(aws_read("network-interfaces-vpc-only-recovery", ["ec2", "describe-network-interfaces", "--filters", f"Name=vpc-id,Values={vpc_id}"], "Network-interface read"), "NetworkInterfaces", "Network-interface")
    instances_value = aws_read("instances-vpc-only-recovery", ["ec2", "describe-instances", "--filters", f"Name=vpc-id,Values={vpc_id}", "Name=instance-state-name,Values=pending,running,stopping,stopped"], "Instance read")
    reservations = collection(instances_value, "Reservations", "Instance")
    instance_count = sum(len(item.get("Instances", [])) for item in reservations if isinstance(item.get("Instances", []), list))
    nat = collection(aws_read("nat-gateways-vpc-only-recovery", ["ec2", "describe-nat-gateways", "--filter", f"Name=vpc-id,Values={vpc_id}"], "NAT gateway read"), "NatGateways", "NAT gateway")
    igws = collection(aws_read("internet-gateways-vpc-only-recovery", ["ec2", "describe-internet-gateways", "--filters", f"Name=attachment.vpc-id,Values={vpc_id}"], "Internet gateway read"), "InternetGateways", "Internet gateway")
    eigws = collection(aws_read("egress-only-internet-gateways-vpc-only-recovery", ["ec2", "describe-egress-only-internet-gateways", "--filters", f"Name=attachment.vpc-id,Values={vpc_id}"], "Egress-only internet gateway read"), "EgressOnlyInternetGateways", "Egress-only internet gateway")
    endpoints = collection(aws_read("vpc-endpoints-vpc-only-recovery", ["ec2", "describe-vpc-endpoints", "--filters", f"Name=vpc-id,Values={vpc_id}"], "VPC endpoint read"), "VpcEndpoints", "VPC endpoint")
    route_tables = collection(aws_read("route-tables-vpc-only-recovery", ["ec2", "describe-route-tables", "--filters", f"Name=vpc-id,Values={vpc_id}"], "Route-table read"), "RouteTables", "Route-table")
    security_groups = collection(aws_read("security-groups-vpc-only-recovery", ["ec2", "describe-security-groups", "--filters", f"Name=vpc-id,Values={vpc_id}"], "Security-group read"), "SecurityGroups", "Security-group")
    network_acls = collection(aws_read("network-acls-vpc-only-recovery", ["ec2", "describe-network-acls", "--filters", f"Name=vpc-id,Values={vpc_id}"], "Network-ACL read"), "NetworkAcls", "Network-ACL")
    requester_peerings = collection(aws_read("requester-vpc-peerings-vpc-only-recovery", ["ec2", "describe-vpc-peering-connections", "--filters", f"Name=requester-vpc-info.vpc-id,Values={vpc_id}"], "Requester VPC peering read"), "VpcPeeringConnections", "Requester VPC peering")
    accepter_peerings = collection(aws_read("accepter-vpc-peerings-vpc-only-recovery", ["ec2", "describe-vpc-peering-connections", "--filters", f"Name=accepter-vpc-info.vpc-id,Values={vpc_id}"], "Accepter VPC peering read"), "VpcPeeringConnections", "Accepter VPC peering")
    vpn_gateways = collection(aws_read("vpn-gateways-vpc-only-recovery", ["ec2", "describe-vpn-gateways", "--filters", f"Name=attachment.vpc-id,Values={vpc_id}"], "VPN gateway read"), "VpnGateways", "VPN gateway")
    transit_attachments = collection(aws_read("transit-gateway-attachments-vpc-only-recovery", ["ec2", "describe-transit-gateway-vpc-attachments", "--filters", f"Name=vpc-id,Values={vpc_id}"], "Transit gateway attachment read"), "TransitGatewayVpcAttachments", "Transit gateway attachment")
    elbv2 = collection(aws_read("load-balancers-vpc-only-recovery", ["elbv2", "describe-load-balancers"], "Load balancer read"), "LoadBalancers", "Load balancer")
    classic_elb = collection(aws_read("classic-load-balancers-vpc-only-recovery", ["elb", "describe-load-balancers"], "Classic load balancer read"), "LoadBalancerDescriptions", "Classic load balancer")

    active_peerings_by_id = {
        str(item.get("VpcPeeringConnectionId")): item
        for item in requester_peerings + accepter_peerings
        if str(item.get("Status", {}).get("Code", "")).lower() not in {"deleted", "rejected", "expired", "failed"}
    }
    counts = {
        "subnetCount": len(subnets),
        "networkInterfaceCount": len(enis),
        "activeInstanceCount": instance_count,
        "activeNatGatewayCount": len(active(nat)),
        "internetGatewayCount": len(igws),
        "egressOnlyInternetGatewayCount": len(eigws),
        "activeVpcEndpointCount": len(active(endpoints)),
        "routeTableCount": len(route_tables),
        "mainRouteTableCount": sum(any(association.get("Main") is True for association in item.get("Associations", []) if isinstance(association, dict)) for item in route_tables),
        "nonMainRouteTableCount": sum(not any(association.get("Main") is True for association in item.get("Associations", []) if isinstance(association, dict)) for item in route_tables),
        "securityGroupCount": len(security_groups),
        "defaultSecurityGroupCount": sum(item.get("GroupName") == "default" for item in security_groups),
        "nonDefaultSecurityGroupCount": sum(item.get("GroupName") != "default" for item in security_groups),
        "networkAclCount": len(network_acls),
        "defaultNetworkAclCount": sum(item.get("IsDefault") is True for item in network_acls),
        "nonDefaultNetworkAclCount": sum(item.get("IsDefault") is not True for item in network_acls),
        "activeVpcPeeringConnectionCount": len(active_peerings_by_id),
        "attachedVpnGatewayCount": len(vpn_gateways),
        "activeTransitGatewayAttachmentCount": len(active(transit_attachments)),
        "loadBalancerCount": sum(item.get("VpcId") == vpc_id for item in elbv2),
        "classicLoadBalancerCount": sum(item.get("VPCId") == vpc_id for item in classic_elb),
    }
    classifications = classify_dependencies(counts)
    interface_types = dict(sorted(Counter(str(item.get("InterfaceType", "unknown")) for item in enis).items()))

    current_history = TEARDOWN.history_counts(parse_json_bytes(run_logged(output, "s3-object-history-vpc-only-recovery", ["aws", "s3api", "list-object-versions", "--bucket", backend["bucket"], "--prefix", TEARDOWN.STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "Current S3 history"))
    before_history = incident["before_history"]
    state_delta = current_history["stateVersions"] - before_history["stateVersions"]
    require(1 <= state_delta <= 3, "Failed final apply state object-version delta is outside the reviewed bound")
    require(current_history["stateDeleteMarkers"] == before_history["stateDeleteMarkers"] == 0, "Failed final apply created a state delete marker")
    require(current_history["lockVersions"] - before_history["lockVersions"] == 1 and current_history["lockDeleteMarkers"] - before_history["lockDeleteMarkers"] == 1, "Failed final apply lock lifecycle changed")
    TEARDOWN.require_clean_lock(current_history)

    evidence = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "incidentControlPlaneCommit": INCIDENT_CONTROL_PLANE_COMMIT,
        "completedAtUtc": utc_text(current),
        "privateRecoveryRequestSha256": file_sha256(context["request_path"]),
        "privateFinalRequestSha256": FINAL_REQUEST_SHA256,
        "binaryPlanSha256": BINARY_PLAN_SHA256,
        "applyStdoutSha256": APPLY_STDOUT_SHA256,
        "applyStderrSha256": APPLY_STDERR_SHA256,
        "vpcOnlyStateSha256": file_sha256(state_path),
        "stateSerial": state.get("serial"),
        "managedStateAddressCount": 1,
        "dataStateAddressCount": 0,
        "stateAddressCount": 1,
        "stateAddressInventorySha256": lines_sha256(listed),
        "subnetDestroyed": True,
        "vpcPresent": True,
        **counts,
        "networkInterfaceTypeHistogram": interface_types,
        "dependencyClassifications": classifications or ["aws-eventual-consistency-or-unclassified-vpc-dependency"],
        "stateObjectVersionDelta": state_delta,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
        "lockObjectAbsent": True,
        "terraformInitExecuted": False,
        "terraformPlanExecuted": False,
        "terraformApplyExecutedByRecovery": False,
        "terraformDestroyExecutedByRecovery": False,
        "statePushExecuted": False,
        "directAwsMutationExecuted": False,
        "automaticRetryPerformed": False,
        "automaticRollbackPerformed": False,
    }
    evidence_path = output / "aws-dev-vpc-only-recovery-evidence.json"
    write_private_json(evidence_path, evidence)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery-result-v1",
        "status": "aws-dev-vpc-only-read-only-recovery-completed",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "incident_control_plane_commit": INCIDENT_CONTROL_PLANE_COMMIT,
        "private_recovery_request_sha256": evidence["privateRecoveryRequestSha256"],
        "private_final_request_sha256": FINAL_REQUEST_SHA256,
        "recovery_evidence_sha256": file_sha256(evidence_path),
        "vpc_only_state_sha256": evidence["vpcOnlyStateSha256"],
        "state_serial": state.get("serial"),
        "managed_state_address_count": 1,
        "data_state_address_count": 0,
        "total_state_address_count": 1,
        "state_address_inventory_sha256": evidence["stateAddressInventorySha256"],
        "subnet_destroyed": True,
        "vpc_present": True,
        **{key[0].lower() + re.sub(r"([A-Z])", r"_\1", key[1:]).lower(): value for key, value in counts.items()},
        "network_interface_type_histogram": interface_types,
        "dependency_classifications": evidence["dependencyClassifications"],
        "state_object_version_delta": state_delta,
        "state_delete_marker_delta": 0,
        "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1,
        "lock_object_absent": True,
        "terraform_init_executed": False,
        "terraform_plan_executed": False,
        "terraform_apply_executed_by_recovery": False,
        "terraform_destroy_executed_by_recovery": False,
        "state_push_executed": False,
        "direct_aws_mutation_executed": False,
        "automatic_retry_performed": False,
        "automatic_rollback_performed": False,
        "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "design-separately-approved-exact-vpc-dependency-cleanup-from-read-only-evidence",
    }
    result_path = output / "aws-dev-vpc-only-recovery-result.json"
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
        parser.exit(1, f"AWS-dev VPC-only recovery stopped: {error}; preserve all private evidence and do not retry automatically\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

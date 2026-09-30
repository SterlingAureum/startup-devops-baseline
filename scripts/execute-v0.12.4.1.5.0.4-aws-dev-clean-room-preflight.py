#!/usr/bin/env python3
"""Verify or execute the guarded aws-dev remote-state clean-room preflight."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any, Callable
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "infra/terraform/aws"
DEV_ROOT = SOURCE_ROOT / "environments/dev"
CONFIRMATION = "inspect-empty-aws-dev-remote-state-clean-room"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
STATE_KEY = "environments/dev/terraform.tfstate"
LOCK_KEY = STATE_KEY + ".tflock"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 120
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
BUCKET_RE = re.compile(r"(?=.{3,63}\Z)[a-z0-9][a-z0-9.-]*[a-z0-9]")
EXPECTED_BACKEND_BLOCK = '''terraform {
  backend "s3" {}

  # Backend values are materialized only in an owner-readable private file
  # generated from state-bootstrap output. This root is initialized only from
  # a reviewed private staged source after remote state and lock absence proof.
  # Clean-room creation uses terraform init -reconfigure, never -migrate-state.
}
'''


class PreflightError(ValueError):
    pass


class CommandFailure(PreflightError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_private(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def write_private_json(path: Path, value: Any) -> None:
    write_private(path, canonical_json(value))


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise PreflightError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise PreflightError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise PreflightError(f"{label} must be a valid UTC timestamp") from error
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
        "expectedAwsAccountId", "expectedAwsRegion", "expectedClusterName",
        "expectedStateBucketName", "expectedStateBucketArn", "expectedStateKmsKeyArn",
        "expectedDevStateAccessPolicyArn", "privateBackendConfigPath",
        "privateBackendConfigSha256", "privatePreflightOutputDirectory",
        "privateStagedSourceDirectory", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Preflight request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    account = value["expectedAwsAccountId"]
    require(isinstance(account, str) and ACCOUNT_RE.fullmatch(account) is not None, "Expected AWS account is invalid")
    require(value["expectedAwsRegion"] == AWS_REGION, "AWS region changed")
    require(value["expectedClusterName"] == CLUSTER_NAME, "Cluster name changed")
    bucket = value["expectedStateBucketName"]
    require(isinstance(bucket, str) and BUCKET_RE.fullmatch(bucket) is not None, "State bucket name is invalid")
    require(value["expectedStateBucketArn"] == f"arn:aws:s3:::{bucket}", "State bucket ARN does not match bucket")
    kms_arn = value["expectedStateKmsKeyArn"]
    require(isinstance(kms_arn, str) and re.fullmatch(rf"arn:aws:kms:{AWS_REGION}:{account}:key/[0-9a-f-]+", kms_arn) is not None, "State KMS key ARN is invalid")
    require(value["expectedDevStateAccessPolicyArn"] == f"arn:aws:iam::{account}:policy/startup-devops-baseline-terraform-state-dev", "Dev state policy ARN is invalid")
    for key in ("privateBackendConfigPath", "privatePreflightOutputDirectory", "privateStagedSourceDirectory"):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(isinstance(value["privateBackendConfigSha256"], str) and SHA256_RE.fullmatch(value["privateBackendConfigSha256"]) is not None, "Backend config digest is invalid")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most one hour")
    require(value["executionBoundary"] == {
        "awsReadOnlyValidation": True,
        "localPrivateSourceStaging": True,
        "terraformInit": False,
        "terraformPlan": False,
        "terraformApply": False,
        "stateMigration": False,
        "statePush": False,
        "destroy": False,
        "iamPolicyAttachment": False,
        "kubernetesCommand": False,
        "secretValueRead": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }, "Execution boundary changed")
    return value


def parse_backend_config(path: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z_]+)\s*=\s*(.+)", line)
        require(match is not None, "Backend config contains unsupported syntax")
        key, encoded = match.groups()
        require(key not in values, f"Duplicate backend config key: {key}")
        try:
            values[key] = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise PreflightError(f"Backend config value is invalid: {key}") from error
    require(set(values) == {"bucket", "key", "region", "encrypt", "kms_key_id", "use_lockfile", "allowed_account_ids"}, "Backend config fields changed")
    return values


def validate_backend_config(values: dict[str, Any], request: dict[str, Any]) -> None:
    require(values["bucket"] == request["expectedStateBucketName"], "Backend bucket changed")
    require(values["key"] == STATE_KEY, "Backend state key changed")
    require(values["region"] == AWS_REGION, "Backend region changed")
    require(values["encrypt"] is True, "Backend encryption disabled")
    require(values["kms_key_id"] == request["expectedStateKmsKeyArn"], "Backend KMS key changed")
    require(values["use_lockfile"] is True, "Native lockfile disabled")
    require(values["allowed_account_ids"] == [request["expectedAwsAccountId"]], "Backend account guard changed")


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise PreflightError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def tracked_source_entries(root: Path, git_runner: GitRunner) -> list[dict[str, str]]:
    raw = git_runner(["ls-files", "-s", "--", "infra/terraform/aws"])
    require(raw, "Tracked AWS Terraform source is empty")
    entries: list[dict[str, str]] = []
    for line in raw.splitlines():
        metadata, relative = line.split("\t", 1)
        mode, _blob, stage = metadata.split()
        require(stage == "0", "Unmerged Terraform source entry found")
        require(mode in {"100644", "100755"}, f"Unsupported Terraform source mode: {relative}")
        path = root / relative
        require(path.is_file() and not path.is_symlink(), f"Terraform source is not a regular file: {relative}")
        require(is_within(path.resolve(strict=True), (root / "infra/terraform/aws").resolve(strict=True)), f"Terraform source escaped root: {relative}")
        require("/.terraform/" not in f"/{relative}/" and not relative.endswith(".tfstate") and ".tfstate." not in relative, f"Stateful source file tracked: {relative}")
        require(not (relative.endswith(".tfbackend") and not relative.endswith(".example")), f"Materialized backend config tracked: {relative}")
        require(not (relative.endswith("terraform.tfvars") and not relative.endswith(".example")), f"Materialized private tfvars tracked: {relative}")
        entries.append({"path": relative, "gitMode": mode, "sha256": file_sha256(path)})
    entries.sort(key=lambda item: item["path"])
    return entries


def source_manifest_digest(entries: list[dict[str, str]]) -> str:
    return sha256_bytes(canonical_json(entries))


def validate_local_absence() -> None:
    forbidden = []
    for path in DEV_ROOT.rglob("*"):
        relative = path.relative_to(DEV_ROOT)
        text = str(relative)
        if ".terraform" in relative.parts:
            forbidden.append(text)
        elif path.is_file() and (
            path.name == "terraform.tfvars"
            or path.suffix == ".tfplan"
            or path.suffix == ".tfstate"
            or ".tfstate." in path.name
            or (path.suffix == ".tfbackend" and not path.name.endswith(".example"))
        ):
            forbidden.append(text)
    require(not forbidden, "Dev root contains local state, plan or materialized private input")


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private preflight request")
    require(not is_within(private_request, repository_root), "Preflight request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private preflight request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Preflight approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Preflight approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Preflight must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Preflight requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main, "HEAD does not equal reviewed main")
    require(git_runner(["rev-parse", "origin/main"]) == expected_main, "origin/main does not equal reviewed main")
    require((repository_root / "infra/terraform/aws/environments/dev/backend.tf").read_text() == EXPECTED_BACKEND_BLOCK, "Dev partial backend declaration changed")
    validate_local_absence()

    backend_path = require_private_file(Path(request["privateBackendConfigPath"]), "Private backend config")
    require(not is_within(backend_path, repository_root), "Backend config must remain outside the repository")
    require(file_sha256(backend_path) == request["privateBackendConfigSha256"], "Backend config digest changed")
    backend = parse_backend_config(backend_path)
    validate_backend_config(backend, request)

    output = require_new_private_directory(Path(request["privatePreflightOutputDirectory"]), "Private preflight output")
    staging = require_new_private_directory(Path(request["privateStagedSourceDirectory"]), "Private staged source")
    require(not is_within(output, repository_root) and not is_within(staging, repository_root), "Private output must remain outside the repository")
    require(output != staging and not is_within(output, staging) and not is_within(staging, output), "Private output and staging directories must be distinct")
    entries = tracked_source_entries(repository_root, git_runner)
    return {
        "request": request,
        "request_path": private_request,
        "backend_path": backend_path,
        "backend": backend,
        "output": output,
        "staging": staging,
        "source_entries": entries,
        "source_manifest_sha256": source_manifest_digest(entries),
        "remaining": remaining,
    }


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "aws-dev-remote-state-clean-room-preflight-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "private_preflight_request_sha256": file_sha256(context["request_path"]),
        "private_backend_config_sha256": request["privateBackendConfigSha256"],
        "source_manifest_sha256": context["source_manifest_sha256"],
        "tracked_source_file_count": len(context["source_entries"]),
        "remaining_preflight_approval_seconds": context["remaining"],
        "preflight_execution_authorized": False,
        "terraform_init_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "state_migration_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-aws-dev-clean-room-read-only-preflight-approval",
    }


def safe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("CONFIRM_"):
            del environment[key]
    environment["AWS_REGION"] = AWS_REGION
    environment["AWS_DEFAULT_REGION"] = AWS_REGION
    return environment


def run_logged(
    output: Path,
    label: str,
    arguments: list[str],
    environment: dict[str, str],
    runner: CommandRunner,
    repository_root: Path,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = runner(arguments, environment, COMMAND_TIMEOUT_SECONDS, repository_root)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)
    require(result.returncode == 0, f"{label} failed")
    require(result.stderr == b"", f"{label} produced stderr")
    return result


def run_expected_missing_eks(
    output: Path,
    environment: dict[str, str],
    runner: CommandRunner,
    repository_root: Path,
) -> str:
    label = "eks-cluster-expected-absent"
    try:
        result = runner(
            ["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"],
            environment,
            COMMAND_TIMEOUT_SECONDS,
            repository_root,
        )
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)
    require(result.returncode != 0, "aws-dev EKS cluster already exists")
    require(result.stdout == b"", "Missing EKS read unexpectedly returned stdout")
    match = re.search(rb"An error occurred \(([^)]+)\)", result.stderr)
    require(match is not None and match.group(1) == b"ResourceNotFoundException", "EKS absence error changed")
    return "ResourceNotFoundException"


def validate_versioning(value: dict[str, Any]) -> None:
    require(value.get("Status") == "Enabled", "State bucket versioning is not enabled")
    require(value.get("MFADelete") in {None, "Disabled"}, "Unexpected state bucket MFA delete status")


def validate_public_access(value: dict[str, Any]) -> None:
    block = value.get("PublicAccessBlockConfiguration")
    require(isinstance(block, dict) and set(block) == {"BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"}, "Public access block shape changed")
    require(all(item is True for item in block.values()), "State bucket public access block is incomplete")


def validate_encryption(value: dict[str, Any], expected_kms_arn: str) -> None:
    rules = value.get("ServerSideEncryptionConfiguration", {}).get("Rules")
    require(isinstance(rules, list) and len(rules) == 1, "State bucket encryption rule count changed")
    rule = rules[0]
    default = rule.get("ApplyServerSideEncryptionByDefault")
    require(default == {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": expected_kms_arn}, "State bucket default encryption changed")
    require(rule.get("BucketKeyEnabled") is True, "State bucket key is disabled")


def validate_empty_object_history(value: dict[str, Any]) -> dict[str, int]:
    require(value.get("IsTruncated") in {None, False}, "State object history response is truncated")
    versions = value.get("Versions", [])
    markers = value.get("DeleteMarkers", [])
    require(isinstance(versions, list) and isinstance(markers, list), "State object history shape changed")
    for item in [*versions, *markers]:
        require(item.get("Key") in {STATE_KEY, LOCK_KEY}, "Unexpected key returned for state prefix")
    counts = {
        "stateVersions": sum(item.get("Key") == STATE_KEY for item in versions),
        "stateDeleteMarkers": sum(item.get("Key") == STATE_KEY for item in markers),
        "lockVersions": sum(item.get("Key") == LOCK_KEY for item in versions),
        "lockDeleteMarkers": sum(item.get("Key") == LOCK_KEY for item in markers),
    }
    require(all(count == 0 for count in counts.values()), "Remote dev state or lock history already exists")
    return counts


def validate_kms_description(value: dict[str, Any], expected_arn: str) -> None:
    metadata = value.get("KeyMetadata")
    require(isinstance(metadata, dict), "KMS metadata missing")
    require(metadata.get("Arn") == expected_arn, "KMS key ARN changed")
    require(metadata.get("Enabled") is True and metadata.get("KeyState") == "Enabled", "KMS key is not enabled")
    require(metadata.get("KeyManager") == "CUSTOMER", "KMS key is not customer managed")
    require(metadata.get("KeyUsage") == "ENCRYPT_DECRYPT", "KMS key usage changed")
    require(metadata.get("MultiRegion") in {None, False}, "Unexpected multi-Region KMS key")


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    require(isinstance(value, list) and all(isinstance(item, str) for item in value), "IAM policy list shape changed")
    return sorted(value)


def normalize_condition_values(value: Any) -> list[str]:
    return sorted(normalize_list(value))


def validate_iam_policy_document(value: dict[str, Any], bucket_arn: str, kms_arn: str) -> None:
    document: Any = value.get("PolicyVersion", {}).get("Document")
    if isinstance(document, str):
        try:
            document = json.loads(unquote(document))
        except json.JSONDecodeError as error:
            raise PreflightError("IAM policy document is invalid") from error
    require(isinstance(document, dict) and document.get("Version") == "2012-10-17", "IAM policy document version changed")
    statements = document.get("Statement")
    require(isinstance(statements, list) and len(statements) == 4, "IAM policy statement count changed")
    by_sid = {item.get("Sid"): item for item in statements if isinstance(item, dict)}
    require(set(by_sid) == {"ListExactStateAndLockKeys", "ReadWriteExactStateObject", "ManageExactLockObject", "UseStateEncryptionKeyThroughS3"}, "IAM policy statement inventory changed")
    for statement in by_sid.values():
        require(statement.get("Effect") == "Allow", "IAM policy effect changed")

    listing = by_sid["ListExactStateAndLockKeys"]
    require(normalize_list(listing.get("Action")) == ["s3:ListBucket"], "IAM list action changed")
    require(normalize_list(listing.get("Resource")) == [bucket_arn], "IAM list resource changed")
    prefixes = listing.get("Condition", {}).get("StringEquals", {}).get("s3:prefix")
    require(normalize_condition_values(prefixes) == sorted([STATE_KEY, LOCK_KEY]), "IAM list prefix changed")

    state = by_sid["ReadWriteExactStateObject"]
    require(normalize_list(state.get("Action")) == ["s3:GetObject", "s3:PutObject"], "IAM state actions changed")
    require(normalize_list(state.get("Resource")) == [f"{bucket_arn}/{STATE_KEY}"], "IAM state resource changed")

    lock = by_sid["ManageExactLockObject"]
    require(normalize_list(lock.get("Action")) == ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"], "IAM lock actions changed")
    require(normalize_list(lock.get("Resource")) == [f"{bucket_arn}/{LOCK_KEY}"], "IAM lock resource changed")

    kms = by_sid["UseStateEncryptionKeyThroughS3"]
    require(normalize_list(kms.get("Action")) == ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"], "IAM KMS actions changed")
    require(normalize_list(kms.get("Resource")) == [kms_arn], "IAM KMS resource changed")
    service = kms.get("Condition", {}).get("StringEquals", {}).get("kms:ViaService")
    require(normalize_condition_values(service) == [f"s3.{AWS_REGION}.amazonaws.com"], "IAM KMS service condition changed")


def stage_source(context: dict[str, Any], repository_root: Path) -> str:
    staging: Path = context["staging"]
    staging.mkdir(mode=0o700)
    staging.chmod(0o700)
    for entry in context["source_entries"]:
        source = repository_root / entry["path"]
        relative = Path(entry["path"]).relative_to("infra/terraform/aws")
        target = staging / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        write_private(target, source.read_bytes())
        require(file_sha256(target) == entry["sha256"], f"Staged source digest changed: {relative}")
    manifest = {
        "schemaVersion": "v0.12.4.1.5.0.4-private-staged-source-manifest-v1",
        "controlPlaneCommit": context["request"]["expectedMainCommit"],
        "sourceManifestSha256": context["source_manifest_sha256"],
        "entries": context["source_entries"],
    }
    path = context["output"] / "source-manifest.json"
    write_private_json(path, manifest)
    return file_sha256(path)


def execute(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    context = verify_inputs(request_path, repository_root=repository_root, git_runner=git_runner, now=current)
    require(os.environ.get("CONFIRM_AWS_DEV_CLEAN_ROOM_PREFLIGHT") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_CLEAN_ROOM_PREFLIGHT={CONFIRMATION}")
    forbidden_confirmations = (
        "CONFIRM_AWS_DEV_APPLY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION",
        "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN", "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
    )
    require(all(not os.environ.get(name) for name in forbidden_confirmations), "Mutation confirmations must be unset")
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = safe_environment()
    request = context["request"]

    identity_result = run_logged(output, "aws-identity", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, runner, repository_root)
    identity = parse_json_bytes(identity_result.stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    eks_error_code = run_expected_missing_eks(output, environment, runner, repository_root)

    versioning = parse_json_bytes(run_logged(output, "s3-bucket-versioning", ["aws", "s3api", "get-bucket-versioning", "--bucket", request["expectedStateBucketName"], "--output", "json"], environment, runner, repository_root).stdout, "S3 bucket versioning")
    validate_versioning(versioning)
    public_access = parse_json_bytes(run_logged(output, "s3-public-access-block", ["aws", "s3api", "get-public-access-block", "--bucket", request["expectedStateBucketName"], "--output", "json"], environment, runner, repository_root).stdout, "S3 public access block")
    validate_public_access(public_access)
    encryption = parse_json_bytes(run_logged(output, "s3-bucket-encryption", ["aws", "s3api", "get-bucket-encryption", "--bucket", request["expectedStateBucketName"], "--output", "json"], environment, runner, repository_root).stdout, "S3 bucket encryption")
    validate_encryption(encryption, request["expectedStateKmsKeyArn"])
    history = parse_json_bytes(run_logged(output, "s3-dev-state-object-history", ["aws", "s3api", "list-object-versions", "--bucket", request["expectedStateBucketName"], "--prefix", STATE_KEY, "--output", "json"], environment, runner, repository_root).stdout, "S3 object history")
    history_counts = validate_empty_object_history(history)

    kms_description = parse_json_bytes(run_logged(output, "kms-key", ["aws", "kms", "describe-key", "--key-id", request["expectedStateKmsKeyArn"], "--output", "json"], environment, runner, repository_root).stdout, "KMS key")
    validate_kms_description(kms_description, request["expectedStateKmsKeyArn"])
    rotation = parse_json_bytes(run_logged(output, "kms-rotation", ["aws", "kms", "get-key-rotation-status", "--key-id", request["expectedStateKmsKeyArn"], "--output", "json"], environment, runner, repository_root).stdout, "KMS rotation")
    require(rotation.get("KeyRotationEnabled") is True, "KMS rotation is disabled")

    policy_result = parse_json_bytes(run_logged(output, "iam-dev-state-policy", ["aws", "iam", "get-policy", "--policy-arn", request["expectedDevStateAccessPolicyArn"], "--output", "json"], environment, runner, repository_root).stdout, "IAM dev state policy")
    policy = policy_result.get("Policy")
    require(isinstance(policy, dict) and policy.get("Arn") == request["expectedDevStateAccessPolicyArn"], "IAM dev state policy identity changed")
    require(policy.get("AttachmentCount") == 0 and policy.get("PermissionsBoundaryUsageCount") == 0, "IAM dev state policy is attached")
    version_id = policy.get("DefaultVersionId")
    require(isinstance(version_id, str) and re.fullmatch(r"v[1-9][0-9]*", version_id) is not None, "IAM dev state policy default version is invalid")
    policy_version = parse_json_bytes(run_logged(output, "iam-dev-state-policy-version", ["aws", "iam", "get-policy-version", "--policy-arn", request["expectedDevStateAccessPolicyArn"], "--version-id", version_id, "--output", "json"], environment, runner, repository_root).stdout, "IAM dev state policy version")
    validate_iam_policy_document(policy_version, request["expectedStateBucketArn"], request["expectedStateKmsKeyArn"])

    source_manifest_file_sha256 = stage_source(context, repository_root)
    evidence = {
        "schemaVersion": "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-evidence-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "privateRequestSha256": file_sha256(context["request_path"]),
        "privateBackendConfigSha256": request["privateBackendConfigSha256"],
        "sourceManifestSha256": context["source_manifest_sha256"],
        "sourceManifestFileSha256": source_manifest_file_sha256,
        "trackedSourceFileCount": len(context["source_entries"]),
        "eksClusterAbsent": True,
        "eksErrorCode": eks_error_code,
        "objectHistoryCounts": history_counts,
        "bucketVersioningEnabled": True,
        "bucketPublicAccessBlocked": True,
        "bucketEncryptionValidated": True,
        "kmsKeyValidated": True,
        "kmsRotationEnabled": True,
        "devStatePolicyValidated": True,
        "devStatePolicyAttachmentCount": 0,
        "terraformInitExecuted": False,
        "terraformPlanExecuted": False,
        "terraformApplyExecuted": False,
        "stateMigrationExecuted": False,
        "awsMutationExecuted": False,
        "kubernetesCommandExecuted": False,
        "automaticRetryPerformed": False,
    }
    evidence_path = output / "preflight-evidence.json"
    write_private_json(evidence_path, evidence)
    result = {
        "schemaVersion": "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-result-v1",
        "status": "aws-dev-remote-state-clean-room-preflight-complete-awaiting-separate-plan-review",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_preflight_request_sha256": file_sha256(context["request_path"]),
        "private_backend_config_sha256": request["privateBackendConfigSha256"],
        "source_manifest_sha256": context["source_manifest_sha256"],
        "source_manifest_file_sha256": source_manifest_file_sha256,
        "preflight_evidence_sha256": file_sha256(evidence_path),
        "tracked_source_file_count": len(context["source_entries"]),
        "eks_cluster_absent": True,
        "eks_cluster_error_code": eks_error_code,
        "remote_state_object_version_count": history_counts["stateVersions"],
        "remote_state_delete_marker_count": history_counts["stateDeleteMarkers"],
        "remote_lock_object_version_count": history_counts["lockVersions"],
        "remote_lock_delete_marker_count": history_counts["lockDeleteMarkers"],
        "bucket_versioning_enabled": True,
        "bucket_public_access_blocked": True,
        "bucket_default_encryption_validated": True,
        "kms_key_enabled_customer_managed": True,
        "kms_rotation_enabled": True,
        "dev_state_policy_exact": True,
        "dev_state_policy_attachment_count": 0,
        "staged_source_manifest_matches_repository": True,
        "terraform_init_executed": False,
        "terraform_plan_executed": False,
        "terraform_apply_executed": False,
        "state_migration_executed": False,
        "state_push_executed": False,
        "environment_created": False,
        "external_secrets_preflight_retried": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "human-review-private-preflight-before-v0.12.4.1.5.0.5-saved-create-plan",
    }
    result_path = output / "preflight-result.json"
    write_private_json(result_path, result)
    result["preflight_result_sha256"] = file_sha256(result_path)
    return result


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-preflight-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            result = redacted_verification(verify_inputs(args.private_preflight_request))
        else:
            result = execute(args.private_preflight_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, PreflightError) as error:
        parser.exit(1, f"AWS-dev clean-room preflight stopped: {error}; preserve private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

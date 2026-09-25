#!/usr/bin/env python3
"""Verify or execute one guarded apply of a reviewed state-bootstrap saved plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PLAN_EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.1.1-state-bootstrap-plan.py"
PLAN_GATE_PATH = ROOT / "scripts/check-v0.12.1.1-state-bootstrap-terraform-plan.py"
APPLY_CONFIRMATION = "apply-reviewed-state-backend-foundation"
AWS_REGION = "us-east-1"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_SECONDS = 900
PLAN_ARTIFACTS = {
    "binaryPlanSha256": "state-bootstrap.tfplan",
    "terraformPlanJsonSha256": "terraform-plan.json",
    "terraformPlanTextSha256": "terraform-plan.txt",
    "planGateSha256": "plan-gate.json",
    "sourceManifestSha256": "source-manifest.json",
    "terraformVersionJsonSha256": "terraform-version.json",
}


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_EXECUTOR = load_module(PLAN_EXECUTOR_PATH, "state_bootstrap_plan_executor_v01211")
PLAN_GATE = load_module(PLAN_GATE_PATH, "state_bootstrap_plan_gate_v01211_apply")


class CommandFailure(RuntimeError):
    pass


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
    parent = require_private_directory(path.parent, f"{label} parent")
    return parent / path.name


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"{label} is unreadable or invalid") from error


def validate_apply_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "operation",
        "repository",
        "trustedRef",
        "expectedMainCommit",
        "expectedAwsAccountId",
        "privatePlanRequestPath",
        "privatePlanRequestSha256",
        "privatePlanBundleDirectory",
        "planRecordSha256",
        "binaryPlanSha256",
        "terraformPlanJsonSha256",
        "terraformPlanTextSha256",
        "planGateSha256",
        "sourceManifestSha256",
        "terraformVersionJsonSha256",
        "privateApplyOutputDirectory",
        "approval",
        "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Private apply-request fields changed")
    require(
        value["schemaVersion"] == "v0.12.1.2-state-bootstrap-apply-request-v1",
        "Private apply-request schema changed",
    )
    require(value["operation"] == APPLY_CONFIRMATION, "Private apply-request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(
        isinstance(value["expectedMainCommit"], str)
        and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None,
        "Expected protected-main commit is invalid",
    )
    require(
        isinstance(value["expectedAwsAccountId"], str)
        and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None,
        "Expected AWS account ID is invalid",
    )
    for key in (
        "privatePlanRequestSha256",
        "planRecordSha256",
        *PLAN_ARTIFACTS,
    ):
        require(
            isinstance(value[key], str) and re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None,
            f"Invalid SHA-256: {key}",
        )
    for key in (
        "privatePlanRequestPath",
        "privatePlanBundleDirectory",
        "privateApplyOutputDirectory",
    ):
        require(isinstance(value[key], str), f"Invalid path: {key}")

    approval = value["approval"]
    require(
        isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"},
        "Apply approval fields changed",
    )
    start = utc_timestamp(approval["notBeforeUtc"], "Apply approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Apply approval expiry")
    require(expiry > start, "Apply approval expiry must follow its start")
    require(
        expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS),
        "Apply approval window exceeds one hour",
    )
    require(
        value["executionBoundary"]
        == {
            "terraformApplyExactSavedPlan": True,
            "terraformPlan": False,
            "terraformInit": False,
            "stateMigration": False,
            "iamPolicyAttachment": False,
        },
        "Apply execution boundary changed",
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
        raise CommandFailure("Git identity check failed")
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


def write_private(path: Path, content: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(content)
    path.chmod(0o600)


def record_result(
    output_directory: Path,
    label: str,
    result: subprocess.CompletedProcess[bytes],
) -> None:
    write_private(output_directory / f"{label}.stdout", result.stdout)
    write_private(output_directory / f"{label}.stderr", result.stderr)


def run_logged(
    output_directory: Path,
    label: str,
    arguments: list[str],
    environment: dict[str, str],
    timeout: int,
    runner: CommandRunner,
    cwd: Path,
) -> subprocess.CompletedProcess[bytes]:
    result = runner(arguments, environment, timeout, cwd)
    record_result(output_directory, label, result)
    if result.returncode:
        raise CommandFailure(f"{label} failed; preserve private evidence and local state")
    return result


def require_expected_missing(
    output_directory: Path,
    label: str,
    arguments: list[str],
    accepted_markers: tuple[bytes, ...],
    environment: dict[str, str],
    runner: CommandRunner,
    cwd: Path,
) -> None:
    result = runner(arguments, environment, 90, cwd)
    record_result(output_directory, label, result)
    require(result.returncode != 0, f"{label} unexpectedly found an existing resource")
    require(
        any(marker in result.stderr for marker in accepted_markers),
        f"{label} did not prove expected resource absence",
    )


def require_record(
    record: Any,
    apply_request: dict[str, Any],
    plan_request: dict[str, Any],
    bundle: Path,
    now: datetime,
) -> tuple[dict[str, Any], int]:
    fields = {
        "schemaVersion",
        "status",
        "controlPlaneCommit",
        "createdAtUtc",
        "expiresAtUtc",
        "privateRequestSha256",
        "privateTfvarsSha256",
        "sourceManifestSha256",
        "binaryPlanSha256",
        "terraformPlanJsonSha256",
        "terraformPlanTextSha256",
        "planGateSha256",
        "managedCreateCount",
        "dataChangeCount",
        "awsAccountMatched",
        "terraformInitBackend",
        "terraformPlanExecuted",
        "terraformApplyExecuted",
        "stateMigrationExecuted",
        "backendResourcesCreated",
    }
    require(isinstance(record, dict) and set(record) == fields, "Plan record fields changed")
    require(
        record["schemaVersion"] == "v0.12.1.1-state-bootstrap-plan-record-v1",
        "Plan record schema changed",
    )
    require(
        record["status"] == "state-bootstrap-plan-produced-awaiting-separate-apply-review",
        "Plan record status changed",
    )
    require(record["controlPlaneCommit"] == apply_request["expectedMainCommit"], "Plan main changed")
    require(record["privateRequestSha256"] == apply_request["privatePlanRequestSha256"], "Plan request changed")
    require(record["privateTfvarsSha256"] == plan_request["privateTfvarsSha256"], "Plan tfvars changed")
    for field, name in PLAN_ARTIFACTS.items():
        if field == "terraformVersionJsonSha256":
            require(
                apply_request[field] == file_sha256(bundle / name),
                "Apply request Terraform-version artifact drift",
            )
            continue
        require(record.get(field) == file_sha256(bundle / name), f"Plan artifact changed: {name}")
        require(record[field] == apply_request[field], f"Apply request artifact drift: {field}")
    require(record["managedCreateCount"] == 13, "Managed create count changed")
    require(isinstance(record["dataChangeCount"], int) and record["dataChangeCount"] >= 0, "Data count changed")
    require(record["awsAccountMatched"] is True, "Plan account was not matched")
    require(record["terraformInitBackend"] is False, "Plan initialized a backend")
    require(record["terraformPlanExecuted"] is True, "Plan was not executed")
    for key in ("terraformApplyExecuted", "stateMigrationExecuted", "backendResourcesCreated"):
        require(record[key] is False, f"Plan record already reports mutation: {key}")

    created = utc_timestamp(record["createdAtUtc"], "Plan creation")
    expiry = utc_timestamp(record["expiresAtUtc"], "Plan expiry")
    require(created <= now < expiry, "Saved plan is expired or not yet valid")
    remaining = int((expiry - now).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Saved plan has less than 15 minutes remaining")
    apply_expiry = utc_timestamp(apply_request["approval"]["expiresAtUtc"], "Apply approval expiry")
    require(apply_expiry <= expiry, "Apply approval exceeds saved-plan expiry")

    plan_document = load_json(bundle / "terraform-plan.json", "Terraform plan JSON")
    expected = plan_request["expectedInputs"]
    gate = PLAN_GATE.validate(
        plan_document,
        expected_bucket_name=expected["stateBucketName"],
        expected_kms_alias=expected["stateKmsAlias"],
        expected_additional_tags=expected["additionalTags"],
    )
    require(gate == load_json(bundle / "plan-gate.json", "Plan gate"), "Plan gate changed")
    return gate, remaining


def verify_inputs(
    private_apply_request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    apply_path = require_private_file(private_apply_request_path, "Private apply request")
    require(not is_within(apply_path, repository_root), "Private apply request must remain outside the repository")
    apply_request = validate_apply_request(load_json(apply_path, "Private apply request"))

    plan_request_path = require_private_file(
        Path(apply_request["privatePlanRequestPath"]),
        "Private plan request",
    )
    require(not is_within(plan_request_path, repository_root), "Private plan request must remain outside the repository")
    require(
        file_sha256(plan_request_path) == apply_request["privatePlanRequestSha256"],
        "Private plan request changed",
    )
    plan_request = PLAN_EXECUTOR.validate_request(load_json(plan_request_path, "Private plan request"))
    require(plan_request["expectedMainCommit"] == apply_request["expectedMainCommit"], "Plan/apply main differs")
    require(plan_request["expectedAwsAccountId"] == apply_request["expectedAwsAccountId"], "Plan/apply account differs")
    tfvars_path = require_private_file(Path(plan_request["privateTfvarsPath"]), "Private plan tfvars")
    require(not is_within(tfvars_path, repository_root), "Private plan tfvars must remain outside the repository")
    require(file_sha256(tfvars_path) == plan_request["privateTfvarsSha256"], "Private plan tfvars changed")

    bundle = require_private_directory(
        Path(apply_request["privatePlanBundleDirectory"]),
        "Private plan bundle",
    )
    require(not is_within(bundle, repository_root), "Private plan bundle must remain outside the repository")
    require(Path(plan_request["privateOutputDirectory"]).resolve(strict=True) == bundle, "Plan bundle path changed")
    apply_output = require_new_private_directory(
        Path(apply_request["privateApplyOutputDirectory"]),
        "Private apply output",
    )
    require(not is_within(apply_output, repository_root), "Private apply output must remain outside the repository")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(apply_request["approval"]["notBeforeUtc"], "Apply approval start")
    expiry = utc_timestamp(apply_request["approval"]["expiresAtUtc"], "Apply approval expiry")
    require(start <= current < expiry, "Apply approval is not currently active")
    approval_remaining = int((expiry - current).total_seconds())
    require(approval_remaining >= MINIMUM_REMAINING_SECONDS, "Apply approval has less than 15 minutes remaining")

    expected_main = apply_request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Executor must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Executor requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_main
        and git_runner(["rev-parse", "origin/main"]) == expected_main,
        "HEAD and origin/main must equal the reviewed protected-main commit",
    )

    terraform_root = repository_root / PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE
    PLAN_EXECUTOR.require_empty_local_bootstrap_state(terraform_root)
    for field, name in PLAN_ARTIFACTS.items():
        artifact = require_private_file(bundle / name, f"Plan artifact {name}")
        require(file_sha256(artifact) == apply_request[field], f"Plan artifact hash changed: {name}")
    record_path = require_private_file(bundle / "plan-record.json", "Plan record")
    require(file_sha256(record_path) == apply_request["planRecordSha256"], "Plan record changed")

    source = require_private_directory(bundle / "source", "Staged Terraform source")
    terraform_data = require_private_directory(bundle / "terraform-data", "Saved Terraform data")
    PLAN_EXECUTOR.require_empty_local_bootstrap_state(source)
    for name in PLAN_EXECUTOR.TERRAFORM_SOURCE_FILES:
        staged_file = source / name
        require(
            stat.S_IMODE(staged_file.stat().st_mode) == 0o600,
            f"Staged Terraform source mode changed: {name}",
        )
    source_manifest = load_json(bundle / "source-manifest.json", "Source manifest")
    require(
        source_manifest == PLAN_EXECUTOR.source_manifest(source)
        and source_manifest == PLAN_EXECUTOR.source_manifest(terraform_root),
        "Terraform source manifest changed",
    )
    record = load_json(record_path, "Plan record")
    gate, plan_remaining = require_record(record, apply_request, plan_request, bundle, current)
    return {
        "apply_request": apply_request,
        "apply_request_path": apply_path,
        "plan_request": plan_request,
        "plan_request_path": plan_request_path,
        "bundle": bundle,
        "source": source,
        "terraform_data": terraform_data,
        "apply_output": apply_output,
        "record": record,
        "gate": gate,
        "approval_remaining": approval_remaining,
        "plan_remaining": plan_remaining,
    }


def safe_environment(plan_request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    environment = PLAN_EXECUTOR.safe_environment(plan_request, terraform_data)
    for key in list(environment):
        if key.startswith("TF_CLI_ARGS") or key.startswith("TF_VAR_") or key.startswith("CONFIRM_"):
            del environment[key]
    return environment


def output_value(outputs: dict[str, Any], name: str) -> Any:
    item = outputs.get(name)
    require(isinstance(item, dict) and "value" in item, f"Terraform output missing: {name}")
    return item["value"]


def validate_outputs(outputs: Any, plan_request: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(outputs, dict), "Terraform outputs must be an object")
    expected = plan_request["expectedInputs"]
    bucket = output_value(outputs, "state_bucket_name")
    alias = output_value(outputs, "state_kms_alias")
    kms_arn = output_value(outputs, "state_kms_key_arn")
    policies = output_value(outputs, "root_state_access_policy_arns")
    keys = output_value(outputs, "state_keys")
    backend = output_value(outputs, "backend_configuration")
    require(bucket == expected["stateBucketName"], "State bucket output changed")
    require(alias == expected["stateKmsAlias"], "KMS alias output changed")
    require(isinstance(kms_arn, str) and kms_arn.startswith("arn:aws:kms:us-east-1:"), "KMS ARN invalid")
    expected_keys = {
        "bootstrap": "bootstrap/terraform.tfstate",
        "runtime-identities": "runtime-identities/terraform.tfstate",
        "dev": "environments/dev/terraform.tfstate",
        "test": "environments/test/terraform.tfstate",
        "prod": "environments/prod/terraform.tfstate",
    }
    require(keys == expected_keys, "State-key outputs changed")
    require(isinstance(policies, dict) and set(policies) == set(expected_keys), "Policy outputs changed")
    require(isinstance(backend, dict) and set(backend) == set(expected_keys), "Backend outputs changed")
    for root, key in expected_keys.items():
        require(
            backend[root]
            == {
                "bucket": bucket,
                "encrypt": True,
                "key": key,
                "kms_key_id": kms_arn,
                "region": AWS_REGION,
                "use_lockfile": True,
            },
            f"Backend output changed: {root}",
        )
    return {"bucket": bucket, "alias": alias, "kms_arn": kms_arn, "policies": policies}


def parse_json_result(result: subprocess.CompletedProcess[bytes], label: str) -> Any:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CommandFailure(f"{label} returned invalid JSON") from error


def validate_bucket_policy(document: Any, bucket_arn: str) -> None:
    require(isinstance(document, dict), "Bucket policy must be an object")
    statements = document.get("Statement")
    require(isinstance(statements, list) and len(statements) == 1, "Bucket policy statements changed")
    matches = [item for item in statements if isinstance(item, dict) and item.get("Sid") == "DenyInsecureTransport"]
    require(len(matches) == 1, "TLS-only bucket-policy statement changed")
    statement = matches[0]
    require(statement.get("Effect") == "Deny", "TLS-only policy effect changed")
    require(statement.get("Action") == "s3:*", "TLS-only policy action changed")
    require(statement.get("Principal") == "*", "TLS-only policy principal changed")
    require(set(statement.get("Resource", [])) == {bucket_arn, f"{bucket_arn}/*"}, "TLS-only resources changed")
    condition = statement.get("Condition", {})
    require(condition.get("Bool", {}).get("aws:SecureTransport") == "false", "TLS-only condition changed")


def validate_live_foundation(
    output_directory: Path,
    identities: dict[str, Any],
    environment: dict[str, str],
    runner: CommandRunner,
    cwd: Path,
) -> dict[str, Any]:
    bucket = identities["bucket"]

    def aws_json(label: str, arguments: list[str]) -> Any:
        result = run_logged(
            output_directory,
            label,
            ["aws", "--region", AWS_REGION, *arguments, "--output", "json"],
            environment,
            120,
            runner,
            cwd,
        )
        return parse_json_result(result, label)

    versioning = aws_json("s3-versioning", ["s3api", "get-bucket-versioning", "--bucket", bucket])
    require(versioning.get("Status") == "Enabled", "S3 versioning is not enabled")
    public = aws_json("s3-public-access", ["s3api", "get-public-access-block", "--bucket", bucket])
    public_config = public.get("PublicAccessBlockConfiguration", {})
    for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"):
        require(public_config.get(key) is True, f"S3 public-access block changed: {key}")
    ownership = aws_json("s3-ownership", ["s3api", "get-bucket-ownership-controls", "--bucket", bucket])
    rules = ownership.get("OwnershipControls", {}).get("Rules", [])
    require(rules == [{"ObjectOwnership": "BucketOwnerEnforced"}], "S3 ownership changed")
    encryption = aws_json("s3-encryption", ["s3api", "get-bucket-encryption", "--bucket", bucket])
    encryption_rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    require(isinstance(encryption_rules, list) and len(encryption_rules) == 1, "S3 encryption rules changed")
    encryption_rule = encryption_rules[0]
    default = encryption_rule.get("ApplyServerSideEncryptionByDefault", {})
    require(default.get("SSEAlgorithm") == "aws:kms", "S3 default encryption is not SSE-KMS")
    require(default.get("KMSMasterKeyID") == identities["kms_arn"], "S3 KMS key changed")
    require(encryption_rule.get("BucketKeyEnabled") is True, "S3 Bucket Key is disabled")
    policy_status = aws_json("s3-policy-status", ["s3api", "get-bucket-policy-status", "--bucket", bucket])
    require(policy_status.get("PolicyStatus", {}).get("IsPublic") is False, "S3 bucket policy is public")
    policy_result = aws_json("s3-policy", ["s3api", "get-bucket-policy", "--bucket", bucket])
    policy_text = policy_result.get("Policy")
    require(isinstance(policy_text, str), "S3 bucket policy missing")
    try:
        policy = json.loads(policy_text)
    except json.JSONDecodeError as error:
        raise ValueError("S3 bucket policy JSON is invalid") from error
    validate_bucket_policy(policy, f"arn:aws:s3:::{bucket}")
    inventory = aws_json("s3-object-versions", ["s3api", "list-object-versions", "--bucket", bucket])
    require(not inventory.get("Versions") and not inventory.get("DeleteMarkers"), "State bucket is not empty")

    rotation = aws_json(
        "kms-rotation",
        ["kms", "get-key-rotation-status", "--key-id", identities["kms_arn"]],
    )
    require(rotation.get("KeyRotationEnabled") is True, "KMS rotation is disabled")
    key = aws_json("kms-key", ["kms", "describe-key", "--key-id", identities["kms_arn"]]).get(
        "KeyMetadata", {}
    )
    require(key.get("Arn") == identities["kms_arn"], "KMS key identity changed")
    require(key.get("Enabled") is True and key.get("KeyState") == "Enabled", "KMS key is not enabled")
    require(key.get("KeyManager") == "CUSTOMER", "KMS key is not customer managed")

    for root, arn in sorted(identities["policies"].items()):
        policy_meta = aws_json(f"iam-policy-{root}", ["iam", "get-policy", "--policy-arn", arn]).get("Policy", {})
        require(policy_meta.get("Arn") == arn, f"IAM policy identity changed: {root}")
        require(policy_meta.get("AttachmentCount") == 0, f"IAM policy is attached: {root}")
        entities = aws_json(
            f"iam-policy-entities-{root}",
            ["iam", "list-entities-for-policy", "--policy-arn", arn],
        )
        require(
            entities.get("PolicyGroups", []) == []
            and entities.get("PolicyUsers", []) == []
            and entities.get("PolicyRoles", []) == [],
            f"IAM policy has attached entities: {root}",
        )
    return {
        "s3_versioning_enabled": True,
        "s3_public_access_blocked": True,
        "s3_bucket_owner_enforced": True,
        "s3_sse_kms_enabled": True,
        "s3_bucket_key_enabled": True,
        "s3_policy_public": False,
        "s3_object_version_count": 0,
        "kms_customer_managed_enabled": True,
        "kms_rotation_enabled": True,
        "root_state_policy_count": len(identities["policies"]),
        "attached_root_state_policy_count": 0,
    }


def execute(
    private_apply_request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    verified = verify_inputs(
        private_apply_request_path,
        repository_root=repository_root,
        git_runner=git_runner,
        now=current,
    )
    require(
        os.environ.get("CONFIRM_STATE_BOOTSTRAP_APPLY") == APPLY_CONFIRMATION,
        f"Set CONFIRM_STATE_BOOTSTRAP_APPLY={APPLY_CONFIRMATION}",
    )
    for forbidden in (
        "CONFIRM_STATE_BOOTSTRAP_PLAN",
        "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY",
        "CONFIRM_STATE_MIGRATION",
    ):
        require(not os.environ.get(forbidden), "Plan, legacy apply, destroy and migration confirmations must be unset")

    output = verified["apply_output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    environment = safe_environment(verified["plan_request"], verified["terraform_data"])
    source = verified["source"]
    bundle = verified["bundle"]
    binary_plan = bundle / "state-bootstrap.tfplan"

    version = run_logged(
        output,
        "terraform-version",
        ["terraform", "version", "-json"],
        environment,
        30,
        runner,
        repository_root,
    )
    current_version = PLAN_EXECUTOR.parse_terraform_version(version.stdout)
    planned_version = PLAN_EXECUTOR.parse_terraform_version((bundle / "terraform-version.json").read_bytes())
    require(current_version == planned_version, "Terraform version differs from the reviewed plan")

    identity = run_logged(
        output,
        "aws-identity",
        ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"],
        environment,
        90,
        runner,
        repository_root,
    )
    identity_json = parse_json_result(identity, "AWS identity")
    require(identity_json.get("Account") == verified["apply_request"]["expectedAwsAccountId"], "AWS account changed")

    terraform_prefix = ["terraform", f"-chdir={source}"]
    shown = run_logged(
        output,
        "terraform-show-json",
        [*terraform_prefix, "show", "-json", str(binary_plan)],
        environment,
        300,
        runner,
        repository_root,
    )
    require(file_sha256(bundle / "terraform-plan.json") == hashlib.sha256(shown.stdout).hexdigest(), "terraform show JSON changed")
    expected = verified["plan_request"]["expectedInputs"]
    gate = PLAN_GATE.validate(
        parse_json_result(shown, "Terraform plan show"),
        expected_bucket_name=expected["stateBucketName"],
        expected_kms_alias=expected["stateKmsAlias"],
        expected_additional_tags=expected["additionalTags"],
    )
    require(gate == verified["gate"], "Immediate pre-apply plan gate changed")

    require_expected_missing(
        output,
        "s3-before-apply",
        ["aws", "--region", AWS_REGION, "s3api", "head-bucket", "--bucket", expected["stateBucketName"]],
        (b"(404)", b"NoSuchBucket", b"Not Found"),
        environment,
        runner,
        repository_root,
    )
    require_expected_missing(
        output,
        "kms-before-apply",
        ["aws", "--region", AWS_REGION, "kms", "describe-key", "--key-id", expected["stateKmsAlias"], "--output", "json"],
        (b"NotFoundException",),
        environment,
        runner,
        repository_root,
    )
    policies_before = run_logged(
        output,
        "iam-before-apply",
        ["aws", "--region", AWS_REGION, "iam", "list-policies", "--scope", "Local", "--output", "json"],
        environment,
        120,
        runner,
        repository_root,
    )
    existing_names = {
        item.get("PolicyName")
        for item in parse_json_result(policies_before, "IAM policy inventory").get("Policies", [])
        if isinstance(item, dict)
    }
    expected_policy_names = {
        f"startup-devops-baseline-terraform-state-{root}"
        for root in PLAN_GATE.EXPECTED_POLICY_ROOTS
    }
    require(existing_names.isdisjoint(expected_policy_names), "A state-access IAM policy already exists")

    run_logged(
        output,
        "terraform-apply",
        [*terraform_prefix, "apply", "-input=false", "-auto-approve", str(binary_plan)],
        environment,
        1800,
        runner,
        repository_root,
    )
    state_path = source / "terraform.tfstate"
    require(state_path.is_file() and not state_path.is_symlink(), "Terraform apply did not create local state")
    state_path.chmod(0o600)
    state_copy = output / "state-bootstrap.tfstate.applied"
    shutil.copyfile(state_path, state_copy)
    state_copy.chmod(0o600)

    state_list = run_logged(
        output,
        "terraform-state-list",
        [*terraform_prefix, "state", "list"],
        environment,
        300,
        runner,
        repository_root,
    )
    state_addresses = {line.strip() for line in state_list.stdout.decode().splitlines() if line.strip()}
    require(PLAN_GATE.EXPECTED_MANAGED_ADDRESSES.issubset(state_addresses), "Managed state inventory is incomplete")
    require(
        state_addresses <= PLAN_GATE.EXPECTED_MANAGED_ADDRESSES | PLAN_GATE.ALLOWED_DATA_ADDRESSES,
        "Terraform state contains an unreviewed address",
    )

    outputs_result = run_logged(
        output,
        "terraform-output",
        [*terraform_prefix, "output", "-json"],
        environment,
        300,
        runner,
        repository_root,
    )
    identities = validate_outputs(parse_json_result(outputs_result, "Terraform outputs"), verified["plan_request"])
    live = validate_live_foundation(output, identities, environment, runner, repository_root)
    live_path = output / "live-validation.json"
    write_private(live_path, canonical_json(live))

    result = {
        "status": "state-backend-foundation-applied-and-live-validated",
        "control_plane_commit": verified["apply_request"]["expectedMainCommit"],
        "managed_state_address_count": len(PLAN_GATE.EXPECTED_MANAGED_ADDRESSES),
        "root_state_policy_count": live["root_state_policy_count"],
        "attached_root_state_policy_count": live["attached_root_state_policy_count"],
        "state_bucket_object_version_count": live["s3_object_version_count"],
        "local_bootstrap_state_sha256": file_sha256(state_path),
        "private_state_copy_sha256": file_sha256(state_copy),
        "live_validation_sha256": file_sha256(live_path),
        "plan_record_sha256": verified["apply_request"]["planRecordSha256"],
        "terraform_plan_executed": False,
        "terraform_apply_executed": True,
        "state_migration_executed": False,
        "iam_policy_attachment_executed": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "record-redacted-v0.12.1.2.1-execution-evidence-before-v0.12.2",
    }
    result_path = output / "apply-result.json"
    write_private(result_path, canonical_json(result))
    result["apply_result_sha256"] = file_sha256(result_path)
    return result


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "state-bootstrap-apply-inputs-verified",
        "control_plane_commit": context["apply_request"]["expectedMainCommit"],
        "private_apply_request_sha256": file_sha256(context["apply_request_path"]),
        "private_plan_request_sha256": file_sha256(context["plan_request_path"]),
        "plan_record_sha256": context["apply_request"]["planRecordSha256"],
        "binary_plan_sha256": context["apply_request"]["binaryPlanSha256"],
        "managed_create_count": context["gate"]["managed_create_count"],
        "remaining_plan_seconds": context["plan_remaining"],
        "remaining_apply_approval_seconds": context["approval_remaining"],
        "terraform_apply_authorized": False,
        "terraform_apply_executed": False,
        "state_migration_executed": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-state-bootstrap-apply-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-apply-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            result = redacted_verification(verify_inputs(args.private_apply_request))
        else:
            result = execute(args.private_apply_request)
    except (
        CommandFailure,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as error:
        parser.exit(1, f"State-bootstrap Terraform apply executor stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

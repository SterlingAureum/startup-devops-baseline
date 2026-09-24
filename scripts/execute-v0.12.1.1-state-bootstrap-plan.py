#!/usr/bin/env python3
"""Verify or execute the guarded state-bootstrap Terraform plan-only checkpoint."""

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
TERRAFORM_ROOT_RELATIVE = "infra/terraform/aws/state-bootstrap"
TERRAFORM_SOURCE_FILES = (
    "backend.tf",
    "main.tf",
    "outputs.tf",
    "providers.tf",
    "variables.tf",
    "versions.tf",
)
PLAN_GATE_PATH = ROOT / "scripts/check-v0.12.1.1-state-bootstrap-terraform-plan.py"
PLAN_CONFIRMATION = "plan-state-backend-foundation"
AWS_REGION = "us-east-1"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 3600
MINIMUM_REMAINING_WINDOW_SECONDS = 900


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_GATE = load_module(PLAN_GATE_PATH, "state_bootstrap_plan_gate")


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


def require_private_file(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"{label} path must be absolute")
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular non-symlink file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 0600")
    parent = path.parent
    require(parent.is_dir() and not parent.is_symlink(), f"{label} parent must be a directory")
    require(stat.S_IMODE(parent.stat().st_mode) == 0o700, f"{label} parent mode must be 0700")
    return path.resolve(strict=True)


def require_new_private_directory(path: Path) -> Path:
    require(path.is_absolute(), "Private output directory path must be absolute")
    require(not path.exists() and not path.is_symlink(), "Private output directory must be new")
    parent = path.parent
    require(parent.is_dir() and not parent.is_symlink(), "Private output parent must be a directory")
    require(stat.S_IMODE(parent.stat().st_mode) == 0o700, "Private output parent mode must be 0700")
    return parent.resolve(strict=True) / path.name


def validate_bucket_name(value: Any) -> str:
    require(
        isinstance(value, str)
        and 3 <= len(value) <= 63
        and re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", value) is not None
        and ".." not in value
        and ".-" not in value
        and "-." not in value
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+", value) is None,
        "Private request contains an invalid S3 bucket name",
    )
    return value


def validate_request(value: Any) -> dict[str, Any]:
    fields = {
        "schemaVersion",
        "operation",
        "repository",
        "trustedRef",
        "expectedMainCommit",
        "expectedAwsAccountId",
        "awsRegion",
        "terraformRoot",
        "privateTfvarsPath",
        "privateTfvarsSha256",
        "expectedInputs",
        "privateOutputDirectory",
        "approval",
        "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Private request fields changed")
    require(
        value["schemaVersion"] == "v0.12.1.1-state-bootstrap-plan-request-v1",
        "Private request schema changed",
    )
    require(value["operation"] == PLAN_CONFIRMATION, "Private request operation changed")
    require(
        value["repository"] == "SterlingAureum/startup-devops-baseline",
        "Private request repository changed",
    )
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(
        isinstance(value["expectedMainCommit"], str)
        and re.fullmatch(r"[0-9a-f]{40}", value["expectedMainCommit"]) is not None,
        "Expected protected-main commit must be a 40-character lowercase SHA",
    )
    require(
        isinstance(value["expectedAwsAccountId"], str)
        and re.fullmatch(r"[0-9]{12}", value["expectedAwsAccountId"]) is not None,
        "Expected AWS account ID must have 12 digits",
    )
    require(value["awsRegion"] == AWS_REGION, "AWS region changed")
    require(value["terraformRoot"] == TERRAFORM_ROOT_RELATIVE, "Terraform root changed")
    require(
        isinstance(value["privateTfvarsSha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", value["privateTfvarsSha256"]) is not None,
        "Private tfvars SHA-256 is invalid",
    )

    inputs = value["expectedInputs"]
    require(
        isinstance(inputs, dict)
        and set(inputs) == {"projectName", "stateBucketName", "stateKmsAlias", "additionalTags"},
        "Expected input fields changed",
    )
    require(inputs["projectName"] == "startup-devops-baseline", "Project name changed")
    validate_bucket_name(inputs["stateBucketName"])
    require(
        isinstance(inputs["stateKmsAlias"], str)
        and inputs["stateKmsAlias"].startswith("alias/")
        and len(inputs["stateKmsAlias"]) > 6,
        "KMS alias is invalid",
    )
    tags = inputs["additionalTags"]
    require(
        isinstance(tags, dict)
        and bool(tags)
        and all(
            isinstance(key, str) and key and isinstance(item, str) and item
            for key, item in tags.items()
        ),
        "Additional tags must be a non-empty string map",
    )
    require(
        not any(key in {"ManagedBy", "Project", "Environment"} for key in tags),
        "Additional tags must not override required provider tags",
    )

    approval = value["approval"]
    require(
        isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc"},
        "Approval fields changed",
    )
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    require(expiry > start, "Approval expiry must follow its start")
    require(
        expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS),
        "Approval window exceeds one hour",
    )

    boundary = value["executionBoundary"]
    require(
        boundary
        == {
            "terraformInitBackend": False,
            "terraformPlan": True,
            "terraformShow": True,
            "terraformApply": False,
            "stateMigration": False,
        },
        "Private request execution boundary changed",
    )
    require(isinstance(value["privateTfvarsPath"], str), "Private tfvars path must be a string")
    require(isinstance(value["privateOutputDirectory"], str), "Private output path must be a string")
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


def source_manifest(terraform_root: Path) -> dict[str, str]:
    actual = {path.name for path in terraform_root.glob("*.tf") if path.is_file()}
    require(actual == set(TERRAFORM_SOURCE_FILES), "Terraform source-file inventory changed")
    for name in TERRAFORM_SOURCE_FILES:
        path = terraform_root / name
        require(path.is_file() and not path.is_symlink(), f"Terraform source must be regular: {name}")
    return {name: file_sha256(terraform_root / name) for name in TERRAFORM_SOURCE_FILES}


def require_empty_local_bootstrap_state(terraform_root: Path) -> None:
    candidates = list(terraform_root.glob("terraform.tfstate*"))
    candidates.extend(terraform_root.glob("*.tfplan"))
    candidates.extend(terraform_root.glob("tfplan"))
    require(not candidates, "State-bootstrap root contains local state or a saved plan; stop")
    require(not (terraform_root / "terraform.tfstate.d").exists(), "Terraform workspace state exists; stop")


def verify_inputs(
    private_request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> tuple[dict[str, Any], Path, Path, dict[str, str], int]:
    repository_root = repository_root.resolve(strict=True)
    request_path = require_private_file(private_request_path, "Private request")
    require(not is_within(request_path, repository_root), "Private request must remain outside the repository")
    request = validate_request(json.loads(request_path.read_text()))

    tfvars_path = require_private_file(Path(request["privateTfvarsPath"]), "Private tfvars")
    require(not is_within(tfvars_path, repository_root), "Private tfvars must remain outside the repository")
    require(
        file_sha256(tfvars_path) == request["privateTfvarsSha256"],
        "Private tfvars SHA-256 changed",
    )
    output_directory = require_new_private_directory(Path(request["privateOutputDirectory"]))
    require(not is_within(output_directory, repository_root), "Private output must remain outside the repository")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Plan approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_WINDOW_SECONDS, "Plan approval has less than 15 minutes remaining")

    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Executor must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Executor requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_main
        and git_runner(["rev-parse", "origin/main"]) == expected_main,
        "HEAD and origin/main must equal the reviewed protected-main commit",
    )

    terraform_root = repository_root / TERRAFORM_ROOT_RELATIVE
    require(terraform_root.is_dir() and not terraform_root.is_symlink(), "Terraform root is invalid")
    require_empty_local_bootstrap_state(terraform_root)
    manifest = source_manifest(terraform_root)
    return request, tfvars_path, output_directory, manifest, remaining


def safe_environment(request: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "https_proxy",
        "http_proxy",
        "no_proxy",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in allowed or key.startswith("AWS_")
    }
    for key in list(environment):
        if key.startswith("AWS_ENDPOINT_URL") or key in {"AWS_DATA_PATH", "AWS_CA_BUNDLE"}:
            del environment[key]
    environment.update(
        AWS_REGION=AWS_REGION,
        AWS_DEFAULT_REGION=AWS_REGION,
        AWS_PAGER="",
        TF_DATA_DIR=str(terraform_data),
        TF_IN_AUTOMATION="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment


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
        raise CommandFailure(f"{label} failed; preserve the private plan bundle")
    return result


def parse_terraform_version(stdout: bytes) -> tuple[int, int, int]:
    try:
        value = json.loads(stdout)
        version = value["terraform_version"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("Terraform version JSON is invalid") from error
    require(isinstance(version, str), "Terraform version is invalid")
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:[-+].*)?", version)
    require(match is not None, "Terraform version is invalid")
    parsed = tuple(int(item) for item in match.groups())
    require(parsed >= (1, 11, 0) and parsed < (2, 0, 0), "Terraform must be >= 1.11.0 and < 2.0.0")
    return parsed


def stage_source(
    repository_root: Path,
    destination: Path,
    expected_manifest: dict[str, str],
) -> Path:
    destination.mkdir(mode=0o700)
    source_root = repository_root / TERRAFORM_ROOT_RELATIVE
    for name in TERRAFORM_SOURCE_FILES:
        target = destination / name
        shutil.copyfile(source_root / name, target)
        target.chmod(0o600)
    require(source_manifest(destination) == expected_manifest, "Staged Terraform source changed")
    return destination


def execute(
    private_request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    request, tfvars_path, output_directory, manifest, _ = verify_inputs(
        private_request_path,
        repository_root=repository_root,
        git_runner=git_runner,
        now=current,
    )
    require(
        os.environ.get("CONFIRM_STATE_BOOTSTRAP_PLAN") == PLAN_CONFIRMATION,
        f"Set CONFIRM_STATE_BOOTSTRAP_PLAN={PLAN_CONFIRMATION}",
    )
    for forbidden in (
        "CONFIRM_STATE_BOOTSTRAP_APPLY",
        "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY",
        "CONFIRM_STATE_MIGRATION",
    ):
        require(not os.environ.get(forbidden), "Apply, destroy and migration confirmations must be unset")

    output_directory.mkdir(mode=0o700)
    output_directory.chmod(0o700)
    terraform_data = output_directory / "terraform-data"
    terraform_data.mkdir(mode=0o700)
    staged_root = stage_source(repository_root, output_directory / "source", manifest)
    environment = safe_environment(request, terraform_data)

    version_result = runner(["terraform", "version", "-json"], environment, 30, repository_root)
    if version_result.returncode:
        raise CommandFailure("Terraform version check failed")
    terraform_version = parse_terraform_version(version_result.stdout)
    write_private(output_directory / "terraform-version.json", version_result.stdout)
    write_private(output_directory / "terraform-version.stderr", version_result.stderr)

    identity_result = runner(
        ["aws", "--region", AWS_REGION, "sts", "get-caller-identity", "--output", "json"],
        environment,
        90,
        repository_root,
    )
    write_private(output_directory / "aws-identity.stderr", identity_result.stderr)
    if identity_result.returncode:
        raise CommandFailure("AWS caller identity check failed")
    try:
        identity = json.loads(identity_result.stdout)
    except json.JSONDecodeError as error:
        raise CommandFailure("AWS caller identity response is invalid") from error
    require(
        isinstance(identity, dict)
        and identity.get("Account") == request["expectedAwsAccountId"],
        "AWS caller account differs from the private request",
    )

    terraform_prefix = ["terraform", f"-chdir={staged_root}"]
    run_logged(
        output_directory,
        "terraform-init",
        [*terraform_prefix, "init", "-backend=false", "-input=false"],
        environment,
        900,
        runner,
        repository_root,
    )

    binary_plan = output_directory / "state-bootstrap.tfplan"
    run_logged(
        output_directory,
        "terraform-plan",
        [
            *terraform_prefix,
            "plan",
            "-input=false",
            "-lock=true",
            f"-out={binary_plan}",
            f"-var-file={tfvars_path}",
        ],
        environment,
        1800,
        runner,
        repository_root,
    )
    require(binary_plan.is_file() and not binary_plan.is_symlink(), "Terraform did not create a saved plan")
    binary_plan.chmod(0o600)

    json_result = runner(
        [*terraform_prefix, "show", "-json", str(binary_plan)],
        environment,
        300,
        repository_root,
    )
    write_private(output_directory / "terraform-show-json.stderr", json_result.stderr)
    if json_result.returncode:
        raise CommandFailure("terraform-show-json failed; preserve the private plan bundle")
    plan_json = output_directory / "terraform-plan.json"
    write_private(plan_json, json_result.stdout)
    gate = PLAN_GATE.validate(
        json.loads(json_result.stdout),
        expected_bucket_name=request["expectedInputs"]["stateBucketName"],
        expected_kms_alias=request["expectedInputs"]["stateKmsAlias"],
        expected_additional_tags=request["expectedInputs"]["additionalTags"],
    )

    text_result = runner(
        [*terraform_prefix, "show", "-no-color", str(binary_plan)],
        environment,
        300,
        repository_root,
    )
    write_private(output_directory / "terraform-show-text.stderr", text_result.stderr)
    if text_result.returncode or not text_result.stdout:
        raise CommandFailure("terraform-show-text failed; preserve the private plan bundle")
    plan_text = output_directory / "terraform-plan.txt"
    write_private(plan_text, text_result.stdout)

    require(file_sha256(tfvars_path) == request["privateTfvarsSha256"], "Private tfvars changed during planning")
    require(
        source_manifest(repository_root / TERRAFORM_ROOT_RELATIVE) == manifest,
        "Repository Terraform source changed during planning",
    )
    gate_path = output_directory / "plan-gate.json"
    write_private(gate_path, canonical_json(gate))
    manifest_path = output_directory / "source-manifest.json"
    write_private(manifest_path, canonical_json(manifest))

    approval_expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    review_expiry = min(current + timedelta(seconds=3600), approval_expiry)
    record = {
        "schemaVersion": "v0.12.1.1-state-bootstrap-plan-record-v1",
        "status": "state-bootstrap-plan-produced-awaiting-separate-apply-review",
        "controlPlaneCommit": request["expectedMainCommit"],
        "createdAtUtc": utc_text(current),
        "expiresAtUtc": utc_text(review_expiry),
        "privateRequestSha256": file_sha256(private_request_path),
        "privateTfvarsSha256": request["privateTfvarsSha256"],
        "sourceManifestSha256": file_sha256(manifest_path),
        "binaryPlanSha256": file_sha256(binary_plan),
        "terraformPlanJsonSha256": file_sha256(plan_json),
        "terraformPlanTextSha256": file_sha256(plan_text),
        "planGateSha256": file_sha256(gate_path),
        "managedCreateCount": gate["managed_create_count"],
        "dataChangeCount": gate["data_change_count"],
        "awsAccountMatched": True,
        "terraformInitBackend": False,
        "terraformPlanExecuted": True,
        "terraformApplyExecuted": False,
        "stateMigrationExecuted": False,
        "backendResourcesCreated": False,
    }
    record_path = output_directory / "plan-record.json"
    write_private(record_path, canonical_json(record))

    return {
        "status": "state-bootstrap-plan-produced-awaiting-separate-apply-review",
        "control_plane_commit": request["expectedMainCommit"],
        "terraform_version": ".".join(str(item) for item in terraform_version),
        "managed_create_count": gate["managed_create_count"],
        "data_change_count": gate["data_change_count"],
        "binary_plan_sha256": record["binaryPlanSha256"],
        "terraform_plan_json_sha256": record["terraformPlanJsonSha256"],
        "terraform_plan_text_sha256": record["terraformPlanTextSha256"],
        "plan_gate_sha256": record["planGateSha256"],
        "plan_record_sha256": file_sha256(record_path),
        "plan_review_expires_at_utc": record["expiresAtUtc"],
        "terraform_apply_executed": False,
        "state_migration_executed": False,
        "backend_resources_created": False,
        "private_resource_identity_emitted": False,
        "next_action": "human-review-private-plan-before-v0.12.1.2-apply-design",
    }


def redacted_verification(
    request: dict[str, Any],
    private_request_path: Path,
    manifest: dict[str, str],
    remaining: int,
) -> dict[str, Any]:
    return {
        "status": "state-bootstrap-plan-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "private_request_sha256": file_sha256(private_request_path),
        "private_tfvars_sha256": request["privateTfvarsSha256"],
        "source_manifest_sha256": hashlib.sha256(canonical_json(manifest)).hexdigest(),
        "remaining_window_seconds": remaining,
        "terraform_plan_authorized": False,
        "terraform_plan_executed": False,
        "terraform_apply_executed": False,
        "state_migration_executed": False,
        "commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-state-bootstrap-plan-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            request, _, _, manifest, remaining = verify_inputs(args.private_request)
            result = redacted_verification(
                request,
                args.private_request,
                manifest,
                remaining,
            )
        else:
            result = execute(args.private_request)
    except (
        CommandFailure,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as error:
        parser.exit(1, f"State-bootstrap Terraform plan executor stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify or produce one guarded aws-dev remote-state saved create plan."""

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
PREFLIGHT_EXECUTOR = ROOT / "scripts/execute-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py"
CONFIRMATION = "produce-reviewed-aws-dev-clean-room-create-plan"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
STATE_KEY = "environments/dev/terraform.tfstate"
LOCK_KEY = STATE_KEY + ".tflock"
MAXIMUM_APPROVAL_WINDOW_SECONDS = 7200
MAXIMUM_PLAN_REVIEW_LIFETIME_SECONDS = 28800
MINIMUM_REMAINING_SECONDS = 900
COMMAND_TIMEOUT_SECONDS = 180
TERRAFORM_TIMEOUT_SECONDS = 2400
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ACCOUNT_RE = re.compile(r"[0-9]{12}")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class PlanError(ValueError):
    pass


class CommandFailure(PlanError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int, Path], subprocess.CompletedProcess[bytes]]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PlanError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_module(PREFLIGHT_EXECUTOR, "aws_dev_clean_room_preflight_dependency")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        raise PlanError(f"{label} is invalid") from error


def parse_json_bytes(value: bytes, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise PlanError(f"{label} returned malformed JSON") from error
    require(isinstance(parsed, dict), f"{label} must return a JSON object")
    return parsed


def utc_timestamp(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise PlanError(f"{label} must be a valid UTC timestamp") from error
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
        "expectedTerraformVersion", "privatePreflightRequestPath",
        "privatePreflightRequestSha256", "privatePreflightResultPath",
        "privatePreflightResultSha256", "privatePreflightEvidencePath",
        "privatePreflightEvidenceSha256", "privateSourceManifestPath",
        "privateSourceManifestFileSha256", "sourceManifestSha256",
        "privateStagedSourceDirectory", "privateBackendConfigPath",
        "privateBackendConfigSha256", "privateTerraformTfvarsPath",
        "privateTerraformTfvarsSha256", "privatePlanSourceDirectory",
        "privatePlanOutputDirectory", "humanReview", "approval", "executionBoundary",
    }
    require(isinstance(value, dict) and set(value) == fields, "Create-plan request fields changed")
    require(value["schemaVersion"] == "v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-request-v1", "Request schema changed")
    require(value["operation"] == CONFIRMATION, "Request operation changed")
    require(value["repository"] == "SterlingAureum/startup-devops-baseline", "Repository changed")
    require(value["trustedRef"] == "refs/heads/main", "Only protected main is trusted")
    require(isinstance(value["expectedMainCommit"], str) and COMMIT_RE.fullmatch(value["expectedMainCommit"]) is not None, "Expected main commit is invalid")
    require(isinstance(value["expectedAwsAccountId"], str) and ACCOUNT_RE.fullmatch(value["expectedAwsAccountId"]) is not None, "Expected AWS account is invalid")
    require(value["expectedAwsRegion"] == AWS_REGION, "AWS region changed")
    require(value["expectedClusterName"] == CLUSTER_NAME, "Cluster name changed")
    require(isinstance(value["expectedTerraformVersion"], str) and VERSION_RE.fullmatch(value["expectedTerraformVersion"]) is not None, "Terraform version is invalid")
    for key in (
        "privatePreflightRequestSha256", "privatePreflightResultSha256",
        "privatePreflightEvidenceSha256", "privateSourceManifestFileSha256",
        "sourceManifestSha256", "privateBackendConfigSha256", "privateTerraformTfvarsSha256",
    ):
        require(isinstance(value[key], str) and SHA256_RE.fullmatch(value[key]) is not None, f"Invalid digest: {key}")
    for key in (
        "privatePreflightRequestPath", "privatePreflightResultPath",
        "privatePreflightEvidencePath", "privateSourceManifestPath",
        "privateStagedSourceDirectory", "privateBackendConfigPath",
        "privateTerraformTfvarsPath", "privatePlanSourceDirectory",
        "privatePlanOutputDirectory",
    ):
        require(isinstance(value[key], str), f"Invalid path: {key}")
    require(value["humanReview"] == {"preflightReviewed": True, "reviewedMaximumBudgetUsd": 50}, "Human review boundary changed")
    approval = value["approval"]
    require(isinstance(approval, dict) and set(approval) == {"notBeforeUtc", "expiresAtUtc", "planReviewExpiresAtUtc"}, "Approval fields changed")
    start = utc_timestamp(approval["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(approval["expiresAtUtc"], "Approval expiry")
    review_expiry = utc_timestamp(approval["planReviewExpiresAtUtc"], "Plan review expiry")
    require(expiry > start and expiry - start <= timedelta(seconds=MAXIMUM_APPROVAL_WINDOW_SECONDS), "Approval window must be positive and at most two hours")
    require(review_expiry >= expiry and review_expiry - start <= timedelta(seconds=MAXIMUM_PLAN_REVIEW_LIFETIME_SECONDS), "Plan review window must include execution and be at most eight hours")
    require(value["executionBoundary"] == {
        "awsReadOnlyValidation": True,
        "localPrivateSourceCopy": True,
        "terraformInitReconfigure": True,
        "terraformSavedPlan": True,
        "terraformShow": True,
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


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise PlanError("Git identity check failed")
    return result.stdout.strip()


def run_command(arguments: list[str], environment: dict[str, str], timeout: int, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True, check=False, timeout=timeout)


def validate_preflight_chain(request: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    paths: dict[str, Path] = {}
    bindings = (
        ("preflight_request", "privatePreflightRequestPath", "privatePreflightRequestSha256"),
        ("preflight_result", "privatePreflightResultPath", "privatePreflightResultSha256"),
        ("preflight_evidence", "privatePreflightEvidencePath", "privatePreflightEvidenceSha256"),
        ("source_manifest", "privateSourceManifestPath", "privateSourceManifestFileSha256"),
        ("backend", "privateBackendConfigPath", "privateBackendConfigSha256"),
        ("tfvars", "privateTerraformTfvarsPath", "privateTerraformTfvarsSha256"),
    )
    for label, path_key, digest_key in bindings:
        path = require_private_file(Path(request[path_key]), label.replace("_", " ").title())
        require(not is_within(path, repository_root), f"{label} must remain outside the repository")
        require(file_sha256(path) == request[digest_key], f"{label} digest changed")
        paths[label] = path

    preflight_request = PREFLIGHT.validate_request(load_json(paths["preflight_request"], "Preflight request"))
    require(preflight_request["expectedAwsAccountId"] == request["expectedAwsAccountId"], "Preflight AWS account changed")
    require(preflight_request["expectedAwsRegion"] == AWS_REGION and preflight_request["expectedClusterName"] == CLUSTER_NAME, "Preflight target changed")
    require(preflight_request["privateBackendConfigSha256"] == request["privateBackendConfigSha256"], "Preflight backend digest changed")

    result = load_json(paths["preflight_result"], "Preflight result")
    require(result.get("schemaVersion") == "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-result-v1", "Preflight result schema changed")
    require(result.get("status") == "aws-dev-remote-state-clean-room-preflight-complete-awaiting-separate-plan-review", "Preflight result status changed")
    for key, expected in {
        "control_plane_commit": preflight_request["expectedMainCommit"],
        "private_preflight_request_sha256": request["privatePreflightRequestSha256"],
        "private_backend_config_sha256": request["privateBackendConfigSha256"],
        "preflight_evidence_sha256": request["privatePreflightEvidenceSha256"],
        "source_manifest_sha256": request["sourceManifestSha256"],
        "source_manifest_file_sha256": request["privateSourceManifestFileSha256"],
        "eks_cluster_absent": True,
        "eks_cluster_error_code": "ResourceNotFoundException",
        "remote_state_object_version_count": 0,
        "remote_state_delete_marker_count": 0,
        "remote_lock_object_version_count": 0,
        "remote_lock_delete_marker_count": 0,
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
        "automatic_retry_performed": False,
    }.items():
        require(result.get(key) == expected, f"Preflight result boundary changed: {key}")

    evidence = load_json(paths["preflight_evidence"], "Preflight evidence")
    require(evidence.get("schemaVersion") == "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-evidence-v1", "Preflight evidence schema changed")
    require(evidence.get("controlPlaneCommit") == preflight_request["expectedMainCommit"], "Preflight evidence commit changed")
    require(evidence.get("privateRequestSha256") == request["privatePreflightRequestSha256"], "Preflight evidence request changed")
    require(evidence.get("sourceManifestSha256") == request["sourceManifestSha256"], "Preflight evidence source changed")
    require(evidence.get("sourceManifestFileSha256") == request["privateSourceManifestFileSha256"], "Preflight evidence manifest file changed")
    require(evidence.get("terraformInitExecuted") is False and evidence.get("terraformPlanExecuted") is False and evidence.get("terraformApplyExecuted") is False, "Preflight evidence contains Terraform execution")

    manifest = load_json(paths["source_manifest"], "Source manifest")
    require(manifest.get("schemaVersion") == "v0.12.4.1.5.0.4-private-staged-source-manifest-v1", "Source manifest schema changed")
    require(manifest.get("controlPlaneCommit") == preflight_request["expectedMainCommit"], "Source manifest commit changed")
    require(manifest.get("sourceManifestSha256") == request["sourceManifestSha256"], "Source manifest digest binding changed")
    entries = manifest.get("entries")
    require(isinstance(entries, list) and entries, "Source manifest entries are empty")
    require(PREFLIGHT.source_manifest_digest(entries) == request["sourceManifestSha256"], "Source manifest semantic digest changed")

    staging = require_private_directory(Path(request["privateStagedSourceDirectory"]), "Private staged source")
    require(not is_within(staging, repository_root), "Private staged source must remain outside the repository")
    expected_files: set[str] = set()
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {"path", "gitMode", "sha256"}, "Source entry shape changed")
        relative = Path(entry["path"]).relative_to("infra/terraform/aws")
        require(not relative.is_absolute() and ".." not in relative.parts, "Source entry escaped AWS root")
        path = staging / relative
        require(path.is_file() and not path.is_symlink(), f"Staged source missing: {relative}")
        require(file_sha256(path) == entry["sha256"], f"Staged source digest changed: {relative}")
        expected_files.add(relative.as_posix())
    actual_files = {path.relative_to(staging).as_posix() for path in staging.rglob("*") if path.is_file()}
    require(actual_files == expected_files, "Staged source file inventory changed")
    require(not any(".terraform" in Path(item).parts or item.endswith(".tfstate") or ".tfstate." in item or item.endswith("terraform.tfvars") or item.endswith(".tfplan") for item in actual_files), "Staged source contains private or generated Terraform artifacts")

    backend = PREFLIGHT.parse_backend_config(paths["backend"])
    PREFLIGHT.validate_backend_config(backend, preflight_request)
    return {"paths": paths, "preflight_request": preflight_request, "preflight_result": result, "entries": entries, "staging": staging, "backend": backend}


def verify_inputs(
    request_path: Path,
    *,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    private_request = require_private_file(request_path, "Private create-plan request")
    require(not is_within(private_request, repository_root), "Create-plan request must remain outside the repository")
    request = validate_request(load_json(private_request, "Private create-plan request"))
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = utc_timestamp(request["approval"]["notBeforeUtc"], "Approval start")
    expiry = utc_timestamp(request["approval"]["expiresAtUtc"], "Approval expiry")
    require(start <= current < expiry, "Create-plan approval is not currently active")
    remaining = int((expiry - current).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "Create-plan approval has less than 15 minutes remaining")
    expected_main = request["expectedMainCommit"]
    require(git_runner(["branch", "--show-current"]) == "main", "Create-plan must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Create-plan requires a clean worktree")
    require(git_runner(["rev-parse", "HEAD"]) == expected_main and git_runner(["rev-parse", "origin/main"]) == expected_main, "HEAD and origin/main must equal reviewed main")
    chain = validate_preflight_chain(request, repository_root)
    plan_source = require_new_private_directory(Path(request["privatePlanSourceDirectory"]), "Private plan source")
    output = require_new_private_directory(Path(request["privatePlanOutputDirectory"]), "Private plan output")
    require(not is_within(plan_source, repository_root) and not is_within(output, repository_root), "Private plan directories must remain outside the repository")
    require(plan_source != output and not is_within(plan_source, output) and not is_within(output, plan_source), "Plan source and output directories must be distinct")
    protected_directories = {
        chain["staging"],
        chain["paths"]["preflight_result"].parent,
        chain["paths"]["preflight_evidence"].parent,
        chain["paths"]["source_manifest"].parent,
    }
    for protected in protected_directories:
        require(not is_within(plan_source, protected) and not is_within(output, protected), "New plan directories must not overlap reviewed private inputs")
    return {"request": request, "request_path": private_request, "chain": chain, "plan_source": plan_source, "output": output, "remaining": remaining}


def redacted_verification(context: dict[str, Any]) -> dict[str, Any]:
    request = context["request"]
    return {
        "status": "aws-dev-clean-room-saved-create-plan-inputs-verified",
        "control_plane_commit": request["expectedMainCommit"],
        "private_create_plan_request_sha256": file_sha256(context["request_path"]),
        "private_preflight_request_sha256": request["privatePreflightRequestSha256"],
        "private_preflight_result_sha256": request["privatePreflightResultSha256"],
        "private_preflight_evidence_sha256": request["privatePreflightEvidenceSha256"],
        "private_backend_config_sha256": request["privateBackendConfigSha256"],
        "private_tfvars_sha256": request["privateTerraformTfvarsSha256"],
        "source_manifest_sha256": request["sourceManifestSha256"],
        "tracked_source_file_count": len(context["chain"]["entries"]),
        "human_preflight_review_verified": True,
        "remaining_plan_approval_seconds": context["remaining"],
        "terraform_init_authorized": False,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "state_migration_authorized": False,
        "operational_commands_executed": [],
        "private_resource_identity_emitted": False,
        "next_action": "obtain-separate-aws-dev-clean-room-saved-create-plan-approval",
    }


def safe_environment(terraform_data: Path) -> dict[str, str]:
    allowed = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy"}
    environment = {key: value for key, value in os.environ.items() if key in allowed or key.startswith("AWS_")}
    for key in list(environment):
        if key.startswith("CONFIRM_") or key.startswith("AWS_ENDPOINT_URL") or key in {"AWS_DATA_PATH", "AWS_CA_BUNDLE"}:
            del environment[key]
    environment.update(AWS_REGION=AWS_REGION, AWS_DEFAULT_REGION=AWS_REGION, AWS_PAGER="", TF_DATA_DIR=str(terraform_data), TF_IN_AUTOMATION="1", PYTHONDONTWRITEBYTECODE="1")
    return environment


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


def run_expected_missing_eks(output: Path, label: str, environment: dict[str, str], cwd: Path, runner: CommandRunner) -> None:
    try:
        result = runner(["aws", "eks", "describe-cluster", "--region", AWS_REGION, "--name", CLUSTER_NAME, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, cwd)
    except subprocess.TimeoutExpired as error:
        raise CommandFailure(f"{label} timed out") from error
    record_result(output, label, result)
    require(result.returncode != 0 and result.stdout == b"", "aws-dev EKS cluster unexpectedly exists")
    match = re.search(rb"An error occurred \(([^)]+)\)", result.stderr)
    require(match is not None and match.group(1) == b"ResourceNotFoundException", "EKS absence error changed")


def history_counts(value: dict[str, Any]) -> dict[str, int]:
    require(value.get("IsTruncated") in {None, False}, "State object history response is truncated")
    versions = value.get("Versions", [])
    markers = value.get("DeleteMarkers", [])
    require(isinstance(versions, list) and isinstance(markers, list), "State object history shape changed")
    allowed = {STATE_KEY, LOCK_KEY}
    require(all(item.get("Key") in allowed for item in [*versions, *markers]), "Unexpected object returned for exact state prefix")
    return {
        "stateVersions": sum(item.get("Key") == STATE_KEY for item in versions),
        "stateDeleteMarkers": sum(item.get("Key") == STATE_KEY for item in markers),
        "lockVersions": sum(item.get("Key") == LOCK_KEY for item in versions),
        "lockDeleteMarkers": sum(item.get("Key") == LOCK_KEY for item in markers),
        "lockLatestVersions": sum(item.get("Key") == LOCK_KEY and item.get("IsLatest") is True for item in versions),
        "lockLatestDeleteMarkers": sum(item.get("Key") == LOCK_KEY and item.get("IsLatest") is True for item in markers),
    }


def validate_empty_history(counts: dict[str, int]) -> None:
    require(all(value == 0 for value in counts.values()), "Remote dev state or lock history is not empty before planning")


def validate_post_plan_history(before: dict[str, int], after: dict[str, int]) -> None:
    require(after["stateVersions"] == 0 and after["stateDeleteMarkers"] == 0, "Terraform plan wrote remote state")
    require(after["lockVersions"] - before["lockVersions"] == 1, "Plan lock object-version delta changed")
    require(after["lockDeleteMarkers"] - before["lockDeleteMarkers"] == 1, "Plan lock delete-marker delta changed")
    require(after["lockLatestVersions"] == 0 and after["lockLatestDeleteMarkers"] == 1, "Plan lock was not cleanly released")


def plan_gate(document: dict[str, Any]) -> dict[str, Any]:
    require(document.get("complete") is True and document.get("errored") is False and document.get("applyable") is True, "Saved plan is not complete and applyable")
    drift = document.get("resource_drift", [])
    require(isinstance(drift, list) and not drift, "Saved plan contains resource drift")
    changes = document.get("resource_changes")
    require(isinstance(changes, list) and changes, "Saved plan has no resource changes")
    managed: list[str] = []
    data: list[str] = []
    imports: list[str] = []
    for item in changes:
        require(isinstance(item, dict) and isinstance(item.get("address"), str), "Plan resource change shape changed")
        change = item.get("change")
        require(isinstance(change, dict) and isinstance(change.get("actions"), list), "Plan action shape changed")
        actions = change["actions"]
        if change.get("importing") is not None:
            imports.append(item["address"])
        if item.get("mode") == "managed":
            require(actions == ["create"], f"Managed action is not create-only: {item['address']}")
            managed.append(item["address"])
        elif item.get("mode") == "data":
            require(actions in (["read"], ["no-op"]), f"Data action changed: {item['address']}")
            data.append(item["address"])
        else:
            raise PlanError(f"Unsupported resource mode: {item.get('mode')}")
    require(not imports, "Saved plan contains import")
    require(managed, "Saved plan contains no managed creates")
    require("module.eks.aws_eks_cluster.this" in managed, "Expected EKS cluster create is missing")
    output_changes = document.get("output_changes", {})
    require(isinstance(output_changes, dict), "Plan output changes shape changed")
    require(all(item.get("actions") in (["create"], ["no-op"]) for item in output_changes.values() if isinstance(item, dict)), "Plan output contains a non-create action")
    inventory = {
        "schemaVersion": "v0.12.4.1.5.0.5-private-create-plan-address-inventory-v1",
        "managedCreateAddresses": sorted(managed),
        "dataReadOrNoopAddresses": sorted(data),
        "managedCreateCount": len(managed),
        "dataChangeCount": len(data),
        "resourceDriftCount": 0,
        "importCount": 0,
    }
    return inventory


def copy_plan_source(context: dict[str, Any]) -> None:
    destination: Path = context["plan_source"]
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    staging: Path = context["chain"]["staging"]
    for entry in context["chain"]["entries"]:
        relative = Path(entry["path"]).relative_to("infra/terraform/aws")
        source = staging / relative
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        write_private(target, source.read_bytes(), 0o700 if entry["gitMode"] == "100755" else 0o600)
        require(file_sha256(target) == entry["sha256"], f"Plan source digest changed: {relative}")


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
    require(os.environ.get("CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN") == CONFIRMATION, f"Set CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN={CONFIRMATION}")
    forbidden = (
        "CONFIRM_AWS_DEV_APPLY", "CONFIRM_AWS_DEV_DESTROY", "CONFIRM_TERRAFORM_APPLY",
        "CONFIRM_TERRAFORM_DESTROY", "CONFIRM_STATE_PUSH", "CONFIRM_STATE_MIGRATION",
        "CONFIRM_EXTERNAL_SECRETS_GITOPS_PIN", "CONFIRM_EXTERNAL_SECRETS_LIVE_PREFLIGHT",
    )
    require(all(not os.environ.get(name) for name in forbidden), "Mutation confirmations must be unset")
    request = context["request"]
    output: Path = context["output"]
    output.mkdir(mode=0o700)
    output.chmod(0o700)
    copy_plan_source(context)
    backend_copy = output / "dev.s3.tfbackend"
    tfvars_copy = output / "terraform.tfvars.private"
    write_private(backend_copy, context["chain"]["paths"]["backend"].read_bytes())
    write_private(tfvars_copy, context["chain"]["paths"]["tfvars"].read_bytes())
    terraform_data = output / "terraform-data"
    terraform_data.mkdir(mode=0o700)
    terraform_data.chmod(0o700)
    environment = safe_environment(terraform_data)
    dev_root = context["plan_source"] / "environments/dev"

    identity = parse_json_bytes(run_logged(output, "aws-identity", ["aws", "sts", "get-caller-identity", "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "AWS identity")
    require(identity.get("Account") == request["expectedAwsAccountId"], "AWS caller account changed")
    run_expected_missing_eks(output, "eks-cluster-before-plan", environment, repository_root, runner)
    before_value = parse_json_bytes(run_logged(output, "s3-object-history-before-plan", ["aws", "s3api", "list-object-versions", "--bucket", context["chain"]["backend"]["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history before plan")
    before_counts = history_counts(before_value)
    validate_empty_history(before_counts)

    version = parse_json_bytes(run_logged(output, "terraform-version", ["terraform", "version", "-json"], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner).stdout, "Terraform version")
    require(version.get("terraform_version") == request["expectedTerraformVersion"], "Terraform version changed")
    init = ["terraform", "init", "-input=false", "-reconfigure", f"-backend-config={backend_copy}"]
    run_logged(output, "terraform-init-reconfigure", init, environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    lockfile = dev_root / ".terraform.lock.hcl"
    require(lockfile.is_file() and not lockfile.is_symlink(), "Terraform provider lockfile was not produced")
    lockfile.chmod(0o600)

    binary_plan = output / "aws-dev-create.tfplan"
    plan = ["terraform", "plan", "-input=false", "-lock=true", "-lock-timeout=0s", f"-var-file={tfvars_copy}", f"-out={binary_plan}"]
    run_logged(output, "terraform-plan-create", plan, environment, TERRAFORM_TIMEOUT_SECONDS, dev_root, runner)
    require(binary_plan.is_file() and not binary_plan.is_symlink(), "Terraform did not create a regular saved plan")
    binary_plan.chmod(0o600)
    show_json = run_logged(output, "terraform-show-create-json", ["terraform", "show", "-json", str(binary_plan)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    plan_json_path = output / "aws-dev-create-plan.json"
    write_private(plan_json_path, show_json.stdout)
    document = parse_json_bytes(show_json.stdout, "Terraform saved plan")
    inventory = plan_gate(document)
    inventory_path = output / "create-plan-address-inventory.json"
    write_private_json(inventory_path, inventory)
    show_text = run_logged(output, "terraform-show-create-text", ["terraform", "show", "-no-color", str(binary_plan)], environment, COMMAND_TIMEOUT_SECONDS, dev_root, runner)
    require(show_text.stdout, "Terraform human-readable plan is empty")
    plan_text_path = output / "aws-dev-create-plan.txt"
    write_private(plan_text_path, show_text.stdout)

    run_expected_missing_eks(output, "eks-cluster-after-plan", environment, repository_root, runner)
    after_value = parse_json_bytes(run_logged(output, "s3-object-history-after-plan", ["aws", "s3api", "list-object-versions", "--bucket", context["chain"]["backend"]["bucket"], "--prefix", STATE_KEY, "--output", "json"], environment, COMMAND_TIMEOUT_SECONDS, repository_root, runner).stdout, "S3 history after plan")
    after_counts = history_counts(after_value)
    validate_post_plan_history(before_counts, after_counts)
    require(file_sha256(context["chain"]["paths"]["backend"]) == request["privateBackendConfigSha256"], "Backend config changed during planning")
    require(file_sha256(context["chain"]["paths"]["tfvars"]) == request["privateTerraformTfvarsSha256"], "Terraform tfvars changed during planning")

    record = {
        "schemaVersion": "v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-record-v1",
        "controlPlaneCommit": request["expectedMainCommit"],
        "createdAtUtc": utc_text(current),
        "planReviewExpiresAtUtc": request["approval"]["planReviewExpiresAtUtc"],
        "privateCreatePlanRequestSha256": file_sha256(context["request_path"]),
        "privatePreflightRequestSha256": request["privatePreflightRequestSha256"],
        "privatePreflightResultSha256": request["privatePreflightResultSha256"],
        "privatePreflightEvidenceSha256": request["privatePreflightEvidenceSha256"],
        "sourceManifestSha256": request["sourceManifestSha256"],
        "privateBackendConfigSha256": request["privateBackendConfigSha256"],
        "privateTfvarsSha256": request["privateTerraformTfvarsSha256"],
        "terraformVersion": request["expectedTerraformVersion"],
        "providerLockfileSha256": file_sha256(lockfile),
        "binaryPlanSha256": file_sha256(binary_plan),
        "planJsonSha256": file_sha256(plan_json_path),
        "planTextSha256": file_sha256(plan_text_path),
        "addressInventorySha256": file_sha256(inventory_path),
        "managedCreateCount": inventory["managedCreateCount"],
        "dataChangeCount": inventory["dataChangeCount"],
        "resourceDriftCount": 0,
        "importCount": 0,
        "stateObjectVersionCount": after_counts["stateVersions"],
        "stateDeleteMarkerCount": after_counts["stateDeleteMarkers"],
        "lockObjectVersionDelta": after_counts["lockVersions"] - before_counts["lockVersions"],
        "lockDeleteMarkerDelta": after_counts["lockDeleteMarkers"] - before_counts["lockDeleteMarkers"],
        "terraformApplyExecuted": False,
        "environmentCreated": False,
    }
    record_path = output / "create-plan-record.json"
    write_private_json(record_path, record)
    return {
        "schemaVersion": "v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-result-v1",
        "status": "aws-dev-clean-room-saved-create-plan-produced-awaiting-separate-apply-review",
        "completed_at_utc": utc_text(current),
        "control_plane_commit": request["expectedMainCommit"],
        "private_create_plan_request_sha256": file_sha256(context["request_path"]),
        "private_preflight_result_sha256": request["privatePreflightResultSha256"],
        "source_manifest_sha256": request["sourceManifestSha256"],
        "private_backend_config_sha256": request["privateBackendConfigSha256"],
        "private_tfvars_sha256": request["privateTerraformTfvarsSha256"],
        "terraform_version": request["expectedTerraformVersion"],
        "provider_lockfile_sha256": record["providerLockfileSha256"],
        "binary_plan_sha256": record["binaryPlanSha256"],
        "terraform_plan_json_sha256": record["planJsonSha256"],
        "terraform_plan_text_sha256": record["planTextSha256"],
        "address_inventory_sha256": record["addressInventorySha256"],
        "plan_record_sha256": file_sha256(record_path),
        "managed_create_count": inventory["managedCreateCount"],
        "data_change_count": inventory["dataChangeCount"],
        "resource_drift_count": 0,
        "import_count": 0,
        "remote_state_object_version_count": 0,
        "remote_state_delete_marker_count": 0,
        "lock_object_version_delta": 1,
        "lock_delete_marker_delta": 1,
        "lock_object_absent": True,
        "plan_review_expires_at_utc": request["approval"]["planReviewExpiresAtUtc"],
        "terraform_init_executed": True,
        "terraform_plan_executed": True,
        "terraform_apply_executed": False,
        "state_migration_executed": False,
        "state_push_executed": False,
        "environment_created": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "private_object_version_id_emitted": False,
        "next_action": "human-review-private-create-plan-before-v0.12.4.1.5.0.6-exact-apply",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-plan-request", required=True, type=Path)
    args = parser.parse_args()
    try:
        context = verify_inputs(args.private_plan_request)
        result = redacted_verification(context) if args.phase == "verify" else execute(args.private_plan_request)
    except (CommandFailure, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, PlanError) as error:
        parser.exit(1, f"AWS-dev saved create plan stopped: {error}; preserve private evidence and do not retry\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

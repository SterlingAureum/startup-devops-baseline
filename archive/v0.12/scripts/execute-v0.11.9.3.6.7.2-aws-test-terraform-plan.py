#!/usr/bin/env python3
"""Verify or execute the guarded aws-test Terraform plan-only checkpoint."""

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
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DESIGN_CHECKER_RELATIVE = (
    "scripts/check-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py"
)
DESIGN_CHECKER_PATH = ROOT / DESIGN_CHECKER_RELATIVE
PLAN_CHECKER_PATH = ROOT / "scripts/check-aws-test-create-terraform-plan.py"
PREFLIGHT_RELATIVE = "scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py"
PREFLIGHT_PATH = ROOT / PREFLIGHT_RELATIVE
IMPLEMENTATION_BASELINE = "a94b69c75210a98210a3b9da7d4d32b0e8cbf93d"
DESIGN_PREFLIGHT_SHA256 = (
    "5f12981fc2720ff4ac9a03b11d5d3444f03bbb0408d0e87190643549e81e18c3"
)
DESIGN_CONTRACT = (
    "delivery/contracts/"
    "v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.json"
)
DESIGN_CONTRACT_SHA256 = (
    "02eb0395f0e54a2698f728d06750b4206b698ae14b2bcfdc6290c89acfe7cdb8"
)
DESIGN_TEMPLATE = (
    "delivery/examples/v0.11.9.3.6.7.1-aws-test-live-creation-plan.json"
)
DESIGN_TEMPLATE_SHA256 = (
    "07e4cf748f93878b05164aba9a032aa9baaa27477d3fdb218ecc19bbb1ef53d1"
)
DESIGN_CHECKER_SHA256 = (
    "eadc9322d00027916b1d2c8f14cc87bd51ef3585aed40e2302a8827e5389311d"
)
PREFLIGHT_SHA256 = (
    "b41a1c58865ffd44ae35165a7a17e941dd19d4b05dd0b1d6f2f09938afeec487"
)
PREFLIGHT_CONFIRMATION = "observe-reviewed-aws-test-create-preflight"
PLAN_CONFIRMATION = "execute-reviewed-aws-test-create-plan"
AWS_REGION = "us-east-1"
SECRET_NAME = "startup-devops-baseline-test/demo-api/postgresql"
MINIMUM_REMAINING_WINDOW_SECONDS = 900
PLAN_REVIEW_TTL_SECONDS = 3600


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DESIGN = load_module(DESIGN_CHECKER_PATH, "aws_test_private_plan")
PLAN_GATE = load_module(PLAN_CHECKER_PATH, "aws_test_terraform_plan")


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_private_file(path: Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular non-symlink file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 600")
    parent = path.parent
    require(parent.is_dir() and not parent.is_symlink(), f"{label} parent must be a private directory")
    require(
        stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,
        f"{label} parent must not grant group or other permissions",
    )


def require_private_parent(path: Path) -> None:
    parent = path.parent
    require(parent.is_dir() and not parent.is_symlink(), "Plan output parent must be a private directory")
    require(
        stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,
        "Plan output parent must not grant group or other permissions",
    )
    require(not path.exists() and not path.is_symlink(), "Plan output directory must be new")


def require_fingerprint(root: Path, relative: str, expected: str) -> None:
    path = root / relative
    require(path.is_file() and not path.is_symlink(), "Reviewed repository input must be regular")
    require(file_sha256(path) == expected, "Reviewed repository input fingerprint changed")


def write_private(path: Path, content: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(content)
    path.chmod(0o600)


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
    arguments: list[str], environment: dict[str, str], timeout: int
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def validate_preflight(result: Any, plan: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "account_id_emitted",
        "account_verified",
        "active_rehearsal_environment_count",
        "aws_dev_residual_cost_audit_evidence_sha256",
        "aws_prod_release_held",
        "aws_region",
        "aws_test_created",
        "aws_test_promotion_evidence_sha256",
        "control_plane_commit",
        "dev_test_release_equal",
        "environment_creation_authorized",
        "gitops_bootstrap_executed",
        "legacy_apply_wrapper_invoked",
        "legacy_apply_wrapper_sha256",
        "mutation_executed",
        "next_action",
        "release_id",
        "status",
        "target_environment",
        "terraform_apply_executed",
        "terraform_backend_kind",
        "terraform_command_executed",
        "terraform_plan_executed",
        "terraform_state_exists",
        "terraform_state_path_emitted",
        "terraform_state_resource_block_count",
        "terraform_state_resource_instance_count",
        "traffic_generated",
    }
    require(isinstance(result, dict) and set(result) == fields, "Fresh preflight fields changed")
    expected = {
        "status": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
        "target_environment": "aws-test",
        "control_plane_commit": plan["planned_control_plane_commit"],
        "account_verified": True,
        "account_id_emitted": False,
        "active_rehearsal_environment_count": 0,
        "aws_region": AWS_REGION,
        "aws_dev_residual_cost_audit_evidence_sha256": (
            "d73e4b5107b4c99ae1feebd2a34197040e4d0f50b6c6ccbecdf951bbe1da25e9"
        ),
        "aws_test_promotion_evidence_sha256": (
            "4977ddfb21738530681ce671ebaf9d71d4132e4e81c9ea1135e4b3527c27a96e"
        ),
        "aws_prod_release_held": True,
        "dev_test_release_equal": True,
        "release_id": plan["candidate"]["release_id"],
        "terraform_backend_kind": "local",
        "terraform_state_resource_block_count": 0,
        "terraform_state_resource_instance_count": 0,
        "terraform_state_path_emitted": False,
        "legacy_apply_wrapper_invoked": False,
        "legacy_apply_wrapper_sha256": (
            "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114"
        ),
        "terraform_command_executed": False,
        "terraform_plan_executed": False,
        "terraform_apply_executed": False,
        "environment_creation_authorized": False,
        "mutation_executed": False,
        "gitops_bootstrap_executed": False,
        "traffic_generated": False,
        "aws_test_created": False,
        "next_action": "review-private-aws-test-create-plan-design",
    }
    for key, value in expected.items():
        require(result.get(key) == value, f"Fresh preflight boundary changed: {key}")
    require(type(result["terraform_state_exists"]) is bool, "Fresh preflight state flag changed")
    return result


def verify_inputs(
    private_plan_path: Path,
    fresh_preflight_path: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], Path, int]:
    require_private_file(private_plan_path, "Private creation plan")
    require_private_file(fresh_preflight_path, "Fresh preflight result")
    private_plan = json.loads(private_plan_path.read_text())
    DESIGN.validate(private_plan, repository_root)

    expected_main = private_plan["planned_control_plane_commit"]
    require(
        expected_main != IMPLEMENTATION_BASELINE,
        "Private plan must bind the post-v0.11.9.3.6.7.2 protected main",
    )
    require(
        file_sha256(fresh_preflight_path)
        == private_plan["fresh_preflight_result_sha256"],
        "Fresh preflight result SHA-256 changed",
    )
    preflight = validate_preflight(json.loads(fresh_preflight_path.read_text()), private_plan)

    require(git_runner(["branch", "--show-current"]) == "main", "Executor must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Executor requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_main
        and git_runner(["rev-parse", "origin/main"]) == expected_main,
        "HEAD and origin/main must equal the private-plan main",
    )
    git_runner(["merge-base", "--is-ancestor", IMPLEMENTATION_BASELINE, expected_main])

    for relative, expected in (
        (DESIGN_CONTRACT, DESIGN_CONTRACT_SHA256),
        (DESIGN_TEMPLATE, DESIGN_TEMPLATE_SHA256),
        (DESIGN_CHECKER_RELATIVE, DESIGN_CHECKER_SHA256),
        (PREFLIGHT_RELATIVE, PREFLIGHT_SHA256),
        (
            private_plan["infrastructure"]["backend_declaration_path"],
            private_plan["infrastructure"]["backend_declaration_sha256"],
        ),
        (
            private_plan["infrastructure"]["qualification_profile_path"],
            private_plan["infrastructure"]["qualification_profile_sha256"],
        ),
        (
            private_plan["infrastructure"]["legacy_apply_wrapper"],
            private_plan["infrastructure"]["legacy_apply_wrapper_sha256"],
        ),
    ):
        require_fingerprint(repository_root, relative, expected)

    variable_file = repository_root / private_plan["infrastructure"]["local_variable_file_path"]
    require(
        variable_file.is_file() and not variable_file.is_symlink(),
        "Reviewed local terraform.tfvars must be a regular non-symlink file",
    )
    require(
        file_sha256(variable_file) == private_plan["local_variable_file_sha256"],
        "Local terraform.tfvars fingerprint changed",
    )

    output_directory = Path(private_plan["private_plan_bundle_directory"])
    require_private_parent(output_directory)

    current = now or datetime.now(timezone.utc)
    require(current.tzinfo is not None, "Current time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    start = DESIGN.utc_timestamp(private_plan["cost_control"]["planned_start_utc"], "planned start UTC")
    deadline = DESIGN.utc_timestamp(
        private_plan["cost_control"]["teardown_review_deadline_utc"],
        "teardown deadline UTC",
    )
    require(start <= current < deadline, "Plan execution must be inside the reviewed session window")
    remaining = int((deadline - current).total_seconds())
    require(
        remaining >= MINIMUM_REMAINING_WINDOW_SECONDS,
        "At least 900 seconds must remain in the reviewed session window",
    )
    return private_plan, preflight, output_directory, remaining


def safe_environment(plan: dict[str, Any], terraform_data: Path) -> dict[str, str]:
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
        AWS_ENVIRONMENT="aws-test",
        EXPECTED_AWS_ACCOUNT_ID=plan["aws_account_id"],
        CONFIRM_AWS_TEST_CREATE_PREFLIGHT=PREFLIGHT_CONFIRMATION,
        TF_DATA_DIR=str(terraform_data),
        TF_IN_AUTOMATION="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return environment


def record_result(
    output_directory: Path,
    label: str,
    result: subprocess.CompletedProcess[bytes],
) -> None:
    write_private(output_directory / f"{label}.stdout", result.stdout)
    write_private(output_directory / f"{label}.stderr", result.stderr)


def require_secret_absent(
    output_directory: Path,
    label: str,
    environment: dict[str, str],
    runner: CommandRunner,
) -> None:
    result = runner(
        [
            "aws",
            "--region",
            AWS_REGION,
            "secretsmanager",
            "describe-secret",
            "--secret-id",
            SECRET_NAME,
            "--output",
            "json",
        ],
        environment,
        90,
    )
    record_result(output_directory, label, result)
    if result.returncode == 0:
        raise CommandFailure("aws-test Secret name is already present; stop before Terraform plan")
    require(
        b"(ResourceNotFoundException)" in result.stderr,
        "Secret metadata lookup did not prove absence",
    )


def run_logged(
    output_directory: Path,
    label: str,
    arguments: list[str],
    environment: dict[str, str],
    timeout: int,
    runner: CommandRunner,
) -> subprocess.CompletedProcess[bytes]:
    result = runner(arguments, environment, timeout)
    record_result(output_directory, label, result)
    if result.returncode:
        raise CommandFailure(f"{label} failed; preserve the private plan bundle")
    return result


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def produce_plan(
    plan: dict[str, Any],
    private_plan_path: Path,
    fresh_preflight_path: Path,
    output_directory: Path,
    runner: CommandRunner,
    now: datetime,
    repository_root: Path = ROOT,
) -> dict[str, Any]:
    output_directory.mkdir(mode=0o700)
    output_directory.chmod(0o700)
    terraform_data = output_directory / "terraform-data"
    terraform_data.mkdir(mode=0o700)
    terraform_data.chmod(0o700)
    environment = safe_environment(plan, terraform_data)
    terraform_directory = repository_root / plan["infrastructure"]["terraform_directory"]
    profile = repository_root / plan["infrastructure"]["qualification_profile_path"]
    variable_file = repository_root / plan["infrastructure"]["local_variable_file_path"]
    input_fingerprints = {
        "qualification_profile_sha256": file_sha256(profile),
        "local_variable_file_sha256": file_sha256(variable_file),
    }

    require_secret_absent(output_directory, "secret-before-plan", environment, runner)
    terraform_prefix = ["terraform", f"-chdir={terraform_directory}"]
    run_logged(
        output_directory,
        "terraform-init",
        [*terraform_prefix, "init", "-input=false", "-lockfile=readonly"],
        environment,
        900,
        runner,
    )

    binary_plan = output_directory / "aws-test-create.tfplan"
    management_cidr = f"{plan['management_ipv4']}/32"
    run_logged(
        output_directory,
        "terraform-plan",
        [
            *terraform_prefix,
            "plan",
            "-input=false",
            "-lock=true",
            f"-out={binary_plan}",
            f"-var-file={profile}",
            "-var=environment=test",
            "-var=project_name=startup-devops-baseline",
            f"-var=aws_region={AWS_REGION}",
            f'-var=eks_public_access_cidrs=["{management_cidr}"]',
        ],
        environment,
        1800,
        runner,
    )
    require(binary_plan.is_file() and not binary_plan.is_symlink(), "Terraform did not create a regular saved plan")
    binary_plan.chmod(0o600)

    json_result = runner([*terraform_prefix, "show", "-json", str(binary_plan)], environment, 300)
    write_private(output_directory / "terraform-show-json.stderr", json_result.stderr)
    if json_result.returncode:
        raise CommandFailure("terraform-show-json failed; preserve the private plan bundle")
    plan_json = output_directory / "terraform-plan.json"
    write_private(plan_json, json_result.stdout)
    document = json.loads(json_result.stdout)
    gate = PLAN_GATE.validate(document, plan["aws_account_id"], plan["management_ipv4"])

    text_result = runner([*terraform_prefix, "show", "-no-color", str(binary_plan)], environment, 300)
    write_private(output_directory / "terraform-show-text.stderr", text_result.stderr)
    if text_result.returncode or not text_result.stdout:
        raise CommandFailure("terraform-show-text failed; preserve the private plan bundle")
    plan_text = output_directory / "terraform-plan.txt"
    write_private(plan_text, text_result.stdout)

    require_secret_absent(output_directory, "secret-after-plan", environment, runner)
    require(
        input_fingerprints
        == {
            "qualification_profile_sha256": file_sha256(profile),
            "local_variable_file_sha256": file_sha256(variable_file),
        },
        "Terraform variable inputs changed during planning",
    )

    gate_path = output_directory / "plan-gate.json"
    write_private(gate_path, (json.dumps(gate, indent=2, sort_keys=True) + "\n").encode())
    deadline = DESIGN.utc_timestamp(
        plan["cost_control"]["teardown_review_deadline_utc"],
        "teardown deadline UTC",
    )
    expires = min(now + timedelta(seconds=PLAN_REVIEW_TTL_SECONDS), deadline)
    record = {
        "schema_version": "v0.11.9.3.6.7.2",
        "account_id": plan["aws_account_id"],
        "control_plane_commit": plan["planned_control_plane_commit"],
        "release_id": plan["candidate"]["release_id"],
        "management_cidr": management_cidr,
        "created_at_utc": utc_text(now),
        "expires_at_utc": utc_text(expires),
        "fresh_preflight_sha256": file_sha256(fresh_preflight_path),
        "private_plan_sha256": file_sha256(private_plan_path),
        "qualification_profile_sha256": input_fingerprints[
            "qualification_profile_sha256"
        ],
        "local_variable_file_sha256": input_fingerprints[
            "local_variable_file_sha256"
        ],
        "binary_plan_sha256": file_sha256(binary_plan),
        "terraform_plan_json_sha256": file_sha256(plan_json),
        "terraform_plan_text_sha256": file_sha256(plan_text),
        "plan_gate_sha256": file_sha256(gate_path),
        "action_counts": gate["action_counts"],
        "resource_change_count": gate["resource_change_count"],
        "secret_metadata_absent_before_and_after": True,
        "terraform_apply_executed": False,
        "environment_created": False,
    }
    record_path = output_directory / "plan-record.json"
    write_private(record_path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode())

    return {
        "status": "aws-test-create-only-terraform-plan-produced",
        "control_plane_commit": plan["planned_control_plane_commit"],
        "candidate_release_id": plan["candidate"]["release_id"],
        "fresh_preflight_sha256": file_sha256(fresh_preflight_path),
        "action_counts": gate["action_counts"],
        "resource_change_count": gate["resource_change_count"],
        "aws_test_cluster_create_count": gate["aws_test_cluster_create_count"],
        "runtime_access_entry_create_count": gate[
            "runtime_access_entry_create_count"
        ],
        "binary_plan_sha256": record["binary_plan_sha256"],
        "terraform_plan_json_sha256": record["terraform_plan_json_sha256"],
        "terraform_plan_text_sha256": record["terraform_plan_text_sha256"],
        "plan_gate_sha256": record["plan_gate_sha256"],
        "plan_record_sha256": file_sha256(record_path),
        "plan_review_expires_at_utc": record["expires_at_utc"],
        "secret_metadata_absent_before_and_after": True,
        "variable_inputs_matched": True,
        "terraform_plan_executed": True,
        "terraform_apply_executed": False,
        "environment_creation_authorized": False,
        "environment_created": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "review-private-plan-before-separate-apply-executor-design",
    }


def redacted_verification(
    plan: dict[str, Any],
    private_plan_path: Path,
    fresh_preflight_path: Path,
    remaining: int,
) -> dict[str, Any]:
    return {
        "status": "aws-test-terraform-plan-executor-inputs-verified",
        "control_plane_commit": plan["planned_control_plane_commit"],
        "candidate_release_id": plan["candidate"]["release_id"],
        "private_plan_sha256": file_sha256(private_plan_path),
        "fresh_preflight_sha256": file_sha256(fresh_preflight_path),
        "remaining_window_seconds": remaining,
        "terraform_plan_authorized": False,
        "terraform_plan_executed": False,
        "terraform_apply_executed": False,
        "environment_creation_authorized": False,
        "commands_executed": [],
        "next_action": "obtain-separate-aws-test-terraform-plan-approval",
    }


def execute(
    private_plan_path: Path,
    fresh_preflight_path: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    plan, saved_preflight, output_directory, _ = verify_inputs(
        private_plan_path,
        fresh_preflight_path,
        repository_root,
        git_runner,
        current,
    )
    require(os.environ.get("AWS_ENVIRONMENT") == "aws-test", "AWS_ENVIRONMENT must be aws-test")
    require(
        os.environ.get("EXPECTED_AWS_ACCOUNT_ID") == plan["aws_account_id"],
        "EXPECTED_AWS_ACCOUNT_ID must equal the reviewed private plan",
    )
    require(
        os.environ.get("CONFIRM_AWS_TEST_CREATE_PREFLIGHT") == PREFLIGHT_CONFIRMATION,
        f"Set CONFIRM_AWS_TEST_CREATE_PREFLIGHT={PREFLIGHT_CONFIRMATION}",
    )
    require(
        os.environ.get("CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION")
        == PLAN_CONFIRMATION,
        f"Set CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION={PLAN_CONFIRMATION}",
    )
    for forbidden in (
        "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION",
        "CONFIRM_AWS_DEV_APPLY",
        "CONFIRM_AWS_TEST_APPLY",
        "CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION",
        "AWS_TEST_APPLY_MODE",
    ):
        require(not os.environ.get(forbidden), "Apply, destroy and prior execution controls must be unset")

    temporary_data = output_directory.parent / (
        ".preflight-terraform-data-" + hashlib.sha256(str(output_directory).encode()).hexdigest()[:12]
    )
    environment = safe_environment(plan, temporary_data)
    immediate = runner(
        [
            sys.executable,
            str(PREFLIGHT_PATH),
            "verify",
            "--expected-control-plane-commit",
            plan["planned_control_plane_commit"],
        ],
        environment,
        300,
    )
    require(immediate.returncode == 0, "Immediate aws-test preflight failed")
    require(immediate.stderr == b"", "Immediate aws-test preflight stderr was not empty")
    require(immediate.stdout == fresh_preflight_path.read_bytes(), "Immediate preflight bytes changed")
    require(json.loads(immediate.stdout) == saved_preflight, "Immediate preflight semantics changed")

    return produce_plan(
        plan,
        private_plan_path,
        fresh_preflight_path,
        output_directory,
        runner,
        current.astimezone(timezone.utc),
        repository_root,
    )


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-plan", required=True, type=Path)
    parser.add_argument("--fresh-preflight-result", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            plan, _, _, remaining = verify_inputs(
                args.private_plan,
                args.fresh_preflight_result,
            )
            result = redacted_verification(
                plan,
                args.private_plan,
                args.fresh_preflight_result,
                remaining,
            )
        else:
            result = execute(args.private_plan, args.fresh_preflight_result)
    except (
        CommandFailure,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        OSError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as error:
        parser.exit(1, f"aws-test Terraform plan executor stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

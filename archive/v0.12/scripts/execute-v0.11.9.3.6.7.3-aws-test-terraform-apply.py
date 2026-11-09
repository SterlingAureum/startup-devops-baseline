#!/usr/bin/env python3
"""Verify or execute one guarded apply of a reviewed aws-test saved plan."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_BASELINE = "52e99fcfb86e7159eea037926954e81d1bc5f26f"
PLAN_EVIDENCE_RELATIVE = (
    "delivery/contracts/"
    "v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.json"
)
PLAN_EVIDENCE_SHA256 = (
    "beaaf8195253b085db17729793e9c8365a006d52a9b93e41fb12badf572d3692"
)
PLAN_EXECUTOR_RELATIVE = (
    "scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py"
)
PLAN_EXECUTOR_SHA256 = (
    "6bee71419d5398c0623a7ac9434c3803107dba77bdb9908f204db56fbe1792b5"
)
PLAN_GATE_RELATIVE = "scripts/check-aws-test-create-terraform-plan.py"
PLAN_GATE_SHA256 = (
    "d61a840c164a8e6a22b0ffde5f85c5b5a13de036b24530b3c98cc35002ff23c8"
)
PREFLIGHT_RELATIVE = "scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py"
PREFLIGHT_SHA256 = (
    "b41a1c58865ffd44ae35165a7a17e941dd19d4b05dd0b1d6f2f09938afeec487"
)
OLD_PLAN_MAIN = "845d918bbf272b485461cc6ac193789bd57e9ef8"
OLD_BINARY_PLAN_SHA256 = (
    "f2165bf95e16988a86d314743053c641592151c1e2b3602ca90bf4519b2046e5"
)
PREFLIGHT_CONFIRMATION = "observe-reviewed-aws-test-create-preflight"
APPLY_CONFIRMATION = "apply-reviewed-aws-test-saved-plan"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-test"
SECRET_NAME = "startup-devops-baseline-test/demo-api/postgresql"
STATE_RELATIVE = "infra/terraform/aws/environments/test/terraform.tfstate"
MINIMUM_REMAINING_SECONDS = 900


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_EXECUTOR = load_module(ROOT / PLAN_EXECUTOR_RELATIVE, "aws_test_plan_executor_v672")
PLAN_GATE = load_module(ROOT / PLAN_GATE_RELATIVE, "aws_test_plan_gate_v672")
PREFLIGHT = load_module(ROOT / PREFLIGHT_RELATIVE, "aws_test_preflight_v67")
DESIGN = PLAN_EXECUTOR.DESIGN


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
CommandRunner = Callable[[list[str], dict[str, str], int], subprocess.CompletedProcess[bytes]]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_timestamp(value: str, label: str) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), f"{label} must be UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{label} is invalid") from error
    return parsed.astimezone(timezone.utc)


def require_private_directory(path: Path, label: str) -> None:
    require(path.is_dir() and not path.is_symlink(), f"{label} must be a directory")
    require(stat.S_IMODE(path.stat().st_mode) == 0o700, f"{label} mode must be 700")


def require_private_file(path: Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 600")
    require_private_directory(path.parent, f"{label} parent")


def require_new_private_output(path: Path) -> None:
    require_private_directory(path.parent, "Apply output parent")
    require(not path.exists() and not path.is_symlink(), "Apply output directory must be new")


def require_fingerprint(root: Path, relative: str, expected: str) -> None:
    path = root / relative
    require(path.is_file() and not path.is_symlink(), "Reviewed repository input must be regular")
    require(sha256(path) == expected, f"Reviewed repository input changed: {relative}")


def write_private(path: Path, content: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(content)
    path.chmod(0o600)


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False
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


def load_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"{label} is unreadable or invalid") from error


def validate_record(
    record: Any,
    plan: dict[str, Any],
    private_plan_path: Path,
    fresh_preflight_path: Path,
    bundle: Path,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    expected_fields = {
        "schema_version", "account_id", "control_plane_commit", "release_id",
        "management_cidr", "created_at_utc", "expires_at_utc",
        "fresh_preflight_sha256", "private_plan_sha256",
        "qualification_profile_sha256", "local_variable_file_sha256",
        "binary_plan_sha256", "terraform_plan_json_sha256",
        "terraform_plan_text_sha256", "plan_gate_sha256", "action_counts",
        "resource_change_count", "secret_metadata_absent_before_and_after",
        "terraform_apply_executed", "environment_created",
    }
    require(isinstance(record, dict) and set(record) == expected_fields, "Plan record fields changed")
    require(record["schema_version"] == "v0.11.9.3.6.7.2", "Plan record version changed")
    require(record["account_id"] == plan["aws_account_id"], "Plan account changed")
    require(
        record["control_plane_commit"] == plan["planned_control_plane_commit"],
        "Plan control-plane commit changed",
    )
    require(record["release_id"] == plan["candidate"]["release_id"], "Plan release changed")
    require(record["management_cidr"] == f"{plan['management_ipv4']}/32", "Plan management CIDR changed")
    require(record["fresh_preflight_sha256"] == sha256(fresh_preflight_path), "Plan preflight changed")
    require(record["private_plan_sha256"] == sha256(private_plan_path), "Private plan bytes changed")
    require(record["qualification_profile_sha256"] == plan["infrastructure"]["qualification_profile_sha256"], "Qualification profile changed")
    require(record["local_variable_file_sha256"] == plan["local_variable_file_sha256"], "Local variables changed")
    require(record["secret_metadata_absent_before_and_after"] is True, "Plan did not prove Secret absence")
    require(record["terraform_apply_executed"] is False, "Plan record already reports apply")
    require(record["environment_created"] is False, "Plan record already reports an environment")
    require(
        record["binary_plan_sha256"] != OLD_BINARY_PLAN_SHA256,
        "Expired v0.11.9.3.6.7.2.1 binary plan cannot be reused",
    )

    artifacts = {
        "binary_plan_sha256": bundle / "aws-test-create.tfplan",
        "terraform_plan_json_sha256": bundle / "terraform-plan.json",
        "terraform_plan_text_sha256": bundle / "terraform-plan.txt",
        "plan_gate_sha256": bundle / "plan-gate.json",
    }
    for field, path in artifacts.items():
        require_private_file(path, field)
        require(record[field] == sha256(path), f"Saved plan artifact changed: {field}")
    plan_document = load_json(bundle / "terraform-plan.json", "Terraform plan JSON")
    gate = PLAN_GATE.validate(plan_document, plan["aws_account_id"], plan["management_ipv4"])
    require(gate == load_json(bundle / "plan-gate.json", "Plan gate"), "Plan gate bytes or semantics changed")
    require(record["action_counts"] == gate["action_counts"], "Plan action counts changed")
    require(record["resource_change_count"] == gate["resource_change_count"], "Plan resource count changed")

    created = utc_timestamp(record["created_at_utc"], "Plan creation time")
    expires = utc_timestamp(record["expires_at_utc"], "Plan expiry")
    require(created <= now < expires, "Saved plan is expired or not yet valid")
    remaining = int((expires - now).total_seconds())
    require(remaining >= MINIMUM_REMAINING_SECONDS, "At least 900 seconds must remain before plan expiry")
    deadline = DESIGN.utc_timestamp(plan["cost_control"]["teardown_review_deadline_utc"], "teardown deadline")
    require(expires <= deadline and now < deadline, "Reviewed session window expired")
    return plan_document, gate, remaining


def verify_inputs(
    private_plan_path: Path,
    fresh_preflight_path: Path,
    plan_bundle_directory: Path,
    apply_output_directory: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> dict[str, Any]:
    require_private_file(private_plan_path, "Private creation plan")
    require_private_file(fresh_preflight_path, "Fresh preflight result")
    require_private_directory(plan_bundle_directory, "Plan bundle")
    require_new_private_output(apply_output_directory)
    private_plan = load_json(private_plan_path, "Private creation plan")
    DESIGN.validate(private_plan, repository_root)
    expected_main = private_plan["planned_control_plane_commit"]
    require(expected_main != IMPLEMENTATION_BASELINE, "A post-v0.11.9.3.6.7.3 main is required")
    require(expected_main != OLD_PLAN_MAIN, "Expired plan-evidence main cannot be reused")
    require(Path(private_plan["private_plan_bundle_directory"]) == plan_bundle_directory, "Plan bundle path differs from private plan")
    require(sha256(fresh_preflight_path) == private_plan["fresh_preflight_result_sha256"], "Fresh preflight bytes changed")
    preflight = PLAN_EXECUTOR.validate_preflight(load_json(fresh_preflight_path, "Fresh preflight"), private_plan)

    require(git_runner(["branch", "--show-current"]) == "main", "Executor must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Executor requires a clean worktree")
    require(
        git_runner(["rev-parse", "HEAD"]) == expected_main
        and git_runner(["rev-parse", "origin/main"]) == expected_main,
        "HEAD and origin/main must equal the reviewed plan main",
    )
    git_runner(["merge-base", "--is-ancestor", IMPLEMENTATION_BASELINE, expected_main])
    for relative, expected in (
        (PLAN_EVIDENCE_RELATIVE, PLAN_EVIDENCE_SHA256),
        (PLAN_EXECUTOR_RELATIVE, PLAN_EXECUTOR_SHA256),
        (PLAN_GATE_RELATIVE, PLAN_GATE_SHA256),
        (PREFLIGHT_RELATIVE, PREFLIGHT_SHA256),
        (private_plan["infrastructure"]["backend_declaration_path"], private_plan["infrastructure"]["backend_declaration_sha256"]),
        (private_plan["infrastructure"]["qualification_profile_path"], private_plan["infrastructure"]["qualification_profile_sha256"]),
        (private_plan["infrastructure"]["legacy_apply_wrapper"], private_plan["infrastructure"]["legacy_apply_wrapper_sha256"]),
    ):
        require_fingerprint(repository_root, relative, expected)
    variable_file = repository_root / private_plan["infrastructure"]["local_variable_file_path"]
    require(variable_file.is_file() and not variable_file.is_symlink(), "Local terraform.tfvars must be regular")
    require(sha256(variable_file) == private_plan["local_variable_file_sha256"], "Local terraform.tfvars changed")

    require_private_directory(plan_bundle_directory / "terraform-data", "Saved Terraform data")
    record_path = plan_bundle_directory / "plan-record.json"
    require_private_file(record_path, "Plan record")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    plan_document, gate, remaining = validate_record(
        load_json(record_path, "Plan record"), private_plan, private_plan_path,
        fresh_preflight_path, plan_bundle_directory, current,
    )
    state = PREFLIGHT.summarize_local_state(repository_root / STATE_RELATIVE)
    require(state["resource_block_count"] == 0 and state["resource_instance_count"] == 0, "aws-test state is not empty")
    return {
        "private_plan": private_plan,
        "preflight": preflight,
        "plan_document": plan_document,
        "gate": gate,
        "record": load_json(record_path, "Plan record"),
        "remaining": remaining,
    }


def safe_environment(plan: dict[str, Any], terraform_data: Path) -> dict[str, str]:
    environment = PLAN_EXECUTOR.safe_environment(plan, terraform_data)
    for key in list(environment):
        if key.startswith("TF_CLI_ARGS") or key.startswith("TF_VAR_"):
            del environment[key]
    environment["CONFIRM_AWS_TEST_CREATE_PREFLIGHT"] = PREFLIGHT_CONFIRMATION
    return environment


def local_state_instance_count(path: Path) -> int:
    require(path.is_file() and not path.is_symlink(), "Applied local state must be regular")
    state = load_json(path, "Applied local state")
    require(isinstance(state, dict) and state.get("version") == 4, "Applied local state version changed")
    resources = state.get("resources")
    require(isinstance(resources, list), "Applied local state resources changed")
    total = 0
    for resource in resources:
        require(isinstance(resource, dict), "Applied local state resource is invalid")
        instances = resource.get("instances")
        require(isinstance(instances, list), "Applied local state instances are invalid")
        total += len(instances)
    return total


def record_result(output: Path, label: str, result: subprocess.CompletedProcess[bytes]) -> None:
    write_private(output / f"{label}.stdout", result.stdout)
    write_private(output / f"{label}.stderr", result.stderr)


def logged(
    output: Path,
    label: str,
    arguments: list[str],
    environment: dict[str, str],
    timeout: int,
    runner: CommandRunner,
) -> subprocess.CompletedProcess[bytes]:
    result = runner(arguments, environment, timeout)
    record_result(output, label, result)
    if result.returncode:
        raise CommandFailure(f"{label} failed; preserve private evidence and Terraform state")
    return result


def require_secret_absent(output: Path, environment: dict[str, str], runner: CommandRunner) -> None:
    result = runner(
        ["aws", "--region", AWS_REGION, "secretsmanager", "describe-secret", "--secret-id", SECRET_NAME, "--output", "json"],
        environment, 90,
    )
    record_result(output, "secret-before-apply", result)
    if result.returncode == 0:
        raise CommandFailure("aws-test Secret is already present; stop before apply")
    require(b"(ResourceNotFoundException)" in result.stderr, "Secret lookup did not prove absence")


def execute(
    private_plan_path: Path,
    fresh_preflight_path: Path,
    plan_bundle_directory: Path,
    apply_output_directory: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    runner: CommandRunner = run_command,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    verified = verify_inputs(
        private_plan_path, fresh_preflight_path, plan_bundle_directory,
        apply_output_directory, repository_root, git_runner, current,
    )
    plan = verified["private_plan"]
    require(os.environ.get("AWS_ENVIRONMENT") == "aws-test", "AWS_ENVIRONMENT must be aws-test")
    require(os.environ.get("EXPECTED_AWS_ACCOUNT_ID") == plan["aws_account_id"], "EXPECTED_AWS_ACCOUNT_ID must match")
    require(os.environ.get("CONFIRM_AWS_TEST_CREATE_PREFLIGHT") == PREFLIGHT_CONFIRMATION, "Preflight confirmation missing")
    require(os.environ.get("CONFIRM_AWS_TEST_TERRAFORM_APPLY_EXECUTION") == APPLY_CONFIRMATION, "Apply confirmation missing")
    for forbidden in (
        "CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION", "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION", "CONFIRM_AWS_DEV_APPLY",
        "CONFIRM_AWS_TEST_APPLY", "CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION",
        "AWS_TEST_APPLY_MODE",
    ):
        require(not os.environ.get(forbidden), "Plan, legacy apply and destroy controls must be unset")

    apply_output_directory.mkdir(mode=0o700)
    apply_output_directory.chmod(0o700)
    environment = safe_environment(plan, plan_bundle_directory / "terraform-data")
    immediate = runner(
        [sys.executable, str(repository_root / PREFLIGHT_RELATIVE), "verify", "--expected-control-plane-commit", plan["planned_control_plane_commit"]],
        environment, 300,
    )
    record_result(apply_output_directory, "immediate-preflight", immediate)
    require(immediate.returncode == 0 and immediate.stderr == b"", "Immediate preflight failed")
    require(immediate.stdout == fresh_preflight_path.read_bytes(), "Immediate preflight bytes changed")
    require_secret_absent(apply_output_directory, environment, runner)

    terraform_directory = repository_root / plan["infrastructure"]["terraform_directory"]
    prefix = ["terraform", f"-chdir={terraform_directory}"]
    binary_plan = plan_bundle_directory / "aws-test-create.tfplan"
    show = logged(
        apply_output_directory, "terraform-show-json-before-apply",
        [*prefix, "show", "-json", str(binary_plan)], environment, 300, runner,
    )
    require(show.stdout == (plan_bundle_directory / "terraform-plan.json").read_bytes(), "Saved plan show bytes changed")
    gate = PLAN_GATE.validate(json.loads(show.stdout), plan["aws_account_id"], plan["management_ipv4"])
    require(gate == verified["gate"], "Saved plan gate changed immediately before apply")
    require(PREFLIGHT.summarize_local_state(repository_root / STATE_RELATIVE)["resource_instance_count"] == 0, "aws-test state changed before apply")

    logged(
        apply_output_directory, "terraform-apply",
        [*prefix, "apply", "-input=false", "-auto-approve", str(binary_plan)],
        environment, 5400, runner,
    )
    state_list = logged(
        apply_output_directory, "terraform-state-list",
        [*prefix, "state", "list"], environment, 300, runner,
    )
    state_addresses = {line for line in state_list.stdout.decode().splitlines() if line}
    changes = verified["plan_document"]["resource_changes"]
    expected_addresses = {change["address"] for change in changes}
    create_addresses = {
        change["address"] for change in changes
        if change["change"]["actions"] == ["create"]
    }
    require(create_addresses <= state_addresses, "Applied state is missing planned create addresses")
    require(state_addresses <= expected_addresses, "Applied state contains an unreviewed address")
    require(local_state_instance_count(repository_root / STATE_RELATIVE) >= len(create_addresses), "Applied local state is incomplete")

    cluster = logged(
        apply_output_directory, "eks-describe-cluster",
        ["aws", "--region", AWS_REGION, "eks", "describe-cluster", "--name", CLUSTER_NAME, "--output", "json"],
        environment, 90, runner,
    )
    document = json.loads(cluster.stdout)
    cluster_data = document.get("cluster", {})
    cidrs = cluster_data.get("resourcesVpcConfig", {}).get("publicAccessCidrs")
    require(cluster_data.get("name") == CLUSTER_NAME, "Unexpected EKS cluster identity")
    require(cluster_data.get("status") == "ACTIVE", "aws-test EKS cluster is not ACTIVE")
    require(cidrs == [verified["record"]["management_cidr"]], "EKS public access CIDR changed")

    secret = logged(
        apply_output_directory, "secret-after-apply",
        ["aws", "--region", AWS_REGION, "secretsmanager", "describe-secret", "--secret-id", SECRET_NAME, "--output", "json"],
        environment, 90, runner,
    )
    require(isinstance(json.loads(secret.stdout), dict), "Secret metadata response is invalid")

    return {
        "status": "aws-test-reviewed-saved-plan-applied",
        "control_plane_commit": plan["planned_control_plane_commit"],
        "candidate_release_id": plan["candidate"]["release_id"],
        "fresh_preflight_sha256": sha256(fresh_preflight_path),
        "private_plan_sha256": sha256(private_plan_path),
        "plan_record_sha256": sha256(plan_bundle_directory / "plan-record.json"),
        "binary_plan_sha256": sha256(binary_plan),
        "action_counts": gate["action_counts"],
        "resource_change_count": gate["resource_change_count"],
        "state_address_count": len(state_addresses),
        "terraform_plan_executed": False,
        "terraform_apply_executed": True,
        "environment_creation_authorized": True,
        "environment_created": True,
        "eks_cluster_active": True,
        "secret_metadata_present_after_apply": True,
        "gitops_bootstrap_executed": False,
        "traffic_generated": False,
        "qualification_executed": False,
        "automatic_retry_performed": False,
        "private_resource_identity_emitted": False,
        "next_action": "record-aws-test-terraform-apply-execution-evidence",
    }


def redacted_verification(context: dict[str, Any], private_plan: Path, preflight: Path, bundle: Path) -> dict[str, Any]:
    plan = context["private_plan"]
    return {
        "status": "aws-test-terraform-apply-executor-inputs-verified",
        "control_plane_commit": plan["planned_control_plane_commit"],
        "candidate_release_id": plan["candidate"]["release_id"],
        "fresh_preflight_sha256": sha256(preflight),
        "private_plan_sha256": sha256(private_plan),
        "plan_record_sha256": sha256(bundle / "plan-record.json"),
        "binary_plan_sha256": sha256(bundle / "aws-test-create.tfplan"),
        "remaining_plan_review_seconds": context["remaining"],
        "commands_executed": [],
        "terraform_plan_authorized": False,
        "terraform_plan_executed": False,
        "terraform_apply_authorized": False,
        "terraform_apply_executed": False,
        "environment_creation_authorized": False,
        "next_action": "obtain-separate-aws-test-terraform-apply-approval",
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--private-plan", required=True, type=Path)
    parser.add_argument("--fresh-preflight-result", required=True, type=Path)
    parser.add_argument("--plan-bundle-directory", required=True, type=Path)
    parser.add_argument("--private-output-directory", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            context = verify_inputs(
                args.private_plan, args.fresh_preflight_result,
                args.plan_bundle_directory, args.private_output_directory,
            )
            result = redacted_verification(
                context, args.private_plan, args.fresh_preflight_result,
                args.plan_bundle_directory,
            )
        else:
            result = execute(
                args.private_plan, args.fresh_preflight_result,
                args.plan_bundle_directory, args.private_output_directory,
            )
    except (
        CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError,
        subprocess.TimeoutExpired, UnicodeDecodeError, ValueError,
    ) as error:
        parser.exit(1, f"aws-test Terraform apply executor stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

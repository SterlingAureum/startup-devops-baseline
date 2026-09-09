#!/usr/bin/env python3
"""Verify or execute the reviewed aws-dev infrastructure creation checkpoint."""

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
CREATE_PLAN_CHECKER = ROOT / "scripts/check-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.py"
PREFLIGHT_PLAN_CHECKER = ROOT / "scripts/check-v0.11.9.3.5-aws-dev-live-rehearsal-plan.py"
PREFLIGHT = ROOT / "scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py"
APPLY = ROOT / "scripts/apply-aws-dev.sh"
PREFLIGHT_CONFIRMATION = "observe-reviewed-aws-dev-rehearsal"
EXECUTION_CONFIRMATION = "execute-reviewed-aws-dev-rehearsal-create"
APPLY_CONFIRMATION = "create-ephemeral-aws-dev"


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLAN_CHECKER = load_module(CREATE_PLAN_CHECKER, "aws_dev_create_plan")
PREFLIGHT_CHECKER = load_module(PREFLIGHT_PLAN_CHECKER, "aws_dev_preflight_plan")


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
PreflightRunner = Callable[[Path], bytes]
ApplyRunner = Callable[[dict[str, Any]], int]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_private_file(path: Path, label: str) -> None:
    require(path.is_file() and not path.is_symlink(), f"{label} must be a regular non-symlink file")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{label} mode must be 600")
    parent = path.parent
    require(parent.is_dir() and not parent.is_symlink(), f"{label} parent must be a private directory")
    require(
        stat.S_IMODE(parent.stat().st_mode) & 0o077 == 0,
        f"{label} parent must not grant group or other permissions",
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(arguments: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise CommandFailure(detail)
    return result.stdout.strip()


def validate_preflight_semantics(
    preflight_plan: dict[str, Any],
    result: dict[str, Any],
    create_plan: dict[str, Any],
) -> None:
    control_plane = create_plan["planned_control_plane_commit"]
    require(preflight_plan["schema_version"] == "v0.11.9.3.5", "Fresh preflight schema changed")
    require(preflight_plan["mode"] == "read-only-preflight", "Fresh preflight mode changed")
    require(preflight_plan["target_environment"] == "aws-dev", "Fresh preflight target changed")
    require(preflight_plan["control_plane_commit"] == control_plane, "Fresh preflight main identity changed")
    require(preflight_plan["trusted_git_ref"] == "refs/heads/main", "Fresh preflight Git ref changed")
    require(preflight_plan["aws_account_id"] == create_plan["aws_account_id"], "Fresh preflight account changed")
    require(preflight_plan["aws_region"] == create_plan["aws_region"], "Fresh preflight region changed")
    require(preflight_plan["candidate"] == create_plan["candidate"], "Fresh preflight candidate changed")

    require(result["status"] == "ready-for-separate-aws-dev-create-approval", "Fresh preflight is not ready")
    require(result["execution_authorized"] is False, "Preflight must not authorize execution")
    require(result["control_plane_commit"] == control_plane, "Preflight result main identity changed")
    require(
        result["candidate_release_id"] == create_plan["candidate"]["release_id"],
        "Preflight result candidate changed",
    )
    require(result["aws_account_id"] == create_plan["aws_account_id"], "Preflight result account changed")
    require(result["aws_region"] == create_plan["aws_region"], "Preflight result region changed")
    require(result["active_rehearsal_clusters"] == [], "A rehearsal cluster is active")
    state = result["terraform_state"]
    require(isinstance(state, dict), "Preflight Terraform state summary missing")
    require(state.get("resource_blocks") == 0, "Terraform state contains resource blocks")
    require(state.get("resource_instances") == 0, "Terraform state contains resource instances")
    require(state.get("contains_dev_eks_cluster") is False, "Terraform state contains aws-dev EKS")
    require(result["blocked_reason"] is None, "Preflight result is blocked")
    require(
        result["checks_performed"]
        == [
            "private-plan-permissions",
            "clean-exact-main",
            "candidate-source-ancestry",
            "aws-dev-release-identity",
            "aws-caller-identity",
            "eks-rehearsal-cluster-inventory",
            "local-terraform-state-summary",
        ],
        "Preflight check inventory changed",
    )
    require(result["mutations_performed"] == [], "Preflight reported a mutation")
    require(result["next_action"] == "review-separate-create-approval", "Preflight next action changed")


def verify_inputs(
    create_plan_path: Path,
    preflight_plan_path: Path,
    preflight_result_path: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_private_file(create_plan_path, "Create plan")
    require_private_file(preflight_plan_path, "Fresh preflight plan")
    require_private_file(preflight_result_path, "Fresh preflight result")

    create_plan = json.loads(create_plan_path.read_text())
    PLAN_CHECKER.validate(create_plan, repository_root)
    expected_plan_sha = create_plan["preflight"]["fresh_preflight_plan_sha256"]
    expected_result_sha = create_plan["preflight"]["fresh_preflight_result_sha256"]
    require(file_sha256(preflight_plan_path) == expected_plan_sha, "Fresh preflight plan SHA-256 changed")
    require(file_sha256(preflight_result_path) == expected_result_sha, "Fresh preflight result SHA-256 changed")

    preflight_plan = json.loads(preflight_plan_path.read_text())
    preflight_result = json.loads(preflight_result_path.read_text())
    PREFLIGHT_CHECKER.validate(preflight_plan, repository_root)
    validate_preflight_semantics(preflight_plan, preflight_result, create_plan)

    require(git_runner(["branch", "--show-current"]) == "main", "Executor must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "Executor requires a clean worktree")
    head = git_runner(["rev-parse", "HEAD"])
    origin_main = git_runner(["rev-parse", "origin/main"])
    expected_main = create_plan["planned_control_plane_commit"]
    require(head == expected_main and origin_main == expected_main, "HEAD and origin/main must equal create-plan main")

    current = now or datetime.now(timezone.utc)
    require(current.tzinfo is not None, "Current time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    start = PLAN_CHECKER.utc_timestamp(create_plan["cost_control"]["planned_start_utc"], "planned_start_utc")
    deadline = PLAN_CHECKER.utc_timestamp(
        create_plan["cost_control"]["teardown_review_deadline_utc"],
        "teardown_review_deadline_utc",
    )
    require(start <= current < deadline, "Execution must occur inside the reviewed session window")
    return create_plan, preflight_result


def run_preflight(plan_path: Path) -> bytes:
    environment = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(PREFLIGHT), "--plan", str(plan_path)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or "fresh preflight failed"
        raise CommandFailure(detail)
    return result.stdout


def run_apply(create_plan: dict[str, Any]) -> int:
    environment = os.environ.copy()
    environment["EXPECTED_AWS_ACCOUNT_ID"] = create_plan["aws_account_id"]
    result = subprocess.run([str(APPLY)], cwd=ROOT, env=environment, check=False)
    return result.returncode


def execute(
    create_plan_path: Path,
    preflight_plan_path: Path,
    preflight_result_path: Path,
    repository_root: Path = ROOT,
    git_runner: GitRunner = run_git,
    preflight_runner: PreflightRunner = run_preflight,
    apply_runner: ApplyRunner = run_apply,
    now: datetime | None = None,
) -> dict[str, Any]:
    create_plan, saved_result = verify_inputs(
        create_plan_path,
        preflight_plan_path,
        preflight_result_path,
        repository_root,
        git_runner,
        now,
    )
    require(
        os.environ.get("CONFIRM_AWS_DEV_PREFLIGHT") == PREFLIGHT_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_PREFLIGHT={PREFLIGHT_CONFIRMATION}",
    )
    require(
        os.environ.get("CONFIRM_AWS_DEV_REHEARSAL_CREATE") == EXECUTION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_REHEARSAL_CREATE={EXECUTION_CONFIRMATION}",
    )
    require(
        os.environ.get("CONFIRM_AWS_DEV_APPLY") == APPLY_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_APPLY={APPLY_CONFIRMATION}",
    )

    live_bytes = preflight_runner(preflight_plan_path)
    expected_bytes = preflight_result_path.read_bytes()
    expected_sha = create_plan["preflight"]["fresh_preflight_result_sha256"]
    require(hashlib.sha256(live_bytes).hexdigest() == expected_sha, "Immediate preflight SHA-256 changed")
    require(live_bytes == expected_bytes, "Immediate preflight bytes differ from reviewed result")
    live_result = json.loads(live_bytes)
    validate_preflight_semantics(json.loads(preflight_plan_path.read_text()), live_result, create_plan)
    require(live_result == saved_result, "Immediate preflight semantics changed")

    return_code = apply_runner(create_plan)
    if return_code != 0:
        raise CommandFailure(f"aws-dev create entrypoint exited {return_code}; preserve state and evidence")
    return {
        "status": "aws-dev-infrastructure-created-api-ready",
        "control_plane_commit": create_plan["planned_control_plane_commit"],
        "candidate_release_id": create_plan["candidate"]["release_id"],
        "terraform_plan_policy": "nonempty-create-read-no-op-only",
        "gitops_bootstrapped": False,
        "root_application_deployed": False,
        "runtime_qualified": False,
        "automatic_teardown_executed": False,
        "next_action": "review-separate-gitops-bootstrap",
    }


def redacted_verification(create_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-create-executor-inputs-verified",
        "control_plane_commit": create_plan["planned_control_plane_commit"],
        "candidate_release_id": create_plan["candidate"]["release_id"],
        "maximum_session_hours": create_plan["cost_control"]["maximum_session_hours"],
        "reviewed_session_budget_usd": create_plan["cost_control"]["reviewed_session_budget_usd"],
        "execution_authorized": False,
        "commands_executed": [],
        "next_action": "obtain-separate-live-create-approval",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--create-plan", required=True, type=Path)
    parser.add_argument("--fresh-preflight-plan", required=True, type=Path)
    parser.add_argument("--fresh-preflight-result", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            create_plan, _ = verify_inputs(
                args.create_plan,
                args.fresh_preflight_plan,
                args.fresh_preflight_result,
            )
            result = redacted_verification(create_plan)
        else:
            result = execute(
                args.create_plan,
                args.fresh_preflight_plan,
                args.fresh_preflight_result,
            )
    except (CommandFailure, KeyError, TypeError, json.JSONDecodeError, OSError, ValueError) as error:
        parser.exit(1, f"aws-dev create executor stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

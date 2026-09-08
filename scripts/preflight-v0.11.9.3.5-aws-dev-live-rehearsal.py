#!/usr/bin/env python3
"""Run the v0.11.9.3.5 aws-dev preflight using read-only discovery."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Callable

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts/check-v0.11.9.3.5-aws-dev-live-rehearsal-plan.py"
AWS_DEV_RELEASE = ROOT / "apps/demo-api/helm/values/releases/aws-dev.yaml"
CONFIRMATION = "observe-reviewed-aws-dev-rehearsal"


def load_checker() -> Any:
    spec = importlib.util.spec_from_file_location("aws_dev_live_rehearsal_plan", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load aws-dev rehearsal plan checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


class CommandFailure(RuntimeError):
    pass


CommandRunner = Callable[[list[str]], str]


def run_command(arguments: list[str]) -> str:
    environment = os.environ.copy()
    environment["AWS_PAGER"] = ""
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise CommandFailure(f"{arguments[0]} read-only discovery failed: {detail}")
    return result.stdout.strip()


def require_private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Plan must be a regular non-symlink file")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError("Private plan mode must be 600")


def require_private_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Private evidence directory must already exist and not be a symlink")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Private evidence directory must not grant group or other permissions")


def summarize_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "resource_blocks": 0,
            "resource_instances": 0,
            "contains_dev_eks_cluster": False,
        }
    if path.is_symlink() or not path.is_file():
        raise ValueError("Terraform state path must be a regular non-symlink file")
    try:
        state_value = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError(f"Cannot read Terraform state summary: {error}") from error
    if not isinstance(state_value, dict) or state_value.get("version") != 4:
        raise ValueError("Unsupported or invalid Terraform state version")
    resources = state_value.get("resources", [])
    if not isinstance(resources, list):
        raise ValueError("Terraform state resources must be a list")
    instance_count = 0
    contains_cluster = False
    for resource in resources:
        if not isinstance(resource, dict) or not isinstance(resource.get("instances", []), list):
            raise ValueError("Terraform state resource structure is invalid")
        instance_count += len(resource.get("instances", []))
        if resource.get("type") == "aws_eks_cluster" and resource.get("instances"):
            contains_cluster = True
    return {
        "exists": True,
        "resource_blocks": len(resources),
        "resource_instances": instance_count,
        "contains_dev_eks_cluster": contains_cluster,
    }


def classify_inventory(
    active_clusters: list[str],
    cluster_names: dict[str, str],
    state_summary: dict[str, Any],
) -> tuple[str, str | None]:
    rehearsal_names = set(cluster_names.values())
    active_rehearsal = sorted(name for name in active_clusters if name in rehearsal_names)
    dev = cluster_names["aws_dev"]
    later = {cluster_names["aws_test"], cluster_names["aws_prod"]}

    if any(name in later for name in active_rehearsal):
        return (
            "blocked-other-rehearsal-environment-active",
            "aws-test or aws-prod must be preserved and separately torn down before aws-dev creation",
        )
    if len(active_rehearsal) > 1:
        return (
            "blocked-multiple-rehearsal-environments-active",
            "the one-active-EKS-environment cost boundary is already exceeded",
        )

    dev_active = dev in active_rehearsal
    state_instances = int(state_summary["resource_instances"])
    state_has_cluster = bool(state_summary["contains_dev_eks_cluster"])

    if dev_active:
        if not state_summary["exists"] or state_instances == 0 or not state_has_cluster:
            return (
                "blocked-unmanaged-or-mismatched-aws-dev",
                "aws-dev exists but the expected local Terraform state does not own its EKS cluster",
            )
        return (
            "blocked-existing-aws-dev-requires-resume-review",
            "aws-dev already exists; inspect state and use a separately reviewed resume or maintenance path",
        )

    if state_instances > 0:
        return (
            "blocked-partial-aws-dev-state",
            "aws-dev state is nonempty while the cluster is absent; review partial infrastructure without deleting state",
        )
    if state_has_cluster:
        return (
            "blocked-invalid-aws-dev-state",
            "Terraform state reports an EKS cluster instance while its resource count is empty",
        )

    return (
        "ready-for-separate-aws-dev-create-approval",
        None,
    )


def expected_release(candidate: dict[str, str]) -> dict[str, Any]:
    return {
        "image": {
            "repository": candidate["repository"],
            "tag": candidate["tag"],
            "digest": candidate["digest"],
        },
        "release": {"applicationVersion": candidate["tag"]},
        "delivery": {
            "sourceRepository": "SterlingAureum/startup-devops-baseline",
            "sourceCommit": candidate["source_commit"],
            "workflowRunId": candidate["workflow_run_id"],
        },
    }


def execute_preflight(
    plan_path: Path,
    repository_root: Path = ROOT,
    command_runner: CommandRunner = run_command,
) -> tuple[dict[str, Any], int]:
    require_private_file(plan_path)
    plan_value = json.loads(plan_path.read_text())
    CHECKER.validate(plan_value, repository_root)
    evidence_directory = Path(plan_value["evidence_directory"])
    require_private_directory(evidence_directory)

    if os.environ.get("CONFIRM_AWS_DEV_PREFLIGHT") != CONFIRMATION:
        raise ValueError(
            f"Set CONFIRM_AWS_DEV_PREFLIGHT={CONFIRMATION} for read-only discovery"
        )
    for command_name in ("aws", "git"):
        if shutil.which(command_name) is None:
            raise ValueError(f"Required command not found: {command_name}")

    branch = command_runner(["git", "-C", str(repository_root), "branch", "--show-current"])
    if branch != "main":
        raise ValueError("Run the preflight from main")
    if command_runner(["git", "-C", str(repository_root), "status", "--porcelain"]):
        raise ValueError("Run the preflight from a clean worktree")
    head = command_runner(["git", "-C", str(repository_root), "rev-parse", "HEAD"])
    origin_main = command_runner(
        ["git", "-C", str(repository_root), "rev-parse", "origin/main"]
    )
    expected_main = plan_value["control_plane_commit"]
    if head != expected_main or origin_main != expected_main:
        raise ValueError("HEAD and origin/main must equal the reviewed control-plane commit")
    command_runner(
        [
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            CHECKER.IMPLEMENTATION_BASELINE_COMMIT,
            expected_main,
        ]
    )
    command_runner(
        [
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            plan_value["candidate"]["source_commit"],
            expected_main,
        ]
    )

    release_path = repository_root / "apps/demo-api/helm/values/releases/aws-dev.yaml"
    release_value = yaml.safe_load(release_path.read_text())
    if release_value != expected_release(plan_value["candidate"]):
        raise ValueError("Protected-main aws-dev release identity changed")

    caller = json.loads(command_runner(["aws", "sts", "get-caller-identity", "--output", "json"]))
    actual_account = caller.get("Account")
    if actual_account != plan_value["aws_account_id"]:
        raise ValueError("AWS account mismatch; no environment operation was performed")

    clusters_value = json.loads(
        command_runner(
            [
                "aws",
                "eks",
                "list-clusters",
                "--region",
                plan_value["aws_region"],
                "--output",
                "json",
            ]
        )
    )
    active_clusters = clusters_value.get("clusters")
    if not isinstance(active_clusters, list) or not all(
        isinstance(item, str) for item in active_clusters
    ):
        raise ValueError("AWS EKS cluster inventory response is invalid")

    state_path = repository_root / plan_value["terraform_state_path"]
    state_value = summarize_state(state_path)
    status, reason = classify_inventory(
        active_clusters,
        plan_value["cluster_names"],
        state_value,
    )
    rehearsal_names = set(plan_value["cluster_names"].values())
    active_rehearsal = sorted(name for name in active_clusters if name in rehearsal_names)

    result = {
        "status": status,
        "execution_authorized": False,
        "control_plane_commit": expected_main,
        "candidate_release_id": plan_value["candidate"]["release_id"],
        "aws_account_id": actual_account,
        "aws_region": plan_value["aws_region"],
        "active_rehearsal_clusters": active_rehearsal,
        "terraform_state": state_value,
        "blocked_reason": reason,
        "checks_performed": [
            "private-plan-permissions",
            "clean-exact-main",
            "candidate-source-ancestry",
            "aws-dev-release-identity",
            "aws-caller-identity",
            "eks-rehearsal-cluster-inventory",
            "local-terraform-state-summary",
        ],
        "mutations_performed": [],
        "next_action": (
            "review-separate-create-approval"
            if reason is None
            else "resolve-or-review-blocked-state-without-deleting-terraform-state"
        ),
    }
    return result, 0 if reason is None else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        result, exit_code = execute_preflight(args.plan)
    except (CommandFailure, json.JSONDecodeError, OSError, ValueError) as error:
        parser.exit(1, f"Preflight rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

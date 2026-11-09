#!/usr/bin/env python3
"""Verify or execute the separately reviewed aws-dev GitOps bootstrap."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap-eks-argocd.sh"
TF_DIR = ROOT / "infra/terraform/aws/environments/dev"
AWS_REGION = "us-east-1"
CLUSTER_NAME = "startup-devops-baseline-dev"
PINNED_ARGOCD_VERSION = "v3.5.2"
EXPECTED_STATE_ADDRESS_COUNT = 103
OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-gitops-bootstrap"
EXECUTION_CONFIRMATION = "bootstrap-reviewed-aws-dev-gitops"
ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
VPC_RE = re.compile(r"^vpc-[0-9a-f]+$")


class CommandFailure(RuntimeError):
    pass


GitRunner = Callable[[list[str]], str]
ReadRunner = Callable[[list[str]], str]
BootstrapRunner = Callable[[str], int]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


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


def run_read_command(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"{arguments[0]} command failed"
        raise CommandFailure(detail)
    return result.stdout.strip()


def read_expected_account() -> str:
    account = os.environ.get("EXPECTED_AWS_ACCOUNT_ID", "")
    require(bool(ACCOUNT_RE.fullmatch(account)), "EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID")
    return account


def validate_exact_main(expected_commit: str, git_runner: GitRunner) -> None:
    require(bool(COMMIT_RE.fullmatch(expected_commit)), "Expected control-plane commit must be 40 lowercase hex characters")
    require(git_runner(["branch", "--show-current"]) == "main", "GitOps bootstrap must run from main")
    require(git_runner(["status", "--porcelain"]) == "", "GitOps bootstrap requires a clean worktree")
    head = git_runner(["rev-parse", "HEAD"])
    origin_main = git_runner(["rev-parse", "origin/main"])
    require(head == expected_commit and origin_main == expected_commit, "HEAD and origin/main must equal the reviewed commit")


def require_role_account(role_arn: str, expected_account: str, label: str) -> None:
    match = re.fullmatch(r"arn:aws:iam::([0-9]{12}):role/.+", role_arn)
    require(match is not None and match.group(1) == expected_account, f"{label} is not in the reviewed AWS account")


def verify_live_inputs(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_read_command,
) -> dict[str, Any]:
    require(
        os.environ.get("CONFIRM_AWS_DEV_GITOPS_PREFLIGHT") == OBSERVATION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_GITOPS_PREFLIGHT={OBSERVATION_CONFIRMATION}",
    )
    expected_account = read_expected_account()
    validate_exact_main(expected_commit, git_runner)

    actual_account = read_runner(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    )
    require(actual_account == expected_account, "AWS caller account does not match EXPECTED_AWS_ACCOUNT_ID")

    cluster_fields = read_runner(
        [
            "aws",
            "eks",
            "describe-cluster",
            "--region",
            AWS_REGION,
            "--name",
            CLUSTER_NAME,
            "--query",
            "cluster.[status,version,endpoint]",
            "--output",
            "text",
        ]
    ).split()
    require(len(cluster_fields) == 3, "EKS status/version/endpoint response is incomplete")
    require(cluster_fields[0] == "ACTIVE", "aws-dev EKS cluster must be ACTIVE")

    state_lines = [
        line
        for line in read_runner(["terraform", f"-chdir={TF_DIR}", "state", "list"]).splitlines()
        if line.strip()
    ]
    require(len(state_lines) == EXPECTED_STATE_ADDRESS_COUNT, "aws-dev Terraform state address count changed")
    require(any("aws_eks_cluster" in line for line in state_lines), "aws-dev Terraform state has no EKS cluster address")

    kubernetes_server = read_runner(
        ["kubectl", "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]
    )
    require(kubernetes_server == cluster_fields[2], "kubectl context does not point to the reviewed aws-dev EKS cluster")

    readyz = read_runner(["kubectl", "get", "--raw=/readyz"])
    require(readyz == "ok", "Kubernetes /readyz is not ok")

    namespace = read_runner(
        ["kubectl", "get", "namespace", "argocd", "--ignore-not-found", "-o", "name"]
    )
    require(namespace == "", "argocd namespace already exists; stop for partial-bootstrap review")

    outputs = {
        name: read_runner(["terraform", f"-chdir={TF_DIR}", "output", "-raw", name])
        for name in (
            "aws_load_balancer_controller_role_arn",
            "karpenter_controller_role_arn",
            "vpc_id",
        )
    }
    require_role_account(
        outputs["aws_load_balancer_controller_role_arn"],
        expected_account,
        "AWS Load Balancer Controller role",
    )
    require_role_account(
        outputs["karpenter_controller_role_arn"],
        expected_account,
        "Karpenter controller role",
    )
    require(bool(VPC_RE.fullmatch(outputs["vpc_id"])), "Terraform VPC ID is malformed")

    return {
        "control_plane_commit": expected_commit,
        "cluster_status": cluster_fields[0],
        "cluster_version": cluster_fields[1],
        "terraform_state_address_count": len(state_lines),
        "kubernetes_readyz": readyz,
        "argocd_namespace_present": False,
    }


def run_bootstrap(expected_account: str) -> int:
    environment = os.environ.copy()
    environment.update(
        EXPECTED_AWS_ACCOUNT_ID=expected_account,
        AWS_REGION=AWS_REGION,
        CLUSTER_NAME=CLUSTER_NAME,
        TF_DIR=str(TF_DIR),
        ARGOCD_VERSION=PINNED_ARGOCD_VERSION,
    )
    result = subprocess.run([str(BOOTSTRAP)], cwd=ROOT, env=environment, check=False)
    return result.returncode


def verification_result(inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "aws-dev-gitops-bootstrap-inputs-verified",
        **inventory,
        "argocd_version": PINNED_ARGOCD_VERSION,
        "execution_authorized": False,
        "read_only_checks": [
            "clean-exact-main",
            "aws-caller-identity",
            "eks-status-version",
            "terraform-state-addresses",
            "kubernetes-readyz",
            "argocd-namespace-absence",
            "terraform-bootstrap-outputs",
        ],
        "next_action": "obtain-separate-gitops-bootstrap-approval",
    }


def execute(
    expected_commit: str,
    git_runner: GitRunner = run_git,
    read_runner: ReadRunner = run_read_command,
    bootstrap_runner: BootstrapRunner = run_bootstrap,
) -> dict[str, Any]:
    require(
        os.environ.get("CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP") == EXECUTION_CONFIRMATION,
        f"Set CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP={EXECUTION_CONFIRMATION}",
    )
    inventory = verify_live_inputs(expected_commit, git_runner, read_runner)
    expected_account = read_expected_account()
    return_code = bootstrap_runner(expected_account)
    if return_code != 0:
        raise CommandFailure(
            f"aws-dev GitOps bootstrap exited {return_code}; preserve Terraform state and inspect partial cluster state"
        )
    return {
        "status": "aws-dev-gitops-bootstrap-complete",
        "control_plane_commit": inventory["control_plane_commit"],
        "cluster_status": inventory["cluster_status"],
        "argocd_version": PINNED_ARGOCD_VERSION,
        "gitops_bootstrapped": True,
        "root_application_deployed": False,
        "runtime_qualified": False,
        "traffic_generated": False,
        "automatic_teardown_executed": False,
        "next_action": "review-separate-root-application-deploy",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("verify", "execute"))
    parser.add_argument("--expected-control-plane-commit", required=True)
    args = parser.parse_args()
    try:
        if args.phase == "verify":
            result = verification_result(
                verify_live_inputs(args.expected_control_plane_commit)
            )
        else:
            result = execute(args.expected_control_plane_commit)
    except (CommandFailure, KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"aws-dev GitOps bootstrap stopped: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

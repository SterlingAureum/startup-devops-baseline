#!/usr/bin/env python3
"""Produce a redacted, read-only aws-dev teardown readiness summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
TF_DEV = ROOT / "infra/terraform/aws/environments/dev"
TF_TEST = ROOT / "infra/terraform/aws/environments/test"
CONFIRMATION = "observe-reviewed-aws-dev-teardown-preflight"
DEV_CLUSTER = "startup-devops-baseline-dev"
TEST_CLUSTER = "startup-devops-baseline-test"
PROD_CLUSTER = "startup-devops-baseline-prod"
EVIDENCE = ROOT / "delivery/contracts/v0.11.9.3.6.6.4-aws-test-promotion-execution-evidence.json"
EVIDENCE_SHA256 = "4977ddfb21738530681ce671ebaf9d71d4132e4e81c9ea1135e4b3527c27a96e"

Runner = Callable[[list[str]], str]


def run(arguments: list[str]) -> str:
    env = os.environ.copy()
    env["AWS_PAGER"] = ""
    result = subprocess.run(arguments, cwd=ROOT, env=env, text=True,
                            capture_output=True, check=False)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"Read-only command failed: {arguments[0]}: {detail}")
    return result.stdout.strip()


def require_exact_git(expected: str, runner: Runner) -> None:
    if runner(["git", "branch", "--show-current"]) != "main":
        raise ValueError("Run teardown preflight from main")
    if runner(["git", "status", "--porcelain"]):
        raise ValueError("Run teardown preflight from a clean worktree")
    head = runner(["git", "rev-parse", "HEAD"])
    origin = runner(["git", "rev-parse", "origin/main"])
    if head != expected or origin != expected:
        raise ValueError("HEAD and origin/main must equal the reviewed commit")


def execute(expected: str, runner: Runner = run) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("Expected control-plane commit must be a full SHA")
    if os.environ.get("CONFIRM_AWS_DEV_TEARDOWN_PREFLIGHT") != CONFIRMATION:
        raise ValueError(f"Set CONFIRM_AWS_DEV_TEARDOWN_PREFLIGHT={CONFIRMATION}")
    account = os.environ.get("EXPECTED_AWS_ACCOUNT_ID", "")
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID")
    if os.environ.get("CONFIRM_AWS_ENVIRONMENT_DESTROY"):
        raise ValueError("Destructive confirmation must be unset during preflight")
    for command in ("git", "aws", "terraform"):
        if shutil.which(command) is None:
            raise ValueError(f"Required command not found: {command}")

    require_exact_git(expected, runner)
    evidence_bytes = EVIDENCE.read_bytes()
    if hashlib.sha256(evidence_bytes).hexdigest() != EVIDENCE_SHA256:
        raise ValueError("Promotion execution evidence fingerprint changed")
    evidence = json.loads(evidence_bytes)
    if evidence["protectedMainCommit"] != "1ea533e809df32b31689500252f6ed98c06171e0":
        raise ValueError("Promotion execution evidence changed")
    release = evidence["release"]
    for environment, key in (
        ("aws-dev", "awsDevReleaseFileSha256"),
        ("aws-test", "awsTestReleaseFileSha256"),
        ("aws-prod", "awsProdReleaseFileSha256"),
    ):
        path = ROOT / f"apps/demo-api/helm/values/releases/{environment}.yaml"
        if hashlib.sha256(path.read_bytes()).hexdigest() != release[key]:
            raise ValueError(f"{environment} release identity changed")

    caller = json.loads(runner(["aws", "sts", "get-caller-identity", "--output", "json"]))
    if caller.get("Account") != account:
        raise ValueError("AWS caller account does not match expected account")

    clusters = json.loads(runner([
        "aws", "eks", "list-clusters", "--region", "us-east-1", "--output", "json"
    ])).get("clusters", [])
    active_rehearsal = sorted(set(clusters) & {DEV_CLUSTER, TEST_CLUSTER, PROD_CLUSTER})
    if active_rehearsal != [DEV_CLUSTER]:
        raise ValueError("Exactly aws-dev must be the only active rehearsal cluster")
    cluster = json.loads(runner([
        "aws", "eks", "describe-cluster", "--region", "us-east-1", "--name",
        DEV_CLUSTER, "--output", "json"
    ]))["cluster"]
    if cluster.get("name") != DEV_CLUSTER or cluster.get("status") != "ACTIVE":
        raise ValueError("aws-dev cluster is not ACTIVE")

    dev_state = [line for line in runner([
        "terraform", f"-chdir={TF_DEV}", "state", "list"
    ]).splitlines() if line]
    if not dev_state:
        raise ValueError("aws-dev Terraform state is empty")
    test_state = [line for line in runner([
        "terraform", f"-chdir={TF_TEST}", "state", "list"
    ]).splitlines() if line]
    if test_state:
        raise ValueError("aws-test Terraform state is not empty")
    tf_cluster = runner(["terraform", f"-chdir={TF_DEV}", "output", "-raw", "cluster_name"])
    vpc_id = runner(["terraform", f"-chdir={TF_DEV}", "output", "-raw", "vpc_id"])
    bucket = runner(["terraform", f"-chdir={TF_DEV}", "output", "-raw", "cnpg_backup_bucket_name"])
    if tf_cluster != DEV_CLUSTER or not re.fullmatch(r"vpc-[0-9a-f]+", vpc_id):
        raise ValueError("Terraform cluster or VPC identity is invalid")
    if not bucket:
        raise ValueError("Terraform backup bucket identity is empty")
    runner(["aws", "s3api", "head-bucket", "--bucket", bucket])

    return {
        "status": "aws-dev-teardown-preflight-ready-for-separate-approval",
        "control_plane_commit": expected,
        "aws_region": "us-east-1",
        "cluster_status": "ACTIVE",
        "cluster_version": str(cluster.get("version", "")),
        "terraform_resource_count": len(dev_state),
        "aws_test_state_empty": True,
        "backup_bucket_present": True,
        "backup_deletion_is_permanent": True,
        "account_verified": True,
        "account_id_emitted": False,
        "resource_ids_emitted": False,
        "execution_authorized": False,
        "teardown_authorized": False,
        "mutation_executed": False,
        "next_action": "review-preflight-before-separate-destructive-approval",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("verify", nargs="?")
    parser.add_argument("--expected-control-plane-commit", required=True)
    args = parser.parse_args()
    if args.verify != "verify":
        parser.error("only the verify mode is supported")
    print(json.dumps(execute(args.expected_control_plane_commit), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

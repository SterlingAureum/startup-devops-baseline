#!/usr/bin/env python3
"""Verify the exact, read-only boundary before the aws-dev residual audit."""

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
TEARDOWN_EVIDENCE = ROOT / "delivery/contracts/v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.json"
TEARDOWN_EVIDENCE_SHA256 = "85a4eed6b50b75883cfeccd11081f915591ea28c5aa1a03d97c34fbcd9067b4b"
AUDIT = ROOT / "scripts/validate-aws-cost-cleanup.sh"
AUDIT_SHA256 = "ab0bad09b228d09e9451863c047c8da3e4ebf77198f277ad78117b99383f3df7"
CONFIRMATION = "observe-reviewed-aws-dev-residual-cost-audit-preflight"
DEV_CLUSTER = "startup-devops-baseline-dev"
TEST_CLUSTER = "startup-devops-baseline-test"
PROD_CLUSTER = "startup-devops-baseline-prod"

Runner = Callable[[list[str]], str]
Which = Callable[[str], str | None]


def run(arguments: list[str]) -> str:
    env = os.environ.copy()
    env["AWS_PAGER"] = ""
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Command details may contain account, backend or resource identities.
        raise RuntimeError(f"Read-only command failed: {Path(arguments[0]).name}")
    return result.stdout.strip()


def require_exact_git(expected: str, runner: Runner) -> None:
    if runner(["git", "branch", "--show-current"]) != "main":
        raise ValueError("Run residual-cost preflight from main")
    if runner(["git", "status", "--porcelain"]):
        raise ValueError("Run residual-cost preflight from a clean worktree")
    head = runner(["git", "rev-parse", "HEAD"])
    origin = runner(["git", "rev-parse", "origin/main"])
    if head != expected or origin != expected:
        raise ValueError("HEAD and origin/main must equal the reviewed commit")


def execute(
    expected: str,
    runner: Runner = run,
    which: Which = shutil.which,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("Expected control-plane commit must be a full SHA")
    if os.environ.get("CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_PREFLIGHT") != CONFIRMATION:
        raise ValueError(
            "Set CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_PREFLIGHT=" + CONFIRMATION
        )
    if os.environ.get("AWS_ENVIRONMENT") != "aws-dev":
        raise ValueError("AWS_ENVIRONMENT must be exactly aws-dev")
    account = os.environ.get("EXPECTED_AWS_ACCOUNT_ID", "")
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID")
    for destructive in (
        "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION",
        "CONFIRM_AWS_DEV_APPLY",
        "CONFIRM_AWS_TEST_APPLY",
    ):
        if os.environ.get(destructive):
            raise ValueError("Destructive or create confirmation must be unset")
    for command in ("git", "aws", "terraform"):
        if which(command) is None:
            raise ValueError(f"Required command not found: {command}")

    require_exact_git(expected, runner)

    evidence_bytes = TEARDOWN_EVIDENCE.read_bytes()
    if hashlib.sha256(evidence_bytes).hexdigest() != TEARDOWN_EVIDENCE_SHA256:
        raise ValueError("Teardown execution evidence fingerprint changed")
    evidence = json.loads(evidence_bytes)
    if evidence.get("status") != "aws-dev-teardown-execution-recorded":
        raise ValueError("Teardown execution evidence status changed")
    if evidence.get("implementationBaselineCommit") != "0a90e86ca84498b1d639bbb009491f72e5142454":
        raise ValueError("Teardown execution commit changed")
    if evidence.get("operationBoundary") != {
        "awsDevTeardownExecuted": True,
        "permanentBackupDeletionIncluded": True,
        "awsTestCreated": False,
        "automaticRetryPerformed": False,
        "residualCostAuditExecuted": False,
    }:
        raise ValueError("Teardown execution boundary changed")

    if hashlib.sha256(AUDIT.read_bytes()).hexdigest() != AUDIT_SHA256:
        raise ValueError("Residual-cost audit entrypoint fingerprint changed")

    caller = json.loads(
        runner(["aws", "sts", "get-caller-identity", "--output", "json"])
    )
    if caller.get("Account") != account:
        raise ValueError("AWS caller account does not match expected account")

    clusters = json.loads(
        runner(
            [
                "aws",
                "eks",
                "list-clusters",
                "--region",
                "us-east-1",
                "--output",
                "json",
            ]
        )
    ).get("clusters", [])
    active_rehearsal = sorted(
        set(clusters) & {DEV_CLUSTER, TEST_CLUSTER, PROD_CLUSTER}
    )
    if active_rehearsal:
        raise ValueError("No rehearsal EKS environment may be active before audit")

    state_output = runner(
        ["terraform", f"-chdir={TF_DEV}", "state", "list"]
    )
    state_resources = [line for line in state_output.splitlines() if line]
    if state_resources:
        raise ValueError("aws-dev Terraform state is not empty")

    bucket_name = f"startup-devops-baseline-dev-{account}-us-east-1-cnpg"
    buckets = json.loads(
        runner(["aws", "s3api", "list-buckets", "--output", "json"])
    ).get("Buckets", [])
    bucket_names = [item.get("Name") for item in buckets if isinstance(item, dict)]
    if bucket_name in bucket_names:
        raise ValueError("aws-dev backup bucket still exists")

    secret_name = "startup-devops-baseline-dev/demo-api/postgresql"
    secrets = json.loads(
        runner(
            [
                "aws",
                "secretsmanager",
                "list-secrets",
                "--region",
                "us-east-1",
                "--include-planned-deletion",
                "--filters",
                f"Key=name,Values={secret_name}",
                "--output",
                "json",
            ]
        )
    ).get("SecretList", [])
    exact_secrets = [
        item for item in secrets
        if isinstance(item, dict) and item.get("Name") == secret_name
    ]
    if len(exact_secrets) > 1:
        raise ValueError("Unexpected duplicate aws-dev secret identity")
    secret_tombstone_present = bool(exact_secrets)
    if exact_secrets and exact_secrets[0].get("DeletedDate") is None:
        raise ValueError("aws-dev secret is not scheduled for deletion")

    return {
        "status": "aws-dev-residual-cost-audit-preflight-ready-for-separate-approval",
        "control_plane_commit": expected,
        "teardown_evidence_sha256": TEARDOWN_EVIDENCE_SHA256,
        "audit_entrypoint_sha256": AUDIT_SHA256,
        "aws_region": "us-east-1",
        "account_verified": True,
        "account_id_emitted": False,
        "active_rehearsal_environment_count": 0,
        "terraform_backend_readable": True,
        "terraform_state_resource_count": 0,
        "backup_bucket_absent": True,
        "secret_live_value_absent": True,
        "secret_tombstone_present": secret_tombstone_present,
        "full_audit_executed": False,
        "mutation_executed": False,
        "execution_authorized": False,
        "aws_test_created": False,
        "next_action": "review-preflight-before-separate-read-only-audit-approval",
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

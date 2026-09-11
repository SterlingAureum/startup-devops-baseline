#!/usr/bin/env python3
"""Run the exact-main, read-only aws-test live-creation preflight."""

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
IMPLEMENTATION_BASELINE_COMMIT = "c95af1633718eed3429e34311ed55910dbb53a7e"
IMAGE_SOURCE_COMMIT = "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8"
CONFIRMATION = "observe-reviewed-aws-test-create-preflight"
AWS_REGION = "us-east-1"
CLUSTERS = {
    "aws-dev": "startup-devops-baseline-dev",
    "aws-test": "startup-devops-baseline-test",
    "aws-prod": "startup-devops-baseline-prod",
}

AUDIT_EVIDENCE = (
    "delivery/contracts/"
    "v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.json"
)
AUDIT_EVIDENCE_SHA256 = (
    "d73e4b5107b4c99ae1feebd2a34197040e4d0f50b6c6ccbecdf951bbe1da25e9"
)
PROMOTION_EVIDENCE = (
    "delivery/contracts/"
    "v0.11.9.3.6.6.4-aws-test-promotion-execution-evidence.json"
)
PROMOTION_EVIDENCE_SHA256 = (
    "4977ddfb21738530681ce671ebaf9d71d4132e4e81c9ea1135e4b3527c27a96e"
)
LEGACY_APPLY_WRAPPER = "scripts/apply-aws-test.sh"
LEGACY_APPLY_WRAPPER_SHA256 = (
    "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114"
)
TEST_BACKEND = "infra/terraform/aws/environments/test/backend.tf"
TEST_BACKEND_SHA256 = (
    "374c263bc0de2200590d27c33707bfc426bc24fe0d6a3db4dd587a89cd4d9192"
)
TEST_STATE = "infra/terraform/aws/environments/test/terraform.tfstate"
DEV_RELEASE = "apps/demo-api/helm/values/releases/aws-dev.yaml"
TEST_RELEASE = "apps/demo-api/helm/values/releases/aws-test.yaml"
PROD_RELEASE = "apps/demo-api/helm/values/releases/aws-prod.yaml"
PROMOTED_RELEASE_SHA256 = (
    "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
)
PROD_RELEASE_SHA256 = (
    "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22"
)
RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"

Runner = Callable[[list[str]], str]
Which = Callable[[str], str | None]


def run(arguments: list[str]) -> str:
    environment = os.environ.copy()
    environment["AWS_PAGER"] = ""
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Read-only command failed: {Path(arguments[0]).name}")
    return result.stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_fingerprint(root: Path, relative: str, expected: str) -> bytes:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError("Required reviewed input must be a regular file")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("Reviewed input fingerprint changed")
    return content


def require_exact_git(expected: str, root: Path, runner: Runner) -> None:
    prefix = ["git", "-C", str(root)]
    if runner([*prefix, "branch", "--show-current"]) != "main":
        raise ValueError("Run aws-test creation preflight from main")
    if runner([*prefix, "status", "--porcelain"]):
        raise ValueError("Run aws-test creation preflight from a clean worktree")
    head = runner([*prefix, "rev-parse", "HEAD"])
    origin = runner([*prefix, "rev-parse", "origin/main"])
    if head != expected or origin != expected:
        raise ValueError("HEAD and origin/main must equal the reviewed commit")
    runner(
        [
            *prefix,
            "merge-base",
            "--is-ancestor",
            IMPLEMENTATION_BASELINE_COMMIT,
            expected,
        ]
    )
    runner(
        [
            *prefix,
            "merge-base",
            "--is-ancestor",
            IMAGE_SOURCE_COMMIT,
            expected,
        ]
    )


def require_reviewed_evidence(root: Path) -> None:
    audit = json.loads(
        require_fingerprint(root, AUDIT_EVIDENCE, AUDIT_EVIDENCE_SHA256)
    )
    if audit.get("status") != "aws-dev-residual-cost-audit-execution-recorded":
        raise ValueError("aws-dev residual-cost audit evidence status changed")
    execution = audit.get("execution", {})
    if not isinstance(execution, dict) or {
        "status": execution.get("status"),
        "auditPassed": execution.get("auditPassed"),
        "continuingCostIdentityFound": execution.get(
            "continuingCostIdentityFound"
        ),
        "mutationExecuted": execution.get("mutationExecuted"),
        "automaticRetryPerformed": execution.get("automaticRetryPerformed"),
        "awsTestCreated": execution.get("awsTestCreated"),
    } != {
        "status": "aws-dev-residual-cost-audit-complete",
        "auditPassed": True,
        "continuingCostIdentityFound": False,
        "mutationExecuted": False,
        "automaticRetryPerformed": False,
        "awsTestCreated": False,
    }:
        raise ValueError("aws-dev residual-cost audit execution boundary changed")

    promotion = json.loads(
        require_fingerprint(
            root,
            PROMOTION_EVIDENCE,
            PROMOTION_EVIDENCE_SHA256,
        )
    )
    if promotion.get("status") != (
        "reviewed-aws-dev-to-aws-test-release-only-promotion-merged"
    ):
        raise ValueError("aws-test promotion evidence status changed")
    release = promotion.get("release", {})
    if not isinstance(release, dict) or {
        "releaseId": release.get("releaseId"),
        "awsDevReleaseFileSha256": release.get("awsDevReleaseFileSha256"),
        "awsTestReleaseFileSha256": release.get("awsTestReleaseFileSha256"),
        "awsProdReleaseFileSha256": release.get("awsProdReleaseFileSha256"),
    } != {
        "releaseId": RELEASE_ID,
        "awsDevReleaseFileSha256": PROMOTED_RELEASE_SHA256,
        "awsTestReleaseFileSha256": PROMOTED_RELEASE_SHA256,
        "awsProdReleaseFileSha256": PROD_RELEASE_SHA256,
    }:
        raise ValueError("aws-test promoted release evidence changed")


def require_release_transition(root: Path) -> None:
    dev = require_fingerprint(root, DEV_RELEASE, PROMOTED_RELEASE_SHA256)
    test = require_fingerprint(root, TEST_RELEASE, PROMOTED_RELEASE_SHA256)
    prod = require_fingerprint(root, PROD_RELEASE, PROD_RELEASE_SHA256)
    if dev != test or test == prod:
        raise ValueError("Expected dev/test promoted and prod-held release changed")


def summarize_local_state(path: Path) -> dict[str, object]:
    if path.is_symlink():
        raise ValueError("aws-test Terraform state must not be a symlink")
    if not path.exists():
        return {
            "exists": False,
            "version": None,
            "resource_block_count": 0,
            "resource_instance_count": 0,
        }
    if not path.is_file():
        raise ValueError("aws-test Terraform state must be a regular file")
    try:
        state = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise ValueError("aws-test Terraform state is unreadable or invalid") from error
    if not isinstance(state, dict) or state.get("version") != 4:
        raise ValueError("aws-test Terraform state must use version 4")
    resources = state.get("resources", [])
    if not isinstance(resources, list):
        raise ValueError("aws-test Terraform state resources must be a list")
    instance_count = 0
    for resource in resources:
        if not isinstance(resource, dict):
            raise ValueError("aws-test Terraform state resource is invalid")
        instances = resource.get("instances", [])
        if not isinstance(instances, list):
            raise ValueError("aws-test Terraform state instances must be a list")
        instance_count += len(instances)
    summary = {
        "exists": True,
        "version": 4,
        "resource_block_count": len(resources),
        "resource_instance_count": instance_count,
    }
    if resources or instance_count:
        raise ValueError("aws-test Terraform state is not empty")
    return summary


def execute(
    expected_commit: str,
    repository_root: Path = ROOT,
    runner: Runner = run,
    which: Which = shutil.which,
) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("Expected control-plane commit must be a full SHA")
    if os.environ.get("CONFIRM_AWS_TEST_CREATE_PREFLIGHT") != CONFIRMATION:
        raise ValueError(
            "Set CONFIRM_AWS_TEST_CREATE_PREFLIGHT=" + CONFIRMATION
        )
    if os.environ.get("AWS_ENVIRONMENT") != "aws-test":
        raise ValueError("AWS_ENVIRONMENT must be exactly aws-test")
    account = os.environ.get("EXPECTED_AWS_ACCOUNT_ID", "")
    if not re.fullmatch(r"[0-9]{12}", account):
        raise ValueError("EXPECTED_AWS_ACCOUNT_ID must be a 12-digit account ID")
    for operational in (
        "CONFIRM_AWS_ENVIRONMENT_DESTROY",
        "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION",
        "CONFIRM_AWS_DEV_APPLY",
        "CONFIRM_AWS_TEST_APPLY",
        "CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION",
        "AWS_TEST_APPLY_MODE",
    ):
        if os.environ.get(operational):
            raise ValueError("Create, destroy or prior execution controls must be unset")
    for command in ("git", "aws"):
        if which(command) is None:
            raise ValueError(f"Required command not found: {command}")

    require_exact_git(expected_commit, repository_root, runner)
    require_reviewed_evidence(repository_root)
    require_release_transition(repository_root)
    require_fingerprint(
        repository_root,
        LEGACY_APPLY_WRAPPER,
        LEGACY_APPLY_WRAPPER_SHA256,
    )
    require_fingerprint(
        repository_root,
        TEST_BACKEND,
        TEST_BACKEND_SHA256,
    )

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
                AWS_REGION,
                "--output",
                "json",
            ]
        )
    ).get("clusters")
    if not isinstance(clusters, list) or not all(
        isinstance(cluster, str) for cluster in clusters
    ):
        raise ValueError("AWS EKS cluster inventory response is invalid")
    active_rehearsal = sorted(set(clusters) & set(CLUSTERS.values()))
    if active_rehearsal:
        raise ValueError("No rehearsal EKS environment may be active before aws-test")

    state = summarize_local_state(repository_root / TEST_STATE)

    return {
        "status": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
        "control_plane_commit": expected_commit,
        "target_environment": "aws-test",
        "aws_region": AWS_REGION,
        "account_verified": True,
        "account_id_emitted": False,
        "active_rehearsal_environment_count": 0,
        "aws_dev_residual_cost_audit_evidence_sha256": AUDIT_EVIDENCE_SHA256,
        "aws_test_promotion_evidence_sha256": PROMOTION_EVIDENCE_SHA256,
        "release_id": RELEASE_ID,
        "dev_test_release_equal": True,
        "aws_prod_release_held": True,
        "terraform_backend_kind": "local",
        "terraform_state_path_emitted": False,
        "terraform_state_exists": state["exists"],
        "terraform_state_resource_block_count": state["resource_block_count"],
        "terraform_state_resource_instance_count": state[
            "resource_instance_count"
        ],
        "legacy_apply_wrapper_sha256": LEGACY_APPLY_WRAPPER_SHA256,
        "legacy_apply_wrapper_invoked": False,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verify", nargs="?")
    parser.add_argument("--expected-control-plane-commit", required=True)
    args = parser.parse_args()
    if args.verify != "verify":
        parser.error("only the verify mode is supported")
    try:
        result = execute(args.expected_control_plane_commit)
    except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Preflight rejected: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

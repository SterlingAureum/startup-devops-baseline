#!/usr/bin/env python3
"""Validate a private aws-dev live-rehearsal preflight plan offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "v0.11.9.3.5"
REPOSITORY = "SterlingAureum/startup-devops-baseline"
IMPLEMENTATION_BASELINE_COMMIT = "1ede302a833074c567da89b15875c0ad3a8f2c69"
STATE_PATH = "infra/terraform/aws/environments/dev/terraform.tfstate"
CLUSTERS = {
    "aws_dev": "startup-devops-baseline-dev",
    "aws_test": "startup-devops-baseline-test",
    "aws_prod": "startup-devops-baseline-prod",
}
CANDIDATE = {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "source_commit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflow_run_id": "34070524953",
    "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_exact_fields(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == fields, f"{label} fields must match the template exactly")
    return value


def require_concrete(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"Concrete {label} required")
    require(
        not any(marker in value for marker in ("REPLACE", "TODO", "<", ">")),
        f"Concrete {label} required",
    )
    return value


def validate(plan: Any, repository_root: Path | None = None) -> dict[str, Any]:
    fields = {
        "schema_version",
        "mode",
        "repository",
        "target_environment",
        "control_plane_commit",
        "trusted_git_ref",
        "review_reference",
        "operator",
        "recovery_owner",
        "evidence_directory",
        "aws_account_id",
        "aws_region",
        "cluster_names",
        "terraform_state_path",
        "candidate",
        "cost_control",
        "operation_boundary",
    }
    value = require_exact_fields(plan, fields, "Plan")

    require(value["schema_version"] == SCHEMA_VERSION, "schema_version changed")
    require(value["mode"] == "read-only-preflight", "Only read-only-preflight mode is allowed")
    require(value["repository"] == REPOSITORY, "Repository changed")
    require(value["target_environment"] == "aws-dev", "Only aws-dev may be preflighted")
    control_plane_commit = value["control_plane_commit"]
    require(
        isinstance(control_plane_commit, str)
        and re.fullmatch(r"[0-9a-f]{40}", control_plane_commit) is not None,
        "Concrete post-merge control-plane commit required",
    )
    require(
        control_plane_commit != CANDIDATE["source_commit"],
        "Control-plane commit must be later than the image source commit",
    )
    require(value["trusted_git_ref"] == "refs/heads/main", "Trusted Git ref changed")

    for key in ("review_reference", "operator", "recovery_owner"):
        require_concrete(value[key], key)

    evidence_directory = Path(require_concrete(value["evidence_directory"], "evidence_directory"))
    require(evidence_directory.is_absolute(), "Private evidence directory must be absolute")
    if repository_root is not None:
        root = repository_root.resolve()
        evidence = evidence_directory.resolve()
        require(
            evidence != root and root not in evidence.parents,
            "Private evidence directory must stay outside the repository",
        )

    require(
        isinstance(value["aws_account_id"], str)
        and re.fullmatch(r"[0-9]{12}", value["aws_account_id"]) is not None
        and value["aws_account_id"] != "000000000000",
        "Concrete 12-digit AWS account ID required",
    )
    require(value["aws_region"] == "us-east-1", "AWS region changed")
    require(value["cluster_names"] == CLUSTERS, "Rehearsal cluster identities changed")
    require(value["terraform_state_path"] == STATE_PATH, "aws-dev Terraform state path changed")
    require(value["candidate"] == CANDIDATE, "Candidate immutable identity changed")

    cost_control = require_exact_fields(
        value["cost_control"],
        {
            "maximum_active_rehearsal_eks_environments",
            "other_environment_cluster_allowed",
            "require_empty_dev_state_for_create",
            "automatic_teardown",
            "teardown_requires_separate_approval",
        },
        "cost_control",
    )
    require(
        cost_control
        == {
            "maximum_active_rehearsal_eks_environments": 1,
            "other_environment_cluster_allowed": False,
            "require_empty_dev_state_for_create": True,
            "automatic_teardown": False,
            "teardown_requires_separate_approval": True,
        },
        "Cost-control boundary changed",
    )

    operation_boundary = require_exact_fields(
        value["operation_boundary"],
        {
            "requested_action",
            "aws_reads_only",
            "terraform_command_allowed",
            "kubernetes_command_allowed",
            "argocd_command_allowed",
            "environment_creation_allowed",
            "remote_fault_replay_allowed",
        },
        "operation_boundary",
    )
    require(
        operation_boundary
        == {
            "requested_action": "preflight-only",
            "aws_reads_only": True,
            "terraform_command_allowed": False,
            "kubernetes_command_allowed": False,
            "argocd_command_allowed": False,
            "environment_creation_allowed": False,
            "remote_fault_replay_allowed": False,
        },
        "Read-only operation boundary changed",
    )

    return {
        "status": "aws_dev_live_rehearsal_plan_validated_offline",
        "execution_authorized": False,
        "control_plane_commit": control_plane_commit,
        "candidate_release_id": CANDIDATE["release_id"],
        "maximum_active_rehearsal_eks_environments": 1,
        "next_action": "run-read-only-preflight-after-private-plan-review",
        "checks_not_performed": [
            "git_worktree_state",
            "git_main_identity",
            "aws_caller_identity",
            "aws_rehearsal_cluster_inventory",
            "terraform_state_summary",
            "runtime_qualification",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text())
        result = validate(plan, Path(__file__).resolve().parents[1])
    except (json.JSONDecodeError, OSError, ValueError) as error:
        parser.exit(1, f"Plan rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

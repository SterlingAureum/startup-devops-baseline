#!/usr/bin/env python3
"""Validate the v0.11.9.3.0 remote rehearsal plan without live access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "v0.11.9.3.0"
REPOSITORY = "SterlingAureum/startup-devops-baseline"
FEATURE_BRANCH = "feature/v0.11-observability-sre-baseline"
DESIGN_BASELINE_COMMIT = "d2ab89b22e5e048ed4d9121170e04d7fe7156f2c"
CANDIDATE = {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "source_commit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflow_run_id": "34070524953",
    "metadata_artifact": "demo-api-image-metadata-cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "application_version": "sha-cf0a6bc",
    "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
}
SEQUENCE = [
    "offline-plan-validation",
    "existing-image-promotion-implementation",
    "feature-to-main-review-and-merge",
    "existing-image-to-aws-dev-release-pr",
    "aws-dev-create-deploy-and-qualify",
    "aws-dev-to-aws-test-release-pr",
    "preserve-dev-evidence-and-teardown",
    "aws-test-create-deploy-canary-and-qualify",
    "aws-test-to-aws-prod-release-pr-and-approval",
    "preserve-test-evidence-and-teardown",
    "aws-prod-create-deploy-and-reviewed-canary",
    "aws-prod-approved-read-only-qualification",
    "reviewed-final-evidence",
    "approved-prod-teardown",
    "residual-cost-audit",
]
ENVIRONMENTS = [
    {
        "name": "aws-dev",
        "cluster_name": "startup-devops-baseline-dev",
        "release_file": "apps/demo-api/helm/values/releases/aws-dev.yaml",
        "manual_canary_checkpoints": 0,
        "qualification": "runtime-and-observability",
    },
    {
        "name": "aws-test",
        "cluster_name": "startup-devops-baseline-test",
        "release_file": "apps/demo-api/helm/values/releases/aws-test.yaml",
        "manual_canary_checkpoints": 1,
        "qualification": "runtime-and-observability-after-reviewed-canary",
    },
    {
        "name": "aws-prod",
        "cluster_name": "startup-devops-baseline-prod",
        "release_file": "apps/demo-api/helm/values/releases/aws-prod.yaml",
        "manual_canary_checkpoints": 1,
        "qualification": "approval-protected-read-only-observation",
    },
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_exact_fields(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == fields, f"{label} fields must match the supplied template exactly")
    return value


def require_concrete(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"Concrete {label} required")
    require(
        not any(marker in value for marker in ("REPLACE", "TODO", "<", ">")),
        f"Concrete {label} required",
    )
    return value


def validate(plan: Any, repository_root: Path | None = None) -> dict[str, Any]:
    top_fields = {
        "schema_version",
        "mode",
        "repository",
        "feature_branch",
        "design_baseline_commit",
        "planned_main_commit",
        "review_reference",
        "operator",
        "recovery_owner",
        "evidence_directory",
        "aws_account_id",
        "aws_region",
        "candidate",
        "main_integration",
        "artifact_entry",
        "local_failure_evidence",
        "environments",
        "sequence",
        "cost_control",
    }
    value = require_exact_fields(plan, top_fields, "Plan")

    require(value["schema_version"] == SCHEMA_VERSION, "schema_version changed")
    require(value["mode"] == "offline-plan-only", "Only offline-plan-only mode is allowed")
    require(value["repository"] == REPOSITORY, "Repository changed")
    require(value["feature_branch"] == FEATURE_BRANCH, "Feature branch changed")
    require(
        value["design_baseline_commit"] == DESIGN_BASELINE_COMMIT,
        "Design baseline commit changed",
    )

    planned_main = value["planned_main_commit"]
    require(
        isinstance(planned_main, str) and re.fullmatch(r"[0-9a-f]{40}", planned_main) is not None,
        "Concrete post-integration main commit required",
    )
    require(
        planned_main not in {DESIGN_BASELINE_COMMIT, CANDIDATE["source_commit"]},
        "Planned main commit must be the later merged control-plane commit",
    )

    for key in ("review_reference", "operator", "recovery_owner"):
        require_concrete(value[key], key)

    evidence_directory = Path(require_concrete(value["evidence_directory"], "evidence_directory"))
    require(evidence_directory.is_absolute(), "Private evidence directory must be absolute")
    if repository_root is not None:
        resolved_root = repository_root.resolve()
        resolved_evidence = evidence_directory.resolve()
        require(
            resolved_evidence != resolved_root
            and resolved_root not in resolved_evidence.parents,
            "Private evidence directory must stay outside the repository",
        )

    require(
        isinstance(value["aws_account_id"], str)
        and re.fullmatch(r"[0-9]{12}", value["aws_account_id"]) is not None
        and value["aws_account_id"] != "000000000000",
        "Concrete 12-digit AWS account ID required",
    )
    require(value["aws_region"] == "us-east-1", "AWS region changed")

    candidate = require_exact_fields(value["candidate"], set(CANDIDATE), "candidate")
    require(candidate == CANDIDATE, "Candidate immutable identity changed")
    digest_prefix = candidate["digest"].removeprefix("sha256:")[:12]
    expected_release_id = f"demo-api-{candidate['source_commit'][:12]}-{digest_prefix}"
    require(candidate["tag"] == f"sha-{candidate['source_commit'][:7]}", "Candidate tag/source mismatch")
    require(candidate["application_version"] == candidate["tag"], "Candidate application version mismatch")
    require(candidate["release_id"] == expected_release_id, "Candidate release ID mismatch")

    main_integration = require_exact_fields(
        value["main_integration"],
        {
            "required_before_remote_credentials",
            "trusted_runtime_ref",
            "pull_request_code_allowed",
            "feature_direct_runtime_allowed",
            "active_aws_overlays_restored_to_main",
        },
        "main_integration",
    )
    require(
        main_integration
        == {
            "required_before_remote_credentials": True,
            "trusted_runtime_ref": "refs/heads/main",
            "pull_request_code_allowed": False,
            "feature_direct_runtime_allowed": False,
            "active_aws_overlays_restored_to_main": True,
        },
        "Protected-main runtime boundary changed",
    )

    artifact_entry = require_exact_fields(
        value["artifact_entry"],
        {
            "method",
            "implementation_status",
            "implementation_checkpoint",
            "rebuild_required",
            "release_file_only",
            "automatic_merge",
        },
        "artifact_entry",
    )
    require(
        artifact_entry
        == {
            "method": "existing-image-metadata-release-pr",
            "implementation_status": "required-before-live",
            "implementation_checkpoint": "v0.11.9.3.1",
            "rebuild_required": False,
            "release_file_only": True,
            "automatic_merge": False,
        },
        "Existing-image entry boundary changed",
    )

    failure = require_exact_fields(
        value["local_failure_evidence"],
        {
            "accepted_for_v011_failure_scenario",
            "failed_revision",
            "recovered_revision",
            "remote_replay_allowed",
            "closure_contract",
            "private_archive_sha256",
        },
        "local_failure_evidence",
    )
    require(failure["accepted_for_v011_failure_scenario"] is True, "Local failure evidence not accepted")
    require((failure["failed_revision"], failure["recovered_revision"]) == (69, 70), "Local revisions changed")
    require(failure["remote_replay_allowed"] is False, "Non-local fault replay was enabled")
    require(
        failure["closure_contract"]
        == "delivery/contracts/v0.11.9.2.2.3.3.3-baseline-restoration-closure.json",
        "Local closure contract changed",
    )
    require(
        isinstance(failure["private_archive_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", failure["private_archive_sha256"]) is not None,
        "Reviewed private archive SHA-256 required",
    )

    environments = value["environments"]
    require(isinstance(environments, list) and len(environments) == 3, "Exactly three AWS environments required")
    contexts: list[str] = []
    environment_fields = {
        "name",
        "cluster_name",
        "kube_context",
        "release_file",
        "manual_canary_checkpoints",
        "qualification",
    }
    for actual, expected in zip(environments, ENVIRONMENTS, strict=True):
        item = require_exact_fields(actual, environment_fields, f"environment {expected['name']}")
        context = require_concrete(item["kube_context"], f"{expected['name']} kube_context")
        contexts.append(context)
        without_context = {key: item[key] for key in item if key != "kube_context"}
        require(without_context == expected, f"{expected['name']} contract changed")
    require(len(set(contexts)) == 3, "Every AWS environment requires a distinct explicit context")

    require(value["sequence"] == SEQUENCE, "Remote rehearsal sequence changed")

    cost_control = require_exact_fields(
        value["cost_control"],
        {
            "maximum_active_eks_environments",
            "source_evidence_preserved_before_teardown",
            "source_qualification_fresh_for_promotion",
            "automatic_teardown",
            "teardown_requires_separate_approval",
            "residual_cost_audit_required",
        },
        "cost_control",
    )
    require(
        cost_control
        == {
            "maximum_active_eks_environments": 1,
            "source_evidence_preserved_before_teardown": True,
            "source_qualification_fresh_for_promotion": True,
            "automatic_teardown": False,
            "teardown_requires_separate_approval": True,
            "residual_cost_audit_required": True,
        },
        "Cost-control boundary changed",
    )

    return {
        "status": "remote_rehearsal_plan_validated_offline",
        "runtime_qualified": False,
        "execution_authorized": False,
        "candidate_release_id": candidate["release_id"],
        "planned_main_commit": planned_main,
        "environment_order": [item["name"] for item in environments],
        "maximum_active_eks_environments": 1,
        "blocked_reasons": [
            "existing-image promotion implementation v0.11.9.3.1 required",
            "feature-to-main merge requires separate review",
            "live environment creation requires separate approval",
        ],
        "checks_not_performed": [
            "git_ancestry",
            "main_branch_state",
            "metadata_artifact_availability",
            "image_attestations",
            "aws_identity",
            "cluster_identity",
            "runtime_readiness",
            "qualification_freshness",
            "cost_state",
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

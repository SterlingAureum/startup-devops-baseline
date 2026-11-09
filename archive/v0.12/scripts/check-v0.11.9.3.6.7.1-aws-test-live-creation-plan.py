#!/usr/bin/env python3
"""Validate a private aws-test creation-plan design without live commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "v0.11.9.3.6.7.1"
REPOSITORY = "SterlingAureum/startup-devops-baseline"
IMPLEMENTATION_BASELINE = "05f481b5ce06705e130e5674175028f6645a63e1"
REVIEWED_PREFLIGHT_SHA256 = (
    "e1cf8f0fed49292b45ea3f79f5f43b51ce879f01e3d6f64753b429cab41b60f2"
)
EMPTY_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
REVIEWED_PREFLIGHT_STATUS = (
    "aws-test-live-creation-preflight-ready-for-separate-plan-review"
)
RELEASE_ID = "demo-api-cf0a6bcbc466-cdffd3d71763"
IMAGE_SOURCE_COMMIT = "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8"
PROFILE_SHA256 = (
    "03c7447a6cba2c01f4ac0da85c9cd6c68f84b3cfeb807e2f3d58bab81ffdc497"
)
BACKEND_SHA256 = (
    "374c263bc0de2200590d27c33707bfc426bc24fe0d6a3db4dd587a89cd4d9192"
)
LEGACY_WRAPPER_SHA256 = (
    "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114"
)
MAXIMUM_SESSION_HOURS = 8
MAXIMUM_SESSION_BUDGET_USD = 50.0
PLAN_REVIEW_TTL_SECONDS = 3600

REVIEWED_PREFLIGHT = {
    "control_plane_commit": IMPLEMENTATION_BASELINE,
    "result_sha256": REVIEWED_PREFLIGHT_SHA256,
    "stderr_sha256": EMPTY_SHA256,
    "status": REVIEWED_PREFLIGHT_STATUS,
    "account_verified": True,
    "account_id_emitted": False,
    "active_rehearsal_environment_count": 0,
    "terraform_backend_kind": "local",
    "terraform_state_exists": True,
    "terraform_state_resource_block_count": 0,
    "terraform_state_resource_instance_count": 0,
    "dev_test_release_equal": True,
    "aws_prod_release_held": True,
    "release_id": RELEASE_ID,
    "terraform_command_executed": False,
    "terraform_plan_executed": False,
    "terraform_apply_executed": False,
    "environment_creation_authorized": False,
    "mutation_executed": False,
    "aws_test_created": False,
}

CANDIDATE = {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "source_commit": IMAGE_SOURCE_COMMIT,
    "workflow_run_id": "34070524953",
    "release_id": RELEASE_ID,
}

INFRASTRUCTURE = {
    "cluster_name": "startup-devops-baseline-test",
    "terraform_directory": "infra/terraform/aws/environments/test",
    "terraform_state_path": "infra/terraform/aws/environments/test/terraform.tfstate",
    "terraform_backend_kind": "local",
    "backend_declaration_path": "infra/terraform/aws/environments/test/backend.tf",
    "backend_declaration_sha256": BACKEND_SHA256,
    "qualification_profile_path": "delivery/profiles/aws-test-observability-qualification.tfvars",
    "qualification_profile_sha256": PROFILE_SHA256,
    "local_variable_file_path": "infra/terraform/aws/environments/test/terraform.tfvars",
    "legacy_apply_wrapper": "scripts/apply-aws-test.sh",
    "legacy_apply_wrapper_sha256": LEGACY_WRAPPER_SHA256,
    "legacy_apply_wrapper_invocation_allowed": False,
    "historical_feature_planner_invocation_allowed": False,
    "terraform_variables_reviewed": True,
    "owner_tag_reviewed": True,
    "qualification_capacity_reviewed": True,
}

PLAN_CONTROLS = {
    "plan_executor_checkpoint": "v0.11.9.3.6.7.2",
    "plan_mode": "create",
    "plan_confirmation_variable": "CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION",
    "plan_confirmation_value": "execute-reviewed-aws-test-create-plan",
    "expected_account_variable": "EXPECTED_AWS_ACCOUNT_ID",
    "require_fresh_post_merge_preflight": True,
    "require_immediate_preflight_match": True,
    "require_clean_exact_main": True,
    "require_empty_state": True,
    "require_absent_test_cluster": True,
    "terraform_init_allowed_after_separate_plan_approval": True,
    "terraform_plan_allowed_after_separate_plan_approval": True,
    "terraform_show_allowed_for_private_review": True,
    "terraform_apply_allowed": False,
    "allowed_action_vectors": [["create"], ["read"], ["no-op"]],
    "at_least_one_create_required": True,
    "update_allowed": False,
    "delete_allowed": False,
    "replacement_allowed": False,
    "unknown_action_allowed": False,
    "private_bundle_directory_mode": "0700",
    "private_bundle_file_mode": "0600",
    "raw_plan_identity_emitted": False,
    "review_ttl_seconds": PLAN_REVIEW_TTL_SECONDS,
}

SEQUENCE = [
    "merge-plan-design-to-protected-main",
    "fresh-exact-main-read-only-preflight",
    "populate-and-offline-validate-private-plan",
    "implement-and-merge-guarded-plan-executor",
    "verify-plan-executor-inputs",
    "separate-terraform-plan-approval",
    "terraform-init-with-private-data-directory",
    "terraform-create-plan",
    "private-terraform-show-json-and-text",
    "machine-create-read-no-op-gate",
    "human-cost-and-resource-review",
    "implement-and-merge-guarded-apply-executor",
    "verify-apply-executor-inputs",
    "separate-terraform-apply-approval",
    "terraform-apply-reviewed-saved-plan",
]

FAILURE_POLICY = {
    "unknown_aws_discovery_stops": True,
    "account_or_region_mismatch_stops": True,
    "moving_main_stops": True,
    "fresh_preflight_mismatch_stops": True,
    "nonempty_or_partial_state_stops": True,
    "existing_test_cluster_stops": True,
    "variable_input_drift_stops": True,
    "terraform_destroy_update_replace_or_unknown_stops": True,
    "expired_plan_stops": True,
    "preserve_state_and_private_evidence_on_failure": True,
    "automatic_retry_allowed": False,
    "automatic_apply_allowed": False,
    "automatic_destroy_allowed": False,
}

OPERATION_BOUNDARY = {
    "requested_action": "offline-private-plan-design-validation-only",
    "aws_command_allowed": False,
    "terraform_command_allowed": False,
    "kubernetes_command_allowed": False,
    "argocd_command_allowed": False,
    "environment_creation_allowed": False,
    "gitops_bootstrap_allowed": False,
    "traffic_generation_allowed": False,
    "promotion_allowed": False,
    "teardown_allowed": False,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == fields, f"{label} fields changed")
    return value


def concrete(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"Concrete {label} required")
    require(
        not any(marker in value for marker in ("REPLACE", "TODO", "<", ">")),
        f"Concrete {label} required",
    )
    return value


def sha256(value: Any, label: str) -> str:
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        f"Valid {label} required",
    )
    return value


def utc_timestamp(value: Any, label: str) -> datetime:
    raw = concrete(value, label)
    require(raw.endswith("Z"), f"{label} must use UTC Z form")
    try:
        parsed = datetime.fromisoformat(raw.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError(f"Valid {label} required") from error
    require(parsed.tzinfo == timezone.utc, f"{label} must be UTC")
    return parsed


def positive_number(value: Any, label: str) -> float:
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{label} must be numeric",
    )
    result = float(value)
    require(result > 0, f"{label} must be positive")
    return result


def validate(plan: Any, repository_root: Path | None = None) -> dict[str, Any]:
    fields = {
        "schema_version",
        "mode",
        "repository",
        "target_environment",
        "implementation_baseline_commit",
        "planned_control_plane_commit",
        "trusted_git_ref",
        "review_reference",
        "operator",
        "recovery_owner",
        "private_plan_bundle_directory",
        "aws_account_id",
        "aws_region",
        "management_ipv4",
        "reviewed_preflight",
        "fresh_preflight_result_sha256",
        "candidate",
        "infrastructure",
        "local_variable_file_sha256",
        "plan_controls",
        "cost_control",
        "sequence",
        "failure_policy",
        "operation_boundary",
    }
    value = exact_object(plan, fields, "Plan")
    require(value["schema_version"] == SCHEMA_VERSION, "schema_version changed")
    require(
        value["mode"] == "offline-private-aws-test-create-plan-design",
        "Only offline private plan design is allowed",
    )
    require(value["repository"] == REPOSITORY, "Repository changed")
    require(value["target_environment"] == "aws-test", "Only aws-test is allowed")
    require(
        value["implementation_baseline_commit"] == IMPLEMENTATION_BASELINE,
        "Implementation baseline changed",
    )
    require(value["trusted_git_ref"] == "refs/heads/main", "Trusted Git ref changed")

    control_plane = value["planned_control_plane_commit"]
    require(
        isinstance(control_plane, str)
        and re.fullmatch(r"[0-9a-f]{40}", control_plane) is not None,
        "Concrete post-implementation protected-main commit required",
    )
    require(
        control_plane not in {IMPLEMENTATION_BASELINE, IMAGE_SOURCE_COMMIT},
        "Plan must bind the later post-implementation protected-main commit",
    )

    for key in ("review_reference", "operator", "recovery_owner"):
        concrete(value[key], key)
    bundle = Path(concrete(value["private_plan_bundle_directory"], "private plan bundle directory"))
    require(bundle.is_absolute(), "Private plan bundle directory must be absolute")
    if repository_root is not None:
        root = repository_root.resolve()
        resolved = bundle.resolve()
        require(
            resolved != root and root not in resolved.parents,
            "Private plan bundle must stay outside the repository",
        )

    account = value["aws_account_id"]
    require(
        isinstance(account, str)
        and re.fullmatch(r"[0-9]{12}", account) is not None
        and account != "000000000000",
        "Concrete AWS account ID required",
    )
    require(value["aws_region"] == "us-east-1", "AWS region changed")
    try:
        management = ipaddress.ip_address(concrete(value["management_ipv4"], "management IPv4"))
    except ValueError as error:
        raise ValueError("Valid globally routable management IPv4 required") from error
    require(
        management.version == 4 and management.is_global,
        "Valid globally routable management IPv4 required",
    )

    reviewed = exact_object(
        value["reviewed_preflight"], set(REVIEWED_PREFLIGHT), "reviewed_preflight"
    )
    require(reviewed == REVIEWED_PREFLIGHT, "Reviewed preflight boundary changed")
    fresh = sha256(value["fresh_preflight_result_sha256"], "fresh preflight result SHA-256")
    require(
        fresh not in {REVIEWED_PREFLIGHT_SHA256, EMPTY_SHA256},
        "Fresh post-merge preflight fingerprint must be new",
    )

    candidate = exact_object(value["candidate"], set(CANDIDATE), "candidate")
    require(candidate == CANDIDATE, "Candidate immutable identity changed")
    require(candidate["tag"] == f"sha-{candidate['source_commit'][:7]}", "Candidate tag/source mismatch")
    require(
        candidate["release_id"]
        == f"demo-api-{candidate['source_commit'][:12]}-{candidate['digest'].removeprefix('sha256:')[:12]}",
        "Candidate release ID mismatch",
    )

    infrastructure = exact_object(
        value["infrastructure"], set(INFRASTRUCTURE), "infrastructure"
    )
    require(infrastructure == INFRASTRUCTURE, "Infrastructure boundary changed")
    local_variables = sha256(
        value["local_variable_file_sha256"], "local terraform.tfvars SHA-256"
    )
    require(local_variables != EMPTY_SHA256, "Reviewed local terraform.tfvars must not be empty")
    if repository_root is not None:
        for key in (
            "terraform_directory",
            "backend_declaration_path",
            "qualification_profile_path",
            "legacy_apply_wrapper",
        ):
            require(
                (repository_root / infrastructure[key]).exists(),
                f"Missing repository path: {infrastructure[key]}",
            )

    controls = exact_object(value["plan_controls"], set(PLAN_CONTROLS), "plan_controls")
    require(controls == PLAN_CONTROLS, "Plan controls changed")

    cost = exact_object(
        value["cost_control"],
        {
            "currency",
            "pricing_estimate_reference",
            "estimated_hourly_cost_usd",
            "reviewed_session_budget_usd",
            "maximum_session_hours",
            "planned_start_utc",
            "teardown_review_deadline_utc",
            "maximum_active_rehearsal_eks_environments",
            "automatic_budget_enforcement",
            "automatic_teardown",
            "teardown_requires_separate_approval",
            "residual_cost_audit_required",
        },
        "cost_control",
    )
    require(cost["currency"] == "USD", "Cost currency changed")
    concrete(cost["pricing_estimate_reference"], "pricing estimate reference")
    hourly = positive_number(cost["estimated_hourly_cost_usd"], "estimated hourly cost")
    budget = positive_number(cost["reviewed_session_budget_usd"], "reviewed session budget")
    require(cost["maximum_session_hours"] == MAXIMUM_SESSION_HOURS, "Session limit changed")
    require(budget <= MAXIMUM_SESSION_BUDGET_USD, "Reviewed budget exceeds portfolio ceiling")
    require(
        budget >= hourly * MAXIMUM_SESSION_HOURS,
        "Reviewed budget does not cover the maximum session",
    )
    start = utc_timestamp(cost["planned_start_utc"], "planned start UTC")
    deadline = utc_timestamp(cost["teardown_review_deadline_utc"], "teardown deadline UTC")
    duration = (deadline - start).total_seconds()
    require(0 < duration <= MAXIMUM_SESSION_HOURS * 3600, "Session window must be within eight hours")
    require(
        cost["maximum_active_rehearsal_eks_environments"] == 1,
        "Only one active rehearsal EKS environment is allowed",
    )
    require(cost["automatic_budget_enforcement"] is False, "Unimplemented budget automation claimed")
    require(cost["automatic_teardown"] is False, "Automatic teardown enabled")
    require(cost["teardown_requires_separate_approval"] is True, "Separate teardown approval disabled")
    require(cost["residual_cost_audit_required"] is True, "Residual-cost audit disabled")

    require(value["sequence"] == SEQUENCE, "Plan/apply sequence changed")
    failure = exact_object(value["failure_policy"], set(FAILURE_POLICY), "failure_policy")
    require(failure == FAILURE_POLICY, "Failure-stop policy changed")
    operation = exact_object(
        value["operation_boundary"], set(OPERATION_BOUNDARY), "operation_boundary"
    )
    require(operation == OPERATION_BOUNDARY, "Offline operation boundary changed")

    return {
        "status": "aws-test-private-creation-plan-design-validated-offline",
        "target_environment": "aws-test",
        "planned_control_plane_commit": control_plane,
        "candidate_release_id": RELEASE_ID,
        "reviewed_preflight_sha256": REVIEWED_PREFLIGHT_SHA256,
        "fresh_post_merge_preflight_required": True,
        "maximum_session_hours": MAXIMUM_SESSION_HOURS,
        "reviewed_session_budget_usd": budget,
        "plan_review_ttl_seconds": PLAN_REVIEW_TTL_SECONDS,
        "terraform_plan_authorized": False,
        "terraform_apply_authorized": False,
        "environment_creation_authorized": False,
        "commands_executed": [],
        "next_action": "merge-design-run-fresh-preflight-and-implement-guarded-plan-executor",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.plan.read_text())
        result = validate(document, Path(__file__).resolve().parents[1])
    except (json.JSONDecodeError, OSError, ValueError) as error:
        parser.exit(1, f"Private aws-test creation plan rejected: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

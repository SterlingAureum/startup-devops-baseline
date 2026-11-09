#!/usr/bin/env python3
"""Validate a private aws-dev creation plan without executing live commands."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "v0.11.9.3.6"
REPOSITORY = "SterlingAureum/startup-devops-baseline"
IMPLEMENTATION_BASELINE = "05270a186fcf8aa5b82ff4d1e44ea467f4a1498d"
PRIOR_CONTROL_PLANE = "cd5aac1f2ab4363fe05ac3507d2abe0a15f54422"
PRIOR_PLAN_SHA256 = "56eef1a83217d9d5b2287ac295dcc0fa915313b3d23f3f494d20ab56b151a66b"
PRIOR_RESULT_SHA256 = "ad91ef09cd481b9d32efbfb2fbe91ca8e552827bda369f063bf9e02fc499e068"
PRIOR_STATUS = "ready-for-separate-aws-dev-create-approval"
MAXIMUM_SESSION_HOURS = 8
MAXIMUM_SESSION_BUDGET_USD = 50.0

CANDIDATE = {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "source_commit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflow_run_id": "34070524953",
    "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
}

INFRASTRUCTURE = {
    "cluster_name": "startup-devops-baseline-dev",
    "terraform_directory": "infra/terraform/aws/environments/dev",
    "terraform_vars_path": "infra/terraform/aws/environments/dev/terraform.tfvars",
    "terraform_state_path": "infra/terraform/aws/environments/dev/terraform.tfstate",
    "create_entrypoint": "scripts/apply-aws-dev.sh",
    "gitops_bootstrap_entrypoint": "scripts/bootstrap-eks-argocd.sh",
    "root_deploy_entrypoint": "scripts/deploy-aws-dev-root-app.sh",
    "destroy_entrypoint": "scripts/destroy-aws-dev.sh",
    "residual_cost_audit_entrypoint": "scripts/validate-aws-cost-cleanup.sh",
    "terraform_vars_reviewed": True,
    "owner_tag_reviewed": True,
}

CREATION_CONTROLS = {
    "environment_confirmation_variable": "CONFIRM_AWS_DEV_APPLY",
    "environment_confirmation_value": "create-ephemeral-aws-dev",
    "expected_account_variable": "EXPECTED_AWS_ACCOUNT_ID",
    "interactive_terraform_plan_confirmation": "apply-aws-dev",
    "reject_destroy_actions": True,
    "reject_replacement_actions": True,
    "require_empty_state": True,
    "require_clean_exact_main": True,
    "remote_fault_replay_allowed": False,
}

SEQUENCE = [
    "fresh-read-only-preflight",
    "separate-live-create-approval",
    "guarded-terraform-plan",
    "interactive-plan-confirmation",
    "terraform-apply",
    "eks-api-readiness",
    "argocd-bootstrap",
    "root-application-deploy",
    "aws-dev-runtime-observability-qualification",
    "preserve-private-evidence",
    "separate-teardown-review",
    "destroy-and-residual-cost-audit",
]

FAILURE_POLICY = {
    "unknown_aws_discovery_stops": True,
    "account_or_region_mismatch_stops": True,
    "moving_main_stops": True,
    "fresh_preflight_mismatch_stops": True,
    "nonempty_or_partial_state_stops": True,
    "terraform_destroy_or_replace_stops": True,
    "deadline_stops_qualification": True,
    "preserve_state_and_evidence_on_failure": True,
    "no_automatic_destroy_on_failure": True,
}

OPERATION_BOUNDARY = {
    "requested_action": "plan-validation-only",
    "aws_command_allowed": False,
    "terraform_command_allowed": False,
    "kubernetes_command_allowed": False,
    "argocd_command_allowed": False,
    "environment_creation_allowed": False,
    "traffic_generation_allowed": False,
    "remote_fault_replay_allowed": False,
    "automatic_teardown_allowed": False,
    "aws_test_promotion_allowed": False,
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
    require(isinstance(value, str), f"{label} must be a string")
    require(re.fullmatch(r"[0-9a-f]{64}", value) is not None, f"Valid {label} required")
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
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    converted = float(value)
    require(converted > 0, f"{label} must be positive")
    return converted


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
        "evidence_directory",
        "aws_account_id",
        "aws_region",
        "preflight",
        "candidate",
        "infrastructure",
        "creation_controls",
        "cost_control",
        "sequence",
        "failure_policy",
        "operation_boundary",
    }
    value = exact_object(plan, fields, "Plan")
    require(value["schema_version"] == SCHEMA_VERSION, "schema_version changed")
    require(value["mode"] == "offline-create-plan-only", "Only offline-create-plan-only is allowed")
    require(value["repository"] == REPOSITORY, "Repository changed")
    require(value["target_environment"] == "aws-dev", "Only aws-dev is allowed")
    require(value["implementation_baseline_commit"] == IMPLEMENTATION_BASELINE, "Implementation baseline changed")
    require(value["trusted_git_ref"] == "refs/heads/main", "Trusted Git ref changed")

    control_plane = value["planned_control_plane_commit"]
    require(
        isinstance(control_plane, str) and re.fullmatch(r"[0-9a-f]{40}", control_plane) is not None,
        "Concrete post-implementation main commit required",
    )
    require(
        control_plane not in {IMPLEMENTATION_BASELINE, PRIOR_CONTROL_PLANE, CANDIDATE["source_commit"]},
        "Planned control plane must be the later post-implementation main commit",
    )

    for key in ("review_reference", "operator", "recovery_owner"):
        concrete(value[key], key)
    evidence = Path(concrete(value["evidence_directory"], "evidence_directory"))
    require(evidence.is_absolute(), "Evidence directory must be absolute")
    if repository_root is not None:
        root = repository_root.resolve()
        resolved = evidence.resolve()
        require(resolved != root and root not in resolved.parents, "Evidence directory must stay outside repository")
    require(
        isinstance(value["aws_account_id"], str)
        and re.fullmatch(r"[0-9]{12}", value["aws_account_id"]) is not None
        and value["aws_account_id"] != "000000000000",
        "Concrete AWS account ID required",
    )
    require(value["aws_region"] == "us-east-1", "AWS region changed")

    preflight = exact_object(
        value["preflight"],
        {
            "prior_execution_contract",
            "prior_plan_sha256",
            "prior_result_sha256",
            "prior_status",
            "fresh_preflight_required",
            "fresh_preflight_plan_sha256",
            "fresh_preflight_result_sha256",
        },
        "preflight",
    )
    require(
        preflight["prior_execution_contract"]
        == "delivery/contracts/v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.json",
        "Prior preflight contract changed",
    )
    require(preflight["prior_plan_sha256"] == PRIOR_PLAN_SHA256, "Prior plan fingerprint changed")
    require(preflight["prior_result_sha256"] == PRIOR_RESULT_SHA256, "Prior result fingerprint changed")
    require(preflight["prior_status"] == PRIOR_STATUS, "Prior ready status changed")
    require(preflight["fresh_preflight_required"] is True, "Fresh preflight requirement disabled")
    fresh_plan = sha256(preflight["fresh_preflight_plan_sha256"], "fresh preflight plan SHA-256")
    fresh_result = sha256(preflight["fresh_preflight_result_sha256"], "fresh preflight result SHA-256")
    require(fresh_plan not in {PRIOR_PLAN_SHA256, PRIOR_RESULT_SHA256}, "Fresh plan fingerprint was reused")
    require(fresh_result not in {PRIOR_PLAN_SHA256, PRIOR_RESULT_SHA256}, "Fresh result fingerprint was reused")
    require(fresh_plan != fresh_result, "Fresh preflight fingerprints must be distinct")

    candidate = exact_object(value["candidate"], set(CANDIDATE), "candidate")
    require(candidate == CANDIDATE, "Candidate immutable identity changed")
    require(candidate["tag"] == f"sha-{candidate['source_commit'][:7]}", "Candidate tag/source mismatch")
    require(
        candidate["release_id"]
        == f"demo-api-{candidate['source_commit'][:12]}-{candidate['digest'].removeprefix('sha256:')[:12]}",
        "Candidate release ID mismatch",
    )

    infrastructure = exact_object(value["infrastructure"], set(INFRASTRUCTURE), "infrastructure")
    require(infrastructure == INFRASTRUCTURE, "Infrastructure boundary changed")
    if repository_root is not None:
        for key in (
            "terraform_directory",
            "create_entrypoint",
            "gitops_bootstrap_entrypoint",
            "root_deploy_entrypoint",
            "destroy_entrypoint",
            "residual_cost_audit_entrypoint",
        ):
            require((repository_root / infrastructure[key]).exists(), f"Missing repository path: {infrastructure[key]}")

    controls = exact_object(value["creation_controls"], set(CREATION_CONTROLS), "creation_controls")
    require(controls == CREATION_CONTROLS, "Creation controls changed")

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
    concrete(cost["pricing_estimate_reference"], "pricing_estimate_reference")
    hourly = positive_number(cost["estimated_hourly_cost_usd"], "estimated_hourly_cost_usd")
    budget = positive_number(cost["reviewed_session_budget_usd"], "reviewed_session_budget_usd")
    require(cost["maximum_session_hours"] == MAXIMUM_SESSION_HOURS, "Session duration boundary changed")
    require(budget <= MAXIMUM_SESSION_BUDGET_USD, "Reviewed session budget exceeds portfolio ceiling")
    require(budget >= hourly * MAXIMUM_SESSION_HOURS, "Reviewed budget does not cover the estimated session")
    start = utc_timestamp(cost["planned_start_utc"], "planned_start_utc")
    deadline = utc_timestamp(cost["teardown_review_deadline_utc"], "teardown_review_deadline_utc")
    duration_hours = (deadline - start).total_seconds() / 3600
    require(0 < duration_hours <= MAXIMUM_SESSION_HOURS, "Teardown review deadline must be within eight hours")
    require(cost["maximum_active_rehearsal_eks_environments"] == 1, "Only one active EKS environment is allowed")
    require(cost["automatic_budget_enforcement"] is False, "Unimplemented automatic budget enforcement claimed")
    require(cost["automatic_teardown"] is False, "Automatic teardown enabled")
    require(cost["teardown_requires_separate_approval"] is True, "Separate teardown review disabled")
    require(cost["residual_cost_audit_required"] is True, "Residual cost audit disabled")

    require(value["sequence"] == SEQUENCE, "Creation and teardown sequence changed")
    failure = exact_object(value["failure_policy"], set(FAILURE_POLICY), "failure_policy")
    require(failure == FAILURE_POLICY, "Failure-stop policy changed")
    operation = exact_object(value["operation_boundary"], set(OPERATION_BOUNDARY), "operation_boundary")
    require(operation == OPERATION_BOUNDARY, "Offline operation boundary changed")

    return {
        "status": "aws_dev_create_plan_validated_offline",
        "target_environment": "aws-dev",
        "planned_control_plane_commit": control_plane,
        "candidate_release_id": candidate["release_id"],
        "maximum_session_hours": MAXIMUM_SESSION_HOURS,
        "reviewed_session_budget_usd": budget,
        "maximum_active_rehearsal_eks_environments": 1,
        "fresh_preflight_required": True,
        "execution_authorized": False,
        "blocked_reasons": [
            "v0.11.9.3.6 must be reviewed and merged to protected main",
            "fresh read-only preflight must match the post-implementation main commit",
            "live creation requires the separate v0.11.9.3.6.1 executor review",
        ],
        "commands_executed": [],
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

#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.py"
TEMPLATE = ROOT / "delivery/examples/v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.json"
SPEC = importlib.util.spec_from_file_location("aws_dev_create_plan", CHECKER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-dev create-plan checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_plan() -> dict:
    plan = json.loads(TEMPLATE.read_text())
    plan.update(
        planned_control_plane_commit="f" * 40,
        review_reference="review-v0.11.9.3.6-create-001",
        operator="SterlingAureum",
        recovery_owner="SterlingAureum",
        evidence_directory="/tmp/private-v0.11.9.3.6-aws-dev-evidence",
        aws_account_id="123456789012",
    )
    plan["preflight"]["fresh_preflight_plan_sha256"] = "c" * 64
    plan["preflight"]["fresh_preflight_result_sha256"] = "d" * 64
    plan["infrastructure"]["terraform_vars_reviewed"] = True
    plan["infrastructure"]["owner_tag_reviewed"] = True
    plan["cost_control"].update(
        pricing_estimate_reference="reviewed-current-pricing-estimate-001",
        estimated_hourly_cost_usd=2.5,
        reviewed_session_budget_usd=25.0,
        planned_start_utc="2026-09-09T01:00:00Z",
        teardown_review_deadline_utc="2026-09-09T09:00:00Z",
    )
    return plan


class AwsDevCreatePlanTests(unittest.TestCase):
    def test_valid_plan_is_offline_and_blocked(self) -> None:
        result = MODULE.validate(valid_plan(), ROOT)
        self.assertEqual(result["status"], "aws_dev_create_plan_validated_offline")
        self.assertEqual(result["target_environment"], "aws-dev")
        self.assertEqual(result["maximum_session_hours"], 8)
        self.assertEqual(result["maximum_active_rehearsal_eks_environments"], 1)
        self.assertTrue(result["fresh_preflight_required"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["commands_executed"], [])

    def test_repository_template_is_rejected(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--plan", str(TEMPLATE)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Plan rejected", result.stderr)

    def test_post_implementation_main_commit_is_required(self) -> None:
        for replacement in (
            MODULE.IMPLEMENTATION_BASELINE,
            MODULE.PRIOR_CONTROL_PLANE,
            MODULE.CANDIDATE["source_commit"],
            "short",
        ):
            with self.subTest(replacement=replacement):
                plan = valid_plan()
                plan["planned_control_plane_commit"] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_prior_and_fresh_preflight_evidence_is_strict(self) -> None:
        mutations = (
            ("prior_plan_sha256", "a" * 64),
            ("prior_result_sha256", "b" * 64),
            ("prior_status", "blocked"),
            ("fresh_preflight_required", False),
            ("fresh_preflight_plan_sha256", MODULE.PRIOR_PLAN_SHA256),
            ("fresh_preflight_result_sha256", "short"),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["preflight"][key] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_fresh_preflight_fingerprints_must_be_distinct(self) -> None:
        plan = valid_plan()
        plan["preflight"]["fresh_preflight_result_sha256"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "distinct"):
            MODULE.validate(plan, ROOT)

    def test_candidate_mutations_are_rejected(self) -> None:
        for key, replacement in (
            ("tag", "sha-deadbee"),
            ("digest", "sha256:" + "a" * 64),
            ("source_commit", "b" * 40),
            ("workflow_run_id", "1"),
            ("release_id", "demo-api-wrong"),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["candidate"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Candidate"):
                    MODULE.validate(plan, ROOT)

    def test_infrastructure_and_review_attestations_are_strict(self) -> None:
        for key, replacement in (
            ("cluster_name", "startup-devops-baseline-test"),
            ("terraform_directory", "infra/terraform/aws/environments/test"),
            ("create_entrypoint", "scripts/apply-aws-test.sh"),
            ("terraform_vars_reviewed", False),
            ("owner_tag_reviewed", False),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["infrastructure"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Infrastructure"):
                    MODULE.validate(plan, ROOT)

    def test_creation_controls_cannot_be_weakened(self) -> None:
        for key, replacement in (
            ("environment_confirmation_value", "yes"),
            ("interactive_terraform_plan_confirmation", "yes"),
            ("reject_destroy_actions", False),
            ("reject_replacement_actions", False),
            ("require_empty_state", False),
            ("require_clean_exact_main", False),
            ("remote_fault_replay_allowed", True),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["creation_controls"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Creation controls"):
                    MODULE.validate(plan, ROOT)

    def test_cost_and_time_boundaries_are_enforced(self) -> None:
        mutations = (
            ("estimated_hourly_cost_usd", 0),
            ("reviewed_session_budget_usd", 51),
            ("reviewed_session_budget_usd", 10),
            ("maximum_session_hours", 12),
            ("teardown_review_deadline_utc", "2026-09-09T10:00:00Z"),
            ("automatic_budget_enforcement", True),
            ("automatic_teardown", True),
            ("teardown_requires_separate_approval", False),
            ("maximum_active_rehearsal_eks_environments", 2),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["cost_control"][key] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_sequence_failure_and_operation_boundaries_are_strict(self) -> None:
        plan = valid_plan()
        plan["sequence"][1], plan["sequence"][2] = plan["sequence"][2], plan["sequence"][1]
        with self.assertRaisesRegex(ValueError, "sequence"):
            MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["failure_policy"]["no_automatic_destroy_on_failure"] = False
        with self.assertRaisesRegex(ValueError, "Failure-stop"):
            MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["operation_boundary"]["terraform_command_allowed"] = True
        with self.assertRaisesRegex(ValueError, "Offline operation"):
            MODULE.validate(plan, ROOT)

    def test_private_fields_and_exact_shape_are_required(self) -> None:
        for key, replacement in (
            ("review_reference", "REPLACE_ME"),
            ("operator", ""),
            ("aws_account_id", "123"),
            ("evidence_directory", str(ROOT / "evidence")),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan[key] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["execute"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            MODULE.validate(plan, ROOT)


if __name__ == "__main__":
    unittest.main()

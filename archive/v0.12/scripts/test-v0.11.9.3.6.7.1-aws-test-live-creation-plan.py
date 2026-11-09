#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py"
TEMPLATE = ROOT / "delivery/examples/v0.11.9.3.6.7.1-aws-test-live-creation-plan.json"
SPEC = importlib.util.spec_from_file_location("aws_test_private_plan", CHECKER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-test private-plan checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_plan() -> dict:
    plan = json.loads(TEMPLATE.read_text())
    plan.update(
        planned_control_plane_commit="f" * 40,
        review_reference="review-v0.11.9.3.6.7.1-plan-001",
        operator="SterlingAureum",
        recovery_owner="SterlingAureum",
        private_plan_bundle_directory="/tmp/private-v0.11.9.3.6.7.1-aws-test-plan",
        aws_account_id="123456789012",
        management_ipv4="8.8.8.8",
        fresh_preflight_result_sha256="c" * 64,
        local_variable_file_sha256="d" * 64,
    )
    plan["cost_control"].update(
        pricing_estimate_reference="reviewed-current-pricing-estimate-001",
        estimated_hourly_cost_usd=2.5,
        reviewed_session_budget_usd=25.0,
        planned_start_utc="2026-09-12T01:00:00Z",
        teardown_review_deadline_utc="2026-09-12T09:00:00Z",
    )
    return plan


class AwsTestPrivateCreationPlanTests(unittest.TestCase):
    def test_valid_plan_is_offline_and_unauthorized(self) -> None:
        result = MODULE.validate(valid_plan(), ROOT)
        self.assertEqual(
            result["status"],
            "aws-test-private-creation-plan-design-validated-offline",
        )
        self.assertEqual(result["target_environment"], "aws-test")
        self.assertEqual(result["plan_review_ttl_seconds"], 3600)
        self.assertTrue(result["fresh_post_merge_preflight_required"])
        self.assertFalse(result["terraform_plan_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(result["environment_creation_authorized"])
        self.assertEqual(result["commands_executed"], [])

    def test_repository_template_is_rejected(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--plan", str(TEMPLATE)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("rejected", result.stderr)

    def test_later_protected_main_is_required(self) -> None:
        for replacement in (
            MODULE.IMPLEMENTATION_BASELINE,
            MODULE.IMAGE_SOURCE_COMMIT,
            "short",
        ):
            with self.subTest(replacement=replacement):
                plan = valid_plan()
                plan["planned_control_plane_commit"] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_reviewed_preflight_is_byte_exact(self) -> None:
        mutations = (
            ("control_plane_commit", "e" * 40),
            ("result_sha256", "a" * 64),
            ("status", "not-ready"),
            ("account_verified", False),
            ("account_id_emitted", True),
            ("active_rehearsal_environment_count", 1),
            ("terraform_state_exists", False),
            ("terraform_state_resource_block_count", 1),
            ("terraform_state_resource_instance_count", 1),
            ("terraform_plan_executed", True),
            ("mutation_executed", True),
            ("aws_test_created", True),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["reviewed_preflight"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Reviewed preflight"):
                    MODULE.validate(plan, ROOT)

    def test_fresh_preflight_must_be_new_and_valid(self) -> None:
        for replacement in (
            MODULE.REVIEWED_PREFLIGHT_SHA256,
            MODULE.EMPTY_SHA256,
            "short",
        ):
            with self.subTest(replacement=replacement):
                plan = valid_plan()
                plan["fresh_preflight_result_sha256"] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_candidate_identity_is_immutable(self) -> None:
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

    def test_infrastructure_boundary_is_strict(self) -> None:
        for key, replacement in (
            ("cluster_name", "startup-devops-baseline-dev"),
            ("terraform_directory", "infra/terraform/aws/environments/dev"),
            ("terraform_backend_kind", "s3"),
            ("legacy_apply_wrapper_invocation_allowed", True),
            ("historical_feature_planner_invocation_allowed", True),
            ("terraform_variables_reviewed", False),
            ("owner_tag_reviewed", False),
            ("qualification_capacity_reviewed", False),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["infrastructure"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Infrastructure"):
                    MODULE.validate(plan, ROOT)

    def test_plan_controls_cannot_be_weakened(self) -> None:
        for key, replacement in (
            ("plan_mode", "resume"),
            ("require_fresh_post_merge_preflight", False),
            ("require_immediate_preflight_match", False),
            ("require_empty_state", False),
            ("require_absent_test_cluster", False),
            ("terraform_apply_allowed", True),
            ("allowed_action_vectors", [["create"], ["update"]]),
            ("at_least_one_create_required", False),
            ("update_allowed", True),
            ("delete_allowed", True),
            ("replacement_allowed", True),
            ("unknown_action_allowed", True),
            ("review_ttl_seconds", 7200),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["plan_controls"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Plan controls"):
                    MODULE.validate(plan, ROOT)

    def test_private_values_and_ipv4_are_required(self) -> None:
        for key, replacement in (
            ("review_reference", "REPLACE_ME"),
            ("operator", ""),
            ("aws_account_id", "123"),
            ("management_ipv4", "10.0.0.1"),
            ("management_ipv4", "2001:4860:4860::8888"),
            ("private_plan_bundle_directory", str(ROOT / "private")),
            ("local_variable_file_sha256", MODULE.EMPTY_SHA256),
        ):
            with self.subTest(key=key, replacement=replacement):
                plan = valid_plan()
                plan[key] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_cost_and_time_limits_are_enforced(self) -> None:
        mutations = (
            ("estimated_hourly_cost_usd", 0),
            ("reviewed_session_budget_usd", 51),
            ("reviewed_session_budget_usd", 10),
            ("maximum_session_hours", 12),
            ("teardown_review_deadline_utc", "2026-09-12T10:00:00Z"),
            ("maximum_active_rehearsal_eks_environments", 2),
            ("automatic_budget_enforcement", True),
            ("automatic_teardown", True),
            ("teardown_requires_separate_approval", False),
            ("residual_cost_audit_required", False),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["cost_control"][key] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_sequence_failure_and_operation_boundaries_are_strict(self) -> None:
        plan = valid_plan()
        plan["sequence"][5], plan["sequence"][6] = (
            plan["sequence"][6],
            plan["sequence"][5],
        )
        with self.assertRaisesRegex(ValueError, "sequence"):
            MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["failure_policy"]["automatic_apply_allowed"] = True
        with self.assertRaisesRegex(ValueError, "Failure-stop"):
            MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["operation_boundary"]["terraform_command_allowed"] = True
        with self.assertRaisesRegex(ValueError, "Offline operation"):
            MODULE.validate(plan, ROOT)

    def test_exact_shape_rejects_undeclared_execution_switch(self) -> None:
        plan = valid_plan()
        plan["execute"] = True
        with self.assertRaisesRegex(ValueError, "fields"):
            MODULE.validate(plan, ROOT)


if __name__ == "__main__":
    unittest.main()

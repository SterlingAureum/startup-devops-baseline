#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check-v0.11.9.3.0-remote-release-rehearsal-plan.py"
TEMPLATE = ROOT / "delivery/examples/v0.11.9.3.0-remote-release-rehearsal-plan.json"
SPEC = importlib.util.spec_from_file_location("remote_rehearsal_plan", CHECKER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load remote rehearsal checker")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_plan() -> dict:
    plan = json.loads(TEMPLATE.read_text())
    plan.update(
        planned_main_commit="f" * 40,
        review_reference="review-v0.11-remote-001",
        operator="SterlingAureum",
        recovery_owner="SterlingAureum",
        evidence_directory="/tmp/private-v0.11-remote-evidence",
        aws_account_id="123456789012",
    )
    plan["local_failure_evidence"]["private_archive_sha256"] = "a" * 64
    for environment in plan["environments"]:
        environment["kube_context"] = f"eks-{environment['name']}-explicit"
    return plan


class RemoteRehearsalPlanTests(unittest.TestCase):
    def test_valid_plan_remains_offline_and_blocked(self) -> None:
        result = MODULE.validate(valid_plan(), ROOT)
        self.assertEqual(result["status"], "remote_rehearsal_plan_validated_offline")
        self.assertFalse(result["runtime_qualified"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["environment_order"], ["aws-dev", "aws-test", "aws-prod"])
        self.assertEqual(result["maximum_active_eks_environments"], 1)
        self.assertIn("existing-image promotion implementation v0.11.9.3.1 required", result["blocked_reasons"])

    def test_template_is_rejected_by_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--plan", str(TEMPLATE)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Plan rejected", result.stderr)

    def test_candidate_identity_mutations_are_rejected(self) -> None:
        mutations = (
            ("tag", "sha-deadbee"),
            ("digest", "sha256:" + "b" * 64),
            ("source_commit", "b" * 40),
            ("workflow_run_id", "1"),
            ("release_id", "demo-api-wrong"),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["candidate"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Candidate"):
                    MODULE.validate(plan, ROOT)

    def test_protected_main_mutations_are_rejected(self) -> None:
        mutations = (
            ("required_before_remote_credentials", False),
            ("trusted_runtime_ref", "refs/heads/feature"),
            ("pull_request_code_allowed", True),
            ("feature_direct_runtime_allowed", True),
            ("active_aws_overlays_restored_to_main", False),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["main_integration"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Protected-main"):
                    MODULE.validate(plan, ROOT)

    def test_existing_image_entry_mutations_are_rejected(self) -> None:
        mutations = (
            ("method", "rebuild-image"),
            ("implementation_status", "implemented"),
            ("rebuild_required", True),
            ("release_file_only", False),
            ("automatic_merge", True),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan["artifact_entry"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Existing-image"):
                    MODULE.validate(plan, ROOT)

    def test_remote_fault_replay_and_evidence_mutations_are_rejected(self) -> None:
        for key, replacement in (
            ("accepted_for_v011_failure_scenario", False),
            ("failed_revision", 68),
            ("recovered_revision", 71),
            ("remote_replay_allowed", True),
            ("private_archive_sha256", "short"),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["local_failure_evidence"][key] = replacement
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)

    def test_environment_order_context_and_canary_mutations_are_rejected(self) -> None:
        plan = valid_plan()
        plan["environments"].reverse()
        with self.assertRaises(ValueError):
            MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["environments"][1]["kube_context"] = plan["environments"][0]["kube_context"]
        with self.assertRaisesRegex(ValueError, "distinct explicit context"):
            MODULE.validate(plan, ROOT)

        plan = valid_plan()
        plan["environments"][2]["manual_canary_checkpoints"] = 0
        with self.assertRaises(ValueError):
            MODULE.validate(plan, ROOT)

    def test_sequence_and_cost_mutations_are_rejected(self) -> None:
        plan = valid_plan()
        plan["sequence"][2], plan["sequence"][3] = plan["sequence"][3], plan["sequence"][2]
        with self.assertRaisesRegex(ValueError, "sequence"):
            MODULE.validate(plan, ROOT)

        for key, replacement in (
            ("maximum_active_eks_environments", 2),
            ("source_evidence_preserved_before_teardown", False),
            ("source_qualification_fresh_for_promotion", False),
            ("automatic_teardown", True),
            ("teardown_requires_separate_approval", False),
            ("residual_cost_audit_required", False),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["cost_control"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Cost-control"):
                    MODULE.validate(plan, ROOT)

    def test_private_fields_and_control_plane_identity_are_required(self) -> None:
        for key, replacement in (
            ("planned_main_commit", MODULE.DESIGN_BASELINE_COMMIT),
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

    def test_missing_extra_and_wrong_type_are_rejected(self) -> None:
        plans = [
            [],
            {**valid_plan(), "execute": True},
            {key: value for key, value in valid_plan().items() if key != "sequence"},
        ]
        for plan in plans:
            with self.subTest(plan_type=type(plan).__name__):
                with self.assertRaises(ValueError):
                    MODULE.validate(plan, ROOT)


if __name__ == "__main__":
    unittest.main()

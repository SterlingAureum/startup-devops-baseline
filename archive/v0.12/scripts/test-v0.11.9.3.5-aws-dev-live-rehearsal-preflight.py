#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts/check-v0.11.9.3.5-aws-dev-live-rehearsal-plan.py"
PREFLIGHT_PATH = ROOT / "scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py"
TEMPLATE = ROOT / "delivery/examples/v0.11.9.3.5-aws-dev-live-rehearsal-plan.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_module("aws_dev_plan", CHECKER_PATH)
PREFLIGHT = load_module("aws_dev_preflight", PREFLIGHT_PATH)


def valid_plan(evidence_directory: str = "/tmp/private-v0.11-aws-dev-evidence") -> dict:
    plan = json.loads(TEMPLATE.read_text())
    plan.update(
        control_plane_commit="f" * 40,
        review_reference="PR-74-reviewed-main",
        operator="SterlingAureum",
        recovery_owner="SterlingAureum",
        evidence_directory=evidence_directory,
        aws_account_id="123456789012",
    )
    return plan


class AwsDevPlanTests(unittest.TestCase):
    def test_valid_plan_remains_non_authorizing(self) -> None:
        result = CHECKER.validate(valid_plan(), ROOT)
        self.assertEqual(result["status"], "aws_dev_live_rehearsal_plan_validated_offline")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["control_plane_commit"], "f" * 40)
        self.assertEqual(result["maximum_active_rehearsal_eks_environments"], 1)

    def test_template_is_rejected_by_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER_PATH), "--plan", str(TEMPLATE)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("Plan rejected", result.stderr)

    def test_identity_and_operation_mutations_are_rejected(self) -> None:
        mutations = (
            ("control_plane_commit", "short"),
            ("target_environment", "aws-test"),
            ("trusted_git_ref", "refs/heads/feature"),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                plan = valid_plan()
                plan[key] = replacement
                with self.assertRaises(ValueError):
                    CHECKER.validate(plan, ROOT)

        for key, replacement in (
            ("terraform_command_allowed", True),
            ("kubernetes_command_allowed", True),
            ("argocd_command_allowed", True),
            ("environment_creation_allowed", True),
            ("remote_fault_replay_allowed", True),
        ):
            with self.subTest(key=key):
                plan = valid_plan()
                plan["operation_boundary"][key] = replacement
                with self.assertRaisesRegex(ValueError, "Read-only"):
                    CHECKER.validate(plan, ROOT)

    def test_candidate_and_cost_mutations_are_rejected(self) -> None:
        plan = valid_plan()
        plan["candidate"]["digest"] = "sha256:" + "a" * 64
        with self.assertRaisesRegex(ValueError, "Candidate"):
            CHECKER.validate(plan, ROOT)

        plan = valid_plan()
        plan["cost_control"]["maximum_active_rehearsal_eks_environments"] = 2
        with self.assertRaisesRegex(ValueError, "Cost-control"):
            CHECKER.validate(plan, ROOT)

    def test_private_evidence_must_stay_outside_repository(self) -> None:
        plan = valid_plan(str(ROOT / "private-evidence"))
        with self.assertRaisesRegex(ValueError, "outside"):
            CHECKER.validate(plan, ROOT)


class AwsDevInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clusters = CHECKER.CLUSTERS
        self.empty_state = {
            "exists": False,
            "resource_blocks": 0,
            "resource_instances": 0,
            "contains_dev_eks_cluster": False,
        }

    def test_absent_environment_and_empty_state_are_ready(self) -> None:
        status, reason = PREFLIGHT.classify_inventory([], self.clusters, self.empty_state)
        self.assertEqual(status, "ready-for-separate-aws-dev-create-approval")
        self.assertIsNone(reason)

    def test_other_rehearsal_environment_blocks(self) -> None:
        status, reason = PREFLIGHT.classify_inventory(
            [self.clusters["aws_test"]], self.clusters, self.empty_state
        )
        self.assertEqual(status, "blocked-other-rehearsal-environment-active")
        self.assertIn("aws-test", reason or "")

    def test_existing_dev_requires_state_owned_resume_review(self) -> None:
        status, _ = PREFLIGHT.classify_inventory(
            [self.clusters["aws_dev"]], self.clusters, self.empty_state
        )
        self.assertEqual(status, "blocked-unmanaged-or-mismatched-aws-dev")

        managed = {
            "exists": True,
            "resource_blocks": 1,
            "resource_instances": 1,
            "contains_dev_eks_cluster": True,
        }
        status, _ = PREFLIGHT.classify_inventory(
            [self.clusters["aws_dev"]], self.clusters, managed
        )
        self.assertEqual(status, "blocked-existing-aws-dev-requires-resume-review")

    def test_partial_state_blocks_create(self) -> None:
        partial = {
            "exists": True,
            "resource_blocks": 1,
            "resource_instances": 2,
            "contains_dev_eks_cluster": False,
        }
        status, reason = PREFLIGHT.classify_inventory([], self.clusters, partial)
        self.assertEqual(status, "blocked-partial-aws-dev-state")
        self.assertIn("nonempty", reason or "")

    def test_state_summary_never_returns_resource_attributes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "terraform.tfstate"
            state_path.write_text(
                json.dumps(
                    {
                        "version": 4,
                        "resources": [
                            {
                                "type": "aws_eks_cluster",
                                "name": "this",
                                "instances": [
                                    {"attributes": {"endpoint": "private-value-not-for-output"}}
                                ],
                            }
                        ],
                    }
                )
            )
            summary = PREFLIGHT.summarize_state(state_path)
        self.assertEqual(summary["resource_instances"], 1)
        self.assertTrue(summary["contains_dev_eks_cluster"])
        self.assertNotIn("private-value-not-for-output", json.dumps(summary))

    def test_complete_ready_preflight_uses_mocked_read_only_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            private_root = Path(directory)
            evidence = private_root / "evidence"
            evidence.mkdir(mode=0o700)
            plan_path = private_root / "plan.json"
            plan_path.write_text(json.dumps(valid_plan(str(evidence))))
            plan_path.chmod(0o600)

            def fake_command(arguments: list[str]) -> str:
                if arguments[:4] == ["git", "-C", str(ROOT), "branch"]:
                    return "main"
                if arguments[:4] == ["git", "-C", str(ROOT), "status"]:
                    return ""
                if arguments[:4] == ["git", "-C", str(ROOT), "rev-parse"]:
                    return "f" * 40
                if arguments[:4] == ["git", "-C", str(ROOT), "merge-base"]:
                    return ""
                if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
                    return json.dumps({"Account": "123456789012"})
                if arguments[:3] == ["aws", "eks", "list-clusters"]:
                    return json.dumps({"clusters": []})
                raise AssertionError(f"Unexpected command: {arguments}")

            with (
                mock.patch.dict(
                    os.environ,
                    {"CONFIRM_AWS_DEV_PREFLIGHT": PREFLIGHT.CONFIRMATION},
                ),
                mock.patch.object(PREFLIGHT.shutil, "which", return_value="/fake"),
                mock.patch.object(
                    PREFLIGHT,
                    "summarize_state",
                    return_value=self.empty_state,
                ) as summarize_state,
            ):
                result, exit_code = PREFLIGHT.execute_preflight(
                    plan_path,
                    ROOT,
                    fake_command,
                )

        summarize_state.assert_called_once_with(ROOT / CHECKER.STATE_PATH)
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "ready-for-separate-aws-dev-create-approval")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["mutations_performed"], [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "scripts/execute-v0.11.9.3.6.1-aws-dev-live-rehearsal-create.py"
CREATE_TEMPLATE = ROOT / "delivery/examples/v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.json"
PREFLIGHT_TEMPLATE = ROOT / "delivery/examples/v0.11.9.3.5-aws-dev-live-rehearsal-plan.json"
SPEC = importlib.util.spec_from_file_location("aws_dev_create_executor", EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-dev create executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

CONTROL_PLANE = "f" * 40
NOW = datetime(2026, 9, 9, 4, 0, tzinfo=timezone.utc)


class Fixture:
    def __init__(self, parent: Path) -> None:
        self.private = parent / "private"
        self.evidence = self.private / "evidence"
        self.private.mkdir(mode=0o700, parents=True)
        self.evidence.mkdir(mode=0o700)
        self.create_plan_path = self.private / "create-plan.json"
        self.preflight_plan_path = self.private / "preflight-plan.json"
        self.preflight_result_path = self.private / "preflight-result.json"

        self.preflight_plan = json.loads(PREFLIGHT_TEMPLATE.read_text())
        self.preflight_plan.update(
            control_plane_commit=CONTROL_PLANE,
            review_reference="fresh-preflight-review-001",
            operator="SterlingAureum",
            recovery_owner="SterlingAureum",
            evidence_directory=str(self.evidence),
            aws_account_id="123456789012",
        )
        self.preflight_plan_path.write_text(json.dumps(self.preflight_plan, indent=2, sort_keys=True) + "\n")
        self.preflight_plan_path.chmod(0o600)

        self.preflight_result = {
            "status": "ready-for-separate-aws-dev-create-approval",
            "execution_authorized": False,
            "control_plane_commit": CONTROL_PLANE,
            "candidate_release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
            "aws_account_id": "123456789012",
            "aws_region": "us-east-1",
            "active_rehearsal_clusters": [],
            "terraform_state": {
                "exists": True,
                "resource_blocks": 0,
                "resource_instances": 0,
                "contains_dev_eks_cluster": False,
            },
            "blocked_reason": None,
            "checks_performed": [
                "private-plan-permissions",
                "clean-exact-main",
                "candidate-source-ancestry",
                "aws-dev-release-identity",
                "aws-caller-identity",
                "eks-rehearsal-cluster-inventory",
                "local-terraform-state-summary",
            ],
            "mutations_performed": [],
            "next_action": "review-separate-create-approval",
        }
        self.preflight_result_bytes = (
            json.dumps(self.preflight_result, indent=2, sort_keys=True) + "\n"
        ).encode()
        self.preflight_result_path.write_bytes(self.preflight_result_bytes)
        self.preflight_result_path.chmod(0o600)

        self.create_plan = json.loads(CREATE_TEMPLATE.read_text())
        self.create_plan.update(
            planned_control_plane_commit=CONTROL_PLANE,
            review_reference="create-review-001",
            operator="SterlingAureum",
            recovery_owner="SterlingAureum",
            evidence_directory=str(self.evidence),
            aws_account_id="123456789012",
        )
        self.create_plan["preflight"]["fresh_preflight_plan_sha256"] = hashlib.sha256(
            self.preflight_plan_path.read_bytes()
        ).hexdigest()
        self.create_plan["preflight"]["fresh_preflight_result_sha256"] = hashlib.sha256(
            self.preflight_result_bytes
        ).hexdigest()
        self.create_plan["infrastructure"]["terraform_vars_reviewed"] = True
        self.create_plan["infrastructure"]["owner_tag_reviewed"] = True
        self.create_plan["cost_control"].update(
            pricing_estimate_reference="reviewed-current-pricing-estimate-001",
            estimated_hourly_cost_usd=2.5,
            reviewed_session_budget_usd=25.0,
            planned_start_utc="2026-09-09T01:00:00Z",
            teardown_review_deadline_utc="2026-09-09T09:00:00Z",
        )
        self.write_create_plan()

    def write_create_plan(self) -> None:
        self.create_plan_path.write_text(json.dumps(self.create_plan, indent=2, sort_keys=True) + "\n")
        self.create_plan_path.chmod(0o600)

    @staticmethod
    def git_runner(arguments: list[str]) -> str:
        values = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): CONTROL_PLANE,
            ("rev-parse", "origin/main"): CONTROL_PLANE,
        }
        return values[tuple(arguments)]


class AwsDevCreateExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def verify(self, **kwargs):
        return MODULE.verify_inputs(
            self.fixture.create_plan_path,
            self.fixture.preflight_plan_path,
            self.fixture.preflight_result_path,
            ROOT,
            kwargs.get("git_runner", self.fixture.git_runner),
            kwargs.get("now", NOW),
        )

    def test_verify_accepts_exact_private_inputs_without_live_command(self) -> None:
        create_plan, result = self.verify()
        redacted = MODULE.redacted_verification(create_plan)
        self.assertEqual(result["status"], "ready-for-separate-aws-dev-create-approval")
        self.assertEqual(redacted["commands_executed"], [])
        self.assertFalse(redacted["execution_authorized"])
        self.assertNotIn("aws_account_id", redacted)

    def test_private_file_and_parent_modes_are_enforced(self) -> None:
        self.fixture.preflight_result_path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode must be 600"):
            self.verify()
        self.fixture.preflight_result_path.chmod(0o600)
        self.fixture.private.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "parent"):
            self.verify()

    def test_preflight_plan_and_result_hashes_are_enforced(self) -> None:
        self.fixture.preflight_plan_path.write_text(self.fixture.preflight_plan_path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "plan SHA-256"):
            self.verify()

        self.fixture = Fixture(Path(self.temp.name) / "second")
        self.fixture.preflight_result_path.write_bytes(self.fixture.preflight_result_bytes + b"\n")
        with self.assertRaisesRegex(ValueError, "result SHA-256"):
            self.verify()

    def test_preflight_ready_identity_and_empty_inventory_are_required(self) -> None:
        mutations = (
            ("status", "blocked"),
            ("control_plane_commit", "e" * 40),
            ("active_rehearsal_clusters", ["startup-devops-baseline-test"]),
            ("blocked_reason", "blocked"),
            ("mutations_performed", ["terraform plan"]),
        )
        for key, replacement in mutations:
            with self.subTest(key=key):
                fixture = Fixture(Path(self.temp.name) / key)
                fixture.preflight_result[key] = replacement
                fixture.preflight_result_bytes = (
                    json.dumps(fixture.preflight_result, indent=2, sort_keys=True) + "\n"
                ).encode()
                fixture.preflight_result_path.write_bytes(fixture.preflight_result_bytes)
                fixture.create_plan["preflight"]["fresh_preflight_result_sha256"] = hashlib.sha256(
                    fixture.preflight_result_bytes
                ).hexdigest()
                fixture.write_create_plan()
                with self.assertRaises(ValueError):
                    MODULE.verify_inputs(
                        fixture.create_plan_path,
                        fixture.preflight_plan_path,
                        fixture.preflight_result_path,
                        ROOT,
                        fixture.git_runner,
                        NOW,
                    )

    def test_clean_exact_main_is_required(self) -> None:
        def wrong_git(arguments: list[str]) -> str:
            if arguments == ["rev-parse", "origin/main"]:
                return "e" * 40
            return self.fixture.git_runner(arguments)

        with self.assertRaisesRegex(ValueError, "HEAD and origin/main"):
            self.verify(git_runner=wrong_git)

    def test_reviewed_time_window_is_enforced(self) -> None:
        for moment in (
            datetime(2026, 9, 9, 0, 59, tzinfo=timezone.utc),
            datetime(2026, 9, 9, 9, 0, tzinfo=timezone.utc),
        ):
            with self.subTest(moment=moment):
                with self.assertRaisesRegex(ValueError, "session window"):
                    self.verify(now=moment)

    def test_execution_requires_all_three_confirmations(self) -> None:
        base = {
            "CONFIRM_AWS_DEV_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            "CONFIRM_AWS_DEV_REHEARSAL_CREATE": MODULE.EXECUTION_CONFIRMATION,
            "CONFIRM_AWS_DEV_APPLY": MODULE.APPLY_CONFIRMATION,
        }
        for missing in tuple(base):
            with self.subTest(missing=missing):
                values = {key: value for key, value in base.items() if key != missing}
                with mock.patch.dict(os.environ, values, clear=True):
                    with self.assertRaisesRegex(ValueError, "Set CONFIRM"):
                        MODULE.execute(
                            self.fixture.create_plan_path,
                            self.fixture.preflight_plan_path,
                            self.fixture.preflight_result_path,
                            ROOT,
                            self.fixture.git_runner,
                            lambda _: self.fixture.preflight_result_bytes,
                            lambda _: 0,
                            NOW,
                        )

    def test_immediate_preflight_must_be_byte_identical(self) -> None:
        environment = {
            "CONFIRM_AWS_DEV_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            "CONFIRM_AWS_DEV_REHEARSAL_CREATE": MODULE.EXECUTION_CONFIRMATION,
            "CONFIRM_AWS_DEV_APPLY": MODULE.APPLY_CONFIRMATION,
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "Immediate preflight"):
                MODULE.execute(
                    self.fixture.create_plan_path,
                    self.fixture.preflight_plan_path,
                    self.fixture.preflight_result_path,
                    ROOT,
                    self.fixture.git_runner,
                    lambda _: self.fixture.preflight_result_bytes + b"\n",
                    lambda _: 0,
                    NOW,
                )

    def test_successful_execute_stops_before_gitops(self) -> None:
        calls: list[str] = []
        environment = {
            "CONFIRM_AWS_DEV_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            "CONFIRM_AWS_DEV_REHEARSAL_CREATE": MODULE.EXECUTION_CONFIRMATION,
            "CONFIRM_AWS_DEV_APPLY": MODULE.APPLY_CONFIRMATION,
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            result = MODULE.execute(
                self.fixture.create_plan_path,
                self.fixture.preflight_plan_path,
                self.fixture.preflight_result_path,
                ROOT,
                self.fixture.git_runner,
                lambda _: self.fixture.preflight_result_bytes,
                lambda _: calls.append("apply") or 0,
                NOW,
            )
        self.assertEqual(calls, ["apply"])
        self.assertEqual(result["status"], "aws-dev-infrastructure-created-api-ready")
        self.assertFalse(result["gitops_bootstrapped"])
        self.assertFalse(result["runtime_qualified"])
        self.assertEqual(result["next_action"], "review-separate-gitops-bootstrap")

    def test_apply_failure_preserves_stop_boundary(self) -> None:
        environment = {
            "CONFIRM_AWS_DEV_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            "CONFIRM_AWS_DEV_REHEARSAL_CREATE": MODULE.EXECUTION_CONFIRMATION,
            "CONFIRM_AWS_DEV_APPLY": MODULE.APPLY_CONFIRMATION,
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(MODULE.CommandFailure, "preserve state and evidence"):
                MODULE.execute(
                    self.fixture.create_plan_path,
                    self.fixture.preflight_plan_path,
                    self.fixture.preflight_result_path,
                    ROOT,
                    self.fixture.git_runner,
                    lambda _: self.fixture.preflight_result_bytes,
                    lambda _: 2,
                    NOW,
                )


if __name__ == "__main__":
    unittest.main()

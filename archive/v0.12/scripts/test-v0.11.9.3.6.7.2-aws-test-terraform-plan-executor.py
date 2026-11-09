#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = (
    ROOT / "scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py"
)
SPEC = importlib.util.spec_from_file_location("aws_test_plan_executor", EXECUTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load aws-test plan executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ACCOUNT = "123456789012"
MAIN = "f" * 40
NOW = datetime(2026, 9, 12, 2, 0, 0, tzinfo=timezone.utc)


def terraform_document(actions: list[str] | None = None) -> dict:
    return {
        "format_version": "1.2",
        "variables": {
            "environment": {"value": "test"},
            "project_name": {"value": "startup-devops-baseline"},
            "aws_region": {"value": "us-east-1"},
            "eks_node_min_size": {"value": 4},
            "eks_node_desired_size": {"value": 4},
            "eks_node_max_size": {"value": 4},
            "eks_public_access_cidrs": {"value": ["8.8.8.8/32"]},
            "enable_github_actions_runtime_identity": {"value": False},
            "github_actions_runtime_role_arn": {"value": None},
        },
        "resource_changes": [
            {
                "address": "module.eks.aws_eks_cluster.this",
                "type": "aws_eks_cluster",
                "change": {
                    "actions": ["create"],
                    "after": {
                        "name": "startup-devops-baseline-test",
                        "tags": {"Environment": "test"},
                    },
                },
            },
            {
                "address": "module.vpc.aws_vpc.this",
                "type": "aws_vpc",
                "change": {
                    "actions": actions or ["create"],
                    "after": {"tags_all": {"Environment": "test"}},
                },
            },
        ],
    }


def preflight() -> dict:
    return {
        "account_id_emitted": False,
        "account_verified": True,
        "active_rehearsal_environment_count": 0,
        "aws_dev_residual_cost_audit_evidence_sha256": (
            "d73e4b5107b4c99ae1feebd2a34197040e4d0f50b6c6ccbecdf951bbe1da25e9"
        ),
        "aws_prod_release_held": True,
        "aws_region": "us-east-1",
        "aws_test_created": False,
        "aws_test_promotion_evidence_sha256": (
            "4977ddfb21738530681ce671ebaf9d71d4132e4e81c9ea1135e4b3527c27a96e"
        ),
        "control_plane_commit": MAIN,
        "dev_test_release_equal": True,
        "environment_creation_authorized": False,
        "gitops_bootstrap_executed": False,
        "legacy_apply_wrapper_invoked": False,
        "legacy_apply_wrapper_sha256": (
            "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114"
        ),
        "mutation_executed": False,
        "next_action": "review-private-aws-test-create-plan-design",
        "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
        "status": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
        "target_environment": "aws-test",
        "terraform_apply_executed": False,
        "terraform_backend_kind": "local",
        "terraform_command_executed": False,
        "terraform_plan_executed": False,
        "terraform_state_exists": True,
        "terraform_state_path_emitted": False,
        "terraform_state_resource_block_count": 0,
        "terraform_state_resource_instance_count": 0,
        "traffic_generated": False,
    }


class AwsTestTerraformPlanExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repository = root / "repository"
        self.repository.mkdir(mode=0o700)
        self.private = root / "private"
        self.private.mkdir(mode=0o700)
        self.output = self.private / "terraform-plan-output"
        for relative in (
            MODULE.DESIGN_CONTRACT,
            MODULE.DESIGN_TEMPLATE,
            MODULE.DESIGN_CHECKER_RELATIVE,
            MODULE.PREFLIGHT_RELATIVE,
            "infra/terraform/aws/environments/test/backend.tf",
            "delivery/profiles/aws-test-observability-qualification.tfvars",
            "scripts/apply-aws-test.sh",
        ):
            source = ROOT / relative
            target = self.repository / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (self.repository / "infra/terraform/aws/environments/test").mkdir(
            parents=True, exist_ok=True
        )
        self.tfvars = (
            self.repository
            / "infra/terraform/aws/environments/test/terraform.tfvars"
        )
        self.tfvars.write_text('additional_tags = { Owner = "fixture-owner" }\n')

        self.preflight = self.private / "fresh-preflight.json"
        self.preflight.write_text(json.dumps(preflight(), sort_keys=True) + "\n")
        self.preflight.chmod(0o600)
        template = json.loads((ROOT / MODULE.DESIGN_TEMPLATE).read_text())
        template.update(
            planned_control_plane_commit=MAIN,
            review_reference="review-v0.11.9.3.6.7.2-plan-001",
            operator="SterlingAureum",
            recovery_owner="SterlingAureum",
            private_plan_bundle_directory=str(self.output),
            aws_account_id=ACCOUNT,
            management_ipv4="8.8.8.8",
            fresh_preflight_result_sha256=hashlib.sha256(
                self.preflight.read_bytes()
            ).hexdigest(),
            local_variable_file_sha256=hashlib.sha256(
                self.tfvars.read_bytes()
            ).hexdigest(),
        )
        template["cost_control"].update(
            pricing_estimate_reference="reviewed-current-pricing-estimate-001",
            estimated_hourly_cost_usd=2.5,
            reviewed_session_budget_usd=25.0,
            planned_start_utc="2026-09-12T01:00:00Z",
            teardown_review_deadline_utc="2026-09-12T09:00:00Z",
        )
        self.plan = self.private / "private-plan.json"
        self.plan.write_text(json.dumps(template, indent=2) + "\n")
        self.plan.chmod(0o600)
        self.calls: list[tuple[list[str], dict[str, str], int]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git_runner(self, arguments: list[str]) -> str:
        if arguments == ["branch", "--show-current"]:
            return "main"
        if arguments == ["status", "--porcelain"]:
            return ""
        if arguments in (["rev-parse", "HEAD"], ["rev-parse", "origin/main"]):
            return MAIN
        if arguments == [
            "merge-base",
            "--is-ancestor",
            MODULE.IMPLEMENTATION_BASELINE,
            MAIN,
        ]:
            return ""
        raise AssertionError(f"Unexpected Git command: {arguments}")

    def runner(
        self, arguments: list[str], environment: dict[str, str], timeout: int
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append((arguments, environment, timeout))
        if arguments[0] == os.sys.executable:
            return subprocess.CompletedProcess(
                arguments, 0, self.preflight.read_bytes(), b""
            )
        if arguments[0] == "aws":
            return subprocess.CompletedProcess(
                arguments,
                254,
                b"",
                b"An error occurred (ResourceNotFoundException) during DescribeSecret",
            )
        if arguments[0] == "terraform" and "plan" in arguments:
            output = next(value.removeprefix("-out=") for value in arguments if value.startswith("-out="))
            Path(output).write_bytes(b"private-binary-plan")
            return subprocess.CompletedProcess(arguments, 0, b"plan stdout", b"")
        if arguments[0] == "terraform" and "show" in arguments and "-json" in arguments:
            return subprocess.CompletedProcess(
                arguments,
                0,
                json.dumps(terraform_document()).encode(),
                b"",
            )
        if arguments[0] == "terraform" and "show" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b"human-readable plan\n", b"")
        if arguments[0] == "terraform" and "init" in arguments:
            return subprocess.CompletedProcess(arguments, 0, b"init stdout", b"")
        raise AssertionError(f"Unexpected command: {arguments}")

    def environment(self, **extra: str):
        values = {
            "AWS_ENVIRONMENT": "aws-test",
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_TEST_CREATE_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            "CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION": MODULE.PLAN_CONFIRMATION,
        }
        values.update(extra)
        return mock.patch.dict(os.environ, values, clear=True)

    def verify(self, now: datetime = NOW):
        return MODULE.verify_inputs(
            self.plan,
            self.preflight,
            self.repository,
            self.git_runner,
            now,
        )

    def execute(self, runner=None, now: datetime = NOW):
        with self.environment():
            return MODULE.execute(
                self.plan,
                self.preflight,
                self.repository,
                self.git_runner,
                runner or self.runner,
                now,
            )

    def test_verify_is_zero_command_and_keeps_plan_blocked(self) -> None:
        plan, result, output, remaining = self.verify()
        redacted = MODULE.redacted_verification(
            plan, self.plan, self.preflight, remaining
        )
        self.assertEqual(
            redacted["status"], "aws-test-terraform-plan-executor-inputs-verified"
        )
        self.assertEqual(result["control_plane_commit"], MAIN)
        self.assertEqual(output, self.output)
        self.assertEqual(redacted["commands_executed"], [])
        self.assertFalse(redacted["terraform_plan_authorized"])
        self.assertFalse(redacted["terraform_plan_executed"])
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_execute_produces_private_create_only_plan_and_never_applies(self) -> None:
        result = self.execute()
        self.assertEqual(result["status"], "aws-test-create-only-terraform-plan-produced")
        self.assertEqual(result["action_counts"], {"create": 2, "read": 0, "no-op": 0})
        self.assertTrue(result["terraform_plan_executed"])
        self.assertFalse(result["terraform_apply_executed"])
        self.assertFalse(result["environment_created"])
        self.assertTrue(result["secret_metadata_absent_before_and_after"])
        serialized = json.dumps(result)
        self.assertNotIn(ACCOUNT, serialized)
        self.assertNotIn("8.8.8.8", serialized)
        self.assertNotIn(str(self.output), serialized)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for path in self.output.iterdir():
            if path.is_file():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        commands = [arguments for arguments, _, _ in self.calls]
        self.assertTrue(any("init" in arguments for arguments in commands))
        self.assertTrue(any("plan" in arguments for arguments in commands))
        self.assertFalse(any("apply" in arguments for arguments in commands))
        self.assertEqual(sum(arguments[0] == "aws" for arguments in commands), 2)

    def test_environment_is_sanitized(self) -> None:
        with self.environment(
            TF_VAR_environment="prod",
            TF_CLI_ARGS="-destroy",
            AWS_ENDPOINT_URL="https://example.invalid",
            AWS_PROFILE="reviewed-profile",
        ):
            MODULE.execute(
                self.plan,
                self.preflight,
                self.repository,
                self.git_runner,
                self.runner,
                NOW,
            )
        for _, environment, _ in self.calls:
            self.assertNotIn("TF_VAR_environment", environment)
            self.assertNotIn("TF_CLI_ARGS", environment)
            self.assertNotIn("AWS_ENDPOINT_URL", environment)
            self.assertEqual(environment.get("AWS_PROFILE"), "reviewed-profile")
            self.assertEqual(environment.get("AWS_DEFAULT_REGION"), "us-east-1")

    def test_missing_confirmation_stops_before_commands(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "AWS_ENVIRONMENT": "aws-test",
                "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
                "CONFIRM_AWS_TEST_CREATE_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            },
            clear=True,
        ), self.assertRaisesRegex(ValueError, "PLAN_EXECUTION"):
            MODULE.execute(
                self.plan,
                self.preflight,
                self.repository,
                self.git_runner,
                self.runner,
                NOW,
            )
        self.assertEqual(self.calls, [])

    def test_immediate_preflight_mismatch_stops_before_output(self) -> None:
        def runner(arguments, environment, timeout):
            return subprocess.CompletedProcess(arguments, 0, b"{}\n", b"")

        with self.environment(), self.assertRaisesRegex(ValueError, "bytes changed"):
            MODULE.execute(
                self.plan,
                self.preflight,
                self.repository,
                self.git_runner,
                runner,
                NOW,
            )
        self.assertFalse(self.output.exists())

    def test_destructive_plan_stops_and_preserves_private_bundle(self) -> None:
        def runner(arguments, environment, timeout):
            if arguments[0] == "terraform" and "show" in arguments and "-json" in arguments:
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    json.dumps(terraform_document(["delete", "create"])).encode(),
                    b"",
                )
            return self.runner(arguments, environment, timeout)

        with self.assertRaisesRegex(ValueError, "rejects"):
            self.execute(runner)
        self.assertTrue(self.output.is_dir())
        self.assertTrue((self.output / "aws-test-create.tfplan").is_file())
        self.assertFalse(any("apply" in call[0] for call in self.calls))

    def test_secret_presence_or_lookup_failure_stops_before_terraform(self) -> None:
        for result in (
            subprocess.CompletedProcess([], 0, b'{"Name":"present"}', b""),
            subprocess.CompletedProcess([], 254, b"", b"AccessDenied"),
        ):
            with self.subTest(returncode=result.returncode):
                if self.output.exists():
                    shutil.rmtree(self.output)
                calls = []

                def runner(arguments, environment, timeout):
                    calls.append(arguments)
                    if arguments[0] == os.sys.executable:
                        return subprocess.CompletedProcess(
                            arguments, 0, self.preflight.read_bytes(), b""
                        )
                    if arguments[0] == "aws":
                        return subprocess.CompletedProcess(
                            arguments,
                            result.returncode,
                            result.stdout,
                            result.stderr,
                        )
                    raise AssertionError("Terraform should not run")

                with self.assertRaises((ValueError, MODULE.CommandFailure)):
                    self.execute(runner)
                self.assertFalse(any(arguments[0] == "terraform" for arguments in calls))

    def test_drift_time_and_existing_output_fail_closed(self) -> None:
        self.tfvars.write_text(self.tfvars.read_text() + "# changed\n")
        with self.assertRaisesRegex(ValueError, "tfvars fingerprint"):
            self.verify()
        self.tfvars.write_text('additional_tags = { Owner = "fixture-owner" }\n')

        with self.assertRaisesRegex(ValueError, "session window"):
            self.verify(datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc))

        self.output.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.verify()

    def test_preflight_semantic_drift_and_exact_main_mismatch_fail(self) -> None:
        changed = preflight()
        changed["active_rehearsal_environment_count"] = 1
        self.preflight.write_text(json.dumps(changed, sort_keys=True) + "\n")
        self.preflight.chmod(0o600)
        plan = json.loads(self.plan.read_text())
        plan["fresh_preflight_result_sha256"] = hashlib.sha256(
            self.preflight.read_bytes()
        ).hexdigest()
        self.plan.write_text(json.dumps(plan, indent=2) + "\n")
        self.plan.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "active_rehearsal"):
            self.verify()

        self.preflight.write_text(json.dumps(preflight(), sort_keys=True) + "\n")
        self.preflight.chmod(0o600)
        plan["fresh_preflight_result_sha256"] = hashlib.sha256(
            self.preflight.read_bytes()
        ).hexdigest()
        self.plan.write_text(json.dumps(plan, indent=2) + "\n")
        self.plan.chmod(0o600)

        def git_runner(arguments):
            if arguments == ["rev-parse", "origin/main"]:
                return "e" * 40
            return self.git_runner(arguments)

        with self.assertRaisesRegex(ValueError, "HEAD and origin"):
            MODULE.verify_inputs(
                self.plan,
                self.preflight,
                self.repository,
                git_runner,
                NOW,
            )


if __name__ == "__main__":
    unittest.main()

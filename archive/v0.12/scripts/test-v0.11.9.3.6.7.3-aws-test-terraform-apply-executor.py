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
EXECUTOR = ROOT / "scripts/execute-v0.11.9.3.6.7.3-aws-test-terraform-apply.py"
SPEC = importlib.util.spec_from_file_location("aws_test_apply_executor", EXECUTOR)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load apply executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ACCOUNT = "123456789012"
MAIN = "f" * 40
NOW = datetime(2026, 9, 12, 2, 0, 0, tzinfo=timezone.utc)


def plan_document(actions: list[str] | None = None) -> dict:
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
                    "after": {"name": "startup-devops-baseline-test", "tags": {"Environment": "test"}},
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
        "aws_dev_residual_cost_audit_evidence_sha256": "d73e4b5107b4c99ae1feebd2a34197040e4d0f50b6c6ccbecdf951bbe1da25e9",
        "aws_prod_release_held": True,
        "aws_region": "us-east-1",
        "aws_test_created": False,
        "aws_test_promotion_evidence_sha256": "4977ddfb21738530681ce671ebaf9d71d4132e4e81c9ea1135e4b3527c27a96e",
        "control_plane_commit": MAIN,
        "dev_test_release_equal": True,
        "environment_creation_authorized": False,
        "gitops_bootstrap_executed": False,
        "legacy_apply_wrapper_invoked": False,
        "legacy_apply_wrapper_sha256": "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114",
        "mutation_executed": False,
        "next_action": "review-private-aws-test-create-plan-design",
        "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
        "status": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
        "target_environment": "aws-test",
        "terraform_apply_executed": False,
        "terraform_backend_kind": "local",
        "terraform_command_executed": False,
        "terraform_plan_executed": False,
        "terraform_state_exists": False,
        "terraform_state_path_emitted": False,
        "terraform_state_resource_block_count": 0,
        "terraform_state_resource_instance_count": 0,
        "traffic_generated": False,
    }


class AwsTestApplyExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.repo.mkdir(mode=0o700)
        self.private = base / "private"
        self.private.mkdir(mode=0o700)
        self.bundle = self.private / "plan-bundle"
        self.bundle.mkdir(mode=0o700)
        (self.bundle / "terraform-data").mkdir(mode=0o700)
        self.output = self.private / "apply-output"
        self.state = self.repo / MODULE.STATE_RELATIVE
        self.state.parent.mkdir(parents=True)
        self.tfvars = self.state.parent / "terraform.tfvars"
        self.tfvars.write_text("# private fixture\n")

        self.preflight = self.private / "preflight.json"
        self.preflight.write_text(json.dumps(preflight(), sort_keys=True) + "\n")
        self.preflight.chmod(0o600)
        self.plan = {
            "planned_control_plane_commit": MAIN,
            "aws_account_id": ACCOUNT,
            "management_ipv4": "8.8.8.8",
            "candidate": {"release_id": "demo-api-cf0a6bcbc466-cdffd3d71763"},
            "fresh_preflight_result_sha256": self.digest(self.preflight),
            "private_plan_bundle_directory": str(self.bundle),
            "local_variable_file_sha256": self.digest(self.tfvars),
            "cost_control": {
                "teardown_review_deadline_utc": "2026-09-12T09:00:00Z",
            },
            "infrastructure": {
                "terraform_directory": "infra/terraform/aws/environments/test",
                "local_variable_file_path": "infra/terraform/aws/environments/test/terraform.tfvars",
                "backend_declaration_path": "infra/terraform/aws/environments/test/backend.tf",
                "backend_declaration_sha256": "a" * 64,
                "qualification_profile_path": "delivery/profiles/profile.tfvars",
                "qualification_profile_sha256": "b" * 64,
                "legacy_apply_wrapper": "scripts/apply-aws-test.sh",
                "legacy_apply_wrapper_sha256": "c" * 64,
            },
        }
        self.private_plan = self.private / "private-plan.json"
        self.private_plan.write_text(json.dumps(self.plan, indent=2) + "\n")
        self.private_plan.chmod(0o600)
        self.document = plan_document()
        self.plan_json = self.bundle / "terraform-plan.json"
        self.plan_json.write_text(json.dumps(self.document, sort_keys=True) + "\n")
        self.plan_json.chmod(0o600)
        self.gate = MODULE.PLAN_GATE.validate(self.document, ACCOUNT, "8.8.8.8")
        self.gate_path = self.bundle / "plan-gate.json"
        self.gate_path.write_text(json.dumps(self.gate, indent=2, sort_keys=True) + "\n")
        self.gate_path.chmod(0o600)
        for name, content in (
            ("aws-test-create.tfplan", b"fresh-reviewed-binary-plan"),
            ("terraform-plan.txt", b"reviewed text plan\n"),
        ):
            path = self.bundle / name
            path.write_bytes(content)
            path.chmod(0o600)
        self.record_path = self.bundle / "plan-record.json"
        self.write_record()
        self.calls: list[list[str]] = []
        self.secret_calls = 0

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_record(self, **changes) -> None:
        record = {
            "schema_version": "v0.11.9.3.6.7.2",
            "account_id": ACCOUNT,
            "control_plane_commit": MAIN,
            "release_id": "demo-api-cf0a6bcbc466-cdffd3d71763",
            "management_cidr": "8.8.8.8/32",
            "created_at_utc": "2026-09-12T01:30:00Z",
            "expires_at_utc": "2026-09-12T03:00:00Z",
            "fresh_preflight_sha256": self.digest(self.preflight),
            "private_plan_sha256": self.digest(self.private_plan),
            "qualification_profile_sha256": "b" * 64,
            "local_variable_file_sha256": self.digest(self.tfvars),
            "binary_plan_sha256": self.digest(self.bundle / "aws-test-create.tfplan"),
            "terraform_plan_json_sha256": self.digest(self.plan_json),
            "terraform_plan_text_sha256": self.digest(self.bundle / "terraform-plan.txt"),
            "plan_gate_sha256": self.digest(self.gate_path),
            "action_counts": self.gate["action_counts"],
            "resource_change_count": self.gate["resource_change_count"],
            "secret_metadata_absent_before_and_after": True,
            "terraform_apply_executed": False,
            "environment_created": False,
        }
        record.update(changes)
        self.record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        self.record_path.chmod(0o600)

    def git_runner(self, args: list[str]) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["status", "--porcelain"]:
            return ""
        if args in (["rev-parse", "HEAD"], ["rev-parse", "origin/main"]):
            return MAIN
        if args == ["merge-base", "--is-ancestor", MODULE.IMPLEMENTATION_BASELINE, MAIN]:
            return ""
        raise AssertionError(f"Unexpected git command: {args}")

    def runner(self, args, environment, timeout):
        self.calls.append(args)
        if args[0] == os.sys.executable:
            return subprocess.CompletedProcess(args, 0, self.preflight.read_bytes(), b"")
        if args[0] == "terraform" and "show" in args:
            return subprocess.CompletedProcess(args, 0, self.plan_json.read_bytes(), b"")
        if args[0] == "terraform" and "apply" in args:
            self.state.write_text(json.dumps({
                "version": 4,
                "resources": [
                    {"instances": [{}]}, {"instances": [{}]},
                ],
            }))
            return subprocess.CompletedProcess(args, 0, b"apply complete", b"")
        if args[0] == "terraform" and "state" in args:
            return subprocess.CompletedProcess(
                args, 0,
                b"module.eks.aws_eks_cluster.this\nmodule.vpc.aws_vpc.this\n", b"",
            )
        if args[0] == "aws" and "secretsmanager" in args:
            self.secret_calls += 1
            if self.secret_calls == 1:
                return subprocess.CompletedProcess(
                    args, 254, b"", b"An error occurred (ResourceNotFoundException)",
                )
            return subprocess.CompletedProcess(args, 0, b'{"Name":"redacted"}', b"")
        if args[0] == "aws" and "describe-cluster" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps({
                "cluster": {
                    "name": "startup-devops-baseline-test",
                    "status": "ACTIVE",
                    "resourcesVpcConfig": {"publicAccessCidrs": ["8.8.8.8/32"]},
                }
            }).encode(), b"")
        raise AssertionError(f"Unexpected command: {args}")

    def environment(self, **extra):
        values = {
            "AWS_ENVIRONMENT": "aws-test",
            "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            "CONFIRM_AWS_TEST_CREATE_PREFLIGHT": MODULE.PREFLIGHT_CONFIRMATION,
            "CONFIRM_AWS_TEST_TERRAFORM_APPLY_EXECUTION": MODULE.APPLY_CONFIRMATION,
        }
        values.update(extra)
        return mock.patch.dict(os.environ, values, clear=True)

    def verify(self, now=NOW):
        with mock.patch.object(MODULE.DESIGN, "validate"), mock.patch.object(MODULE, "require_fingerprint"):
            return MODULE.verify_inputs(
                self.private_plan, self.preflight, self.bundle, self.output,
                self.repo, self.git_runner, now,
            )

    def execute(self, runner=None, now=NOW):
        with self.environment(), mock.patch.object(MODULE.DESIGN, "validate"), mock.patch.object(MODULE, "require_fingerprint"):
            return MODULE.execute(
                self.private_plan, self.preflight, self.bundle, self.output,
                self.repo, self.git_runner, runner or self.runner, now,
            )

    def test_verify_is_local_only_and_keeps_apply_blocked(self) -> None:
        context = self.verify()
        result = MODULE.redacted_verification(context, self.private_plan, self.preflight, self.bundle)
        self.assertEqual(result["status"], "aws-test-terraform-apply-executor-inputs-verified")
        self.assertEqual(result["commands_executed"], [])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(self.output.exists())
        self.assertEqual(self.calls, [])

    def test_execute_applies_exact_saved_plan_once_and_stops_before_gitops(self) -> None:
        result = self.execute()
        self.assertEqual(result["status"], "aws-test-reviewed-saved-plan-applied")
        self.assertTrue(result["terraform_apply_executed"])
        self.assertTrue(result["environment_created"])
        self.assertFalse(result["terraform_plan_executed"])
        self.assertFalse(result["gitops_bootstrap_executed"])
        commands = [" ".join(args) for args in self.calls]
        self.assertEqual(sum("terraform" in cmd and " apply " in f" {cmd} " for cmd in commands), 1)
        self.assertFalse(any(" plan " in f" {cmd} " or "destroy" in cmd for cmd in commands))
        self.assertFalse(any(args[0] in {"kubectl", "argocd"} for args in self.calls))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        for path in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        serialized = json.dumps(result)
        self.assertNotIn(ACCOUNT, serialized)
        self.assertNotIn("8.8.8.8", serialized)
        self.assertNotIn(str(self.bundle), serialized)

    def test_expired_plan_and_historical_plan_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "expired"):
            self.verify(datetime(2026, 9, 12, 3, 1, tzinfo=timezone.utc))
        self.write_record(binary_plan_sha256=MODULE.OLD_BINARY_PLAN_SHA256)
        with self.assertRaisesRegex(ValueError, "Expired"):
            self.verify()

    def test_hash_or_gate_drift_rejects_before_commands(self) -> None:
        (self.bundle / "terraform-plan.txt").write_text("changed\n")
        (self.bundle / "terraform-plan.txt").chmod(0o600)
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            self.verify()
        self.assertEqual(self.calls, [])

    def test_missing_or_polluted_confirmation_rejects_before_output(self) -> None:
        with self.environment(CONFIRM_AWS_TEST_TERRAFORM_APPLY_EXECUTION=""), mock.patch.object(MODULE.DESIGN, "validate"), mock.patch.object(MODULE, "require_fingerprint"), self.assertRaisesRegex(ValueError, "Apply confirmation"):
            MODULE.execute(
                self.private_plan, self.preflight, self.bundle, self.output,
                self.repo, self.git_runner, self.runner, NOW,
            )
        self.assertFalse(self.output.exists())
        with self.environment(CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION="polluted"), mock.patch.object(MODULE.DESIGN, "validate"), mock.patch.object(MODULE, "require_fingerprint"), self.assertRaisesRegex(ValueError, "must be unset"):
            MODULE.execute(
                self.private_plan, self.preflight, self.bundle, self.output,
                self.repo, self.git_runner, self.runner, NOW,
            )
        self.assertFalse(self.output.exists())

    def test_immediate_preflight_or_secret_drift_stops_before_apply(self) -> None:
        def changed_preflight(args, environment, timeout):
            self.calls.append(args)
            if args[0] == os.sys.executable:
                return subprocess.CompletedProcess(args, 0, b"{}\n", b"")
            raise AssertionError("No later command allowed")

        with self.assertRaisesRegex(ValueError, "bytes changed"):
            self.execute(changed_preflight)
        self.assertFalse(any("apply" in args for args in self.calls))

    def test_saved_plan_show_drift_stops_before_apply(self) -> None:
        def changed_show(args, environment, timeout):
            if args[0] == "terraform" and "show" in args:
                return subprocess.CompletedProcess(args, 0, b"{}", b"")
            return self.runner(args, environment, timeout)

        with self.assertRaisesRegex(ValueError, "show bytes"):
            self.execute(changed_show)
        self.assertFalse(any(args[0] == "terraform" and "apply" in args for args in self.calls))

    def test_apply_failure_is_not_retried_and_private_evidence_survives(self) -> None:
        def failed_apply(args, environment, timeout):
            if args[0] == "terraform" and "apply" in args:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 1, b"partial", b"failed")
            return self.runner(args, environment, timeout)

        with self.assertRaisesRegex(MODULE.CommandFailure, "preserve"):
            self.execute(failed_apply)
        apply_calls = [args for args in self.calls if args[0] == "terraform" and "apply" in args]
        self.assertEqual(len(apply_calls), 1)
        self.assertTrue((self.output / "terraform-apply.stdout").is_file())
        self.assertTrue((self.output / "terraform-apply.stderr").is_file())

    def test_post_apply_state_or_cluster_drift_fails_closed(self) -> None:
        def bad_state(args, environment, timeout):
            if args[0] == "terraform" and "state" in args:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, b"module.eks.aws_eks_cluster.this\n", b"")
            return self.runner(args, environment, timeout)

        with self.assertRaisesRegex(ValueError, "missing"):
            self.execute(bad_state)
        self.assertEqual(sum(args[0] == "terraform" and "apply" in args for args in self.calls), 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts/preflight-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py"
EXECUTOR_PATH = ROOT / "scripts/execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight_module = load("residual_preflight", PREFLIGHT_PATH)
executor_module = load("residual_executor", EXECUTOR_PATH)
COMMIT = "c876331f1191d489d2bf369047ec68990dac3885"
ACCOUNT = "123456789012"
NOW = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)


def successful_runner(arguments: list[str]) -> str:
    command = " ".join(arguments)
    if command == "git branch --show-current":
        return "main"
    if command == "git status --porcelain":
        return ""
    if command in ("git rev-parse HEAD", "git rev-parse origin/main"):
        return COMMIT
    if command == "aws sts get-caller-identity --output json":
        return json.dumps({"Account": ACCOUNT})
    if command == "aws eks list-clusters --region us-east-1 --output json":
        return json.dumps({"clusters": []})
    if command.endswith(" state list") and command.startswith("terraform -chdir="):
        return ""
    if command == "aws s3api list-buckets --output json":
        return json.dumps({"Buckets": []})
    if command.startswith("aws secretsmanager list-secrets "):
        return json.dumps({
            "SecretList": [{
                "Name": "startup-devops-baseline-dev/demo-api/postgresql",
                "DeletedDate": "2026-09-11T07:00:00Z",
            }]
        })
    raise AssertionError(f"Unexpected command: {command}")


def reviewed_result() -> dict[str, object]:
    return {
        "status": "aws-dev-residual-cost-audit-preflight-ready-for-separate-approval",
        "control_plane_commit": COMMIT,
        "teardown_evidence_sha256": preflight_module.TEARDOWN_EVIDENCE_SHA256,
        "audit_entrypoint_sha256": preflight_module.AUDIT_SHA256,
        "aws_region": "us-east-1",
        "account_verified": True,
        "account_id_emitted": False,
        "active_rehearsal_environment_count": 0,
        "terraform_backend_readable": True,
        "terraform_state_resource_count": 0,
        "backup_bucket_absent": True,
        "secret_live_value_absent": True,
        "secret_tombstone_present": True,
        "full_audit_executed": False,
        "mutation_executed": False,
        "execution_authorized": False,
        "aws_test_created": False,
        "next_action": "review-preflight-before-separate-read-only-audit-approval",
    }


class PreflightTests(unittest.TestCase):
    def environment(self):
        return mock.patch.dict(
            os.environ,
            {
                "AWS_ENVIRONMENT": "aws-dev",
                "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
                "CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_PREFLIGHT": preflight_module.CONFIRMATION,
            },
            clear=True,
        )

    def test_success_is_redacted_and_read_only(self):
        with self.environment():
            result = preflight_module.execute(
                COMMIT, successful_runner, which=lambda _command: "/mock"
            )
        self.assertEqual(result, reviewed_result())
        self.assertNotIn(ACCOUNT, json.dumps(result))

    def test_wrong_account_fails_closed(self):
        def runner(arguments: list[str]) -> str:
            if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
                return json.dumps({"Account": "999999999999"})
            return successful_runner(arguments)

        with self.environment(), self.assertRaisesRegex(ValueError, "account"):
            preflight_module.execute(COMMIT, runner, which=lambda _command: "/mock")

    def test_active_rehearsal_environment_is_rejected(self):
        def runner(arguments: list[str]) -> str:
            if arguments[:3] == ["aws", "eks", "list-clusters"]:
                return json.dumps({"clusters": [preflight_module.TEST_CLUSTER]})
            return successful_runner(arguments)

        with self.environment(), self.assertRaisesRegex(ValueError, "No rehearsal"):
            preflight_module.execute(COMMIT, runner, which=lambda _command: "/mock")

    def test_terraform_backend_error_is_not_empty_state(self):
        def runner(arguments: list[str]) -> str:
            if arguments[0] == "terraform":
                raise RuntimeError("mock backend failure")
            return successful_runner(arguments)

        with self.environment(), self.assertRaisesRegex(RuntimeError, "backend failure"):
            preflight_module.execute(COMMIT, runner, which=lambda _command: "/mock")

    def test_backup_bucket_presence_is_rejected(self):
        def runner(arguments: list[str]) -> str:
            if arguments[:3] == ["aws", "s3api", "list-buckets"]:
                return json.dumps({
                    "Buckets": [{
                        "Name": f"startup-devops-baseline-dev-{ACCOUNT}-us-east-1-cnpg"
                    }]
                })
            return successful_runner(arguments)

        with self.environment(), self.assertRaisesRegex(ValueError, "bucket"):
            preflight_module.execute(COMMIT, runner, which=lambda _command: "/mock")

    def test_live_secret_is_rejected(self):
        def runner(arguments: list[str]) -> str:
            if arguments[:3] == ["aws", "secretsmanager", "list-secrets"]:
                return json.dumps({
                    "SecretList": [{
                        "Name": "startup-devops-baseline-dev/demo-api/postgresql"
                    }]
                })
            return successful_runner(arguments)

        with self.environment(), self.assertRaisesRegex(ValueError, "not scheduled"):
            preflight_module.execute(COMMIT, runner, which=lambda _command: "/mock")

    def test_destructive_confirmation_is_rejected(self):
        with self.environment(), mock.patch.dict(
            os.environ, {"CONFIRM_AWS_ENVIRONMENT_DESTROY": "unexpected"}
        ), self.assertRaisesRegex(ValueError, "Destructive"):
            preflight_module.execute(
                COMMIT, successful_runner, which=lambda _command: "/mock"
            )


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.directory.chmod(0o700)
        self.preflight_path = self.directory / "preflight.json"
        self.preflight_path.write_text(json.dumps(reviewed_result(), sort_keys=True))
        self.preflight_path.chmod(0o600)
        self.digest = hashlib.sha256(self.preflight_path.read_bytes()).hexdigest()
        self.output_number = 0

    def tearDown(self):
        self.temp.cleanup()

    def output_directory(self) -> Path:
        self.output_number += 1
        path = self.directory / f"output-{self.output_number}"
        path.mkdir(mode=0o700)
        return path

    def call(self, mode="verify", audit=lambda: (0, "", ""), output=None):
        return executor_module.execute(
            mode,
            COMMIT,
            self.preflight_path,
            self.digest,
            "2026-09-12T01:00:00Z",
            "2026-09-12T04:00:00Z",
            output,
            now=NOW,
            preflight=lambda _commit: reviewed_result(),
            audit=audit,
        )

    def test_verify_never_runs_full_audit(self):
        calls = []
        result = self.call(audit=lambda: calls.append(True) or (0, "", ""))
        self.assertEqual(calls, [])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["full_audit_executed"])

    def test_execute_requires_separate_confirmation(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            ValueError, "confirmation"
        ):
            self.call("execute", output=self.output_directory())

    def test_success_runs_once_and_writes_private_logs(self):
        calls = []
        raw_identity = "arn:aws:ec2:us-east-1:123456789012:fleet/fleet-private"
        stdout = (
            "AWS cleanup audit passed for aws-dev.\n"
            "Accepted 8 terminal or expired EC2 Fleet record(s); no repeat deletion is required.\n"
            "No continuing cluster, network, compute, volume, load-balancer, bucket, certificate, DNS, or tagged-resource identity was found.\n"
            + raw_identity
        )
        output = self.output_directory()
        with mock.patch.dict(
            os.environ,
            {
                "CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION": executor_module.EXECUTION_CONFIRMATION
            },
            clear=True,
        ):
            result = self.call(
                "execute",
                audit=lambda: calls.append(True) or (0, stdout, ""),
                output=output,
            )
        self.assertEqual(calls, [True])
        self.assertTrue(result["audit_passed"])
        self.assertEqual(result["terminal_or_expired_fleet_record_count"], 8)
        self.assertNotIn(raw_identity, json.dumps(result))
        for name in ("residual-cost-audit.stdout", "residual-cost-audit.stderr"):
            self.assertEqual(stat.S_IMODE((output / name).stat().st_mode), 0o600)

    def test_failure_is_redacted_and_not_retried(self):
        calls = []
        private_error = "residual arn:aws:ec2:us-east-1:123456789012:volume/vol-private"
        output = self.output_directory()
        with mock.patch.dict(
            os.environ,
            {
                "CONFIRM_AWS_DEV_RESIDUAL_COST_AUDIT_EXECUTION": executor_module.EXECUTION_CONFIRMATION
            },
            clear=True,
        ):
            result = self.call(
                "execute",
                audit=lambda: calls.append(True) or (1, "", private_error),
                output=output,
            )
        self.assertEqual(calls, [True])
        self.assertFalse(result["audit_passed"])
        self.assertIsNone(result["continuing_cost_identity_found"])
        self.assertNotIn(private_error, json.dumps(result))
        self.assertIn(private_error, (output / "residual-cost-audit.stderr").read_text())

    def test_expired_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            executor_module.execute(
                "verify",
                COMMIT,
                self.preflight_path,
                self.digest,
                "2026-09-11T00:00:00Z",
                "2026-09-11T03:00:00Z",
                None,
                now=NOW,
                preflight=lambda _commit: reviewed_result(),
            )

    def test_changed_immediate_preflight_is_rejected(self):
        changed = reviewed_result()
        changed["terraform_state_resource_count"] = 1
        with self.assertRaisesRegex(ValueError, "does not match"):
            executor_module.execute(
                "verify",
                COMMIT,
                self.preflight_path,
                self.digest,
                "2026-09-12T01:00:00Z",
                "2026-09-12T04:00:00Z",
                None,
                now=NOW,
                preflight=lambda _commit: changed,
            )


if __name__ == "__main__":
    unittest.main()

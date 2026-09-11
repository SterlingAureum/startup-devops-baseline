#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = (
    ROOT / "scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_module("aws_test_live_creation_preflight", PREFLIGHT_PATH)
COMMIT = "f" * 40
ACCOUNT = "123456789012"


class AwsTestLiveCreationPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = Path(self.temp.name) / "repository"
        self.repository.mkdir()
        for relative in (
            PREFLIGHT.AUDIT_EVIDENCE,
            PREFLIGHT.PROMOTION_EVIDENCE,
            PREFLIGHT.LEGACY_APPLY_WRAPPER,
            PREFLIGHT.TEST_BACKEND,
            PREFLIGHT.DEV_RELEASE,
            PREFLIGHT.TEST_RELEASE,
            PREFLIGHT.PROD_RELEASE,
        ):
            source = ROOT / relative
            target = self.repository / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.calls: list[list[str]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def environment(self):
        return mock.patch.dict(
            os.environ,
            {
                "AWS_ENVIRONMENT": "aws-test",
                "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
                "CONFIRM_AWS_TEST_CREATE_PREFLIGHT": PREFLIGHT.CONFIRMATION,
            },
            clear=True,
        )

    def runner(self, arguments: list[str]) -> str:
        self.calls.append(arguments)
        prefix = ["git", "-C", str(self.repository)]
        if arguments == [*prefix, "branch", "--show-current"]:
            return "main"
        if arguments == [*prefix, "status", "--porcelain"]:
            return ""
        if arguments in (
            [*prefix, "rev-parse", "HEAD"],
            [*prefix, "rev-parse", "origin/main"],
        ):
            return COMMIT
        if arguments[: len(prefix) + 2] == [*prefix, "merge-base", "--is-ancestor"]:
            return ""
        if arguments == ["aws", "sts", "get-caller-identity", "--output", "json"]:
            return json.dumps({"Account": ACCOUNT})
        if arguments == [
            "aws",
            "eks",
            "list-clusters",
            "--region",
            "us-east-1",
            "--output",
            "json",
        ]:
            return json.dumps({"clusters": []})
        raise AssertionError(f"Unexpected command: {arguments}")

    def execute(self, runner=None):
        with self.environment():
            return PREFLIGHT.execute(
                COMMIT,
                self.repository,
                runner or self.runner,
                which=lambda _command: "/mock",
            )

    def test_success_is_redacted_and_runs_only_reviewed_reads(self) -> None:
        result = self.execute()
        self.assertEqual(
            result["status"],
            "aws-test-live-creation-preflight-ready-for-separate-plan-review",
        )
        self.assertFalse(result["account_id_emitted"])
        self.assertFalse(result["terraform_state_exists"])
        self.assertFalse(result["environment_creation_authorized"])
        self.assertFalse(result["terraform_plan_executed"])
        self.assertFalse(result["terraform_apply_executed"])
        self.assertFalse(result["aws_test_created"])
        self.assertNotIn(ACCOUNT, json.dumps(result))
        self.assertFalse(any(call[0] == "terraform" for call in self.calls))
        aws_calls = [call for call in self.calls if call[0] == "aws"]
        self.assertEqual(len(aws_calls), 2)

    def test_valid_empty_version_four_state_is_accepted(self) -> None:
        state = self.repository / PREFLIGHT.TEST_STATE
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"version": 4, "resources": []}))
        result = self.execute()
        self.assertTrue(result["terraform_state_exists"])
        self.assertEqual(result["terraform_state_resource_block_count"], 0)
        self.assertEqual(result["terraform_state_resource_instance_count"], 0)

    def test_nonempty_state_is_rejected_without_returning_attributes(self) -> None:
        state = self.repository / PREFLIGHT.TEST_STATE
        state.parent.mkdir(parents=True, exist_ok=True)
        private_value = "private-endpoint-value"
        state.write_text(
            json.dumps(
                {
                    "version": 4,
                    "resources": [
                        {
                            "type": "aws_eks_cluster",
                            "instances": [{"attributes": {"endpoint": private_value}}],
                        }
                    ],
                }
            )
        )
        with self.environment(), self.assertRaisesRegex(ValueError, "not empty") as error:
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                self.runner,
                which=lambda _command: "/mock",
            )
        self.assertNotIn(private_value, str(error.exception))

    def test_invalid_or_symlink_state_is_rejected(self) -> None:
        state = self.repository / PREFLIGHT.TEST_STATE
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("not-json")
        with self.environment(), self.assertRaisesRegex(ValueError, "invalid"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                self.runner,
                which=lambda _command: "/mock",
            )

        state.unlink()
        state.symlink_to(self.repository / "missing-private-state")
        with self.environment(), self.assertRaisesRegex(ValueError, "symlink"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                self.runner,
                which=lambda _command: "/mock",
            )

    def test_wrong_account_fails_closed(self) -> None:
        def runner(arguments: list[str]) -> str:
            if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
                return json.dumps({"Account": "999999999999"})
            return self.runner(arguments)

        with self.environment(), self.assertRaisesRegex(ValueError, "account"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                runner,
                which=lambda _command: "/mock",
            )

    def test_each_active_rehearsal_cluster_is_rejected(self) -> None:
        for cluster in PREFLIGHT.CLUSTERS.values():
            with self.subTest(cluster=cluster):
                def runner(arguments: list[str], active=cluster) -> str:
                    if arguments[:3] == ["aws", "eks", "list-clusters"]:
                        return json.dumps({"clusters": [active]})
                    return self.runner(arguments)

                with self.environment(), self.assertRaisesRegex(
                    ValueError, "No rehearsal"
                ):
                    PREFLIGHT.execute(
                        COMMIT,
                        self.repository,
                        runner,
                        which=lambda _command: "/mock",
                    )

    def test_aws_inventory_failure_is_not_absence(self) -> None:
        def runner(arguments: list[str]) -> str:
            if arguments[:3] == ["aws", "eks", "list-clusters"]:
                raise RuntimeError("mock inventory failure")
            return self.runner(arguments)

        with self.environment(), self.assertRaisesRegex(RuntimeError, "inventory"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                runner,
                which=lambda _command: "/mock",
            )

    def test_missing_confirmation_and_operational_controls_are_rejected(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "AWS_ENVIRONMENT": "aws-test",
                "EXPECTED_AWS_ACCOUNT_ID": ACCOUNT,
            },
            clear=True,
        ), self.assertRaisesRegex(ValueError, "CONFIRM_AWS_TEST_CREATE_PREFLIGHT"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                self.runner,
                which=lambda _command: "/mock",
            )

        for key in (
            "CONFIRM_AWS_TEST_APPLY",
            "CONFIRM_AWS_ENVIRONMENT_DESTROY",
            "AWS_TEST_APPLY_MODE",
        ):
            with self.subTest(key=key), self.environment(), mock.patch.dict(
                os.environ, {key: "unexpected"}
            ), self.assertRaisesRegex(ValueError, "controls"):
                PREFLIGHT.execute(
                    COMMIT,
                    self.repository,
                    self.runner,
                    which=lambda _command: "/mock",
                )

    def test_exact_main_mismatch_is_rejected_before_aws(self) -> None:
        def runner(arguments: list[str]) -> str:
            prefix = ["git", "-C", str(self.repository)]
            if arguments == [*prefix, "rev-parse", "origin/main"]:
                return "e" * 40
            return self.runner(arguments)

        with self.environment(), self.assertRaisesRegex(ValueError, "HEAD"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                runner,
                which=lambda _command: "/mock",
            )
        self.assertFalse(any(call[0] == "aws" for call in self.calls))

    def test_reviewed_audit_evidence_drift_is_rejected_before_aws(self) -> None:
        path = self.repository / PREFLIGHT.AUDIT_EVIDENCE
        path.write_bytes(path.read_bytes() + b"\n")
        with self.environment(), self.assertRaisesRegex(ValueError, "fingerprint"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                self.runner,
                which=lambda _command: "/mock",
            )
        self.assertFalse(any(call[0] == "aws" for call in self.calls))

    def test_release_drift_is_rejected_before_aws(self) -> None:
        path = self.repository / PREFLIGHT.TEST_RELEASE
        path.write_bytes(path.read_bytes() + b"\n")
        with self.environment(), self.assertRaisesRegex(ValueError, "fingerprint"):
            PREFLIGHT.execute(
                COMMIT,
                self.repository,
                self.runner,
                which=lambda _command: "/mock",
            )
        self.assertFalse(any(call[0] == "aws" for call in self.calls))


if __name__ == "__main__":
    unittest.main()

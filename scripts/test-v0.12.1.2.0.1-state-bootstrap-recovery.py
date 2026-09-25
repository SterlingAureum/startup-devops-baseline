#!/usr/bin/env python3
"""Offline tests for v0.12.1.2.0.1 state-bootstrap post-apply recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.12.1.2.0.1-state-bootstrap-recovery.py"
SPEC = importlib.util.spec_from_file_location("state_bootstrap_recovery_v0121201", PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load recovery executor")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

APPLY_TEST_PATH = ROOT / "scripts/test-v0.12.1.2-state-bootstrap-apply.py"
APPLY_TEST_SPEC = importlib.util.spec_from_file_location("state_bootstrap_apply_fixture", APPLY_TEST_PATH)
if APPLY_TEST_SPEC is None or APPLY_TEST_SPEC.loader is None:
    raise RuntimeError("Could not load apply executor fixture")
APPLY_TEST = importlib.util.module_from_spec(APPLY_TEST_SPEC)
APPLY_TEST_SPEC.loader.exec_module(APPLY_TEST)

ACCOUNT = "123456789012"
KMS_ARN = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/11111111-2222-3333-4444-555555555555"
BUCKET = "private-reviewed-state-bucket"


def policy_document() -> dict:
    bucket_arn = f"arn:aws:s3:::{BUCKET}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [bucket_arn, f"{bucket_arn}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            }
        ],
    }


class StateEvidenceTests(unittest.TestCase):
    def test_exact_managed_state_addresses_are_reconstructed(self) -> None:
        resources = []
        for address in sorted(MODULE.PLAN_GATE.EXPECTED_MANAGED_ADDRESSES):
            if "[" in address:
                base, raw_key = address.split("[", 1)
                key = json.loads("[" + raw_key)[0]
            else:
                base, key = address, None
            resource_type, name = base.split(".", 1)
            instance = {} if key is None else {"index_key": key}
            match = next(
                (
                    item
                    for item in resources
                    if item["type"] == resource_type and item["name"] == name
                ),
                None,
            )
            if match is None:
                match = {
                    "mode": "managed",
                    "type": resource_type,
                    "name": name,
                    "instances": [],
                }
                resources.append(match)
            match["instances"].append(instance)
        managed, data = MODULE.state_addresses({"version": 4, "resources": resources})
        self.assertEqual(managed, MODULE.PLAN_GATE.EXPECTED_MANAGED_ADDRESSES)
        self.assertEqual(data, set())

    def test_unreviewed_managed_state_is_visible(self) -> None:
        state = {
            "version": 4,
            "resources": [
                {
                    "mode": "managed",
                    "type": "aws_s3_bucket",
                    "name": "unexpected",
                    "instances": [{}],
                }
            ],
        }
        managed, _ = MODULE.state_addresses(state)
        self.assertEqual(managed, {"aws_s3_bucket.unexpected"})

    def test_only_invalid_arn_incident_code_is_accepted(self) -> None:
        value = b"An error occurred (InvalidArnException) when calling GetKeyRotationStatus"
        self.assertEqual(MODULE.error_code(value), "InvalidArnException")
        self.assertEqual(
            MODULE.error_code(b"An error occurred (AccessDeniedException) when calling operation"),
            "AccessDeniedException",
        )
        with self.assertRaisesRegex(ValueError, "code is missing"):
            MODULE.error_code(b"unstructured failure")


class RecoveryInputChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = APPLY_TEST.ApplyExecutorTests(methodName="test_verify_is_operationally_command_free_and_redacted")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def state_resources() -> list[dict]:
        resources: list[dict] = []
        for address in sorted(MODULE.PLAN_GATE.EXPECTED_MANAGED_ADDRESSES):
            if "[" in address:
                base, raw_key = address.split("[", 1)
                key = json.loads("[" + raw_key)[0]
            else:
                base, key = address, None
            resource_type, name = base.split(".", 1)
            match = next(
                (item for item in resources if item["type"] == resource_type and item["name"] == name),
                None,
            )
            if match is None:
                match = {"mode": "managed", "type": resource_type, "name": name, "instances": []}
                resources.append(match)
            instance = {"attributes": {}}
            if key is not None:
                instance["index_key"] = key
            match["instances"].append(instance)
        return resources

    def incident_runner(self, arguments, environment, timeout, cwd):
        if arguments[0] == "terraform" and "apply" in arguments:
            self.fixture.calls.append(arguments)
            self.fixture.applied = True
            state = {
                "version": 4,
                "terraform_version": "1.16.3",
                "serial": 1,
                "lineage": "11111111-2222-3333-4444-555555555555",
                "outputs": self.fixture.terraform_outputs(),
                "resources": self.state_resources(),
            }
            (self.fixture.source / "terraform.tfstate").write_text(json.dumps(state))
            return subprocess.CompletedProcess(arguments, 0, b"Apply complete", b"")
        if "get-key-rotation-status" in arguments:
            self.fixture.calls.append(arguments)
            return subprocess.CompletedProcess(
                arguments,
                254,
                b"",
                b"An error occurred (InvalidArnException) when calling GetKeyRotationStatus",
            )
        return self.fixture.runner(arguments, environment, timeout, cwd)

    def write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        path.chmod(0o600)

    def recovery_git_runner(self, arguments: list[str]) -> str:
        mapping = {
            ("branch", "--show-current"): "main",
            ("status", "--porcelain"): "",
            ("rev-parse", "HEAD"): "f" * 40,
            ("rev-parse", "origin/main"): "f" * 40,
        }
        return mapping[tuple(arguments)]

    def test_exact_failed_apply_chain_is_accepted_without_operational_commands(self) -> None:
        with self.assertRaisesRegex(APPLY_TEST.EXECUTOR.CommandFailure, "kms-rotation failed"):
            self.fixture.execute(runner=self.incident_runner)
        state_copy = self.fixture.apply_output / "state-bootstrap.tfstate.applied"
        kms_stderr = self.fixture.apply_output / "kms-rotation.stderr"
        recovery_output = self.fixture.private / "recovery-output"
        request_path = self.fixture.private / "recovery-request.json"
        now = APPLY_TEST.NOW + timedelta(minutes=10)
        request = {
            "schemaVersion": "v0.12.1.2.0.1-state-bootstrap-recovery-request-v1",
            "operation": MODULE.RECOVERY_CONFIRMATION,
            "repository": "SterlingAureum/startup-devops-baseline",
            "trustedRef": "refs/heads/main",
            "expectedRecoveryMainCommit": "f" * 40,
            "incidentControlPlaneCommit": APPLY_TEST.MAIN_SHA,
            "expectedAwsAccountId": APPLY_TEST.ACCOUNT,
            "privateApplyRequestPath": str(self.fixture.apply_request_path),
            "privateApplyRequestSha256": self.digest(self.fixture.apply_request_path),
            "privatePlanBundleDirectory": str(self.fixture.bundle),
            "planRecordSha256": self.digest(self.fixture.record_path),
            "binaryPlanSha256": self.digest(self.fixture.binary_plan),
            "privateFailedApplyOutputDirectory": str(self.fixture.apply_output),
            "failedKmsRotationStderrSha256": self.digest(kms_stderr),
            "appliedStateSha256": self.digest(state_copy),
            "privateRecoveryOutputDirectory": str(recovery_output),
            "approval": {
                "notBeforeUtc": (now - timedelta(minutes=1)).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "expiresAtUtc": (now + timedelta(minutes=40)).isoformat(timespec="seconds").replace("+00:00", "Z"),
            },
            "executionBoundary": {
                "terraformApply": False,
                "terraformPlan": False,
                "terraformInit": False,
                "stateMigration": False,
                "destroy": False,
                "awsReadOnlyLiveValidation": True,
            },
        }
        self.write_json(request_path, request)
        calls_before = len(self.fixture.calls)
        context = MODULE.verify_inputs(
            request_path,
            repository_root=self.fixture.repository,
            git_runner=self.recovery_git_runner,
            now=now,
        )
        self.assertEqual(len(self.fixture.calls), calls_before)
        result = MODULE.redacted_verification(context)
        self.assertTrue(result["prior_apply_evidence_verified"])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(recovery_output.exists())

        request["appliedStateSha256"] = "0" * 64
        self.write_json(request_path, request)
        with self.assertRaisesRegex(ValueError, "state copy changed"):
            MODULE.verify_inputs(
                request_path,
                repository_root=self.fixture.repository,
                git_runner=self.recovery_git_runner,
                now=now,
            )


class RecoveryExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name) / "private"
        self.parent.mkdir(mode=0o700)
        self.failed_output = self.parent / "failed-apply"
        self.failed_output.mkdir(mode=0o700)
        (self.failed_output / "terraform-data").mkdir(mode=0o700)
        self.output = self.parent / "recovery"
        self.policies = {
            root: f"arn:aws:iam::{ACCOUNT}:policy/startup-devops-baseline-terraform-state-{root}"
            for root in MODULE.PLAN_GATE.EXPECTED_POLICY_ROOTS
        }
        self.context = {
            "request": {
                "expectedRecoveryMainCommit": "f" * 40,
                "incidentControlPlaneCommit": "e" * 40,
                "expectedAwsAccountId": ACCOUNT,
                "privateApplyRequestSha256": "a" * 64,
                "planRecordSha256": "b" * 64,
                "binaryPlanSha256": "c" * 64,
                "appliedStateSha256": "d" * 64,
            },
            "plan_request": {"awsRegion": "us-east-1"},
            "failed_output": self.failed_output,
            "recovery_output": self.output,
            "identities": {
                "bucket": BUCKET,
                "alias": "alias/startup-devops-baseline-terraform-state",
                "kms_arn": KMS_ARN,
                "policies": self.policies,
            },
        }
        self.calls: list[list[str]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def runner(self, arguments, environment, timeout, cwd):
        self.calls.append(arguments)
        joined = " ".join(arguments)
        if "get-caller-identity" in joined:
            body = {"Account": ACCOUNT}
        elif "get-bucket-versioning" in joined:
            body = {"Status": "Enabled"}
        elif "get-public-access-block" in joined:
            body = {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            }
        elif "get-bucket-ownership-controls" in joined:
            body = {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}}
        elif "get-bucket-encryption" in joined:
            body = {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "aws:kms",
                                "KMSMasterKeyID": KMS_ARN,
                            },
                            "BucketKeyEnabled": True,
                        }
                    ]
                }
            }
        elif "get-bucket-policy-status" in joined:
            body = {"PolicyStatus": {"IsPublic": False}}
        elif "get-bucket-policy" in joined:
            body = {"Policy": json.dumps(policy_document())}
        elif "list-object-versions" in joined:
            body = {}
        elif "get-key-rotation-status" in joined:
            self.assertIn(KMS_ARN, arguments)
            self.assertNotIn("alias/startup-devops-baseline-terraform-state", arguments)
            body = {"KeyRotationEnabled": True}
        elif "describe-key" in joined:
            self.assertIn(KMS_ARN, arguments)
            body = {
                "KeyMetadata": {
                    "Arn": KMS_ARN,
                    "Enabled": True,
                    "KeyState": "Enabled",
                    "KeyManager": "CUSTOMER",
                }
            }
        elif "get-policy" in joined:
            arn = arguments[arguments.index("--policy-arn") + 1]
            body = {"Policy": {"Arn": arn, "AttachmentCount": 0}}
        elif "list-entities-for-policy" in joined:
            body = {"PolicyGroups": [], "PolicyUsers": [], "PolicyRoles": []}
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, json.dumps(body).encode(), b"")

    def execute(self):
        with mock.patch.object(MODULE, "verify_inputs", return_value=self.context):
            return MODULE.execute(Path("/ignored"), runner=self.runner)

    def test_execute_completes_read_only_validation_without_second_apply(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CONFIRM_STATE_BOOTSTRAP_RECOVERY": MODULE.RECOVERY_CONFIRMATION},
            clear=True,
        ):
            result = self.execute()
        self.assertEqual(result["status"], "state-backend-foundation-post-apply-recovered-and-live-validated")
        self.assertTrue(result["prior_terraform_apply_succeeded"])
        self.assertFalse(result["terraform_apply_reexecuted"])
        self.assertFalse(result["state_migration_executed"])
        self.assertEqual(result["root_state_policy_count"], 5)
        self.assertEqual(result["attached_root_state_policy_count"], 0)
        self.assertTrue(all(call[0] == "aws" for call in self.calls))
        self.assertFalse(any("apply" in call or "destroy" in call for call in self.calls))
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in self.output.iterdir()))

    def test_confirmation_and_mutating_confirmations_stop_before_commands(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "Set CONFIRM"):
            self.execute()
        self.assertEqual(self.calls, [])
        with mock.patch.dict(
            os.environ,
            {
                "CONFIRM_STATE_BOOTSTRAP_RECOVERY": MODULE.RECOVERY_CONFIRMATION,
                "CONFIRM_STATE_BOOTSTRAP_APPLY": "polluted",
            },
            clear=True,
        ), self.assertRaisesRegex(ValueError, "must be unset"):
            self.execute()
        self.assertEqual(self.calls, [])

    def test_account_change_stops_before_live_resource_reads(self) -> None:
        def wrong_account(arguments, environment, timeout, cwd):
            self.calls.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, b'{"Account":"999999999999"}', b"")

        with mock.patch.object(MODULE, "verify_inputs", return_value=self.context), mock.patch.dict(
            os.environ,
            {"CONFIRM_STATE_BOOTSTRAP_RECOVERY": MODULE.RECOVERY_CONFIRMATION},
            clear=True,
        ), self.assertRaisesRegex(ValueError, "AWS account changed"):
            MODULE.execute(Path("/ignored"), runner=wrong_account)
        self.assertEqual(len(self.calls), 1)

    def test_verify_result_is_command_free_and_unauthorized(self) -> None:
        context = dict(self.context)
        context.update(
            request_path=self.parent / "request.json",
            remaining=3000,
        )
        context["request_path"].write_text("{}")
        context["request_path"].chmod(0o600)
        result = MODULE.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["recovery_execution_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

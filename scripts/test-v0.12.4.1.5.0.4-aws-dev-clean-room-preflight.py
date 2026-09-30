#!/usr/bin/env python3
"""Offline tests for the guarded aws-dev clean-room preflight executor."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_clean_room_preflight_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"
BUCKET = "private-state-bucket-example"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"
KMS_ARN = f"arn:aws:kms:us-east-1:{ACCOUNT}:key/11111111-2222-3333-4444-555555555555"
POLICY_ARN = f"arn:aws:iam::{ACCOUNT}:policy/startup-devops-baseline-terraform-state-dev"


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": ACCOUNT,
        "expectedAwsRegion": EXECUTOR.AWS_REGION,
        "expectedClusterName": EXECUTOR.CLUSTER_NAME,
        "expectedStateBucketName": BUCKET,
        "expectedStateBucketArn": BUCKET_ARN,
        "expectedStateKmsKeyArn": KMS_ARN,
        "expectedDevStateAccessPolicyArn": POLICY_ARN,
        "privateBackendConfigPath": "/private/dev.s3.tfbackend",
        "privateBackendConfigSha256": "2" * 64,
        "privatePreflightOutputDirectory": "/private/preflight-output",
        "privateStagedSourceDirectory": "/private/staged-source",
        "approval": {
            "notBeforeUtc": "2026-09-30T01:00:00Z",
            "expiresAtUtc": "2026-09-30T02:00:00Z",
        },
        "executionBoundary": {
            "awsReadOnlyValidation": True,
            "localPrivateSourceStaging": True,
            "terraformInit": False,
            "terraformPlan": False,
            "terraformApply": False,
            "stateMigration": False,
            "statePush": False,
            "destroy": False,
            "iamPolicyAttachment": False,
            "kubernetesCommand": False,
            "secretValueRead": False,
            "automaticRetry": False,
            "automaticRollback": False,
        },
    }


def backend_text() -> str:
    return f'''bucket              = "{BUCKET}"
key                 = "{EXECUTOR.STATE_KEY}"
region              = "{EXECUTOR.AWS_REGION}"
encrypt             = true
kms_key_id          = "{KMS_ARN}"
use_lockfile        = true
allowed_account_ids = ["{ACCOUNT}"]
'''


def policy_document() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ListExactStateAndLockKeys",
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": BUCKET_ARN,
                "Condition": {"StringEquals": {"s3:prefix": [EXECUTOR.STATE_KEY, EXECUTOR.LOCK_KEY]}},
            },
            {
                "Sid": "ReadWriteExactStateObject",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject"],
                "Resource": f"{BUCKET_ARN}/{EXECUTOR.STATE_KEY}",
            },
            {
                "Sid": "ManageExactLockObject",
                "Effect": "Allow",
                "Action": ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
                "Resource": f"{BUCKET_ARN}/{EXECUTOR.LOCK_KEY}",
            },
            {
                "Sid": "UseStateEncryptionKeyThroughS3",
                "Effect": "Allow",
                "Action": ["kms:Decrypt", "kms:DescribeKey", "kms:Encrypt", "kms:GenerateDataKey"],
                "Resource": KMS_ARN,
                "Condition": {"StringEquals": {"kms:ViaService": "s3.us-east-1.amazonaws.com"}},
            },
        ],
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_mutating_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformInit"] = True
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "Execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_long_window_is_rejected(self):
        value = request()
        value["approval"]["expiresAtUtc"] = "2026-09-30T02:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "at most one hour"):
            EXECUTOR.validate_request(value)

    def test_backend_identity_must_match_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backend.tfbackend"
            path.write_text(backend_text())
            values = EXECUTOR.parse_backend_config(path)
            EXECUTOR.validate_backend_config(values, request())
            values["key"] = "bootstrap/terraform.tfstate"
            with self.assertRaisesRegex(EXECUTOR.PreflightError, "state key"):
                EXECUTOR.validate_backend_config(values, request())

    def test_backend_config_rejects_extra_field(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backend.tfbackend"
            path.write_text(backend_text() + 'profile = "default"\n')
            with self.assertRaisesRegex(EXECUTOR.PreflightError, "fields changed"):
                EXECUTOR.parse_backend_config(path)

    def test_verification_is_command_free_and_unauthorized(self):
        context = {
            "request": request(),
            "request_path": Path("/private/request.json"),
            "source_manifest_sha256": "3" * 64,
            "source_entries": [{"path": "infra/terraform/aws/example.tf"}],
            "remaining": 1800,
        }
        with patch.object(EXECUTOR, "file_sha256", return_value="4" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["preflight_execution_authorized"])
        self.assertFalse(result["terraform_init_authorized"])
        self.assertFalse(result["terraform_plan_authorized"])


class LiveValidationTests(unittest.TestCase):
    def test_exact_backend_foundation_shapes_are_accepted(self):
        EXECUTOR.validate_versioning({"Status": "Enabled"})
        EXECUTOR.validate_public_access({"PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }})
        EXECUTOR.validate_encryption({"ServerSideEncryptionConfiguration": {"Rules": [{
            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": KMS_ARN},
            "BucketKeyEnabled": True,
        }]}}, KMS_ARN)

    def test_existing_state_history_is_rejected(self):
        value = {"Versions": [{"Key": EXECUTOR.STATE_KEY, "VersionId": "private"}], "DeleteMarkers": []}
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "already exists"):
            EXECUTOR.validate_empty_object_history(value)

    def test_exact_iam_policy_is_accepted(self):
        EXECUTOR.validate_iam_policy_document({"PolicyVersion": {"Document": policy_document()}}, BUCKET_ARN, KMS_ARN)

    def test_wildcard_iam_state_resource_is_rejected(self):
        document = policy_document()
        document["Statement"][1]["Resource"] = f"{BUCKET_ARN}/*"
        with self.assertRaisesRegex(EXECUTOR.PreflightError, "state resource"):
            EXECUTOR.validate_iam_policy_document({"PolicyVersion": {"Document": document}}, BUCKET_ARN, KMS_ARN)

    def test_only_resource_not_found_proves_eks_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = subprocess.CompletedProcess([], 254, b"", b"An error occurred (AccessDeniedException) when calling the DescribeCluster operation")
            with self.assertRaisesRegex(EXECUTOR.PreflightError, "absence error changed"):
                EXECUTOR.run_expected_missing_eks(output, {}, lambda *_args: result, ROOT)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.repo = self.root / "repo"
        source = self.repo / "infra/terraform/aws/example.tf"
        source.parent.mkdir(parents=True)
        source.write_text("terraform {}\n")
        self.request_path = self.private / "request.json"
        self.request_path.write_text("{}\n")
        self.request_path.chmod(0o600)
        self.backend_path = self.private / "dev.s3.tfbackend"
        self.backend_path.write_text(backend_text())
        self.backend_path.chmod(0o600)
        self.output = self.private / "output"
        self.staging = self.private / "staging"
        entry = {
            "path": "infra/terraform/aws/example.tf",
            "gitMode": "100644",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        self.context = {
            "request": request(),
            "request_path": self.request_path,
            "backend_path": self.backend_path,
            "backend": EXECUTOR.parse_backend_config(self.backend_path),
            "output": self.output,
            "staging": self.staging,
            "source_entries": [entry],
            "source_manifest_sha256": EXECUTOR.source_manifest_digest([entry]),
            "remaining": 1800,
        }
        self.responses = {
            ("sts", "get-caller-identity"): {"Account": ACCOUNT, "Arn": "private", "UserId": "private"},
            ("s3api", "get-bucket-versioning"): {"Status": "Enabled"},
            ("s3api", "get-public-access-block"): {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }},
            ("s3api", "get-bucket-encryption"): {"ServerSideEncryptionConfiguration": {"Rules": [{
                "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": KMS_ARN},
                "BucketKeyEnabled": True,
            }]}},
            ("s3api", "list-object-versions"): {"Versions": [], "DeleteMarkers": [], "IsTruncated": False},
            ("kms", "describe-key"): {"KeyMetadata": {
                "Arn": KMS_ARN, "Enabled": True, "KeyState": "Enabled",
                "KeyManager": "CUSTOMER", "KeyUsage": "ENCRYPT_DECRYPT", "MultiRegion": False,
            }},
            ("kms", "get-key-rotation-status"): {"KeyRotationEnabled": True},
            ("iam", "get-policy"): {"Policy": {
                "Arn": POLICY_ARN, "AttachmentCount": 0,
                "PermissionsBoundaryUsageCount": 0, "DefaultVersionId": "v1",
            }},
            ("iam", "get-policy-version"): {"PolicyVersion": {"Document": policy_document()}},
        }
        self.commands: list[list[str]] = []

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, arguments, _environment, _timeout, _cwd):
        self.commands.append(arguments)
        if arguments[1:3] == ["eks", "describe-cluster"]:
            return subprocess.CompletedProcess(arguments, 254, b"", b"An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation: No cluster found")
        payload = self.responses[tuple(arguments[1:3])]
        return subprocess.CompletedProcess(arguments, 0, json.dumps(payload).encode(), b"")

    def test_execute_completes_read_only_preflight_and_stages_source(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_CLEAN_ROOM_PREFLIGHT": EXECUTOR.CONFIRMATION}, clear=False),
        ):
            result = EXECUTOR.execute(
                self.request_path,
                repository_root=self.repo,
                runner=self.runner,
                now=datetime(2026, 9, 30, 1, 30, tzinfo=timezone.utc),
            )
        self.assertEqual(result["status"], "aws-dev-remote-state-clean-room-preflight-complete-awaiting-separate-plan-review")
        self.assertTrue(result["eks_cluster_absent"])
        self.assertTrue(result["staged_source_manifest_matches_repository"])
        self.assertFalse(result["terraform_init_executed"])
        self.assertTrue((self.staging / "example.tf").is_file())
        self.assertEqual(len(self.commands), 10)
        self.assertEqual({command[0] for command in self.commands}, {"aws"})

    def test_mutation_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {
                "CONFIRM_AWS_DEV_CLEAN_ROOM_PREFLIGHT": EXECUTOR.CONFIRMATION,
                "CONFIRM_TERRAFORM_APPLY": "unsafe",
            }, clear=False),
        ):
            with self.assertRaisesRegex(EXECUTOR.PreflightError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

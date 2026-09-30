#!/usr/bin/env python3
"""Offline tests for the aws-dev create-plan recovery executor."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_create_plan_recovery_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "incidentControlPlaneCommit": EXECUTOR.INCIDENT_COMMIT,
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": ACCOUNT,
        "expectedAwsRegion": EXECUTOR.AWS_REGION,
        "expectedClusterName": EXECUTOR.CLUSTER_NAME,
        "expectedTerraformVersion": "1.14.5",
        "privateFailedPlanRequestPath": "/private/failed-request.json",
        "privateFailedPlanRequestSha256": EXECUTOR.FAILED_REQUEST_SHA256,
        "privateFailedPlanSourceDirectory": "/private/failed-source",
        "privateFailedPlanOutputDirectory": "/private/failed-output",
        "failedArtifactSha256s": dict(EXECUTOR.FAILED_ARTIFACTS),
        "failedProviderLockfileSha256": EXECUTOR.FAILED_LOCKFILE_SHA256,
        "privateManagementCidr": "8.8.8.8/32",
        "privateRecoveryPlanSourceDirectory": "/private/recovery-source",
        "privateRecoveryPlanOutputDirectory": "/private/recovery-output",
        "humanReview": {
            "failedAttemptReviewed": True,
            "failureCause": "eks-public-endpoint-missing-restricted-cidr",
            "managementCidrPrivatelyValidated": True,
            "reviewedMaximumBudgetUsd": 50,
        },
        "approval": {
            "notBeforeUtc": "2026-09-30T04:00:00Z",
            "expiresAtUtc": "2026-09-30T06:00:00Z",
            "planReviewExpiresAtUtc": "2026-09-30T12:00:00Z",
        },
        "executionBoundary": {
            "awsReadOnlyValidation": True,
            "localPrivateSourceCopy": True,
            "terraformInitReconfigureReadonlyLockfile": True,
            "terraformSavedPlan": True,
            "terraformShow": True,
            "terraformApply": False,
            "stateMigration": False,
            "statePush": False,
            "destroy": False,
            "iamPolicyAttachment": False,
            "kubernetesCommand": False,
            "secretValueRead": False,
            "directS3Mutation": False,
            "forceUnlock": False,
            "automaticRetry": False,
            "automaticRollback": False,
        },
    }


def plan_json() -> dict:
    return {
        "complete": True,
        "errored": False,
        "applyable": True,
        "resource_drift": [],
        "resource_changes": [
            {"address": "module.eks.aws_eks_cluster.this", "mode": "managed", "change": {"actions": ["create"]}},
            {"address": "data.aws_caller_identity.current", "mode": "data", "change": {"actions": ["read"]}},
        ],
        "output_changes": {"cluster_name": {"actions": ["create"]}},
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_management_cidr_must_be_one_global_ipv4_host(self):
        for value in ("0.0.0.0/0", "10.0.0.1/32", "127.0.0.1/32", "8.8.8.0/24", "8.8.8.8"):
            candidate = request()
            candidate["privateManagementCidr"] = value
            with self.subTest(value=value), self.assertRaises(EXECUTOR.RecoveryError):
                EXECUTOR.validate_request(candidate)

    def test_failed_artifact_digest_cannot_change(self):
        candidate = request()
        candidate["failedArtifactSha256s"]["terraform-plan-create.stderr"] = "0" * 64
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "artifact digest"):
            EXECUTOR.validate_request(candidate)

    def test_mutating_authority_is_rejected(self):
        candidate = request()
        candidate["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Execution boundary"):
            EXECUTOR.validate_request(candidate)

    def test_verification_is_command_free_and_redacts_cidr(self):
        context = {"request": request(), "request_path": Path("/private/request.json"), "remaining": 3600}
        with patch.object(EXECUTOR, "file_sha256", return_value="9" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["recovery_plan_execution_authorized"])
        self.assertFalse(result["management_cidr_emitted"])
        self.assertNotIn("8.8.8.8", json.dumps(result))


class HistoryTests(unittest.TestCase):
    def test_incident_history_requires_one_clean_failed_lock_cycle(self):
        exact = {"stateVersions": 0, "stateDeleteMarkers": 0, "lockVersions": 1, "lockDeleteMarkers": 1, "lockLatestVersions": 0, "lockLatestDeleteMarkers": 1}
        EXECUTOR.validate_incident_history(exact)
        changed = dict(exact, lockVersions=2)
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "lock history"):
            EXECUTOR.validate_incident_history(changed)

    def test_recovery_history_requires_one_additional_clean_lock_cycle(self):
        before = {"stateVersions": 0, "stateDeleteMarkers": 0, "lockVersions": 1, "lockDeleteMarkers": 1, "lockLatestVersions": 0, "lockLatestDeleteMarkers": 1}
        after = dict(before, lockVersions=2, lockDeleteMarkers=2, lockLatestDeleteMarkers=1)
        EXECUTOR.validate_recovery_history(before, after)
        after["stateVersions"] = 1
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "wrote remote state"):
            EXECUTOR.validate_recovery_history(before, after)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.request_path = self.private / "request.json"
        self.request_path.write_text("{}\n")
        self.request_path.chmod(0o600)
        self.staging = self.private / "staging"
        (self.staging / "environments/dev").mkdir(parents=True, mode=0o700)
        source = self.staging / "environments/dev/main.tf"
        source.write_text("terraform {}\n")
        source.chmod(0o600)
        self.backend = self.private / "dev.s3.tfbackend"
        self.backend.write_text('bucket = "private-state-bucket"\n')
        self.backend.chmod(0o600)
        self.tfvars = self.private / "terraform.tfvars"
        self.tfvars.write_text('environment = "dev"\n')
        self.tfvars.chmod(0o600)
        self.failed_source = self.private / "failed-source"
        (self.failed_source / "environments/dev").mkdir(parents=True, mode=0o700)
        self.failed_lockfile = self.failed_source / "environments/dev/.terraform.lock.hcl"
        self.failed_lockfile.write_text("# reviewed provider lock\n")
        self.failed_lockfile.chmod(0o600)
        self.recovery_source = self.private / "recovery-source"
        self.output = self.private / "recovery-output"
        value = request()
        value["privateManagementCidr"] = "8.8.8.8/32"
        value["privateFailedPlanRequestSha256"] = EXECUTOR.FAILED_REQUEST_SHA256
        value["privateFailedPlanSourceDirectory"] = str(self.failed_source)
        value["privateRecoveryPlanSourceDirectory"] = str(self.recovery_source)
        value["privateRecoveryPlanOutputDirectory"] = str(self.output)
        failed_request = {
            "privateBackendConfigSha256": EXECUTOR.file_sha256(self.backend),
            "privateTerraformTfvarsSha256": EXECUTOR.file_sha256(self.tfvars),
        }
        self.context = {
            "request": value,
            "request_path": self.request_path,
            "incident": {
                "failed_request": failed_request,
                "failed_request_path": self.private / "failed-request.json",
                "failed_source": self.failed_source,
                "failed_output": self.private / "failed-output",
                "failed_lockfile": self.failed_lockfile,
                "chain": {
                    "entries": [{"path": "infra/terraform/aws/environments/dev/main.tf", "gitMode": "100644", "sha256": EXECUTOR.file_sha256(source)}],
                    "staging": self.staging,
                    "paths": {"backend": self.backend, "tfvars": self.tfvars},
                    "backend": {"bucket": "private-state-bucket"},
                },
            },
            "plan_source": self.recovery_source,
            "output": self.output,
            "remaining": 3600,
        }
        self.history_reads = 0
        self.commands: list[list[str]] = []

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, arguments, _environment, _timeout, cwd):
        self.commands.append(arguments)
        if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Account": ACCOUNT}).encode(), b"")
        if arguments[:3] == ["aws", "eks", "describe-cluster"]:
            return subprocess.CompletedProcess(arguments, 254, b"", b"An error occurred (ResourceNotFoundException) when calling DescribeCluster")
        if arguments[:3] == ["aws", "s3api", "list-object-versions"]:
            self.history_reads += 1
            versions = [{"Key": EXECUTOR.LOCK_KEY, "VersionId": "private", "IsLatest": False} for _ in range(self.history_reads)]
            markers = [{"Key": EXECUTOR.LOCK_KEY, "VersionId": "private", "IsLatest": index == self.history_reads - 1} for index in range(self.history_reads)]
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Versions": versions, "DeleteMarkers": markers, "IsTruncated": False}).encode(), b"")
        if arguments[:3] == ["terraform", "version", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"terraform_version": "1.14.5"}).encode(), b"")
        if arguments[:2] == ["terraform", "init"]:
            return subprocess.CompletedProcess(arguments, 0, b"Terraform initialized\n", b"")
        if arguments[:2] == ["terraform", "plan"]:
            output_argument = next(item for item in arguments if item.startswith("-out="))
            Path(output_argument.removeprefix("-out=")).write_bytes(b"private recovery plan")
            return subprocess.CompletedProcess(arguments, 0, b"Plan: 1 to add\n", b"")
        if arguments[:3] == ["terraform", "show", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(plan_json()).encode(), b"")
        if arguments[:3] == ["terraform", "show", "-no-color"]:
            return subprocess.CompletedProcess(arguments, 0, b"Plan: 1 to add, 0 to change, 0 to destroy.\n", b"")
        raise AssertionError(arguments)

    def test_execute_uses_reviewed_lockfile_and_private_cidr_without_apply(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.object(EXECUTOR, "FAILED_LOCKFILE_SHA256", EXECUTOR.file_sha256(self.failed_lockfile)),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY": EXECUTOR.CONFIRMATION}, clear=True),
        ):
            result = EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner, now=datetime(2026, 9, 30, 5, 0, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "aws-dev-create-plan-recovered-awaiting-separate-apply-review")
        init = next(command for command in self.commands if command[:2] == ["terraform", "init"])
        plan = next(command for command in self.commands if command[:2] == ["terraform", "plan"])
        self.assertIn("-lockfile=readonly", init)
        reviewed_management_cidr = self.context["request"]["privateManagementCidr"]
        self.assertIn(f'-var=eks_public_access_cidrs=["{reviewed_management_cidr}"]', plan)
        self.assertFalse(any(command[:2] == ["terraform", "apply"] for command in self.commands))
        self.assertFalse(result["management_cidr_emitted"])

    def test_other_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_CREATE_PLAN_RECOVERY": EXECUTOR.CONFIRMATION, "CONFIRM_TERRAFORM_APPLY": "unsafe"}, clear=True),
        ):
            with self.assertRaisesRegex(EXECUTOR.RecoveryError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

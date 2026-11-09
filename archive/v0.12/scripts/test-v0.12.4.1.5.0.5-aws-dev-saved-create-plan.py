#!/usr/bin/env python3
"""Offline tests for the guarded aws-dev saved create-plan executor."""

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_saved_create_plan_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": ACCOUNT,
        "expectedAwsRegion": EXECUTOR.AWS_REGION,
        "expectedClusterName": EXECUTOR.CLUSTER_NAME,
        "expectedTerraformVersion": "1.14.5",
        "privatePreflightRequestPath": "/private/preflight-request.json",
        "privatePreflightRequestSha256": "2" * 64,
        "privatePreflightResultPath": "/private/preflight-result.json",
        "privatePreflightResultSha256": "3" * 64,
        "privatePreflightEvidencePath": "/private/preflight-evidence.json",
        "privatePreflightEvidenceSha256": "4" * 64,
        "privateSourceManifestPath": "/private/source-manifest.json",
        "privateSourceManifestFileSha256": "5" * 64,
        "sourceManifestSha256": "6" * 64,
        "privateStagedSourceDirectory": "/private/staged-source",
        "privateBackendConfigPath": "/private/dev.s3.tfbackend",
        "privateBackendConfigSha256": "7" * 64,
        "privateTerraformTfvarsPath": "/private/terraform.tfvars",
        "privateTerraformTfvarsSha256": "8" * 64,
        "privatePlanSourceDirectory": "/private/plan-source",
        "privatePlanOutputDirectory": "/private/plan-output",
        "humanReview": {"preflightReviewed": True, "reviewedMaximumBudgetUsd": 50},
        "approval": {
            "notBeforeUtc": "2026-09-30T01:00:00Z",
            "expiresAtUtc": "2026-09-30T03:00:00Z",
            "planReviewExpiresAtUtc": "2026-09-30T09:00:00Z",
        },
        "executionBoundary": {
            "awsReadOnlyValidation": True,
            "localPrivateSourceCopy": True,
            "terraformInitReconfigure": True,
            "terraformSavedPlan": True,
            "terraformShow": True,
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


def plan_json(managed_actions=None) -> dict:
    actions = managed_actions or ["create"]
    return {
        "format_version": "1.2",
        "terraform_version": "1.14.5",
        "complete": True,
        "errored": False,
        "applyable": True,
        "resource_drift": [],
        "resource_changes": [
            {"address": "module.eks.aws_eks_cluster.this", "mode": "managed", "type": "aws_eks_cluster", "change": {"actions": actions}},
            {"address": "data.aws_caller_identity.current", "mode": "data", "type": "aws_caller_identity", "change": {"actions": ["read"]}},
        ],
        "output_changes": {"cluster_name": {"actions": ["create"]}},
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_two_hour_execution_window_is_maximum(self):
        value = request()
        value["approval"]["expiresAtUtc"] = "2026-09-30T03:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.PlanError, "at most two hours"):
            EXECUTOR.validate_request(value)

    def test_eight_hour_review_window_is_maximum(self):
        value = request()
        value["approval"]["planReviewExpiresAtUtc"] = "2026-09-30T09:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.PlanError, "at most eight hours"):
            EXECUTOR.validate_request(value)

    def test_mutating_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(EXECUTOR.PlanError, "Execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_human_review_cannot_be_removed(self):
        value = request()
        value["humanReview"]["preflightReviewed"] = False
        with self.assertRaisesRegex(EXECUTOR.PlanError, "Human review boundary changed"):
            EXECUTOR.validate_request(value)

    def test_verification_is_command_free_and_unauthorized(self):
        context = {
            "request": request(),
            "request_path": Path("/private/request.json"),
            "chain": {"entries": [{"path": "infra/terraform/aws/example.tf"}]},
            "remaining": 3600,
        }
        with patch.object(EXECUTOR, "file_sha256", return_value="9" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["terraform_init_authorized"])
        self.assertFalse(result["terraform_plan_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])


class PlanGateTests(unittest.TestCase):
    def test_exact_create_plan_is_accepted(self):
        inventory = EXECUTOR.plan_gate(plan_json())
        self.assertEqual(inventory["managedCreateCount"], 1)
        self.assertEqual(inventory["dataChangeCount"], 1)

    def test_managed_update_is_rejected(self):
        with self.assertRaisesRegex(EXECUTOR.PlanError, "not create-only"):
            EXECUTOR.plan_gate(plan_json(["update"]))

    def test_resource_drift_is_rejected(self):
        value = plan_json()
        value["resource_drift"] = [{"address": "unexpected"}]
        with self.assertRaisesRegex(EXECUTOR.PlanError, "resource drift"):
            EXECUTOR.plan_gate(value)

    def test_import_is_rejected(self):
        value = plan_json()
        value["resource_changes"][0]["change"]["importing"] = {"id": "private"}
        with self.assertRaisesRegex(EXECUTOR.PlanError, "import"):
            EXECUTOR.plan_gate(value)

    def test_missing_eks_cluster_is_rejected(self):
        value = plan_json()
        value["resource_changes"][0]["address"] = "aws_s3_bucket.unexpected"
        with self.assertRaisesRegex(EXECUTOR.PlanError, "EKS cluster"):
            EXECUTOR.plan_gate(value)

    def test_post_plan_history_requires_one_clean_lock_cycle(self):
        before = {key: 0 for key in ("stateVersions", "stateDeleteMarkers", "lockVersions", "lockDeleteMarkers", "lockLatestVersions", "lockLatestDeleteMarkers")}
        after = dict(before, lockVersions=1, lockDeleteMarkers=1, lockLatestDeleteMarkers=1)
        EXECUTOR.validate_post_plan_history(before, after)
        after["stateVersions"] = 1
        with self.assertRaisesRegex(EXECUTOR.PlanError, "wrote remote state"):
            EXECUTOR.validate_post_plan_history(before, after)


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
        staged_file = self.staging / "environments/dev/main.tf"
        staged_file.write_text("terraform {}\n")
        staged_file.chmod(0o600)
        self.backend = self.private / "dev.s3.tfbackend"
        self.backend.write_text('bucket = "private-state-bucket"\n')
        self.backend.chmod(0o600)
        self.tfvars = self.private / "terraform.tfvars"
        self.tfvars.write_text('environment = "dev"\n')
        self.tfvars.chmod(0o600)
        self.plan_source = self.private / "plan-source"
        self.output = self.private / "plan-output"
        entry = {
            "path": "infra/terraform/aws/environments/dev/main.tf",
            "gitMode": "100644",
            "sha256": hashlib.sha256(staged_file.read_bytes()).hexdigest(),
        }
        value = request()
        value["privateBackendConfigSha256"] = hashlib.sha256(self.backend.read_bytes()).hexdigest()
        value["privateTerraformTfvarsSha256"] = hashlib.sha256(self.tfvars.read_bytes()).hexdigest()
        self.context = {
            "request": value,
            "request_path": self.request_path,
            "chain": {
                "entries": [entry],
                "staging": self.staging,
                "paths": {"backend": self.backend, "tfvars": self.tfvars},
                "backend": {"bucket": "private-state-bucket"},
            },
            "plan_source": self.plan_source,
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
            return subprocess.CompletedProcess(arguments, 254, b"", b"An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation")
        if arguments[:3] == ["aws", "s3api", "list-object-versions"]:
            self.history_reads += 1
            value = {"Versions": [], "DeleteMarkers": [], "IsTruncated": False}
            if self.history_reads == 2:
                value = {
                    "Versions": [{"Key": EXECUTOR.LOCK_KEY, "VersionId": "private", "IsLatest": False}],
                    "DeleteMarkers": [{"Key": EXECUTOR.LOCK_KEY, "VersionId": "private", "IsLatest": True}],
                    "IsTruncated": False,
                }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value).encode(), b"")
        if arguments[:3] == ["terraform", "version", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"terraform_version": "1.14.5"}).encode(), b"")
        if arguments[:2] == ["terraform", "init"]:
            (Path(cwd) / ".terraform.lock.hcl").write_text("# private lock\n")
            return subprocess.CompletedProcess(arguments, 0, b"Terraform initialized\n", b"")
        if arguments[:2] == ["terraform", "plan"]:
            output_argument = next(item for item in arguments if item.startswith("-out="))
            Path(output_argument.removeprefix("-out=")).write_bytes(b"private binary plan")
            return subprocess.CompletedProcess(arguments, 0, b"Plan: 1 to add\n", b"")
        if arguments[:3] == ["terraform", "show", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(plan_json()).encode(), b"")
        if arguments[:3] == ["terraform", "show", "-no-color"]:
            return subprocess.CompletedProcess(arguments, 0, b"Plan: 1 to add, 0 to change, 0 to destroy.\n", b"")
        raise AssertionError(arguments)

    def test_execute_produces_private_saved_plan_without_apply(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN": EXECUTOR.CONFIRMATION}, clear=True),
        ):
            result = EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner, now=datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "aws-dev-clean-room-saved-create-plan-produced-awaiting-separate-apply-review")
        self.assertTrue(result["terraform_plan_executed"])
        self.assertFalse(result["terraform_apply_executed"])
        self.assertEqual(result["lock_object_version_delta"], 1)
        self.assertTrue((self.output / "aws-dev-create.tfplan").is_file())
        self.assertFalse(any(command[:2] == ["terraform", "apply"] for command in self.commands))

    def test_mutation_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_CLEAN_ROOM_CREATE_PLAN": EXECUTOR.CONFIRMATION, "CONFIRM_TERRAFORM_APPLY": "unsafe"}, clear=True),
        ):
            with self.assertRaisesRegex(EXECUTOR.PlanError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

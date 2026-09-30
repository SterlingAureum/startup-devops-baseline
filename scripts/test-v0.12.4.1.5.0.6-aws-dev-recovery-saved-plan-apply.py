#!/usr/bin/env python3
"""Offline tests for the reviewed aws-dev recovery saved-plan apply."""

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_recovery_saved_plan_apply_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "recoveryControlPlaneCommit": EXECUTOR.RECOVERY_CONTROL_PLANE_COMMIT,
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": ACCOUNT,
        "expectedAwsRegion": EXECUTOR.AWS_REGION,
        "expectedClusterName": EXECUTOR.CLUSTER_NAME,
        "expectedTerraformVersion": "1.14.5",
        "privateRecoveryRequestPath": "/private/recovery-request.json",
        "privateRecoveryRequestSha256": EXECUTOR.RECOVERY_REQUEST_SHA256,
        "privateRecoveryPlanSourceDirectory": "/private/recovery-source",
        "privateRecoveryPlanOutputDirectory": "/private/recovery-output",
        "reviewedArtifactSha256s": dict(EXECUTOR.REVIEWED_ARTIFACTS),
        "reviewedProviderLockfileSha256": EXECUTOR.PROVIDER_LOCKFILE_SHA256,
        "privateApplyOutputDirectory": "/private/apply-output",
        "humanReview": {
            "recoveryPlanReviewed": True,
            "managedCreateCount": 90,
            "dataReadOrNoopCount": 6,
            "resourceDriftCount": 0,
            "importCount": 0,
            "unexpectedResourceMutationFound": False,
            "unexpectedIamAttachmentFound": False,
            "unexplainedStderrFound": False,
            "reviewedMaximumBudgetUsd": 50,
        },
        "approval": {
            "notBeforeUtc": "2026-09-30T14:00:00Z",
            "expiresAtUtc": "2026-09-30T17:00:00Z",
            "planReviewExpiresAtUtc": EXECUTOR.PLAN_REVIEW_EXPIRES_AT,
        },
        "executionBoundary": {
            "awsReadOnlyValidation": True,
            "terraformShowExistingPlan": True,
            "exactSavedPlanApply": True,
            "terraformStateRead": True,
            "terraformInit": False,
            "terraformPlan": False,
            "unsavedApply": False,
            "stateMigration": False,
            "statePush": False,
            "destroy": False,
            "iamPolicyAttachment": False,
            "kubernetesCommand": False,
            EXECUTOR.SECRET_READ_FIELD: False,
            "directS3Mutation": False,
            "forceUnlock": False,
            "automaticRetry": False,
            "automaticRollback": False,
        },
    }


def reviewed_plan() -> tuple[dict, dict]:
    managed = [f"module.workload.aws_test_resource.item[{index}]" for index in range(89)] + ["module.eks.aws_eks_cluster.this"]
    data = [f"data.aws_test_data.item[{index}]" for index in range(6)]
    changes = [
        {"address": address, "mode": "managed", "change": {"actions": ["create"]}}
        for address in managed
    ] + [
        {"address": address, "mode": "data", "change": {"actions": ["read"]}}
        for address in data
    ]
    document = {
        "complete": True,
        "errored": False,
        "applyable": True,
        "resource_drift": [],
        "resource_changes": changes,
        "output_changes": {"cluster_name": {"actions": ["create"]}},
    }
    inventory = EXECUTOR.BASE.plan_gate(document)
    inventory["schemaVersion"] = "v0.12.4.1.5.0.5.0.1-private-create-plan-recovery-address-inventory-v1"
    return document, inventory


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_apply_window_must_end_before_review_expiry(self):
        candidate = request()
        candidate["approval"]["notBeforeUtc"] = "2026-09-30T19:00:00Z"
        candidate["approval"]["expiresAtUtc"] = "2026-09-30T21:00:00Z"
        with self.assertRaisesRegex(EXECUTOR.ApplyError, "reviewed plan"):
            EXECUTOR.validate_request(candidate)

    def test_reviewed_digest_cannot_change(self):
        candidate = request()
        candidate["reviewedArtifactSha256s"]["aws-dev-create-recovery.tfplan"] = "0" * 64
        with self.assertRaisesRegex(EXECUTOR.ApplyError, "artifact digest"):
            EXECUTOR.validate_request(candidate)

    def test_extra_mutation_authority_is_rejected(self):
        candidate = request()
        candidate["executionBoundary"]["terraformPlan"] = True
        with self.assertRaisesRegex(EXECUTOR.ApplyError, "Execution boundary"):
            EXECUTOR.validate_request(candidate)

    def test_verification_is_command_free_and_redacted(self):
        context = {"request": request(), "request_path": Path("/private/request.json"), "remaining": 3600}
        with patch.object(EXECUTOR, "file_sha256", return_value="9" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["apply_execution_authorized"])
        self.assertNotIn("management", json.dumps(result).lower())


class HistoryTests(unittest.TestCase):
    def test_exact_pre_apply_history_is_required(self):
        exact = {"stateVersions": 0, "stateDeleteMarkers": 0, "lockVersions": 2, "lockDeleteMarkers": 2, "lockLatestVersions": 0, "lockLatestDeleteMarkers": 1}
        EXECUTOR.validate_before_apply_history(exact)
        with self.assertRaisesRegex(EXECUTOR.ApplyError, "lock history"):
            EXECUTOR.validate_before_apply_history(dict(exact, lockVersions=3))

    def test_post_apply_requires_state_and_one_clean_lock_cycle(self):
        before = {"stateVersions": 0, "stateDeleteMarkers": 0, "lockVersions": 2, "lockDeleteMarkers": 2, "lockLatestVersions": 0, "lockLatestDeleteMarkers": 1}
        after = {"stateVersions": 1, "stateDeleteMarkers": 0, "lockVersions": 3, "lockDeleteMarkers": 3, "lockLatestVersions": 0, "lockLatestDeleteMarkers": 1}
        value = {
            "Versions": [{"Key": EXECUTOR.STATE_KEY, "IsLatest": True}],
            "DeleteMarkers": [{"Key": EXECUTOR.LOCK_KEY, "IsLatest": True}],
        }
        self.assertEqual(EXECUTOR.validate_after_apply_history(before, after, value), 1)
        with self.assertRaisesRegex(EXECUTOR.ApplyError, "delete marker"):
            EXECUTOR.validate_after_apply_history(before, dict(after, stateDeleteMarkers=1), value)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.source = self.private / "source"
        self.dev = self.source / "environments/dev"
        self.dev.mkdir(parents=True, mode=0o700)
        self.plan_output = self.private / "plan-output"
        self.plan_output.mkdir(mode=0o700)
        self.terraform_data = self.plan_output / "terraform-data"
        self.terraform_data.mkdir(mode=0o700)
        self.apply_output = self.private / "apply-output"
        self.request_path = self.private / "apply-request.json"
        self.request_path.write_text("{}\n")
        self.request_path.chmod(0o600)
        self.lockfile = self.dev / ".terraform.lock.hcl"
        self.lockfile.write_bytes(b"reviewed lockfile\n")
        self.lockfile.chmod(0o600)
        self.binary = self.plan_output / "aws-dev-create-recovery.tfplan"
        self.binary.write_bytes(b"reviewed binary plan\n")
        self.binary.chmod(0o600)
        self.plan, self.inventory = reviewed_plan()
        self.plan_bytes = json.dumps(self.plan, separators=(",", ":")).encode()
        self.plan_text = b"Plan: 90 to add, 0 to change, 0 to destroy.\n"
        self.artifacts = {
            "aws-dev-create-recovery.tfplan": self.binary,
            "aws-dev-create-recovery-plan.json": self.plan_output / "plan.json",
            "aws-dev-create-recovery-plan.txt": self.plan_output / "plan.txt",
            "create-plan-recovery-address-inventory.json": self.plan_output / "inventory.json",
            "create-plan-recovery-record.json": self.plan_output / "record.json",
        }
        for path in self.artifacts.values():
            if not path.exists():
                path.write_bytes(b"private evidence\n")
                path.chmod(0o600)
        value = request()
        value["privateApplyOutputDirectory"] = str(self.apply_output)
        self.context = {
            "request": value,
            "request_path": self.request_path,
            "output": self.apply_output,
            "remaining": 7200,
            "evidence": {
                "source": self.source,
                "output": self.plan_output,
                "terraform_data": self.terraform_data,
                "lockfile": self.lockfile,
                "artifacts": self.artifacts,
                "inventory": self.inventory,
                "incident": {"chain": {"backend": {"bucket": "private-state-bucket"}}},
            },
        }
        self.expected = set(self.inventory["managedCreateAddresses"]) | set(self.inventory["dataReadOrNoopAddresses"])
        resources = [{"address": address} for address in sorted(self.expected)]
        self.state_show = {"values": {"root_module": {"resources": resources}}}
        self.history_reads = 0
        self.commands: list[list[str]] = []

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, arguments, _environment, _timeout, _cwd):
        self.commands.append(arguments)
        if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Account": ACCOUNT}).encode(), b"")
        if arguments[:3] == ["aws", "eks", "describe-cluster"]:
            if self.history_reads == 0:
                return subprocess.CompletedProcess(arguments, 254, b"", b"An error occurred (ResourceNotFoundException) when calling DescribeCluster")
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"cluster": {"name": EXECUTOR.CLUSTER_NAME, "status": "ACTIVE"}}).encode(), b"")
        if arguments[:3] == ["aws", "s3api", "list-object-versions"]:
            self.history_reads += 1
            before = self.history_reads == 1
            versions = [{"Key": EXECUTOR.LOCK_KEY, "VersionId": f"private-{index}", "IsLatest": False} for index in range(2 if before else 3)]
            if not before:
                versions.append({"Key": EXECUTOR.STATE_KEY, "VersionId": "private-state", "IsLatest": True})
            markers = [{"Key": EXECUTOR.LOCK_KEY, "VersionId": f"private-marker-{index}", "IsLatest": index == (1 if before else 2)} for index in range(2 if before else 3)]
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Versions": versions, "DeleteMarkers": markers, "IsTruncated": False}).encode(), b"")
        if arguments[:3] == ["terraform", "version", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"terraform_version": "1.14.5"}).encode(), b"")
        if arguments[:3] == ["terraform", "show", "-json"] and len(arguments) == 4:
            return subprocess.CompletedProcess(arguments, 0, self.plan_bytes, b"")
        if arguments[:3] == ["terraform", "show", "-no-color"]:
            return subprocess.CompletedProcess(arguments, 0, self.plan_text, b"")
        if arguments[:2] == ["terraform", "apply"]:
            return subprocess.CompletedProcess(arguments, 0, b"Apply complete! Resources: 90 added, 0 changed, 0 destroyed.\n", b"")
        if arguments[:3] == ["terraform", "state", "pull"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"version": 4, "terraform_version": "1.14.5", "serial": 1, "lineage": "private-lineage", "outputs": {}, "resources": []}).encode(), b"")
        if arguments[:3] == ["terraform", "state", "list"]:
            return subprocess.CompletedProcess(arguments, 0, ("\n".join(sorted(self.expected)) + "\n").encode(), b"")
        if arguments[:3] == ["terraform", "show", "-json"] and len(arguments) == 3:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(self.state_show).encode(), b"")
        raise AssertionError(arguments)

    def test_execute_applies_exact_plan_once_without_init_or_plan(self):
        reviewed = dict(EXECUTOR.REVIEWED_ARTIFACTS)
        reviewed["aws-dev-create-recovery.tfplan"] = EXECUTOR.file_sha256(self.binary)
        reviewed["aws-dev-create-recovery-plan.json"] = EXECUTOR.hashlib.sha256(self.plan_bytes).hexdigest()
        reviewed["aws-dev-create-recovery-plan.txt"] = EXECUTOR.hashlib.sha256(self.plan_text).hexdigest()
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.object(EXECUTOR, "REVIEWED_ARTIFACTS", reviewed),
            patch.object(EXECUTOR, "PROVIDER_LOCKFILE_SHA256", EXECUTOR.file_sha256(self.lockfile)),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY": EXECUTOR.CONFIRMATION}, clear=True),
        ):
            result = EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner, now=datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "aws-dev-recovery-saved-plan-applied-and-read-only-validated")
        apply_commands = [command for command in self.commands if command[:2] == ["terraform", "apply"]]
        self.assertEqual(len(apply_commands), 1)
        self.assertEqual(apply_commands[0][-1], str(self.binary))
        self.assertFalse(any(command[:2] == ["terraform", "init"] for command in self.commands))
        self.assertFalse(any(command[:2] == ["terraform", "plan"] for command in self.commands))

    def test_other_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_RECOVERY_SAVED_PLAN_APPLY": EXECUTOR.CONFIRMATION, "CONFIRM_STATE_PUSH": "unsafe"}, clear=True),
        ):
            with self.assertRaisesRegex(EXECUTOR.ApplyError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

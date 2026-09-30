#!/usr/bin/env python3
"""Offline tests for the aws-dev post-apply read-only recovery."""

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_post_apply_recovery_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": ACCOUNT,
        "expectedTerraformVersion": "1.14.5",
        "privateApplyRequestPath": "/private/apply-request.json",
        "privateRecoveryPlanOutputDirectory": "/private/plan-output",
        "privateApplyOutputDirectory": "/private/apply-output",
        "privatePostApplyRecoveryOutputDirectory": "/private/recovery-output",
        "expectedIncidentArtifactSha256s": {
            "terraform-apply-reviewed-recovery-plan.stdout": "2" * 64,
            "s3-object-history-before-apply.stdout": "3" * 64,
            "terraform-state-list-after-apply.stdout": "4" * 64,
        },
        "evidenceBoundary": {
            "applyControlPlaneCommit": EXECUTOR.APPLY_CONTROL_PLANE_COMMIT,
            "privateApplyRequestSha256": EXECUTOR.APPLY_REQUEST_SHA256,
            "applySucceeded": True,
            "applySummary": "90 added, 0 changed, 0 destroyed.",
            "applyStderrSha256": EXECUTOR.EMPTY_SHA256,
            "stateSha256": EXECUTOR.STATE_SHA256,
            "stateLineageSha256": EXECUTOR.STATE_LINEAGE_SHA256,
            "stateSerial": 9,
            "reviewedManagedAddressCount": 90,
            "reviewedDataAddressCount": 6,
            "priorStateDataAddressCount": 7,
            "priorStateDataAddressSha256": EXECUTOR.PRIOR_STATE_DATA_SHA256,
            "totalStateAddressCount": 103,
            "totalStateAddressSha256": EXECUTOR.STATE_ADDRESS_INVENTORY_SHA256,
            "unexplainedAddressCount": 0,
        },
        "approval": {
            "notBeforeUtc": "2026-09-30T14:00:00Z",
            "expiresAtUtc": "2026-09-30T17:00:00Z",
        },
        "executionBoundary": {
            "awsIdentityRead": True,
            "eksDescribeCluster": True,
            "s3ObjectHistoryRead": True,
            "terraformVersionRead": True,
            "terraformStatePull": True,
            "terraformStateList": True,
            "terraformShowState": True,
            "terraformInit": False,
            "terraformPlan": False,
            "terraformApply": False,
            "terraformDestroy": False,
            "statePush": False,
            "stateMigration": False,
            "directS3Mutation": False,
            "forceUnlock": False,
            "iamPolicyAttachment": False,
            "kubernetesCommand": False,
            EXECUTOR.SECRET_READ_FIELD: False,
            "automaticRetry": False,
            "automaticRollback": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_mutation_authority_is_rejected(self):
        candidate = request()
        candidate["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Execution boundary"):
            EXECUTOR.validate_request(candidate)

    def test_window_is_limited_to_three_hours(self):
        candidate = request()
        candidate["approval"]["expiresAtUtc"] = "2026-09-30T18:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "at most three hours"):
            EXECUTOR.validate_request(candidate)

    def test_verification_is_command_free_and_redacted(self):
        context = {"request": request(), "request_path": Path("/private/request.json"), "remaining": 3600}
        with patch.object(EXECUTOR, "file_sha256", return_value="9" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertEqual(result["unexplained_address_count"], 0)


class EvidenceTests(unittest.TestCase):
    def test_value_address_collection_preserves_modes(self):
        module = {
            "resources": [
                {"address": "aws_test.one", "mode": "managed"},
                {"address": "data.aws_test.two", "mode": "data"},
            ],
            "child_modules": [{"resources": [{"address": "module.child.data.aws_test.three", "mode": "data"}]}],
        }
        managed, data = EXECUTOR.collect_value_addresses(module)
        self.assertEqual(managed, {"aws_test.one"})
        self.assertEqual(data, {"data.aws_test.two", "module.child.data.aws_test.three"})

    def test_address_digest_is_order_independent(self):
        self.assertEqual(EXECUTOR.address_digest({"b", "a"}), EXECUTOR.address_digest({"a", "b"}))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.source = self.private / "source"
        self.dev = self.source / "environments/dev"
        self.dev.mkdir(parents=True, mode=0o700)
        self.plan_output = self.private / "plan-output"
        self.plan_output.mkdir(mode=0o700)
        self.terraform_data = self.plan_output / "terraform-data"
        self.terraform_data.mkdir(mode=0o700)
        self.apply_output = self.private / "apply-output"
        self.apply_output.mkdir(mode=0o700)
        self.recovery_output = self.private / "recovery-output"
        self.request_path = self.private / "recovery-request.json"
        self.request_path.write_text("{}\n")
        self.request_path.chmod(0o600)

        self.managed = {f"aws_test_resource.item[{index}]" for index in range(90)}
        self.reviewed_data = {f"data.aws_test.reviewed[{index}]" for index in range(6)}
        self.prior_data = {f"data.aws_test.prior[{index}]" for index in range(7)}
        self.expected = self.managed | self.reviewed_data | self.prior_data
        resources = [
            {"mode": "managed", "type": "aws_test_resource", "name": "item", "instances": [{"index_key": index}]}
            for index in range(90)
        ] + [
            {"mode": "data", "type": "aws_test", "name": "reviewed", "instances": [{"index_key": index}]}
            for index in range(6)
        ] + [
            {"mode": "data", "type": "aws_test", "name": "prior", "instances": [{"index_key": index}]}
            for index in range(7)
        ]
        self.lineage = "private-lineage"
        self.state = {
            "version": 4,
            "terraform_version": "1.14.5",
            "serial": 9,
            "lineage": self.lineage,
            "outputs": {},
            "resources": resources,
        }
        self.state_bytes = json.dumps(self.state, separators=(",", ":")).encode()
        self.state_show = {"values": {"root_module": {"resources": [{"address": address} for address in sorted(self.expected)]}}}
        self.commands: list[list[str]] = []

        value = request()
        value["privatePostApplyRecoveryOutputDirectory"] = str(self.recovery_output)
        self.context = {
            "request": value,
            "request_path": self.request_path,
            "output": self.recovery_output,
            "remaining": 7200,
            "incident": {
                "apply_output": self.apply_output,
                "expected_addresses": self.expected,
                "before_counts": {
                    "stateVersions": 0,
                    "stateDeleteMarkers": 0,
                    "lockVersions": 2,
                    "lockDeleteMarkers": 2,
                    "lockLatestVersions": 0,
                    "lockLatestDeleteMarkers": 1,
                },
                "plan_evidence": {
                    "source": self.source,
                    "output": self.plan_output,
                    "terraform_data": self.terraform_data,
                    "incident": {"chain": {"backend": {"bucket": "private-state-bucket"}}},
                },
            },
        }

    def tearDown(self):
        self.temp.cleanup()

    def runner(self, arguments, _environment, _timeout, _cwd):
        self.commands.append(arguments)
        if arguments[:3] == ["aws", "sts", "get-caller-identity"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Account": ACCOUNT}).encode(), b"")
        if arguments[:3] == ["terraform", "version", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"terraform_version": "1.14.5"}).encode(), b"")
        if arguments[:3] == ["terraform", "state", "pull"]:
            return subprocess.CompletedProcess(arguments, 0, self.state_bytes, b"")
        if arguments[:3] == ["terraform", "state", "list"]:
            return subprocess.CompletedProcess(arguments, 0, ("\n".join(sorted(self.expected)) + "\n").encode(), b"")
        if arguments[:3] == ["terraform", "show", "-json"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(self.state_show).encode(), b"")
        if arguments[:3] == ["aws", "eks", "describe-cluster"]:
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"cluster": {"name": EXECUTOR.APPLY.CLUSTER_NAME, "status": "ACTIVE"}}).encode(), b"")
        if arguments[:3] == ["aws", "s3api", "list-object-versions"]:
            versions = [{"Key": EXECUTOR.APPLY.STATE_KEY, "VersionId": f"state-{index}", "IsLatest": index == 8} for index in range(9)]
            versions += [{"Key": EXECUTOR.APPLY.LOCK_KEY, "VersionId": f"lock-{index}", "IsLatest": False} for index in range(3)]
            markers = [{"Key": EXECUTOR.APPLY.LOCK_KEY, "VersionId": f"marker-{index}", "IsLatest": index == 2} for index in range(3)]
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"Versions": versions, "DeleteMarkers": markers, "IsTruncated": False}).encode(), b"")
        raise AssertionError(arguments)

    def test_execute_is_read_only_and_completes_post_apply_validation(self):
        inventory_digest = EXECUTOR.address_digest(self.expected)
        state_digest = hashlib.sha256(self.state_bytes).hexdigest()
        lineage_digest = hashlib.sha256(self.lineage.encode()).hexdigest()
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.object(EXECUTOR, "STATE_ADDRESS_INVENTORY_SHA256", inventory_digest),
            patch.object(EXECUTOR, "STATE_SHA256", state_digest),
            patch.object(EXECUTOR, "STATE_LINEAGE_SHA256", lineage_digest),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY": EXECUTOR.CONFIRMATION}, clear=True),
        ):
            result = EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner, now=datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "aws-dev-saved-plan-apply-recovered-and-read-only-validated")
        self.assertFalse(result["terraform_apply_executed_by_recovery"])
        self.assertTrue(result["eks_cluster_active"])
        self.assertFalse(any(command[:2] == ["terraform", "apply"] for command in self.commands))
        self.assertFalse(any(command[:2] == ["terraform", "init"] for command in self.commands))
        self.assertFalse(any(command[:2] == ["terraform", "plan"] for command in self.commands))

    def test_mutation_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {
                "CONFIRM_AWS_DEV_POST_APPLY_READ_ONLY_RECOVERY": EXECUTOR.CONFIRMATION,
                "CONFIRM_TERRAFORM_APPLY": "unsafe",
            }, clear=True),
        ):
            with self.assertRaisesRegex(EXECUTOR.RecoveryError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

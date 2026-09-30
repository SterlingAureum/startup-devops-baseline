#!/usr/bin/env python3
"""Offline tests for aws-dev semantic-state recovery."""

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("aws_dev_semantic_state_recovery_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()
ACCOUNT = "123456789012"


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": ACCOUNT,
        "expectedTerraformVersion": "1.14.5",
        "privatePriorRecoveryRequestPath": "/private/prior-request.json",
        "privatePriorRecoveryOutputDirectory": "/private/prior-output",
        "privateRecoveryOutputDirectory": "/private/recovery-output",
        "evidenceBoundary": {
            "priorRecoveryControlPlaneCommit": EXECUTOR.PRIOR_CONTROL_PLANE_COMMIT,
            "privatePriorRecoveryRequestSha256": EXECUTOR.PRIOR_RECOVERY_REQUEST_SHA256,
            "privateApplyRequestSha256": EXECUTOR.PRIOR.APPLY_REQUEST_SHA256,
            "preservedStateSha256": EXECUTOR.PRIOR.STATE_SHA256,
            "priorPulledStateSha256": EXECUTOR.PRIOR_PULLED_STATE_SHA256,
            "stateLineageSha256": EXECUTOR.PRIOR.STATE_LINEAGE_SHA256,
            "stateSerial": 9,
            "managedStateAddressCount": 90,
            "reviewedDataStateAddressCount": 6,
            "priorStateDataAddressCount": 7,
            "totalStateAddressCount": 103,
            "stateAddressInventorySha256": EXECUTOR.PRIOR.STATE_ADDRESS_INVENTORY_SHA256,
            "normalizedCheckResultsSha256": EXECUTOR.NORMALIZED_CHECK_RESULTS_SHA256,
            "checkResultCount": 28,
            "checkStatusHistogram": {"pass": 56},
            "checkObjectKindHistogram": {"resource": 4, "var": 24},
            "semanticStateEqual": True,
            "unexplainedAddressCount": 0,
        },
        "approval": {"notBeforeUtc": "2026-09-30T16:00:00Z", "expiresAtUtc": "2026-09-30T19:00:00Z"},
        "executionBoundary": {
            "awsIdentityRead": True, "eksDescribeCluster": True, "s3ObjectHistoryRead": True,
            "terraformVersionRead": True, "terraformStatePull": True, "terraformStateList": True,
            "terraformShowState": True, "terraformInit": False, "terraformPlan": False,
            "terraformApply": False, "terraformDestroy": False, "statePush": False,
            "stateMigration": False, "directS3Mutation": False, "forceUnlock": False,
            "iamPolicyAttachment": False, "kubernetesCommand": False,
            EXECUTOR.SECRET_READ_FIELD: False, "automaticRetry": False, "automaticRollback": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_apply_authority_is_rejected(self):
        candidate = request()
        candidate["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Execution boundary"):
            EXECUTOR.validate_request(candidate)

    def test_semantic_evidence_cannot_be_relaxed(self):
        candidate = request()
        candidate["evidenceBoundary"]["semanticStateEqual"] = False
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Evidence boundary"):
            EXECUTOR.validate_request(candidate)

    def test_verification_is_command_free(self):
        context = {"request": request(), "request_path": Path("/private/request.json"), "remaining": 3600}
        with patch.object(EXECUTOR, "file_sha256", return_value="9" * 64):
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertTrue(result["semantic_state_equal"])


class SemanticTests(unittest.TestCase):
    def test_check_result_order_is_ignored(self):
        first = {"check_results": [{"status": "pass", "object_kind": "var"}, {"status": "pass", "object_kind": "resource"}]}
        second = {"check_results": list(reversed(first["check_results"]))}
        with (
            patch.object(EXECUTOR, "CHECK_RESULT_COUNT", 2),
            patch.object(EXECUTOR, "CHECK_STATUS_HISTOGRAM", {"pass": 2}),
            patch.object(EXECUTOR, "CHECK_OBJECT_KIND_HISTOGRAM", {"resource": 1, "var": 1}),
            patch.object(EXECUTOR, "NORMALIZED_CHECK_RESULTS_SHA256", hashlib.sha256(EXECUTOR.compact_json(EXECUTOR.normalize_unordered(first["check_results"]))).hexdigest()),
        ):
            self.assertEqual(EXECUTOR.semantic_state(first), EXECUTOR.semantic_state(second))

    def test_non_check_state_change_is_not_ignored(self):
        first = {"serial": 9, "check_results": []}
        second = {"serial": 10, "check_results": []}
        digest = hashlib.sha256(EXECUTOR.compact_json([])).hexdigest()
        with (
            patch.object(EXECUTOR, "CHECK_RESULT_COUNT", 0),
            patch.object(EXECUTOR, "CHECK_STATUS_HISTOGRAM", {}),
            patch.object(EXECUTOR, "CHECK_OBJECT_KIND_HISTOGRAM", {}),
            patch.object(EXECUTOR, "NORMALIZED_CHECK_RESULTS_SHA256", digest),
        ):
            self.assertNotEqual(EXECUTOR.semantic_state(first), EXECUTOR.semantic_state(second))


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
        self.prior_output = self.private / "prior-output"
        self.prior_output.mkdir(mode=0o700)
        self.output = self.private / "output"
        self.request_path = self.private / "request.json"
        self.request_path.write_text("{}\n")
        self.request_path.chmod(0o600)
        self.managed = {f"aws_test.item[{index}]" for index in range(90)}
        self.data = {f"data.aws_test.item[{index}]" for index in range(13)}
        self.expected = self.managed | self.data
        resources = [
            {"mode": "managed", "type": "aws_test", "name": "item", "instances": [{"index_key": index}]}
            for index in range(90)
        ] + [
            {"mode": "data", "type": "aws_test", "name": "item", "instances": [{"index_key": index}]}
            for index in range(13)
        ]
        self.checks = [{"object_kind": "var", "status": "pass", "objects": [{"status": "pass"}]}]
        self.state = {"version": 4, "terraform_version": "1.14.5", "serial": 9, "lineage": "private-lineage", "outputs": {}, "resources": resources, "check_results": self.checks}
        self.state_bytes = json.dumps(self.state, separators=(",", ":")).encode()
        self.state_show = {"values": {"root_module": {"resources": [{"address": address} for address in sorted(self.expected)]}}}
        value = request()
        value["privateRecoveryOutputDirectory"] = str(self.output)
        self.context = {
            "request": value, "request_path": self.request_path, "output": self.output, "remaining": 7200,
            "prior": {
                "prior_state": self.state,
                "prior_output": self.prior_output,
                "incident": {
                    "expected_addresses": self.expected,
                    "before_counts": {"stateVersions": 0, "stateDeleteMarkers": 0, "lockVersions": 2, "lockDeleteMarkers": 2, "lockLatestVersions": 0, "lockLatestDeleteMarkers": 1},
                    "apply_output": self.apply_output,
                    "plan_evidence": {"source": self.source, "output": self.plan_output, "terraform_data": self.terraform_data, "incident": {"chain": {"backend": {"bucket": "private-state-bucket"}}}},
                },
            },
        }
        self.commands: list[list[str]] = []

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

    def test_execute_completes_without_mutation_command(self):
        check_digest = hashlib.sha256(EXECUTOR.compact_json(EXECUTOR.normalize_unordered(self.checks))).hexdigest()
        lineage_digest = hashlib.sha256(b"private-lineage").hexdigest()
        inventory_digest = EXECUTOR.PRIOR.address_digest(self.expected)
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.object(EXECUTOR, "CHECK_RESULT_COUNT", 1),
            patch.object(EXECUTOR, "CHECK_STATUS_HISTOGRAM", {"pass": 2}),
            patch.object(EXECUTOR, "CHECK_OBJECT_KIND_HISTOGRAM", {"var": 1}),
            patch.object(EXECUTOR, "NORMALIZED_CHECK_RESULTS_SHA256", check_digest),
            patch.object(EXECUTOR.PRIOR, "STATE_LINEAGE_SHA256", lineage_digest),
            patch.object(EXECUTOR.PRIOR, "STATE_ADDRESS_INVENTORY_SHA256", inventory_digest),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_SEMANTIC_STATE_RECOVERY": EXECUTOR.CONFIRMATION}, clear=True),
        ):
            result = EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner, now=datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "aws-dev-saved-plan-apply-semantically-validated")
        self.assertFalse(result["terraform_apply_executed_by_recovery"])
        self.assertFalse(any(command[:2] in (["terraform", "apply"], ["terraform", "plan"], ["terraform", "init"]) for command in self.commands))

    def test_mutation_confirmation_stops_before_commands(self):
        with (
            patch.object(EXECUTOR, "verify_inputs", return_value=self.context),
            patch.dict(os.environ, {"CONFIRM_AWS_DEV_SEMANTIC_STATE_RECOVERY": EXECUTOR.CONFIRMATION, "CONFIRM_TERRAFORM_APPLY": "unsafe"}, clear=True),
        ):
            with self.assertRaisesRegex(EXECUTOR.RecoveryError, "must be unset"):
                EXECUTOR.execute(self.request_path, repository_root=self.repo, runner=self.runner)
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

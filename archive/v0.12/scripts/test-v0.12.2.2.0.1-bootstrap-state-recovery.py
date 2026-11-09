#!/usr/bin/env python3
"""Offline tests for v0.12.2.2.0.1 state identity-rebase recovery."""

from __future__ import annotations

from contextlib import ExitStack
import copy
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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.2.0.1-bootstrap-state-recovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bootstrap_identity_rebase_recovery_tests", EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load recovery executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.2.0.1-bootstrap-state-recovery-request-v1",
        "operation": EXECUTOR.RECOVERY_CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedRecoveryMainCommit": "1" * 40,
        "incidentControlPlaneCommit": EXECUTOR.INCIDENT_MAIN_COMMIT,
        "expectedAwsAccountId": "1" * 12,
        "privateMigrationRequestPath": "/private/migration-request.json",
        "privateMigrationRequestSha256": EXECUTOR.MIGRATION_REQUEST_SHA256,
        "privateMigrationOutputDirectory": "/private/migration-output",
        "privateRecoveryOutputDirectory": "/private/recovery-output",
        "approval": {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsReadOnlyValidation": True, "terraformStatePull": True,
            "terraformStateList": True, "s3ObjectRead": True,
            "terraformInit": False, "terraformPlan": False, "terraformApply": False,
            "stateMigration": False, "statePush": False, "destroy": False,
            "iamPolicyAttachment": False, "automaticRetry": False, "automaticRollback": False,
        },
    }


def states() -> tuple[dict, dict, set[str], set[str]]:
    resources = []
    managed = set()
    data = set()
    for index in range(13):
        resources.append({"mode": "managed", "type": "aws_test_resource", "name": f"item_{index}", "instances": [{}]})
        managed.add(f"aws_test_resource.item_{index}")
    for index in range(9):
        resources.append({"mode": "data", "type": "aws_test_data", "name": f"item_{index}", "instances": [{}]})
        data.add(f"data.aws_test_data.item_{index}")
    common = {
        "version": 4, "terraform_version": "1.14.5",
        "outputs": {"safe": {"value": "same", "type": "string"}},
        "resources": resources,
    }
    backup = {**common, "serial": 20, "lineage": "old-lineage", "check_results": [{"old": 1}, {"old": 2}]}
    remote = {**copy.deepcopy(common), "serial": 1, "lineage": "new-lineage", "check_results": [{"new": 1}, {"new": 2}]}
    return backup, remote, managed, data


def transition_context(backup, remote, managed, data):
    stack = ExitStack()
    stack.enter_context(patch.object(EXECUTOR, "OLD_LINEAGE_SHA256", hashlib.sha256(b"old-lineage").hexdigest()))
    stack.enter_context(patch.object(EXECUTOR, "NEW_LINEAGE_SHA256", hashlib.sha256(b"new-lineage").hexdigest()))
    stack.enter_context(patch.object(EXECUTOR, "RESOURCES_SHA256", EXECUTOR.compact_digest(backup["resources"])))
    stack.enter_context(patch.object(EXECUTOR, "OUTPUTS_SHA256", EXECUTOR.compact_digest(backup["outputs"])))
    stack.enter_context(patch.object(EXECUTOR, "BACKUP_CHECK_RESULTS_SHA256", EXECUTOR.compact_digest(backup["check_results"])))
    stack.enter_context(patch.object(EXECUTOR, "REMOTE_CHECK_RESULTS_SHA256", EXECUTOR.compact_digest(remote["check_results"])))
    stack.enter_context(patch.object(EXECUTOR, "SEMANTIC_PROJECTION_SHA256", EXECUTOR.compact_digest(EXECUTOR.semantic_projection(backup))))
    stack.enter_context(patch.object(EXECUTOR.PLAN_GATE, "EXPECTED_MANAGED_ADDRESSES", managed))
    stack.enter_context(patch.object(EXECUTOR.PLAN_GATE, "ALLOWED_DATA_ADDRESSES", data))
    return stack


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.RECOVERY_CONFIRMATION)

    def test_migration_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["stateMigration"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_init_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformInit"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_incident_digest_mutation_is_rejected(self):
        value = request()
        value["privateMigrationRequestSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Migration request digest changed"):
            EXECUTOR.validate_request(value)


class DigestTests(unittest.TestCase):
    def test_compact_digest_includes_one_trailing_lf(self):
        expected = hashlib.sha256(b'{"a":1}\n').hexdigest()
        self.assertEqual(EXECUTOR.compact_digest({"a": 1}), expected)


class TransitionTests(unittest.TestCase):
    def test_exact_identity_rebase_is_accepted(self):
        backup, remote, managed, data = states()
        with transition_context(backup, remote, managed, data):
            result = EXECUTOR.validate_identity_rebase(backup, remote)
        self.assertEqual(result["old_serial"], 20)
        self.assertEqual(result["new_serial"], 1)
        self.assertEqual(result["managed"], managed)

    def test_resource_drift_is_rejected(self):
        backup, remote, managed, data = states()
        remote["resources"][0]["instances"][0]["attributes"] = {"changed": True}
        with transition_context(backup, remote, managed, data):
            with self.assertRaisesRegex(ValueError, "resources changed"):
                EXECUTOR.validate_identity_rebase(backup, remote)

    def test_output_drift_is_rejected(self):
        backup, remote, managed, data = states()
        remote["outputs"] = {"safe": {"value": "changed", "type": "string"}}
        with transition_context(backup, remote, managed, data):
            with self.assertRaisesRegex(ValueError, "outputs changed"):
                EXECUTOR.validate_identity_rebase(backup, remote)

    def test_unreviewed_lineage_is_rejected(self):
        backup, remote, managed, data = states()
        remote["lineage"] = "third-lineage"
        with transition_context(backup, remote, managed, data):
            with self.assertRaisesRegex(ValueError, "lineage rebase changed"):
                EXECUTOR.validate_identity_rebase(backup, remote)


class ExecutionTests(unittest.TestCase):
    def test_verify_result_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text("{}\n")
            transition = {
                "old_lineage_sha256": "a" * 64, "new_lineage_sha256": "b" * 64,
                "old_serial": 20, "new_serial": 1, "managed": set(range(13)),
                "data": set(range(9)), "semantic_projection_sha256": "c" * 64,
            }
            context = {"request": {"expectedRecoveryMainCommit": "1" * 40}, "request_path": path, "transition": transition, "remaining": 1800}
            result = EXECUTOR.redacted_verification(context)
            self.assertEqual(result["operational_commands_executed"], [])
            self.assertFalse(result["recovery_execution_authorized"])
            self.assertFalse(result["terraform_init_authorized"])
            self.assertFalse(result["state_migration_authorized"])

    def test_execute_completes_only_read_only_continuation(self):
        backup, remote, managed, data = states()
        remote_bytes = EXECUTOR.canonical_json(remote)
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            output = private / "recovery-output"
            working = private / "migration-source"
            working.mkdir(mode=0o700)
            terraform_data = private / "terraform-data"
            terraform_data.mkdir(mode=0o700)
            backup_path = private / "backup.tfstate"
            backup_path.write_bytes(EXECUTOR.canonical_json(backup))
            backup_path.chmod(0o600)
            request_path = private / "request.json"
            request_path.write_text("{}\n")
            request_path.chmod(0o600)
            transition = {
                "old_lineage_sha256": hashlib.sha256(b"old-lineage").hexdigest(),
                "new_lineage_sha256": hashlib.sha256(b"new-lineage").hexdigest(),
                "old_serial": 20, "new_serial": 1, "managed": managed, "data": data,
                "resources_sha256": EXECUTOR.compact_digest(backup["resources"]),
                "outputs_sha256": EXECUTOR.compact_digest(backup["outputs"]),
                "semantic_projection_sha256": EXECUTOR.compact_digest(EXECUTOR.semantic_projection(backup)),
                "remote_check_results_sha256": EXECUTOR.compact_digest(remote["check_results"]),
            }
            context = {
                "request": {"expectedRecoveryMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12},
                "request_path": request_path, "recovery_output": output,
                "working": working, "terraform_data": terraform_data,
                "plan_request": {}, "backup": backup_path, "transition": transition,
                "identities": {"bucket": "bucket", "kms_arn": "kms"},
                "backend_values": {"key": "bootstrap/terraform.tfstate"},
            }
            calls = []

            def runner(arguments, environment, timeout, cwd):
                calls.append(arguments)
                if arguments[-2:] == ["state", "pull"]:
                    return subprocess.CompletedProcess(arguments, 0, remote_bytes, b"")
                if arguments[-2:] == ["state", "list"]:
                    return subprocess.CompletedProcess(arguments, 0, ("\n".join(sorted(managed | data)) + "\n").encode(), b"")
                if "head-object" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, b'{"ServerSideEncryption":"aws:kms","SSEKMSKeyId":"kms","BucketKeyEnabled":true,"VersionId":"version-1"}\n', b"")
                if "list-object-versions" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, b'{"Versions":[{"Key":"bootstrap/terraform.tfstate","VersionId":"version-1","IsLatest":true}],"DeleteMarkers":[]}\n', b"")
                return subprocess.CompletedProcess(arguments, 0, b'{"Account":"111111111111"}\n', b"")

            with transition_context(backup, remote, managed, data), patch.object(
                EXECUTOR, "verify_inputs", return_value=context
            ), patch.object(EXECUTOR, "REMOTE_STATE_SHA256", hashlib.sha256(remote_bytes).hexdigest()), patch.object(
                EXECUTOR, "safe_environment", return_value={}
            ), patch.dict(os.environ, {"CONFIRM_STATE_BOOTSTRAP_IDENTITY_REBASE_RECOVERY": EXECUTOR.RECOVERY_CONFIRMATION}, clear=True):
                result = EXECUTOR.execute(request_path, repository_root=private, runner=runner, now=datetime(2026, 9, 26, tzinfo=timezone.utc))

            self.assertEqual(len(calls), 5)
            self.assertFalse(any("init" in call or "plan" in call or "apply" in call for call in calls))
            self.assertTrue(result["prior_terraform_init_succeeded"])
            self.assertFalse(result["terraform_init_reexecuted"])
            self.assertFalse(result["state_migration_reexecuted"])
            self.assertFalse(result["automatic_retry_performed"])

    def test_state_version_gate_rejects_delete_marker(self):
        value = {
            "Versions": [{"Key": "bootstrap/terraform.tfstate", "VersionId": "v1", "IsLatest": True}],
            "DeleteMarkers": [{"Key": "bootstrap/terraform.tfstate", "VersionId": "v2"}],
        }
        with self.assertRaisesRegex(ValueError, "delete marker"):
            EXECUTOR.exact_state_versions(value, "bootstrap/terraform.tfstate", "v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)

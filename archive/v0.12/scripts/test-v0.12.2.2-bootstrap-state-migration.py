#!/usr/bin/env python3
"""Offline tests for the guarded v0.12.2.2 bootstrap state migration."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.2-bootstrap-state-migration.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("bootstrap_migration_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.2-bootstrap-state-migration-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "1" * 12,
        "privatePreflightRequestPath": "/private/preflight-request.json",
        "privatePreflightRequestSha256": EXECUTOR.EXPECTED_PREFLIGHT_REQUEST_SHA256,
        "privatePreflightOutputDirectory": "/private/preflight-output",
        "preflightResultSha256": EXECUTOR.EXPECTED_PREFLIGHT_RESULT_SHA256,
        "stateInventorySha256": EXECUTOR.EXPECTED_STATE_INVENTORY_SHA256,
        "migrationSourceManifestSha256": EXECUTOR.EXPECTED_SOURCE_MANIFEST_SHA256,
        "migrationCommandPlanSha256": EXECUTOR.EXPECTED_COMMAND_PLAN_SHA256,
        "immutableBackupSha256": EXECUTOR.EXPECTED_STATE_SHA256,
        "resourceIdentitySha256": EXECUTOR.EXPECTED_RESOURCE_IDENTITY_SHA256,
        "preflightLiveValidationSha256": EXECUTOR.EXPECTED_PREFLIGHT_LIVE_SHA256,
        "privateMigrationOutputDirectory": "/private/migration-output",
        "approval": {"notBeforeUtc": "2026-09-25T00:00:00Z", "expiresAtUtc": "2026-09-25T01:00:00Z"},
        "executionBoundary": {
            "terraformInitMigrateState": True, "terraformPlan": False,
            "terraformApply": False, "stateMigration": True, "statePush": False,
            "destroy": False, "iamPolicyAttachment": False, "automaticRetry": False,
            "localBackupDeletion": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_preflight_digest_mutation_is_rejected(self):
        value = request()
        value["preflightResultSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Reviewed preflight digest changed"):
            EXECUTOR.validate_request(value)

    def test_apply_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_retry_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["automaticRetry"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)


class CommandPlanTests(unittest.TestCase):
    def test_exact_reviewed_command_is_accepted(self):
        working = Path("/private/preflight/migration-source")
        backend = Path("/private/backend.tfbackend")
        command = ["terraform", f"-chdir={working}", "init", "-input=false", "-migrate-state", "-force-copy", f"-backend-config={backend}"]
        plan = {
            "schemaVersion": "v0.12.2.1-bootstrap-migration-command-plan-v1",
            "workingDirectory": str(working), "backendConfigPath": str(backend),
            "command": command, "expectedRemoteKey": "bootstrap/terraform.tfstate",
            "expectedManagedAddressCount": 13, "requiresSeparateV01222Approval": True,
            "executedByThisPreflight": False,
        }
        self.assertEqual(EXECUTOR.exact_command_plan(plan, working, backend), command)

    def test_unreviewed_command_flag_is_rejected(self):
        working = Path("/private/preflight/migration-source")
        backend = Path("/private/backend.tfbackend")
        plan = {
            "schemaVersion": "v0.12.2.1-bootstrap-migration-command-plan-v1",
            "workingDirectory": str(working), "backendConfigPath": str(backend),
            "command": ["terraform", f"-chdir={working}", "init", "-reconfigure", f"-backend-config={backend}"],
            "expectedRemoteKey": "bootstrap/terraform.tfstate", "expectedManagedAddressCount": 13,
            "requiresSeparateV01222Approval": True, "executedByThisPreflight": False,
        }
        with self.assertRaisesRegex(ValueError, "Reviewed migration command changed"):
            EXECUTOR.exact_command_plan(plan, working, backend)


class ExecutionTests(unittest.TestCase):
    def test_verify_output_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text("{}\n")
            context = {
                "request": {
                    "expectedMainCommit": "1" * 40,
                    "privatePreflightRequestSha256": EXECUTOR.EXPECTED_PREFLIGHT_REQUEST_SHA256,
                    "preflightResultSha256": EXECUTOR.EXPECTED_PREFLIGHT_RESULT_SHA256,
                    "immutableBackupSha256": EXECUTOR.EXPECTED_STATE_SHA256,
                    "resourceIdentitySha256": EXECUTOR.EXPECTED_RESOURCE_IDENTITY_SHA256,
                },
                "request_path": path, "managed": set(range(13)), "remaining": 1800,
            }
            result = EXECUTOR.redacted_verification(context)
            self.assertEqual(result["operational_commands_executed"], [])
            self.assertFalse(result["migration_execution_authorized"])
            self.assertFalse(result["terraform_apply_authorized"])

    def test_execute_runs_exact_init_once_and_never_plan_or_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            working = private / "preflight" / "migration-source"
            working.mkdir(parents=True)
            working.parent.chmod(0o700)
            working.chmod(0o700)
            plan_bundle = private / "plan"
            (plan_bundle / "source").mkdir(parents=True)
            plan_bundle.chmod(0o700)
            (plan_bundle / "source").chmod(0o700)
            apply_output = private / "apply"
            apply_output.mkdir()
            apply_output.chmod(0o700)
            output = private / "migration-output"
            request_path = private / "request.json"
            request_path.write_text("{}\n")
            request_path.chmod(0o600)
            managed = {f"aws_test_resource.item[{index}]" for index in range(13)}
            data = {"data.aws_caller_identity.current"}
            resources = [
                {"mode": "managed", "type": "aws_test_resource", "name": "item", "instances": [{"index_key": index} for index in range(13)]},
                {"mode": "data", "type": "aws_caller_identity", "name": "current", "instances": [{}]},
            ]
            remote_state = {"version": 4, "serial": 7, "lineage": "lineage", "resources": resources, "outputs": {}}
            state_bytes = EXECUTOR.canonical_json(remote_state)
            for path in (
                working / "terraform.tfstate",
                plan_bundle / "source/terraform.tfstate",
                apply_output / "state-bootstrap.tfstate.applied",
            ):
                path.write_bytes(state_bytes)
                path.chmod(0o600)
            backup = private / "preflight/bootstrap-state.pre-migration.backup"
            backup.write_bytes(state_bytes)
            backup.chmod(0o600)
            resource_digest = EXECUTOR.PREFLIGHT_EXECUTOR.resource_identity_digest(remote_state)
            command = ["terraform", f"-chdir={working}", "init", "-input=false", "-migrate-state", "-force-copy", f"-backend-config={private / 'backend.tfbackend'}"]
            context = {
                "request": {
                    "expectedMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12,
                    "privatePreflightRequestSha256": "2" * 64, "preflightResultSha256": "3" * 64,
                    "immutableBackupSha256": EXECUTOR.file_sha256(backup),
                    "resourceIdentitySha256": resource_digest,
                },
                "request_path": request_path,
                "preflight_request": {
                    "privatePlanBundleDirectory": str(plan_bundle),
                    "privateApplyOutputDirectory": str(apply_output),
                },
                "migration_output": output, "working": working,
                "backup": backup, "inventory": {"lineage": "lineage", "serial": 7},
                "managed": managed, "data": data,
                "identities": {"bucket": "bucket", "kms_arn": "kms", "policies": {}},
                "backend_values": {"key": "bootstrap/terraform.tfstate"},
                "plan_request": {}, "command": command,
            }
            calls: list[list[str]] = []

            def runner(arguments, environment, timeout, cwd):
                calls.append(arguments)
                if arguments == command:
                    return subprocess.CompletedProcess(arguments, 0, b"", b"")
                if arguments[-2:] == ["state", "pull"]:
                    return subprocess.CompletedProcess(arguments, 0, state_bytes, b"")
                if arguments[-2:] == ["state", "list"]:
                    return subprocess.CompletedProcess(arguments, 0, ("\n".join(sorted(managed | data)) + "\n").encode(), b"")
                if "head-object" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, b'{"ServerSideEncryption":"aws:kms","SSEKMSKeyId":"kms","BucketKeyEnabled":true,"VersionId":"version-1"}\n', b"")
                if "list-object-versions" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, b'{"Versions":[{"Key":"bootstrap/terraform.tfstate","VersionId":"version-1","IsLatest":true}],"DeleteMarkers":[]}\n', b"")
                return subprocess.CompletedProcess(arguments, 0, b'{"Account":"111111111111"}\n', b"")

            before = {"s3_object_version_count": 0}
            with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
                EXECUTOR.APPLY_EXECUTOR, "validate_live_foundation", return_value=before
            ), patch.object(EXECUTOR.APPLY_EXECUTOR, "validate_outputs", return_value=context["identities"]), patch.dict(
                os.environ, {"CONFIRM_STATE_BOOTSTRAP_MIGRATION": EXECUTOR.CONFIRMATION}, clear=True
            ):
                result = EXECUTOR.execute(request_path, repository_root=private, runner=runner)

            self.assertEqual(calls.count(command), 1)
            self.assertFalse(any("plan" in call or "apply" in call for call in calls))
            self.assertTrue(result["state_migration_executed"])
            self.assertFalse(result["terraform_apply_executed"])
            self.assertFalse(result["automatic_retry_performed"])
            self.assertEqual(EXECUTOR.file_sha256(backup), context["request"]["immutableBackupSha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

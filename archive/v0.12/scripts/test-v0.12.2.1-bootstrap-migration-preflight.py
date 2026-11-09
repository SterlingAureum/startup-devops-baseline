#!/usr/bin/env python3
"""Offline unit tests for the v0.12.2.1 migration preflight."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.1-bootstrap-migration-preflight.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("migration_preflight_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.1-bootstrap-migration-preflight-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "1" * 12,
        "privatePlanRequestPath": "/private/plan.json",
        "privatePlanRequestSha256": EXECUTOR.EXPECTED_PLAN_REQUEST_SHA256,
        "privateApplyRequestPath": "/private/apply.json",
        "privateApplyRequestSha256": EXECUTOR.EXPECTED_APPLY_REQUEST_SHA256,
        "privateRecoveryRequestPath": "/private/recovery.json",
        "privateRecoveryRequestSha256": EXECUTOR.EXPECTED_RECOVERY_REQUEST_SHA256,
        "privatePlanBundleDirectory": "/private/plan",
        "privateApplyOutputDirectory": "/private/apply",
        "privateRecoveryOutputDirectory": "/private/recovery",
        "appliedStateSha256": EXECUTOR.EXPECTED_STATE_SHA256,
        "recoveryResultSha256": EXECUTOR.EXPECTED_RECOVERY_RESULT_SHA256,
        "liveValidationSha256": EXECUTOR.EXPECTED_LIVE_VALIDATION_SHA256,
        "privateBackendConfigPath": "/private/bootstrap.s3.tfbackend",
        "privateBackendConfigSha256": "2" * 64,
        "privatePreflightOutputDirectory": "/private/preflight",
        "approval": {"notBeforeUtc": "2026-09-25T00:00:00Z", "expiresAtUtc": "2026-09-25T01:00:00Z"},
        "executionBoundary": {
            "terraformInit": False, "terraformPlan": False, "terraformApply": False,
            "stateMigration": False, "statePush": False, "destroy": False,
            "awsReadOnlyValidation": True, "localPrivateBackup": True,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_state_digest_mutation_is_rejected(self):
        value = request()
        value["appliedStateSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Reviewed digest changed"):
            EXECUTOR.validate_request(value)

    def test_migration_authority_mutation_is_rejected(self):
        value = request()
        value["executionBoundary"]["stateMigration"] = True
        with self.assertRaisesRegex(ValueError, "Execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_window_over_one_hour_is_rejected(self):
        value = request()
        value["approval"]["expiresAtUtc"] = "2026-09-25T01:00:01Z"
        with self.assertRaisesRegex(ValueError, "at most one hour"):
            EXECUTOR.validate_request(value)


class BackendConfigTests(unittest.TestCase):
    def write(self, text: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "backend.tfbackend"
        path.write_text(text)
        return path

    def test_exact_backend_config_is_parsed(self):
        path = self.write('bucket="bucket-name"\nkey="bootstrap/terraform.tfstate"\nregion="us-east-1"\nencrypt=true\nkms_key_id="key-arn"\nuse_lockfile=true\n')
        value = EXECUTOR.parse_backend_config(path)
        self.assertEqual(value["key"], "bootstrap/terraform.tfstate")
        self.assertTrue(value["use_lockfile"])

    def test_credential_field_is_rejected(self):
        path = self.write('bucket="bucket-name"\nkey="bootstrap/terraform.tfstate"\nregion="us-east-1"\nencrypt=true\nkms_key_id="key-arn"\nuse_lockfile=true\naccess_key="no"\n')
        with self.assertRaisesRegex(ValueError, "fields changed"):
            EXECUTOR.parse_backend_config(path)

    def test_duplicate_field_is_rejected(self):
        path = self.write('bucket="one"\nbucket="two"\n')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            EXECUTOR.parse_backend_config(path)


class EvidenceTests(unittest.TestCase):
    def test_resource_digest_is_canonical(self):
        left = {"resources": [{"name": "state", "type": "aws_s3_bucket", "mode": "managed"}]}
        right = json.loads(json.dumps(left, sort_keys=True))
        self.assertEqual(EXECUTOR.resource_identity_digest(left), EXECUTOR.resource_identity_digest(right))

    def test_redacted_verify_is_command_free_and_unauthorized(self):
        context = {
            "request": {
                "expectedMainCommit": "1" * 40,
                "privatePlanRequestSha256": EXECUTOR.EXPECTED_PLAN_REQUEST_SHA256,
                "privateApplyRequestSha256": EXECUTOR.EXPECTED_APPLY_REQUEST_SHA256,
                "privateRecoveryRequestSha256": EXECUTOR.EXPECTED_RECOVERY_REQUEST_SHA256,
                "appliedStateSha256": EXECUTOR.EXPECTED_STATE_SHA256,
            },
            "request_path": EXECUTOR_PATH,
            "managed": set(range(13)),
            "remaining": 1800,
        }
        result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["preflight_execution_authorized"])
        self.assertFalse(result["state_migration_authorized"])
        self.assertNotIn("privatePlanBundleDirectory", result)


class ExecutionTests(unittest.TestCase):
    def test_execute_writes_private_plan_without_running_init(self):
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            private_root.chmod(0o700)
            repository = private_root / "repository"
            terraform_root = repository / EXECUTOR.PLAN_EXECUTOR.TERRAFORM_ROOT_RELATIVE
            terraform_root.mkdir(parents=True)
            for name in EXECUTOR.PLAN_EXECUTOR.TERRAFORM_SOURCE_FILES:
                (terraform_root / name).write_text(f"# {name}\n")
            manifest = EXECUTOR.PLAN_EXECUTOR.source_manifest(terraform_root)
            canonical_state = private_root / "canonical.tfstate"
            state = {"version": 4, "serial": 1, "lineage": "reviewed-lineage", "resources": []}
            canonical_state.write_bytes(EXECUTOR.canonical_json(state))
            canonical_state.chmod(0o600)
            request_path = private_root / "request.json"
            request_path.write_text("{}\n")
            request_path.chmod(0o600)
            backend_path = private_root / "bootstrap.s3.tfbackend"
            backend_path.write_text('bucket="private"\n')
            backend_path.chmod(0o600)
            output = private_root / "preflight-output"
            context = {
                "request": {
                    "expectedMainCommit": "1" * 40,
                    "expectedAwsAccountId": "1" * 12,
                    "appliedStateSha256": EXECUTOR.file_sha256(canonical_state),
                },
                "request_path": request_path,
                "plan_request": {},
                "canonical_state": canonical_state,
                "state": state,
                "managed": set(range(13)),
                "data": set(),
                "identities": {},
                "backend_path": backend_path,
                "output": output,
                "current_manifest": manifest,
            }
            calls: list[list[str]] = []

            def runner(arguments, environment, timeout, cwd):
                calls.append(arguments)
                if arguments[:2] == ["terraform", "version"]:
                    return subprocess.CompletedProcess(arguments, 0, b'{"terraform_version":"1.14.5"}\n', b"")
                return subprocess.CompletedProcess(arguments, 0, b'{"Account":"111111111111"}\n', b"")

            live = {"s3_object_version_count": 0, "attached_root_state_policy_count": 0}
            with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
                EXECUTOR.APPLY_EXECUTOR, "validate_live_foundation", return_value=live
            ), patch.dict(os.environ, {"CONFIRM_STATE_BOOTSTRAP_MIGRATION_PREFLIGHT": EXECUTOR.CONFIRMATION}, clear=True):
                result = EXECUTOR.execute(request_path, repository_root=repository, runner=runner)

            self.assertEqual(calls, [["terraform", "version", "-json"], ["aws", "--region", "us-east-1", "sts", "get-caller-identity", "--output", "json"]])
            self.assertFalse(result["terraform_init_executed"])
            self.assertFalse(result["state_migration_executed"])
            self.assertTrue((output / "bootstrap-state.pre-migration.backup").is_file())
            command = json.loads((output / "migration-command-plan.json").read_text())
            self.assertFalse(command["executedByThisPreflight"])
            self.assertIn("-migrate-state", command["command"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

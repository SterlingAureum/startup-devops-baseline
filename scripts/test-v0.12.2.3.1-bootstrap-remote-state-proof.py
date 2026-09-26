#!/usr/bin/env python3
"""Offline tests for the v0.12.2.3.1 guarded remote-state proof."""

from __future__ import annotations

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1-bootstrap-remote-state-proof.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bootstrap_remote_state_proof_tests", EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load proof executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.3.1-bootstrap-remote-state-proof-request-v1",
        "operation": EXECUTOR.REQUEST_OPERATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": EXECUTOR.EXPECTED_MAIN_COMMIT,
        "expectedAwsAccountId": "1" * 12,
        "privateRecoveryRequestPath": "/private/recovery-request.json",
        "privateRecoveryRequestSha256": EXECUTOR.RECOVERY_REQUEST_SHA256,
        "privateRecoveryOutputDirectory": "/private/recovery-output",
        "recoveryResultSha256": EXECUTOR.RECOVERY_RESULT_SHA256,
        "identityValidationSha256": EXECUTOR.IDENTITY_VALIDATION_SHA256,
        "remoteStateSha256": EXECUTOR.REMOTE_STATE_SHA256,
        "semanticProjectionSha256": EXECUTOR.SEMANTIC_PROJECTION_SHA256,
        "privateProofOutputDirectory": "/private/proof-output",
        "approval": {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsReadOnlyValidation": True, "terraformConsoleLockHolder": True,
            "terraformPlanLockContender": True, "terraformZeroChangeSavedPlan": True,
            "transientLockMutation": True, "stateContentMutation": False,
            "terraformInit": False, "terraformApply": False, "statePush": False,
            "destroy": False, "iamPolicyAttachment": False, "directLockWrite": False,
            "forceUnlock": False, "objectVersionRecovery": False, "automaticRetry": False,
        },
    }


def zero_plan() -> dict:
    return {
        "format_version": "1.2", "terraform_version": "1.14.5", "complete": True,
        "errored": False, "resource_drift": [],
        "resource_changes": [{"address": "aws_test.x", "change": {"actions": ["no-op"]}}],
        "output_changes": {"safe": {"actions": ["no-op"], "before": "x", "after": "x"}},
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.REQUEST_OPERATION)

    def test_init_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformInit"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_state_mutation_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["stateContentMutation"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_recovery_digest_mutation_is_rejected(self):
        value = request()
        value["recoveryResultSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Recovery result digest changed"):
            EXECUTOR.validate_request(value)


class PlanGateTests(unittest.TestCase):
    def test_zero_change_plan_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_zero_change_plan(zero_plan())["create"], 0)

    def test_create_is_rejected(self):
        value = zero_plan()
        value["resource_changes"][0]["change"]["actions"] = ["create"]
        with self.assertRaisesRegex(ValueError, "managed-resource change"):
            EXECUTOR.validate_zero_change_plan(value)

    def test_drift_is_rejected(self):
        value = zero_plan()
        value["resource_drift"] = [{"address": "aws_test.x"}]
        with self.assertRaisesRegex(ValueError, "resource drift"):
            EXECUTOR.validate_zero_change_plan(value)

    def test_import_is_rejected(self):
        value = zero_plan()
        value["resource_changes"][0]["change"]["importing"] = {"id": "x"}
        with self.assertRaisesRegex(ValueError, "import"):
            EXECUTOR.validate_zero_change_plan(value)

    def test_output_change_is_rejected(self):
        value = zero_plan()
        value["output_changes"]["safe"]["actions"] = ["update"]
        with self.assertRaisesRegex(ValueError, "output change"):
            EXECUTOR.validate_zero_change_plan(value)


class LockGateTests(unittest.TestCase):
    def test_exact_lock_error_is_accepted(self):
        result = subprocess.CompletedProcess([], 1, b"", b"Error: Error acquiring the state lock\n")
        self.assertTrue(EXECUTOR.lock_error_only(result))

    def test_non_lock_failure_is_rejected(self):
        result = subprocess.CompletedProcess([], 1, b"", b"provider failed\n")
        self.assertFalse(EXECUTOR.lock_error_only(result))

    def test_lock_plus_unrelated_error_is_rejected(self):
        result = subprocess.CompletedProcess([], 1, b"", b"Error: Error acquiring the state lock\nError: provider failed\n")
        self.assertFalse(EXECUTOR.lock_error_only(result))

    def test_success_is_not_lock_contention(self):
        result = subprocess.CompletedProcess([], 0, b"No changes\n", b"")
        self.assertFalse(EXECUTOR.lock_error_only(result))


class ExecutionTests(unittest.TestCase):
    def test_verify_result_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text("{}\n")
            context = {
                "request": {"expectedMainCommit": EXECUTOR.EXPECTED_MAIN_COMMIT},
                "request_path": path, "managed": set(range(13)), "data": set(range(9)), "remaining": 1800,
            }
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["proof_execution_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(result["state_push_authorized"])

    def test_execute_proves_lock_then_produces_zero_change_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            output = private / "proof"
            working = private / "source"
            working.mkdir(mode=0o700)
            terraform_data = private / "terraform-data"
            terraform_data.mkdir(mode=0o700)
            tfvars = private / "input.tfvars"
            tfvars.write_text("x = true\n")
            tfvars.chmod(0o600)
            request_path = private / "request.json"
            request_path.write_text("{}\n")
            request_path.chmod(0o600)
            resources = [
                {"mode": "managed", "type": "aws_test", "name": f"m{i}", "instances": [{}]}
                for i in range(13)
            ] + [
                {"mode": "data", "type": "aws_data", "name": f"d{i}", "instances": [{}]}
                for i in range(9)
            ]
            state = {
                "version": 4, "terraform_version": "1.14.5", "serial": 1, "lineage": "new",
                "outputs": {}, "resources": resources, "check_results": [],
            }
            state_bytes = EXECUTOR.canonical_json(state)
            managed = {f"aws_test.m{i}" for i in range(13)}
            data = {f"data.aws_data.d{i}" for i in range(9)}
            context = {
                "request": {"expectedMainCommit": EXECUTOR.EXPECTED_MAIN_COMMIT, "expectedAwsAccountId": "1" * 12},
                "request_path": request_path, "proof_output": output, "working": working,
                "terraform_data": terraform_data, "plan_request": {}, "tfvars": tfvars,
                "remote_state": copy.deepcopy(state), "managed": managed, "data": data,
                "identities": {"bucket": "private-bucket", "kms_arn": "private-kms"},
                "backend_values": {"key": "bootstrap/terraform.tfstate"},
            }
            state_flags = {"holder": False, "zero_done": False, "list_calls": 0}
            calls: list[list[str]] = []

            class FakeSession:
                def poll(self):
                    return None

                def finish(self, timeout=30):
                    state_flags["holder"] = False
                    return 0

            def console_starter(arguments, environment, cwd, proof_output):
                calls.append(arguments)
                state_flags["holder"] = True
                return FakeSession()

            def completed(arguments, code=0, stdout=b"", stderr=b""):
                return subprocess.CompletedProcess(arguments, code, stdout, stderr)

            def runner(arguments, environment, timeout, cwd):
                calls.append(arguments)
                if arguments[-2:] == ["state", "pull"]:
                    return completed(arguments, stdout=state_bytes)
                if arguments[-2:] == ["state", "list"]:
                    return completed(arguments, stdout=("\n".join(sorted(managed | data)) + "\n").encode())
                if "get-caller-identity" in arguments:
                    return completed(arguments, stdout=b'{"Account":"111111111111"}\n')
                if "head-object" in arguments:
                    key = arguments[arguments.index("--key") + 1]
                    if key.endswith(".tflock"):
                        if state_flags["holder"]:
                            return completed(arguments, stdout=b'{"VersionId":"lock-live"}\n')
                        return completed(arguments, code=255, stderr=b"An error occurred (404) when calling HeadObject: Not Found\n")
                    return completed(arguments, stdout=b'{"ServerSideEncryption":"aws:kms","SSEKMSKeyId":"private-kms","BucketKeyEnabled":true,"VersionId":"state-v1"}\n')
                if "list-object-versions" in arguments:
                    state_flags["list_calls"] += 1
                    if state_flags["list_calls"] == 1:
                        value = {"Versions": [{"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v1", "IsLatest": True}], "DeleteMarkers": []}
                    else:
                        value = {
                            "Versions": [
                                {"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v1", "IsLatest": True},
                                {"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "lock-v1"},
                                {"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "lock-v2"},
                            ],
                            "DeleteMarkers": [
                                {"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "marker-v1"},
                                {"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "marker-v2", "IsLatest": True},
                            ],
                        }
                    return completed(arguments, stdout=EXECUTOR.canonical_json(value))
                if "plan" in arguments and "-lock-timeout=0s" in arguments:
                    return completed(arguments, code=1, stderr=b"Error: Error acquiring the state lock\n")
                if "plan" in arguments and "-lock-timeout=60s" in arguments:
                    target = Path(next(item.removeprefix("-out=") for item in arguments if item.startswith("-out=")))
                    target.write_bytes(b"binary-plan")
                    target.chmod(0o600)
                    state_flags["zero_done"] = True
                    return completed(arguments, stdout=b"No changes.\n")
                if "show" in arguments and "-json" in arguments:
                    return completed(arguments, stdout=EXECUTOR.canonical_json(zero_plan()))
                if "show" in arguments:
                    return completed(arguments, stdout=b"No changes.\n")
                raise AssertionError(arguments)

            remote_digest = hashlib.sha256(state_bytes).hexdigest()
            with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
                EXECUTOR, "safe_environment", return_value={}
            ), patch.object(EXECUTOR, "REMOTE_STATE_SHA256", remote_digest), patch.dict(
                os.environ, {"CONFIRM_BOOTSTRAP_REMOTE_STATE_PROOF": EXECUTOR.CONFIRMATION}, clear=True
            ):
                result = EXECUTOR.execute(
                    request_path, repository_root=private, runner=runner,
                    console_starter=console_starter, sleeper=lambda _: None,
                    now=datetime(2026, 9, 26, tzinfo=timezone.utc),
                )

            flattened = [item for call in calls for item in call]
            self.assertIn("console", flattened)
            self.assertIn("-lock-timeout=0s", flattened)
            self.assertIn("-lock-timeout=60s", flattened)
            self.assertNotIn("init", flattened)
            self.assertNotIn("apply", flattened)
            self.assertNotIn("push", flattened)
            self.assertNotIn("force-unlock", flattened)
            self.assertTrue(result["lock_contention_observed"])
            self.assertTrue(result["zero_change_saved_plan_produced"])
            self.assertFalse(result["state_content_mutated"])
            self.assertEqual(result["lock_object_version_delta"], 2)
            self.assertEqual(result["lock_object_delete_marker_delta"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)

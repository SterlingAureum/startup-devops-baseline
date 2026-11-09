#!/usr/bin/env python3
"""Offline tests for read-only recovery of existing refresh-only plan evidence."""

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("refresh_plan_evidence_recovery_tests", EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load recovery executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.3.1.0.1.0.1-refresh-plan-evidence-recovery-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedRecoveryMainCommit": "1" * 40,
        "expectedAwsAccountId": "1" * 12,
        "privateFailedRefreshPlanRequestPath": "/private/refresh-request.json",
        "privateFailedRefreshPlanRequestSha256": EXECUTOR.REFRESH_REQUEST_SHA256,
        "privateFailedRefreshPlanOutputDirectory": "/private/refresh-output",
        "binaryRefreshPlanSha256": EXECUTOR.BINARY_PLAN_SHA256,
        "refreshPlanJsonSha256": EXECUTOR.PLAN_JSON_SHA256,
        "refreshPlanTextSha256": EXECUTOR.PLAN_TEXT_SHA256,
        "resourceDriftSha256": EXECUTOR.RESOURCE_DRIFT_SHA256,
        "canonicalRemoteStateSha256": EXECUTOR.REMOTE_STATE_SHA256,
        "privateRecoveryOutputDirectory": "/private/recovery-output",
        "approval": {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsIdentityRead": True, "terraformStatePull": True, "terraformStateList": True,
            "s3StateAndLockRead": True, "terraformInit": False, "terraformPlan": False,
            "terraformApply": False, "statePush": False, "destroy": False,
            "iamPolicyAttachment": False, "directLockWrite": False, "forceUnlock": False,
            "automaticRetry": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_plan_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformPlan"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_apply_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_reviewed_plan_digest_mutation_is_rejected(self):
        value = request()
        value["refreshPlanJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "incident digest changed"):
            EXECUTOR.validate_request(value)


class ExecutionTests(unittest.TestCase):
    def test_verify_result_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text("{}\n")
            context = {
                "request": {"expectedRecoveryMainCommit": "1" * 40},
                "request_path": path, "managed": set(range(13)), "data": set(range(9)),
                "remaining": 1800,
            }
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["recovery_execution_authorized"])
        self.assertFalse(result["terraform_plan_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(result["state_content_mutation_authorized"])

    def test_execute_completes_read_only_postchecks_without_replanning(self):
        managed = {f"aws_test.item_{index}" for index in range(13)}
        data = {f"data.aws_test.item_{index}" for index in range(9)}
        state_bytes = b'{"canonical":"state"}\n'
        state_version = {"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v1", "IsLatest": True}
        lock_version = {"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "lock-v1"}
        lock_marker = {"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "marker-v1", "IsLatest": True}
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            request_path = private / "request.json"
            request_path.write_text("{}\n")
            request_path.chmod(0o600)
            output = private / "recovery-output"
            working = private / "source"
            working.mkdir(mode=0o700)
            terraform_data = private / "terraform-data"
            terraform_data.mkdir(mode=0o700)
            context = {
                "request": {"expectedRecoveryMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12},
                "request_path": request_path, "output": output, "working": working,
                "terraform_data": terraform_data, "original_plan_request": {},
                "managed": managed, "data": data,
                "identities": {"bucket": "bucket", "kms_arn": "kms"},
                "backend_values": {"key": "bootstrap/terraform.tfstate"},
                "state_versions_before": [state_version], "state_markers_before": [],
                "lock_versions_before": [], "lock_markers_before": [],
            }
            calls = []

            def completed(arguments, code=0, stdout=b"", stderr=b""):
                return subprocess.CompletedProcess(arguments, code, stdout, stderr)

            def runner(arguments, environment, timeout, cwd):
                calls.append(arguments)
                if "get-caller-identity" in arguments:
                    return completed(arguments, stdout=b'{"Account":"111111111111"}\n')
                if arguments[-2:] == ["state", "pull"]:
                    return completed(arguments, stdout=state_bytes)
                if arguments[-2:] == ["state", "list"]:
                    return completed(arguments, stdout=("\n".join(sorted(managed | data)) + "\n").encode())
                if "head-object" in arguments:
                    key = arguments[arguments.index("--key") + 1]
                    if key.endswith(".tflock"):
                        return completed(arguments, code=255, stderr=b"404 Not Found\n")
                    return completed(arguments, stdout=b'{"ServerSideEncryption":"aws:kms","SSEKMSKeyId":"kms","BucketKeyEnabled":true,"VersionId":"state-v1"}\n')
                if "list-object-versions" in arguments:
                    value = {"Versions": [state_version, lock_version], "DeleteMarkers": [lock_marker]}
                    return completed(arguments, stdout=EXECUTOR.canonical_json(value))
                raise AssertionError(arguments)

            with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
                EXECUTOR, "REMOTE_STATE_SHA256", __import__("hashlib").sha256(state_bytes).hexdigest()
            ), patch.object(EXECUTOR.PROOF_EXECUTOR, "safe_environment", return_value={}), patch.dict(
                os.environ, {"CONFIRM_REFRESH_PLAN_EVIDENCE_RECOVERY": EXECUTOR.CONFIRMATION}, clear=True
            ):
                result = EXECUTOR.execute(request_path, repository_root=private, runner=runner, now=datetime(2026, 9, 26, tzinfo=timezone.utc))

            flattened = [item for call in calls for item in call]
            self.assertEqual(len(calls), 6)
            self.assertNotIn("plan", flattened)
            self.assertNotIn("init", flattened)
            self.assertNotIn("apply", flattened)
            self.assertNotIn("push", flattened)
            self.assertNotIn("force-unlock", flattened)
            self.assertFalse(result["refresh_plan_reexecuted"])
            self.assertFalse(result["state_content_mutated"])
            self.assertEqual(result["refresh_plan_lock_version_delta"], 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)

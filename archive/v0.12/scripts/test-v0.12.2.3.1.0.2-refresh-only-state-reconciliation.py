#!/usr/bin/env python3
"""Offline tests for exact saved refresh-only plan reconciliation."""

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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("refresh_state_reconciliation_tests", EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load reconciliation executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.3.1.0.2-refresh-only-state-reconciliation-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline", "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12,
        "privateEvidenceRecoveryRequestPath": "/private/evidence-request.json",
        "privateEvidenceRecoveryRequestSha256": EXECUTOR.EVIDENCE_REQUEST_SHA256,
        "privateEvidenceRecoveryOutputDirectory": "/private/evidence-output",
        "evidenceRecoveryResultSha256": EXECUTOR.EVIDENCE_RESULT_SHA256,
        "evidenceValidationSha256": EXECUTOR.EVIDENCE_VALIDATION_SHA256,
        "recoveryStateHeadSha256": "2" * 64, "recoveryObjectVersionsSha256": "3" * 64,
        "privateRefreshPlanRequestPath": "/private/refresh-request.json",
        "privateRefreshPlanRequestSha256": EXECUTOR.REFRESH_REQUEST_SHA256,
        "privateRefreshPlanOutputDirectory": "/private/refresh-output",
        "binaryRefreshPlanSha256": EXECUTOR.BINARY_PLAN_SHA256,
        "refreshPlanJsonSha256": EXECUTOR.PLAN_JSON_SHA256,
        "refreshPlanTextSha256": EXECUTOR.PLAN_TEXT_SHA256,
        "resourceDriftSha256": EXECUTOR.RESOURCE_DRIFT_SHA256,
        "canonicalRemoteStateSha256": EXECUTOR.REMOTE_STATE_SHA256,
        "privateApplyOutputDirectory": "/private/apply-output",
        "humanReview": {
            "reviewedAtUtc": "2026-09-26T00:00:00Z", "exactSevenStateRefreshes": True,
            "resourceChangesEmpty": True, "allSevenOutputsNoOp": True, "noImports": True,
            "noRemoteResourceActions": True, "noUnexpectedResourcesOrIamAttachments": True,
            "noUnexplainedWarnings": True,
        },
        "approval": {"notBeforeUtc": "2026-09-26T00:01:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsIdentityAndS3Read": True, "terraformStatePullAndList": True,
            "exactSavedRefreshPlanApply": True, "terraformInit": False, "terraformPlan": False,
            "unsavedApply": False, "statePush": False, "destroy": False,
            "iamPolicyAttachment": False, "directS3Mutation": False, "forceUnlock": False,
            "automaticRetry": False, "automaticRollback": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_unsaved_apply_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["unsavedApply"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_plan_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformPlan"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_incomplete_human_review_is_rejected(self):
        value = request()
        value["humanReview"]["noRemoteResourceActions"] = False
        with self.assertRaisesRegex(ValueError, "Human review is incomplete"):
            EXECUTOR.validate_request(value)

    def test_review_after_approval_is_rejected(self):
        value = request()
        value["humanReview"]["reviewedAtUtc"] = "2026-09-26T00:02:00Z"
        with self.assertRaisesRegex(ValueError, "precede approval"):
            EXECUTOR.validate_request(value)


class ExecutionTests(unittest.TestCase):
    def context(self, private: Path, state_before: bytes, state_after: bytes):
        managed = {f"aws_test.item_{index}" for index in range(13)}
        data = {f"data.aws_test.item_{index}" for index in range(9)}
        request_path = private / "request.json"
        request_path.write_text("{}\n")
        request_path.chmod(0o600)
        binary = private / "refresh.tfplan"
        binary.write_bytes(b"plan")
        binary.chmod(0o600)
        working = private / "source"
        working.mkdir(mode=0o700)
        terraform_data = private / "terraform-data"
        terraform_data.mkdir(mode=0o700)
        state_version = {"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v1", "IsLatest": True}
        return {
            "request": {"expectedMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12},
            "request_path": request_path, "output": private / "apply-output", "binary": binary,
            "working": working, "terraform_data": terraform_data, "plan_request": {},
            "plan": {"planned_values": {"root_module": {"resources": []}, "outputs": {}}},
            "before_state": json.loads(state_before), "managed": managed, "data": data,
            "identities": {"bucket": "bucket", "kms_arn": "kms"},
            "backend_values": {"key": "bootstrap/terraform.tfstate"},
            "state_versions_before": [state_version], "state_markers_before": [],
            "lock_versions_before": [], "lock_markers_before": [], "remaining": 1800,
        }

    def test_verify_result_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            path = private / "request.json"
            path.write_text("{}\n")
            context = {"request": {"expectedMainCommit": "1" * 40}, "request_path": path, "managed": set(range(13)), "data": set(range(9)), "remaining": 1800}
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["apply_execution_authorized"])
        self.assertFalse(result["terraform_plan_authorized"])
        self.assertFalse(result["unsaved_apply_authorized"])

    def test_execute_applies_exact_saved_plan_once_and_validates_state(self):
        before = {"version": 4, "terraform_version": "1.14.5", "serial": 1, "lineage": "lineage", "outputs": {}, "resources": [], "check_results": []}
        after = dict(before)
        after["serial"] = 2
        before_bytes = EXECUTOR.canonical_json(before)
        after_bytes = EXECUTOR.canonical_json(after)
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            context = self.context(private, before_bytes, after_bytes)
            managed, data = context["managed"], context["data"]
            calls = []
            pull_count = 0
            head_count = 0
            version_count = 0

            def completed(arguments, code=0, stdout=b"", stderr=b""):
                return subprocess.CompletedProcess(arguments, code, stdout, stderr)

            def runner(arguments, environment, timeout, cwd):
                nonlocal pull_count, head_count, version_count
                calls.append(arguments)
                if "get-caller-identity" in arguments:
                    return completed(arguments, stdout=b'{"Account":"111111111111"}\n')
                if arguments[-2:] == ["state", "pull"]:
                    pull_count += 1
                    return completed(arguments, stdout=before_bytes if pull_count == 1 else after_bytes)
                if arguments[-2:] == ["state", "list"]:
                    return completed(arguments, stdout=("\n".join(sorted(managed | data)) + "\n").encode())
                if "apply" in arguments:
                    return completed(arguments, stdout=b"Apply complete! Resources: 0 added, 0 changed, 0 destroyed.\n")
                if arguments[-2:] == ["show", "-json"]:
                    return completed(arguments, stdout=EXECUTOR.canonical_json({"values": context["plan"]["planned_values"]}))
                if "head-object" in arguments:
                    key = arguments[arguments.index("--key") + 1]
                    if key.endswith(".tflock"):
                        return completed(arguments, code=255, stderr=b"404 Not Found\n")
                    head_count += 1
                    version = "state-v1" if head_count == 1 else "state-v2"
                    return completed(arguments, stdout=EXECUTOR.canonical_json({"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "kms", "BucketKeyEnabled": True, "VersionId": version}))
                if "list-object-versions" in arguments:
                    version_count += 1
                    versions = [{"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v1", "IsLatest": version_count == 1}]
                    markers = []
                    if version_count == 2:
                        versions.insert(0, {"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v2", "IsLatest": True})
                        versions.append({"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "lock-v1"})
                        markers.append({"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "marker-v1", "IsLatest": True})
                    return completed(arguments, stdout=EXECUTOR.canonical_json({"Versions": versions, "DeleteMarkers": markers}))
                raise AssertionError(arguments)

            with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
                EXECUTOR, "REMOTE_STATE_SHA256", hashlib.sha256(before_bytes).hexdigest()
            ), patch.object(EXECUTOR.PROOF_EXECUTOR, "safe_environment", return_value={}), patch.object(
                EXECUTOR.RECOVERY_EXECUTOR.RECOVERY_EXECUTOR, "state_addresses", return_value=(managed, data)
            ), patch.dict(os.environ, {"CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION": EXECUTOR.CONFIRMATION}, clear=True):
                result = EXECUTOR.execute(context["request_path"], repository_root=private, runner=runner, now=datetime(2026, 9, 26, tzinfo=timezone.utc))

            flattened = [item for call in calls for item in call]
            self.assertEqual(sum("apply" in call for call in calls), 1)
            self.assertNotIn("plan", flattened)
            self.assertNotIn("init", flattened)
            self.assertNotIn("push", flattened)
            self.assertEqual(result["reconciled_serial"], 2)
            self.assertTrue(result["planned_values_exactly_persisted"])
            self.assertEqual(result["state_object_version_delta"], 1)
            self.assertFalse(result["automatic_retry_performed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

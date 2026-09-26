#!/usr/bin/env python3
"""Offline tests for v0.12.2.3.1.0.1 refresh-only recovery planning."""

from __future__ import annotations

from contextlib import ExitStack
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
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.1-bootstrap-refresh-only-plan.py"


def load_module():
    spec = importlib.util.spec_from_file_location("bootstrap_refresh_only_plan_tests", EXECUTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load refresh-plan executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.3.1.0.1-bootstrap-refresh-only-plan-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "1" * 12,
        "privateFailedProofRequestPath": "/private/proof-request.json",
        "privateFailedProofRequestSha256": EXECUTOR.PROOF_REQUEST_SHA256,
        "privateFailedProofOutputDirectory": "/private/proof-output",
        "failedBinaryPlanSha256": EXECUTOR.BINARY_PLAN_SHA256,
        "failedPlanJsonSha256": EXECUTOR.PLAN_JSON_SHA256,
        "failedPlanTextSha256": EXECUTOR.PLAN_TEXT_SHA256,
        "resourceDriftSha256": EXECUTOR.RESOURCE_DRIFT_SHA256,
        "canonicalRemoteStateSha256": EXECUTOR.REMOTE_STATE_SHA256,
        "privateRefreshPlanOutputDirectory": "/private/refresh-plan-output",
        "approval": {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsReadOnlyValidation": True, "terraformStatePull": True, "terraformStateList": True,
            "terraformRefreshOnlyPlan": True, "terraformShow": True, "transientLockMutation": True,
            "stateContentMutation": False, "terraformInit": False, "terraformApply": False,
            "ordinaryTerraformPlan": False, "statePush": False, "destroy": False,
            "iamPolicyAttachment": False, "directLockWrite": False, "forceUnlock": False,
            "automaticRetry": False,
        },
    }


def reviewed_plan() -> tuple[dict, set[str], dict[str, tuple[str, ...]]]:
    managed = {f"aws_test.item_{index}" for index in range(13)}
    drift_addresses = sorted(managed)[:7]
    changes = []
    drift = []
    paths = {}
    for index, address in enumerate(sorted(managed)):
        refreshed = {"id": index, "tags": {"Managed": "true"}}
        changes.append({"address": address, "change": {"actions": ["no-op"], "before": refreshed, "after": refreshed}})
        if address in drift_addresses:
            drift.append({"address": address, "mode": "managed", "type": "aws_test", "change": {"actions": ["update"], "before": {"id": index}, "after": refreshed}})
            paths[address] = ("tags",)
    plan = {
        "format_version": "1.2", "terraform_version": "1.14.5", "complete": True,
        "errored": False, "resource_drift": drift, "resource_changes": changes,
        "output_changes": {"safe": {"actions": ["no-op"], "before": "x", "after": "x"}},
    }
    return plan, managed, paths


def drift_context(plan, managed, paths):
    stack = ExitStack()
    stack.enter_context(patch.object(EXECUTOR, "EXPECTED_DRIFT_PATHS", paths))
    stack.enter_context(patch.object(EXECUTOR, "RESOURCE_DRIFT_SHA256", EXECUTOR.compact_digest(plan["resource_drift"])))
    stack.enter_context(patch.object(EXECUTOR.PLAN_GATE, "EXPECTED_MANAGED_ADDRESSES", managed))
    return stack


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_apply_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_state_mutation_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["stateContentMutation"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_incident_digest_mutation_is_rejected(self):
        value = request()
        value["failedPlanJsonSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "incident digest changed"):
            EXECUTOR.validate_request(value)


class DriftGateTests(unittest.TestCase):
    def test_exact_reviewed_drift_is_accepted(self):
        plan, managed, paths = reviewed_plan()
        with drift_context(plan, managed, paths):
            result = EXECUTOR.validate_reviewed_drift(plan)
        self.assertEqual(len(result["drift"]), 7)

    def test_unreviewed_drift_address_is_rejected(self):
        plan, managed, paths = reviewed_plan()
        plan["resource_drift"][0]["address"] = "aws_test.unreviewed"
        with drift_context(plan, managed, paths), self.assertRaises(ValueError):
            EXECUTOR.validate_reviewed_drift(plan)

    def test_non_noop_managed_change_is_rejected(self):
        plan, managed, paths = reviewed_plan()
        plan["resource_changes"][0]["change"]["actions"] = ["update"]
        with drift_context(plan, managed, paths), self.assertRaisesRegex(ValueError, "not all no-op"):
            EXECUTOR.validate_reviewed_drift(plan)

    def test_refresh_after_mismatch_is_rejected(self):
        plan, managed, paths = reviewed_plan()
        plan["resource_drift"][0]["change"]["after"] = {"different": True}
        with drift_context(plan, managed, paths), self.assertRaises(ValueError):
            EXECUTOR.validate_reviewed_drift(plan)

    def test_changed_path_mutation_is_rejected(self):
        plan, managed, paths = reviewed_plan()
        plan["resource_drift"][0]["change"]["before"]["extra"] = True
        with drift_context(plan, managed, paths), self.assertRaises(ValueError):
            EXECUTOR.validate_reviewed_drift(plan)

    def test_output_change_is_rejected(self):
        plan, managed, paths = reviewed_plan()
        plan["output_changes"]["safe"]["actions"] = ["update"]
        with drift_context(plan, managed, paths), self.assertRaisesRegex(ValueError, "Output changes"):
            EXECUTOR.validate_reviewed_drift(plan)

    def test_import_is_rejected(self):
        plan, managed, paths = reviewed_plan()
        plan["resource_changes"][0]["change"]["importing"] = {"id": "x"}
        with drift_context(plan, managed, paths), self.assertRaisesRegex(ValueError, "not all no-op"):
            EXECUTOR.validate_reviewed_drift(plan)


class ExecutionTests(unittest.TestCase):
    def test_verify_result_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text("{}\n")
            context = {"request": {"expectedMainCommit": "1" * 40}, "request_path": path, "managed": set(range(13)), "data": set(range(9)), "remaining": 1800}
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["refresh_plan_execution_authorized"])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(result["state_content_mutation_authorized"])

    def test_execute_produces_only_refresh_plan_and_preserves_state(self):
        plan, managed, paths = reviewed_plan()
        data = {f"data.aws_test.item_{index}" for index in range(9)}
        state_bytes = b'{"canonical":"state"}\n'
        state_sha = hashlib.sha256(state_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            private.chmod(0o700)
            output = private / "refresh-output"
            working = private / "source"
            working.mkdir(mode=0o700)
            terraform_data = private / "terraform-data"
            terraform_data.mkdir(mode=0o700)
            tfvars = private / "input.tfvars"
            tfvars.write_text("x=true\n")
            tfvars.chmod(0o600)
            request_path = private / "request.json"
            request_path.write_text("{}\n")
            request_path.chmod(0o600)
            context = {
                "request": {"expectedMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12},
                "request_path": request_path, "output": output, "working": working,
                "terraform_data": terraform_data, "plan_request": {}, "tfvars": tfvars,
                "managed": managed, "data": data, "identities": {"bucket": "bucket", "kms_arn": "kms"},
                "backend_values": {"key": "bootstrap/terraform.tfstate"},
            }
            calls = []
            list_calls = 0

            def completed(arguments, code=0, stdout=b"", stderr=b""):
                return subprocess.CompletedProcess(arguments, code, stdout, stderr)

            def runner(arguments, environment, timeout, cwd):
                nonlocal list_calls
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
                        return completed(arguments, code=255, stderr=b"404 Not Found\n")
                    return completed(arguments, stdout=b'{"ServerSideEncryption":"aws:kms","SSEKMSKeyId":"kms","BucketKeyEnabled":true,"VersionId":"state-v1"}\n')
                if "list-object-versions" in arguments:
                    list_calls += 1
                    value = {"Versions": [{"Key": "bootstrap/terraform.tfstate", "VersionId": "state-v1", "IsLatest": True}], "DeleteMarkers": []}
                    if list_calls == 2:
                        value["Versions"].append({"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "lock-v1"})
                        value["DeleteMarkers"].append({"Key": "bootstrap/terraform.tfstate.tflock", "VersionId": "marker-v1", "IsLatest": True})
                    return completed(arguments, stdout=EXECUTOR.canonical_json(value))
                if "plan" in arguments:
                    target = Path(next(item.removeprefix("-out=") for item in arguments if item.startswith("-out=")))
                    target.write_bytes(b"refresh-plan")
                    target.chmod(0o600)
                    return completed(arguments, code=2, stdout=b"refresh only\n")
                if "show" in arguments and "-json" in arguments:
                    return completed(arguments, stdout=EXECUTOR.canonical_json(plan))
                if "show" in arguments:
                    return completed(arguments, stdout=b"refresh only plan\n")
                raise AssertionError(arguments)

            with drift_context(plan, managed, paths), patch.object(
                EXECUTOR, "verify_inputs", return_value=context
            ), patch.object(EXECUTOR, "REMOTE_STATE_SHA256", state_sha), patch.object(
                EXECUTOR.PROOF_EXECUTOR, "safe_environment", return_value={}
            ), patch.dict(os.environ, {"CONFIRM_BOOTSTRAP_REFRESH_ONLY_PLAN": EXECUTOR.CONFIRMATION}, clear=True):
                result = EXECUTOR.execute(request_path, repository_root=private, runner=runner, now=datetime(2026, 9, 26, tzinfo=timezone.utc))

            flattened = [item for call in calls for item in call]
            self.assertIn("-refresh-only", flattened)
            self.assertNotIn("init", flattened)
            self.assertNotIn("apply", flattened)
            self.assertNotIn("push", flattened)
            self.assertNotIn("force-unlock", flattened)
            self.assertEqual(result["refresh_plan_exit_code"], 2)
            self.assertFalse(result["state_content_mutated"])
            self.assertFalse(result["state_object_history_changed"])
            self.assertEqual(result["lock_object_version_delta"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

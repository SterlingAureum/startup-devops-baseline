#!/usr/bin/env python3
"""Offline tests for the exact state-pull check_results normalization repair."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load executor")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module(EXECUTOR_PATH, "state_pull_check_results_normalization_tests")


def request() -> dict:
    return {
        "schemaVersion": "v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "1" * 12,
        "privateFailedApplyRequestPath": "/private/failed-request.json",
        "privateFailedApplyRequestSha256": EXECUTOR.FAILED_APPLY_REQUEST_SHA256,
        "privateFailedApplyOutputDirectory": "/private/failed-output",
        "failedIdentityStdoutSha256": EXECUTOR.FAILED_IDENTITY_STDOUT_SHA256,
        "failedStatePullSha256": EXECUTOR.NORMALIZED_STATE_SHA256,
        "failedStatePullSize": EXECUTOR.NORMALIZED_STATE_SIZE,
        "normalizedCheckResultsSha256": EXECUTOR.NORMALIZED_CHECK_RESULTS_SHA256,
        "semanticProjectionSha256": EXECUTOR.SEMANTIC_PROJECTION_SHA256,
        "privateApplyOutputDirectory": "/private/new-output",
        "approval": {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsIdentityAndS3Read": True, "terraformStatePullAndList": True,
            "exactSavedRefreshPlanApply": True, "acceptExactCheckResultsNormalization": True,
            "terraformInit": False, "terraformPlan": False, "unsavedApply": False,
            "statePush": False, "destroy": False, "iamPolicyAttachment": False,
            "directS3Mutation": False, "forceUnlock": False,
            "automaticRetry": False, "automaticRollback": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_new_plan_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformPlan"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_unsaved_apply_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["unsavedApply"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)

    def test_retry_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["automaticRetry"] = True
        with self.assertRaisesRegex(ValueError, "execution boundary changed"):
            EXECUTOR.validate_request(value)


class NormalizationTests(unittest.TestCase):
    def test_production_projection_digest_uses_all_non_check_results_keys(self):
        self.assertEqual(
            EXECUTOR.SEMANTIC_PROJECTION_SHA256,
            "1d21a9edbfe82d1d1496b312c8a31996c20f9f4bf8505604a277cbdede2f8d15",
        )

    def states(self):
        reviewed = {
            "version": 4,
            "terraform_version": "1.14.5",
            "serial": 1,
            "lineage": "lineage",
            "outputs": {"value": {"value": "same"}},
            "resources": [{"mode": "managed", "type": "test", "name": "same"}],
            "check_results": [{"status": "old"}],
        }
        observed = deepcopy(reviewed)
        observed["check_results"] = [{"status": "normalized"}]
        observed_bytes = EXECUTOR.BASE.canonical_json(observed)
        projection = {key: value for key, value in observed.items() if key != "check_results"}
        return reviewed, observed, observed_bytes, hashlib.sha256(EXECUTOR.BASE.compact_json(observed["check_results"])).hexdigest(), hashlib.sha256(EXECUTOR.BASE.compact_json(projection)).hexdigest()

    def validate(self, reviewed, observed_bytes, check_results_sha, projection_sha):
        return EXECUTOR.BASE.validate_check_results_normalization(
            reviewed,
            observed_bytes,
            observed_state_sha256=hashlib.sha256(observed_bytes).hexdigest(),
            observed_check_results_sha256=check_results_sha,
            semantic_projection_sha256=projection_sha,
        )

    def test_only_exact_check_results_normalization_is_accepted(self):
        reviewed, observed, observed_bytes, check_results_sha, projection_sha = self.states()
        self.assertEqual(self.validate(reviewed, observed_bytes, check_results_sha, projection_sha), observed)

    def test_resource_change_is_rejected(self):
        reviewed, observed, _, check_results_sha, projection_sha = self.states()
        observed["resources"][0]["name"] = "changed"
        with self.assertRaisesRegex(ValueError, "Only check_results"):
            self.validate(reviewed, EXECUTOR.BASE.canonical_json(observed), check_results_sha, projection_sha)

    def test_lineage_change_is_rejected(self):
        reviewed, observed, _, check_results_sha, projection_sha = self.states()
        observed["lineage"] = "changed"
        with self.assertRaisesRegex(ValueError, "Only check_results"):
            self.validate(reviewed, EXECUTOR.BASE.canonical_json(observed), check_results_sha, projection_sha)

    def test_serial_change_is_rejected(self):
        reviewed, observed, _, check_results_sha, projection_sha = self.states()
        observed["serial"] = 2
        with self.assertRaisesRegex(ValueError, "Only check_results"):
            self.validate(reviewed, EXECUTOR.BASE.canonical_json(observed), check_results_sha, projection_sha)

    def test_wrong_check_results_digest_is_rejected(self):
        reviewed, _, observed_bytes, _, projection_sha = self.states()
        with self.assertRaisesRegex(ValueError, "check_results digest"):
            self.validate(reviewed, observed_bytes, "0" * 64, projection_sha)


class ExecutionBoundaryTests(unittest.TestCase):
    def test_verify_result_is_command_free_and_unauthorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text("{}\n")
            context = {
                "request": {"expectedMainCommit": "1" * 40},
                "request_path": path,
                "managed": set(range(13)),
                "data": set(range(9)),
                "remaining": 1800,
            }
            result = EXECUTOR.redacted_verification(context)
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["apply_execution_authorized"])
        self.assertFalse(result["terraform_plan_authorized"])
        self.assertFalse(result["unsaved_apply_authorized"])
        self.assertFalse(result["prior_apply_executed"])

    def test_execute_delegates_only_after_new_confirmation(self):
        context = {"request": {"expectedMainCommit": "1" * 40}}
        expected = {"status": "ok"}
        with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
            EXECUTOR.BASE, "execute_verified", return_value=expected
        ) as delegated, patch.dict(
            os.environ,
            {"CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION_NORMALIZATION": EXECUTOR.CONFIRMATION},
            clear=True,
        ):
            result = EXECUTOR.execute(Path("/private/request.json"), repository_root=ROOT, now=datetime(2026, 9, 26, tzinfo=timezone.utc))
        self.assertEqual(result, expected)
        delegated.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

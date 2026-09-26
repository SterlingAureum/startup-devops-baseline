#!/usr/bin/env python3
"""Offline tests for the exact dual-form pre-apply state gate."""

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py"

spec = importlib.util.spec_from_file_location("dual_form_tests", PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load executor")
EXECUTOR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EXECUTOR)


def request():
    return {
        "schemaVersion": "v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline", "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40, "expectedAwsAccountId": "1" * 12,
        "privateFailedNormalizationRequestPath": "/private/request.json",
        "privateFailedNormalizationRequestSha256": EXECUTOR.FAILED_NORMALIZATION_REQUEST_SHA256,
        "privateFailedNormalizationOutputDirectory": "/private/output",
        "failedIdentityStdoutSha256": EXECUTOR.FAILED_IDENTITY_STDOUT_SHA256,
        "canonicalStateSha256": EXECUTOR.CANONICAL_STATE_SHA256,
        "normalizedStateSha256": EXECUTOR.NORMALIZED_STATE_SHA256,
        "canonicalCheckResultsSha256": EXECUTOR.CANONICAL_CHECK_RESULTS_SHA256,
        "normalizedCheckResultsSha256": EXECUTOR.NORMALIZED_CHECK_RESULTS_SHA256,
        "semanticProjectionSha256": EXECUTOR.SEMANTIC_PROJECTION_SHA256,
        "privateApplyOutputDirectory": "/private/new-output",
        "approval": {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"},
        "executionBoundary": {
            "awsIdentityAndS3Read": True, "terraformStatePullAndList": True,
            "exactSavedRefreshPlanApply": True, "acceptReviewedCanonicalState": True,
            "acceptReviewedCheckResultsNormalizedState": True,
            "terraformInit": False, "terraformPlan": False, "unsavedApply": False,
            "statePush": False, "destroy": False, "iamPolicyAttachment": False,
            "directS3Mutation": False, "forceUnlock": False,
            "automaticRetry": False, "automaticRollback": False,
        },
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_third_form_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["acceptThirdSemanticForm"] = True
        with self.assertRaisesRegex(ValueError, "fields changed|boundary changed"):
            EXECUTOR.validate_request(value)

    def test_plan_and_retry_authority_are_rejected(self):
        for field in ("terraformPlan", "automaticRetry"):
            value = request()
            value["executionBoundary"][field] = True
            with self.assertRaisesRegex(ValueError, "boundary changed"):
                EXECUTOR.validate_request(value)


class StateGateTests(unittest.TestCase):
    def setUp(self):
        self.canonical = {
            "version": 4, "terraform_version": "1.14.5", "serial": 1,
            "lineage": "lineage", "outputs": {}, "resources": [],
            "check_results": [{"status": "canonical"}],
        }
        self.normalized = deepcopy(self.canonical)
        self.normalized["check_results"] = [{"status": "normalized"}]
        self.canonical_bytes = EXECUTOR.BASE.canonical_json(self.canonical)
        self.normalized_bytes = EXECUTOR.BASE.canonical_json(self.normalized)
        projection = {key: value for key, value in self.canonical.items() if key != "check_results"}
        self.context = {
            "reviewed_before_state": self.canonical,
            "normalized_before_state": self.normalized,
            "accepted_pre_apply_state_forms": {
                hashlib.sha256(self.canonical_bytes).hexdigest(): "reviewed-canonical",
                hashlib.sha256(self.normalized_bytes).hexdigest(): "reviewed-check-results-normalized",
            },
            "check_results_normalization": {
                "check_results_sha256": hashlib.sha256(EXECUTOR.BASE.compact_json(self.normalized["check_results"])).hexdigest(),
                "semantic_projection_sha256": hashlib.sha256(EXECUTOR.BASE.compact_json(projection)).hexdigest(),
            },
        }

    def test_both_exact_forms_are_accepted(self):
        canonical, canonical_form, _ = EXECUTOR.BASE.validate_pre_apply_state(self.context, self.canonical_bytes)
        normalized, normalized_form, _ = EXECUTOR.BASE.validate_pre_apply_state(self.context, self.normalized_bytes)
        self.assertEqual(canonical, self.canonical)
        self.assertEqual(normalized, self.normalized)
        self.assertEqual(canonical_form, "reviewed-canonical")
        self.assertEqual(normalized_form, "reviewed-check-results-normalized")

    def test_third_check_results_form_is_rejected(self):
        third = deepcopy(self.canonical)
        third["check_results"] = [{"status": "third"}]
        with self.assertRaisesRegex(ValueError, "outside the exact accepted forms"):
            EXECUTOR.BASE.validate_pre_apply_state(self.context, EXECUTOR.BASE.canonical_json(third))

    def test_resource_and_serial_changes_are_rejected(self):
        for key, value in (("resources", [{"mode": "managed"}]), ("serial", 2)):
            changed = deepcopy(self.canonical)
            changed[key] = value
            with self.assertRaisesRegex(ValueError, "outside the exact accepted forms"):
                EXECUTOR.BASE.validate_pre_apply_state(self.context, EXECUTOR.BASE.canonical_json(changed))


class ExecutionTests(unittest.TestCase):
    def test_execute_delegates_only_after_new_confirmation(self):
        context = {"request": {"expectedMainCommit": "1" * 40}}
        with patch.object(EXECUTOR, "verify_inputs", return_value=context), patch.object(
            EXECUTOR.BASE, "execute_verified", return_value={"status": "ok"}
        ) as delegated, patch.dict(os.environ, {"CONFIRM_REFRESH_ONLY_STATE_RECONCILIATION_DUAL_FORM": EXECUTOR.CONFIRMATION}, clear=True):
            result = EXECUTOR.execute(Path("/private/request.json"), repository_root=ROOT)
        self.assertEqual(result["status"], "ok")
        delegated.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

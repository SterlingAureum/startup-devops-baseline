#!/usr/bin/env python3
"""Offline mutation tests for shared dev/test teardown request preflight."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.2-shared-dev-test-two-wave-teardown-request-preflight"
MODULE_PATH = ROOT / "scripts/aws_two_wave_teardown_preflight.py"
FIXTURE_PATH = ROOT / f"delivery/examples/{PREFIX}-fixtures.json"


def load_module():
    spec = importlib.util.spec_from_file_location("two_wave_preflight_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text())
        self.now = self.fixture["verificationClockUtc"]
        self.dev = copy.deepcopy(self.fixture["devWaveOnePlanRequest"])
        self.test = copy.deepcopy(self.fixture["testWaveTwoApplyRequest"])

    def rejected(self, value):
        with self.assertRaises(MODULE.TeardownGateError):
            MODULE.verify_request(value, now_utc=self.now)

    def reviewed_plan(self, wave, count):
        return {
            "wave": wave,
            "binaryPlanSha256": "d" * 64,
            "planRecordSha256": "e" * 64,
            "humanReviewed": True,
            "managedDeleteCount": count,
            "planReviewExpiresAtUtc": "2026-10-09T04:00:00Z",
        }

    def test_phase_inventory_is_exact(self):
        self.assertEqual(list(MODULE.PHASES), [
            "controller-cleanup", "wave-one-plan", "wave-one-apply",
            "post-wave-one-inventory", "safe-residue-delete",
            "wave-two-plan", "wave-two-apply", "final-read-only-audit",
        ])

    def test_dev_wave_one_plan_is_accepted(self):
        result = MODULE.verify_request(self.dev, now_utc=self.now)
        self.assertEqual(result["requestedAuthority"], "terraform-plan")
        self.assertFalse(result["executionAuthorized"])
        self.assertEqual(result["remainingApprovalSeconds"], 3300)

    def test_test_wave_two_apply_is_accepted(self):
        result = MODULE.verify_request(self.test, now_utc=self.now)
        self.assertEqual(result["environment"], "aws-test")
        self.assertTrue(result["remoteStateActivationRequiredByProfile"])
        self.assertEqual(result["reviewedBinaryPlanSha256"], "d" * 64)

    def test_request_hash_is_canonical_and_stable(self):
        first = MODULE.verify_request(self.dev, now_utc=self.now)["requestSha256"]
        reordered = {key: self.dev[key] for key in reversed(self.dev)}
        second = MODULE.verify_request(reordered, now_utc=self.now)["requestSha256"]
        self.assertEqual(first, second)

    def test_request_is_not_mutated(self):
        original = copy.deepcopy(self.dev)
        MODULE.verify_request(self.dev, now_utc=self.now)
        self.assertEqual(self.dev, original)

    def test_prod_is_rejected(self):
        self.dev["environment"] = "aws-prod"
        self.dev["stateKey"] = "environments/prod/terraform.tfstate"
        self.rejected(self.dev)

    def test_cross_environment_state_key_is_rejected(self):
        self.dev["stateKey"] = "environments/test/terraform.tfstate"
        self.rejected(self.dev)

    def test_remote_state_not_ready_is_rejected(self):
        self.test["state"]["remoteStateReady"] = False
        self.rejected(self.test)

    def test_malformed_commit_is_rejected(self):
        self.dev["controlPlaneCommit"] = "0" * 39
        self.rejected(self.dev)

    def test_nonpositive_attempt_is_rejected(self):
        self.dev["attemptNumber"] = 0
        self.rejected(self.dev)

    def test_boolean_attempt_is_rejected(self):
        self.dev["attemptNumber"] = True
        self.rejected(self.dev)

    def test_unknown_phase_is_rejected(self):
        self.dev["phase"] = "destroy-everything"
        self.rejected(self.dev)

    def test_future_request_is_rejected(self):
        self.dev["notBeforeUtc"] = "2026-10-09T00:11:00Z"
        self.rejected(self.dev)

    def test_expired_request_is_rejected(self):
        self.dev["expiresAtUtc"] = self.now
        self.rejected(self.dev)

    def test_fractional_timestamp_is_rejected(self):
        self.dev["createdAtUtc"] = "2026-10-09T00:00:00.000Z"
        self.rejected(self.dev)

    def test_plan_window_over_one_hour_is_rejected(self):
        self.dev["expiresAtUtc"] = "2026-10-09T01:05:01Z"
        self.rejected(self.dev)

    def test_apply_window_of_three_hours_is_accepted(self):
        MODULE.verify_request(self.test, now_utc=self.now)

    def test_apply_window_over_three_hours_is_rejected(self):
        self.test["expiresAtUtc"] = "2026-10-09T03:05:01Z"
        self.rejected(self.test)

    def test_first_phase_without_predecessor_is_accepted(self):
        self.dev["phase"] = "controller-cleanup"
        self.dev["predecessorReceiptSha256"] = None
        result = MODULE.verify_request(self.dev, now_utc=self.now)
        self.assertEqual(result["requestedAuthority"], "kubernetes-controller-mutation")

    def test_first_phase_with_predecessor_is_rejected(self):
        self.dev["phase"] = "controller-cleanup"
        self.rejected(self.dev)

    def test_later_phase_without_predecessor_is_rejected(self):
        self.dev["predecessorReceiptSha256"] = None
        self.rejected(self.dev)

    def test_malformed_predecessor_is_rejected(self):
        self.dev["predecessorReceiptSha256"] = "not-a-sha"
        self.rejected(self.dev)

    def test_extra_request_key_is_rejected(self):
        self.dev["unexpected"] = False
        self.rejected(self.dev)

    def test_missing_request_key_is_rejected(self):
        del self.dev["inputEvidenceSha256"]
        self.rejected(self.dev)

    def test_malformed_input_evidence_hash_is_rejected(self):
        self.dev["inputEvidenceSha256"] = "A" * 64
        self.rejected(self.dev)

    def test_state_counts_must_reconcile(self):
        self.dev["state"]["managedAddressCount"] = 5
        self.rejected(self.dev)

    def test_early_phase_requires_non_network_state(self):
        self.dev["state"]["managedAddressCount"] = 2
        self.dev["state"]["nonNetworkAddressCount"] = 0
        self.rejected(self.dev)

    def test_network_phase_rejects_non_network_state(self):
        self.test["phase"] = "wave-two-plan"
        self.test["reviewedPlan"] = None
        self.test["state"]["managedAddressCount"] = 3
        self.test["state"]["nonNetworkAddressCount"] = 1
        self.rejected(self.test)

    def test_final_audit_requires_empty_state(self):
        self.test["phase"] = "final-read-only-audit"
        self.test["reviewedPlan"] = None
        self.rejected(self.test)

    def test_empty_final_audit_is_accepted(self):
        self.test["phase"] = "final-read-only-audit"
        self.test["expiresAtUtc"] = "2026-10-09T01:05:00Z"
        self.test["reviewedPlan"] = None
        self.test["state"].update(managedAddressCount=0, networkAddressCount=0, nonNetworkAddressCount=0)
        result = MODULE.verify_request(self.test, now_utc=self.now)
        self.assertEqual(result["managedAddressCount"], 0)

    def test_reviewed_plan_is_rejected_outside_apply(self):
        self.dev["reviewedPlan"] = self.reviewed_plan("non-network", 2)
        self.rejected(self.dev)

    def test_apply_requires_reviewed_plan(self):
        self.test["reviewedPlan"] = None
        self.rejected(self.test)

    def test_apply_rejects_wrong_wave(self):
        self.test["reviewedPlan"]["wave"] = "non-network"
        self.rejected(self.test)

    def test_apply_rejects_unreviewed_plan(self):
        self.test["reviewedPlan"]["humanReviewed"] = False
        self.rejected(self.test)

    def test_apply_rejects_delete_count_drift(self):
        self.test["reviewedPlan"]["managedDeleteCount"] = 1
        self.rejected(self.test)

    def test_apply_rejects_expired_plan_review(self):
        self.test["reviewedPlan"]["planReviewExpiresAtUtc"] = self.now
        self.rejected(self.test)

    def test_apply_request_cannot_outlive_plan_review(self):
        self.test["reviewedPlan"]["planReviewExpiresAtUtc"] = "2026-10-09T03:00:00Z"
        self.rejected(self.test)

    def test_wave_one_apply_binds_non_network_count(self):
        self.dev["phase"] = "wave-one-apply"
        self.dev["reviewedPlan"] = self.reviewed_plan("non-network", 2)
        result = MODULE.verify_request(self.dev, now_utc=self.now)
        self.assertEqual(result["requestedAuthority"], "terraform-apply")

    def test_safe_residue_phase_is_accepted(self):
        self.test["phase"] = "safe-residue-delete"
        self.test["expiresAtUtc"] = "2026-10-09T01:05:00Z"
        self.test["reviewedPlan"] = None
        self.test["safeResidue"] = {
            "category": "orphan-eks-cluster-security-group",
            "identitySha256": "f" * 64,
            "exactBound": True,
            "deletionAuthorized": False,
        }
        result = MODULE.verify_request(self.test, now_utc=self.now)
        self.assertEqual(result["safeResidueIdentitySha256"], "f" * 64)
        self.assertFalse(result["executionAuthorized"])

    def test_safe_residue_is_rejected_outside_delete_phase(self):
        self.dev["safeResidue"] = {
            "category": "orphan-kubernetes-eni",
            "identitySha256": "f" * 64,
            "exactBound": True,
            "deletionAuthorized": False,
        }
        self.rejected(self.dev)

    def test_safe_residue_unknown_category_is_rejected(self):
        self.test["phase"] = "safe-residue-delete"
        self.test["reviewedPlan"] = None
        self.test["safeResidue"] = {
            "category": "unknown-cloud-object",
            "identitySha256": "f" * 64,
            "exactBound": True,
            "deletionAuthorized": False,
        }
        self.rejected(self.test)

    def test_safe_residue_pre_authorization_is_rejected(self):
        self.test["phase"] = "safe-residue-delete"
        self.test["reviewedPlan"] = None
        self.test["safeResidue"] = {
            "category": "orphan-kubernetes-eni",
            "identitySha256": "f" * 64,
            "exactBound": True,
            "deletionAuthorized": True,
        }
        self.rejected(self.test)

    def test_every_authority_pregrant_is_rejected(self):
        for key in MODULE.AUTHORITY_KEYS:
            with self.subTest(key=key):
                candidate = copy.deepcopy(self.dev)
                candidate["authority"][key] = True
                self.rejected(candidate)


if __name__ == "__main__":
    unittest.main()

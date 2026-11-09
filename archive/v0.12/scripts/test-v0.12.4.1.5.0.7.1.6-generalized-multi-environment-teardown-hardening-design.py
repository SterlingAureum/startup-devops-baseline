#!/usr/bin/env python3
"""Offline mutation tests for generalized teardown hardening design."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6-generalized-multi-environment-teardown-hardening-design"
CHECKER_PATH = ROOT / f"scripts/check-{PREFIX}.py"
CONTRACT_PATH = ROOT / f"delivery/contracts/{PREFIX}.json"


def load_checker():
    spec = importlib.util.spec_from_file_location("generalized_teardown_design_under_test", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads(CONTRACT_PATH.read_text())

    def assert_rejected(self, mutate):
        value = copy.deepcopy(self.contract)
        mutate(value)
        with self.assertRaises(CHECKER.ContractError):
            CHECKER.validate_contract(value)

    def test_canonical_contract_is_accepted(self):
        CHECKER.validate_contract(self.contract)

    def test_false_implementation_claim_is_rejected(self):
        self.assert_rejected(lambda value: value["currentAssessment"].__setitem__("generalizedExecutorImplemented", True))

    def test_backend_destroy_is_rejected(self):
        self.assert_rejected(lambda value: value["backendBoundary"].__setitem__("ordinaryEnvironmentTeardownMayDestroyBackend", True))

    def test_state_object_delete_is_rejected(self):
        self.assert_rejected(lambda value: value["backendBoundary"].__setitem__("ordinaryEnvironmentTeardownMayDeleteStateObject", True))

    def test_test_remote_state_prerequisite_is_rejected(self):
        self.assert_rejected(lambda value: value["environmentProfiles"]["aws-test"].__setitem__("remoteStateActivationRequiredBeforeLiveCreate", False))

    def test_prod_live_destroy_is_rejected(self):
        self.assert_rejected(lambda value: value["environmentProfiles"]["aws-prod"].__setitem__("liveTeardownAllowedAfterImplementationAndSeparateApproval", True))

    def test_prod_backup_delete_is_rejected(self):
        self.assert_rejected(lambda value: value["environmentProfiles"]["aws-prod"].__setitem__("applicationBackupDeletionAllowed", True))

    def test_unknown_dependency_delete_is_rejected(self):
        self.assert_rejected(lambda value: value["planAndRecoveryBoundary"].__setitem__("unknownDependencyDeleteAllowed", True))

    def test_partial_plan_reuse_is_rejected(self):
        self.assert_rejected(lambda value: value["planAndRecoveryBoundary"].__setitem__("partiallyAppliedPlanReusable", True))

    def test_single_wave_regression_is_rejected(self):
        self.assert_rejected(lambda value: value["planAndRecoveryBoundary"].__setitem__("twoWaveTeardownRequired", False))

    def test_incident_recovery_as_acceptance_is_rejected(self):
        self.assert_rejected(lambda value: value["releaseAcceptance"].__setitem__("incidentRecoveryDuringAcceptanceAllowed", True))

    def test_historical_evidence_ci_binding_is_rejected(self):
        self.assert_rejected(lambda value: value["auditAndCiBoundary"].__setitem__("historicalExecutionEvidenceRequiredCi", True))

    def test_live_authority_is_rejected(self):
        self.assert_rejected(lambda value: value["authority"].__setitem__("livePlanAuthorized", True))

    def test_backend_retirement_authority_is_rejected(self):
        self.assert_rejected(lambda value: value["authority"].__setitem__("backendRetirementAuthorized", True))


if __name__ == "__main__":
    unittest.main()

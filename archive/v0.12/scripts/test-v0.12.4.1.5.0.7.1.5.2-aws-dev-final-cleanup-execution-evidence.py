#!/usr/bin/env python3
"""Offline mutation tests for final AWS-dev cleanup evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.5.2-aws-dev-final-cleanup-execution-evidence"
CHECKER_PATH = ROOT / f"scripts/check-{PREFIX}.py"
CONTRACT_PATH = ROOT / f"delivery/contracts/{PREFIX}.json"


def load_checker():
    spec = importlib.util.spec_from_file_location("final_cleanup_evidence_under_test", CHECKER_PATH)
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

    def test_artifact_digest_drift_is_rejected(self):
        self.assert_rejected(lambda value: value["artifactBindings"].__setitem__("binaryPlanSha256", "0" * 64))

    def test_repeat_delete_is_rejected(self):
        self.assert_rejected(lambda value: value["incidentAndRecovery"].__setitem__("securityGroupDeleteRetried", True))

    def test_extra_plan_delete_is_rejected(self):
        self.assert_rejected(lambda value: value["reviewedPlan"].__setitem__("managedDeleteCount", 2))

    def test_nonempty_state_is_rejected(self):
        self.assert_rejected(lambda value: value["validatedOutcome"].__setitem__("totalStateAddressCount", 1))

    def test_vpc_presence_is_rejected(self):
        self.assert_rejected(lambda value: value["validatedOutcome"].__setitem__("vpcAbsent", False))

    def test_live_command_producer_is_rejected(self):
        self.assert_rejected(lambda value: value["packageProducer"].__setitem__("runsAws", True))

    def test_new_execution_authority_is_rejected(self):
        self.assert_rejected(lambda value: value["authority"].__setitem__("executionAuthorized", True))

    def test_private_identity_disclosure_is_rejected(self):
        self.assert_rejected(lambda value: value["privacyBoundary"].__setitem__("privateResourceIdentityEmitted", True))

    def test_account_cost_claim_is_rejected(self):
        self.assert_rejected(lambda value: value["scopeBoundary"].__setitem__("accountWideCostFreeClaimed", True))

    def test_ci_binding_is_rejected(self):
        self.assert_rejected(lambda value: value["auditIntegration"].__setitem__("requiredCiCheck", True))

    def test_raw_aws_identifier_is_rejected(self):
        self.assert_rejected(lambda value: value.__setitem__("leak", "vpc-deadbeef"))


if __name__ == "__main__":
    unittest.main()

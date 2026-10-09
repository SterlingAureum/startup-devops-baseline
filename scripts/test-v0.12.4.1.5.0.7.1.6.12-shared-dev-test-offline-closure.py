#!/usr/bin/env python3
"""Offline tests for the frozen teardown proof and live-readiness boundary."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.12-shared-dev-test-offline-closure"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = load(ROOT / f"scripts/check-{PREFIX}.py", "offline_closure_check_under_test")
CONTRACT = json.loads((ROOT / f"delivery/contracts/{PREFIX}.json").read_text())
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())


class OfflineClosureTests(unittest.TestCase):
    def assert_rejected(self, mutation):
        contract = deepcopy(CONTRACT)
        mutation(contract)
        with self.assertRaises(CHECK.ContractError):
            CHECK.validate_contract(contract, FIXTURE)

    def test_exact_repository_closure_is_valid(self):
        result = CHECK.validate_repository(ROOT)
        self.assertEqual(result["frozenArtifactCount"], 18)
        self.assertEqual(result["liveReadinessGapCount"], 7)
        self.assertTrue(result["offlineClosureReady"])
        self.assertFalse(result["liveExecutionReady"])
        self.assertFalse(result["liveCommandExecuted"])

    def test_baseline_and_frozen_digest_cannot_change(self):
        self.assert_rejected(lambda value: value.update(implementationBaselineCommit="0" * 40))
        first = next(iter(CONTRACT["frozenArtifacts"]))
        self.assert_rejected(lambda value: value["frozenArtifacts"].__setitem__(first, "not-a-digest"))
        self.assert_rejected(lambda value: value["frozenArtifacts"].pop(first))
        self.assert_rejected(lambda value: value["frozenArtifacts"].update({"scripts/replacement.py": value["frozenArtifacts"].pop(first)}))
        with mock.patch.object(CHECK, "file_sha256", return_value="0" * 64):
            with self.assertRaises(CHECK.ContractError):
                CHECK.validate_repository(ROOT)

    def test_live_gap_cannot_be_removed_reordered_or_marked_ready(self):
        self.assert_rejected(lambda value: value["liveReadinessGaps"].pop())
        self.assert_rejected(lambda value: value["liveReadinessGaps"].reverse())
        self.assert_rejected(lambda value: value["liveReadinessGaps"][0].update(status="implemented"))
        self.assert_rejected(lambda value: value["liveReadinessGaps"][0].update(blocksLiveExecutionClaim=False))

    def test_fixed_fake_proof_cannot_be_promoted_to_live_proof(self):
        self.assert_rejected(lambda value: value["offlineProof"].update(liveCommandExecuted=True))
        self.assert_rejected(lambda value: value["offlineProof"].update(rejectedEnvironment="none"))
        self.assert_rejected(lambda value: value["offlineProof"].update(fixedFakeBackendCallCount=99))

    def test_remote_state_backend_cannot_join_application_teardown(self):
        self.assert_rejected(lambda value: value["stateBackendBoundary"].update(applicationTeardownMayDeleteRemoteStateBackend=True))
        self.assert_rejected(lambda value: value["stateBackendBoundary"].update(backendRetirementRequiresSeparatePlanReviewAndApproval=False))
        self.assert_rejected(lambda value: value["stateBackendBoundary"].update(automaticBackendRetirementAuthorized=True))

    def test_closure_cannot_add_runtime_or_live_authority(self):
        self.assert_rejected(lambda value: value["implementationBoundary"].update(runtimeSourceAdded=True))
        self.assert_rejected(lambda value: value["implementationBoundary"].update(commandEntrypointAdded=True))
        self.assert_rejected(lambda value: value["authority"].update(terraformPlanAuthorized=True))
        self.assert_rejected(lambda value: value["authority"].update(backendRetirementAuthorized=True))

    def test_contract_and_fixture_are_redacted(self):
        raw = json.dumps({"contract": CONTRACT, "fixture": FIXTURE}, sort_keys=True).lower()
        for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-"):
            self.assertNotIn(marker, raw)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Offline tests for the shared dev/test two-wave teardown core."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.1-shared-dev-test-two-wave-teardown-core"
CORE_PATH = ROOT / "scripts/aws_two_wave_teardown_core.py"
FIXTURE_PATH = ROOT / f"delivery/examples/{PREFIX}-fixtures.json"


def load_core():
    spec = importlib.util.spec_from_file_location("two_wave_teardown_core_under_test", CORE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORE = load_core()


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text())

    def test_dev_and_test_profiles_are_supported(self):
        self.assertEqual(CORE.environment_profile("aws-dev")["stateKey"], "environments/dev/terraform.tfstate")
        self.assertEqual(CORE.environment_profile("aws-test")["stateKey"], "environments/test/terraform.tfstate")

    def test_prod_profile_is_rejected(self):
        with self.assertRaises(CORE.TeardownGateError):
            CORE.environment_profile("aws-prod")

    def test_address_partition_is_exact(self):
        result = CORE.partition_managed_addresses(self.fixture["initialManagedAddresses"])
        self.assertEqual(len(result["networkAddresses"]), 2)
        self.assertEqual(len(result["nonNetworkAddresses"]), 2)

    def test_duplicate_address_is_rejected(self):
        values = self.fixture["initialManagedAddresses"] * 2
        with self.assertRaises(CORE.TeardownGateError):
            CORE.partition_managed_addresses(values)

    def test_wave_one_plan_is_accepted(self):
        result = CORE.gate_wave_one_plan(self.fixture["waveOnePlan"], self.fixture["initialManagedAddresses"])
        self.assertEqual(result["wave"], "non-network")
        self.assertEqual(result["managedDeleteCount"], 2)

    def test_wave_one_network_delete_is_rejected(self):
        plan = copy.deepcopy(self.fixture["waveOnePlan"])
        plan["resource_changes"].append({"address": "module.vpc.aws_vpc.this", "mode": "managed", "change": {"actions": ["delete"], "importing": None}})
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_wave_one_plan(plan, self.fixture["initialManagedAddresses"])

    def test_wave_one_update_is_rejected(self):
        plan = copy.deepcopy(self.fixture["waveOnePlan"])
        plan["resource_changes"][0]["change"]["actions"] = ["update"]
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_wave_one_plan(plan, self.fixture["initialManagedAddresses"])

    def test_wave_one_import_is_rejected(self):
        plan = copy.deepcopy(self.fixture["waveOnePlan"])
        plan["resource_changes"][0]["change"]["importing"] = {"id": "redacted"}
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_wave_one_plan(plan, self.fixture["initialManagedAddresses"])

    def test_post_wave_one_exact_network_state_is_accepted(self):
        result = CORE.gate_post_wave_one_state(self.fixture["initialManagedAddresses"], self.fixture["postWaveOneManagedAddresses"])
        self.assertEqual(result["nonNetworkManagedCount"], 0)

    def test_post_wave_one_residual_non_network_state_is_rejected(self):
        current = self.fixture["postWaveOneManagedAddresses"] + ["module.eks.aws_eks_cluster.this"]
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_post_wave_one_state(self.fixture["initialManagedAddresses"], current)

    def test_clean_dependency_inventory_is_wave_two_eligible(self):
        result = CORE.gate_dependency_inventory(self.fixture["dependencyInventory"], "aws-dev", 2)
        self.assertTrue(result["waveTwoEligible"])

    def test_safe_residue_requires_separate_approval(self):
        inventory = copy.deepcopy(self.fixture["dependencyInventory"])
        inventory["safeResidues"] = [{"category": "orphan-kubernetes-eni", "identitySha256": "a" * 64, "exactBound": True, "deletionAuthorized": False}]
        result = CORE.gate_dependency_inventory(inventory, "aws-dev", 2)
        self.assertFalse(result["waveTwoEligible"])
        self.assertTrue(result["separateCleanupApprovalRequired"])

    def test_inventory_cannot_authorize_residue_delete(self):
        inventory = copy.deepcopy(self.fixture["dependencyInventory"])
        inventory["safeResidues"] = [{"category": "orphan-kubernetes-eni", "identitySha256": "a" * 64, "exactBound": True, "deletionAuthorized": True}]
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_dependency_inventory(inventory, "aws-dev", 2)

    def test_unknown_dependency_is_rejected(self):
        inventory = copy.deepcopy(self.fixture["dependencyInventory"])
        inventory["unknownDependencyCount"] = 1
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_dependency_inventory(inventory, "aws-dev", 2)

    def test_eks_presence_is_rejected(self):
        inventory = copy.deepcopy(self.fixture["dependencyInventory"])
        inventory["eksAbsent"] = False
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_dependency_inventory(inventory, "aws-dev", 2)

    def test_wave_two_plan_is_accepted(self):
        dependency = CORE.gate_dependency_inventory(self.fixture["dependencyInventory"], "aws-dev", 2)
        result = CORE.gate_wave_two_plan(self.fixture["waveTwoPlan"], self.fixture["postWaveOneManagedAddresses"], dependency)
        self.assertEqual(result["wave"], "network")

    def test_wave_two_with_safe_residue_is_rejected(self):
        dependency = {"safeResidueCount": 1, "separateCleanupApprovalRequired": True, "waveTwoEligible": False}
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_wave_two_plan(self.fixture["waveTwoPlan"], self.fixture["postWaveOneManagedAddresses"], dependency)

    def test_wave_two_missing_network_delete_is_rejected(self):
        plan = copy.deepcopy(self.fixture["waveTwoPlan"])
        plan["resource_changes"].pop()
        dependency = CORE.gate_dependency_inventory(self.fixture["dependencyInventory"], "aws-dev", 2)
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_wave_two_plan(plan, self.fixture["postWaveOneManagedAddresses"], dependency)

    def test_plan_history_delta_is_accepted(self):
        result = CORE.gate_history_delta(self.fixture["planHistoryBefore"], self.fixture["planHistoryAfter"], state_write_expected=False)
        self.assertEqual(result["stateObjectVersionDelta"], 0)

    def test_apply_history_delta_is_accepted(self):
        result = CORE.gate_history_delta(self.fixture["planHistoryAfter"], self.fixture["applyHistoryAfter"], state_write_expected=True)
        self.assertEqual(result["stateObjectVersionDelta"], 1)

    def test_state_delete_marker_is_rejected(self):
        after = copy.deepcopy(self.fixture["applyHistoryAfter"])
        after["stateDeleteMarkers"] = 1
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_history_delta(self.fixture["planHistoryAfter"], after, state_write_expected=True)

    def test_empty_final_state_is_accepted(self):
        self.assertTrue(CORE.gate_final_state([])["finalManagedStateEmpty"])

    def test_nonempty_final_state_is_rejected(self):
        with self.assertRaises(CORE.TeardownGateError):
            CORE.gate_final_state(["module.vpc.aws_vpc.this"])


if __name__ == "__main__":
    unittest.main()

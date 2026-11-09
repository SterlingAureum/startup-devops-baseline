#!/usr/bin/env python3
"""Offline tests for final aws-dev cleanup."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("final_cleanup_under_test", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


class GateTests(unittest.TestCase):
    def document(self):
        return {"complete": True, "errored": False, "applyable": True, "resource_changes": [
            {"address": address, "mode": "managed", "change": {"actions": ["delete"], "importing": None}}
            for address in sorted(EXECUTOR.PENDING_ADDRESSES)
        ], "output_changes": {"vpc_id": {"actions": ["delete"]}}}

    def test_exact_two_resource_plan(self):
        self.assertEqual(EXECUTOR.final_plan_gate(self.document())["managedDeleteCount"], 2)

    def test_extra_resource_is_rejected(self):
        value = self.document(); value["resource_changes"].append({"address": "extra", "mode": "managed", "change": {"actions": ["delete"], "importing": None}})
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "exact two-resource"):
            EXECUTOR.final_plan_gate(value)

    def test_update_is_rejected(self):
        value = self.document(); value["resource_changes"][0]["change"]["actions"] = ["update"]
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "delete-only"):
            EXECUTOR.final_plan_gate(value)

    def test_real_drift_is_rejected(self):
        value = self.document(); value["resource_drift"] = [{"address": "drift"}]
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "resource drift"):
            EXECUTOR.final_plan_gate(value)


class StateTests(unittest.TestCase):
    def test_check_result_order_is_ignored(self):
        first = {"serial": 16, "resources": [], "check_results": [{"a": 1}, {"b": 2}]}
        second = {"serial": 16, "resources": [], "check_results": [{"b": 2}, {"a": 1}]}
        self.assertEqual(EXECUTOR.semantic_partial_state(first), EXECUTOR.semantic_partial_state(second))

    def test_resource_change_is_not_ignored(self):
        first = {"serial": 16, "resources": [{"name": "subnet"}]}
        second = {"serial": 16, "resources": [{"name": "vpc"}]}
        self.assertNotEqual(EXECUTOR.semantic_partial_state(first), EXECUTOR.semantic_partial_state(second))


class RequestTests(unittest.TestCase):
    def test_prepare_example_matches_runtime_contract(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-prepare-request.example.json"
        self.assertEqual(EXECUTOR.validate_prepare_request(json.loads(path.read_text()))["recoveryBoundary"], EXECUTOR.recovery_boundary())

    def test_final_example_matches_runtime_contract(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.3-aws-dev-final-cleanup-apply-request.example.json"
        self.assertEqual(EXECUTOR.validate_final_request(json.loads(path.read_text()))["executionBoundary"], EXECUTOR.final_execution_boundary())


class EniTests(unittest.TestCase):
    def test_exact_private_eni_shape(self):
        eni = {
            "NetworkInterfaceId": "eni-fixture", "SubnetId": "subnet-fixture", "VpcId": "vpc-fixture",
            "OwnerId": "123456789012", "Status": "available", "InterfaceType": "interface",
            "RequesterManaged": False, "Operator": {"Managed": False}, "SourceDestCheck": True,
            "Description": "fixture", "Groups": [{"GroupId": "sg-fixture"}],
            "PrivateIpAddresses": [{"PrivateIpAddress": f"10.0.0.{index}"} for index in range(1, 7)],
            "TagSet": [{"Key": str(index), "Value": "fixture"} for index in range(4)],
        }
        originals = (EXECUTOR.ENI_ID_SHA256, EXECUTOR.SUBNET_ID_SHA256, EXECUTOR.VPC_ID_SHA256, EXECUTOR.DESCRIPTION_SHA256, EXECUTOR.SECURITY_GROUP_INVENTORY_SHA256, EXECUTOR.PRIVATE_IP_INVENTORY_SHA256)
        try:
            EXECUTOR.ENI_ID_SHA256 = EXECUTOR.text_sha256("eni-fixture")
            EXECUTOR.SUBNET_ID_SHA256 = EXECUTOR.text_sha256("subnet-fixture")
            EXECUTOR.VPC_ID_SHA256 = EXECUTOR.text_sha256("vpc-fixture")
            EXECUTOR.DESCRIPTION_SHA256 = EXECUTOR.text_sha256("fixture")
            EXECUTOR.SECURITY_GROUP_INVENTORY_SHA256 = EXECUTOR.lines_sha256(["sg-fixture"])
            EXECUTOR.PRIVATE_IP_INVENTORY_SHA256 = EXECUTOR.lines_sha256([f"10.0.0.{index}" for index in range(1, 7)])
            EXECUTOR.validate_eni({"NetworkInterfaces": [eni]}, "123456789012")
        finally:
            (EXECUTOR.ENI_ID_SHA256, EXECUTOR.SUBNET_ID_SHA256, EXECUTOR.VPC_ID_SHA256, EXECUTOR.DESCRIPTION_SHA256, EXECUTOR.SECURITY_GROUP_INVENTORY_SHA256, EXECUTOR.PRIVATE_IP_INVENTORY_SHA256) = originals

    def test_attached_eni_is_rejected(self):
        value = {"NetworkInterfaces": [{"NetworkInterfaceId": "x"}]}
        with self.assertRaises(EXECUTOR.CleanupError):
            EXECUTOR.validate_eni(value, "123456789012")


if __name__ == "__main__":
    unittest.main()

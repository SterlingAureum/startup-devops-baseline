#!/usr/bin/env python3
"""Offline tests for final AWS-dev EKS-SG/VPC cleanup."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("eks_sg_vpc_cleanup_under_test", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


class GateTests(unittest.TestCase):
    def document(self):
        return {
            "complete": True,
            "errored": False,
            "applyable": True,
            "resource_changes": [{"address": EXECUTOR.VPC_ADDRESS, "mode": "managed", "change": {"actions": ["delete"], "importing": None}}],
            "output_changes": {"vpc_id": {"actions": ["delete"]}},
        }

    def test_exact_vpc_plan(self):
        self.assertEqual(EXECUTOR.vpc_plan_gate(self.document())["managedDeleteCount"], 1)

    def test_extra_resource_is_rejected(self):
        value = self.document()
        value["resource_changes"].append({"address": "extra", "mode": "managed", "change": {"actions": ["delete"], "importing": None}})
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "exact one-resource"):
            EXECUTOR.vpc_plan_gate(value)

    def test_duplicate_vpc_change_is_rejected(self):
        value = self.document()
        value["resource_changes"].append(value["resource_changes"][0].copy())
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "exact one-resource"):
            EXECUTOR.vpc_plan_gate(value)

    def test_update_is_rejected(self):
        value = self.document()
        value["resource_changes"][0]["change"]["actions"] = ["update"]
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "delete-only"):
            EXECUTOR.vpc_plan_gate(value)

    def test_real_drift_is_rejected(self):
        value = self.document()
        value["resource_drift"] = [{"address": "drift"}]
        with self.assertRaisesRegex(EXECUTOR.CleanupError, "resource drift"):
            EXECUTOR.vpc_plan_gate(value)


class RequestTests(unittest.TestCase):
    def test_prepare_example_matches_runtime_contract(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-prepare-request.example.json"
        self.assertEqual(EXECUTOR.validate_prepare_request(json.loads(path.read_text()))["recoveryBoundary"], EXECUTOR.recovery_boundary())

    def test_final_example_matches_runtime_contract(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup-apply-request.example.json"
        self.assertEqual(EXECUTOR.validate_final_request(json.loads(path.read_text()))["executionBoundary"], EXECUTOR.final_execution_boundary())


class SecurityGroupTests(unittest.TestCase):
    def fixture(self):
        return {
            "SecurityGroups": [{
                "GroupId": "sg-fixture",
                "GroupName": "eks-cluster-sg-fixture",
                "Description": "EKS created security group",
                "VpcId": "vpc-fixture",
                "OwnerId": "123456789012",
                "Tags": [{"Key": "aws:eks:cluster-name", "Value": "fixture"}, {"Key": "a", "Value": "b"}, {"Key": "c", "Value": "d"}],
                "IpPermissions": [],
                "IpPermissionsEgress": [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [], "PrefixListIds": [], "UserIdGroupPairs": []}],
            }]
        }

    def test_exact_orphan_eks_security_group_shape(self):
        originals = (EXECUTOR.SG_ID_SHA256, EXECUTOR.SG_NAME_SHA256, EXECUTOR.SG_DESCRIPTION_SHA256, EXECUTOR.VPC_ID_SHA256, EXECUTOR.FORMER_ENI_SG_INVENTORY_SHA256)
        try:
            EXECUTOR.SG_ID_SHA256 = EXECUTOR.text_sha256("sg-fixture")
            EXECUTOR.SG_NAME_SHA256 = EXECUTOR.text_sha256("eks-cluster-sg-fixture")
            EXECUTOR.SG_DESCRIPTION_SHA256 = EXECUTOR.text_sha256("EKS created security group")
            EXECUTOR.VPC_ID_SHA256 = EXECUTOR.text_sha256("vpc-fixture")
            EXECUTOR.FORMER_ENI_SG_INVENTORY_SHA256 = EXECUTOR.lines_sha256(["sg-fixture"])
            EXECUTOR.validate_security_group(self.fixture(), "123456789012")
        finally:
            (EXECUTOR.SG_ID_SHA256, EXECUTOR.SG_NAME_SHA256, EXECUTOR.SG_DESCRIPTION_SHA256, EXECUTOR.VPC_ID_SHA256, EXECUTOR.FORMER_ENI_SG_INVENTORY_SHA256) = originals

    def test_group_reference_is_rejected(self):
        value = self.fixture()
        value["SecurityGroups"][0]["IpPermissionsEgress"][0]["UserIdGroupPairs"] = [{"GroupId": "sg-other"}]
        with self.assertRaises(EXECUTOR.CleanupError):
            EXECUTOR.validate_security_group(value, "123456789012")

    def test_malformed_rule_is_rejected_fail_closed(self):
        value = self.fixture()
        value["SecurityGroups"][0]["IpPermissionsEgress"] = ["not-a-rule"]
        originals = (EXECUTOR.SG_ID_SHA256, EXECUTOR.SG_NAME_SHA256, EXECUTOR.SG_DESCRIPTION_SHA256, EXECUTOR.VPC_ID_SHA256, EXECUTOR.FORMER_ENI_SG_INVENTORY_SHA256)
        try:
            EXECUTOR.SG_ID_SHA256 = EXECUTOR.text_sha256("sg-fixture")
            EXECUTOR.SG_NAME_SHA256 = EXECUTOR.text_sha256("eks-cluster-sg-fixture")
            EXECUTOR.SG_DESCRIPTION_SHA256 = EXECUTOR.text_sha256("EKS created security group")
            EXECUTOR.VPC_ID_SHA256 = EXECUTOR.text_sha256("vpc-fixture")
            EXECUTOR.FORMER_ENI_SG_INVENTORY_SHA256 = EXECUTOR.lines_sha256(["sg-fixture"])
            with self.assertRaisesRegex(EXECUTOR.CleanupError, "rule shape"):
                EXECUTOR.validate_security_group(value, "123456789012")
        finally:
            (EXECUTOR.SG_ID_SHA256, EXECUTOR.SG_NAME_SHA256, EXECUTOR.SG_DESCRIPTION_SHA256, EXECUTOR.VPC_ID_SHA256, EXECUTOR.FORMER_ENI_SG_INVENTORY_SHA256) = originals


if __name__ == "__main__":
    unittest.main()

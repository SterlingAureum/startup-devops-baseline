#!/usr/bin/env python3
"""Offline tests for EKS-SG delete-response recovery."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.5.1-aws-dev-eks-sg-delete-response-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("delete_response_recovery_under_test", PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


class RequestTests(unittest.TestCase):
    def test_recovery_example_matches_runtime_contract(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5.1-aws-dev-eks-sg-delete-response-recovery-request.example.json"
        request = EXECUTOR.validate_recovery_request(json.loads(path.read_text()))
        self.assertEqual(request["incidentBoundary"], EXECUTOR.incident_boundary())
        self.assertEqual(request["executionBoundary"], EXECUTOR.recovery_execution_boundary())

    def test_final_example_matches_runtime_contract(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-apply-request.example.json"
        request = EXECUTOR.validate_final_request(json.loads(path.read_text()))
        self.assertEqual(request["executionBoundary"], EXECUTOR.final_execution_boundary())

    def test_recovery_cannot_authorize_security_group_delete(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5.1-aws-dev-eks-sg-delete-response-recovery-request.example.json"
        request = json.loads(path.read_text())
        request["executionBoundary"]["securityGroupDelete"] = True
        with self.assertRaises(EXECUTOR.RecoveryError):
            EXECUTOR.validate_recovery_request(request)

    def test_final_cannot_authorize_plan(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-apply-request.example.json"
        request = json.loads(path.read_text())
        request["executionBoundary"]["terraformPlan"] = True
        with self.assertRaises(EXECUTOR.RecoveryError):
            EXECUTOR.validate_final_request(request)

    def test_final_window_cannot_exceed_review(self):
        path = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-apply-request.example.json"
        request = json.loads(path.read_text())
        request["approval"]["expiresAtUtc"] = "2026-10-08T14:00:01Z"
        with self.assertRaises(EXECUTOR.RecoveryError):
            EXECUTOR.validate_final_request(request)


class IncidentBoundaryTests(unittest.TestCase):
    def test_delete_response_is_exactly_bound(self):
        boundary = EXECUTOR.incident_boundary()
        self.assertTrue(boundary["deleteReturn"])
        self.assertTrue(boundary["deleteResponseGroupIdBound"])
        self.assertFalse(boundary["postDeleteAbsenceEvidenceCreated"])
        self.assertFalse(boundary["vpcSavedPlanCreated"])

    def test_json_success_response_is_accepted(self):
        original = EXECUTOR.BASE.SG_ID_SHA256
        try:
            EXECUTOR.BASE.SG_ID_SHA256 = EXECUTOR.BASE.text_sha256("sg-fixture")
            value = json.dumps({"GroupId": "sg-fixture", "Return": True}).encode()
            self.assertEqual(EXECUTOR.BASE.validate_delete_security_group_response(value)["responseShape"], "json")
        finally:
            EXECUTOR.BASE.SG_ID_SHA256 = original

    def test_false_delete_response_is_rejected(self):
        original = EXECUTOR.BASE.SG_ID_SHA256
        try:
            EXECUTOR.BASE.SG_ID_SHA256 = EXECUTOR.BASE.text_sha256("sg-fixture")
            value = json.dumps({"GroupId": "sg-fixture", "Return": False}).encode()
            with self.assertRaises(EXECUTOR.RecoveryError):
                EXECUTOR.BASE.validate_delete_security_group_response(value)
        finally:
            EXECUTOR.BASE.SG_ID_SHA256 = original


class PlanGateTests(unittest.TestCase):
    def document(self):
        return {
            "complete": True,
            "errored": False,
            "applyable": True,
            "resource_changes": [{"address": EXECUTOR.BASE.VPC_ADDRESS, "mode": "managed", "change": {"actions": ["delete"], "importing": None}}],
            "output_changes": {"vpc_id": {"actions": ["delete"]}},
        }

    def test_exact_vpc_plan_is_accepted(self):
        self.assertEqual(EXECUTOR.BASE.vpc_plan_gate(self.document())["managedDeleteCount"], 1)

    def test_extra_delete_is_rejected(self):
        value = self.document()
        value["resource_changes"].append({"address": "extra", "mode": "managed", "change": {"actions": ["delete"], "importing": None}})
        with self.assertRaises(EXECUTOR.RecoveryError):
            EXECUTOR.BASE.vpc_plan_gate(value)


if __name__ == "__main__":
    unittest.main()

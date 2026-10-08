#!/usr/bin/env python3
"""Offline tests for AWS-dev VPC-only read-only recovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("vpc_only_recovery_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "123456789012",
        "expectedTerraformVersion": "1.14.3",
        "privateFinalRequestPath": "/private/final-request.json",
        "privateFinalApplyOutputDirectory": "/private/final-output",
        "privateRecoveryOutputDirectory": "/private/recovery-output",
        "incidentBoundary": EXECUTOR.incident_boundary(),
        "approval": {"notBeforeUtc": "2026-10-08T09:00:00Z", "expiresAtUtc": "2026-10-08T12:00:00Z"},
        "executionBoundary": EXECUTOR.execution_boundary(),
    }


class RequestTests(unittest.TestCase):
    def test_exact_request_is_accepted(self):
        self.assertEqual(EXECUTOR.validate_request(request())["operation"], EXECUTOR.CONFIRMATION)

    def test_apply_authority_is_rejected(self):
        value = request()
        value["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Execution boundary"):
            EXECUTOR.validate_request(value)

    def test_direct_aws_mutation_is_rejected(self):
        value = request()
        value["executionBoundary"]["directAwsMutation"] = True
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Execution boundary"):
            EXECUTOR.validate_request(value)

    def test_incident_cannot_be_relaxed(self):
        value = request()
        value["incidentBoundary"]["completedManagedDeleteCount"] = 2
        with self.assertRaisesRegex(EXECUTOR.RecoveryError, "Incident boundary"):
            EXECUTOR.validate_request(value)

    def test_verification_is_command_free(self):
        context = {"request": request(), "request_path": Path("/private/request"), "remaining": 3600}
        original = EXECUTOR.file_sha256
        EXECUTOR.file_sha256 = lambda _path: "2" * 64
        try:
            result = EXECUTOR.redacted_verification(context)
        finally:
            EXECUTOR.file_sha256 = original
        self.assertEqual(result["operational_commands_executed"], [])
        self.assertFalse(result["terraform_apply_authorized"])
        self.assertFalse(result["terraform_destroy_authorized"])


class EvidenceTests(unittest.TestCase):
    def test_failed_apply_address_inventory_is_exact(self):
        stdout = b"\n".join([
            b'module.vpc.aws_subnet.private["us-east-1b"]: Destroying... [id=redacted]',
            b'module.vpc.aws_subnet.private["us-east-1b"]: Destruction complete after 1s',
            b'module.vpc.aws_vpc.this: Destroying... [id=redacted]',
        ])
        started, completed = EXECUTOR.parse_apply_addresses(stdout)
        self.assertEqual(started, EXECUTOR.PLANNED_ADDRESSES)
        self.assertEqual(completed, {EXECUTOR.SUBNET_ADDRESS})

    def test_dependency_classification_reports_blockers(self):
        counts = {"networkInterfaceCount": 1, "nonDefaultSecurityGroupCount": 2, "mainRouteTableCount": 1}
        self.assertEqual(EXECUTOR.classify_dependencies(counts), ["network-interface", "non-default-security-group"])

    def test_dependency_classification_allows_unclassified_result(self):
        self.assertEqual(EXECUTOR.classify_dependencies({"mainRouteTableCount": 1, "defaultSecurityGroupCount": 1}), [])

    def test_active_filters_terminal_resources(self):
        values = [{"State": "available"}, {"State": "deleting"}, {"State": "deleted"}, {"State": "failed"}]
        self.assertEqual(len(EXECUTOR.active(values)), 2)


if __name__ == "__main__":
    unittest.main()

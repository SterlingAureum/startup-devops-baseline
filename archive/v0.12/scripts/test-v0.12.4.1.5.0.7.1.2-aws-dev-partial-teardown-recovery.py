#!/usr/bin/env python3
"""Offline tests for aws-dev partial-teardown read-only recovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("partial_teardown_recovery_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery-request-v1",
        "operation": EXECUTOR.CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "123456789012",
        "expectedTerraformVersion": "1.14.3",
        "privateDestroyRequestPath": "/private/destroy-request.json",
        "privateDestroyOutputDirectory": "/private/destroy-output",
        "privateRecoveryOutputDirectory": "/private/recovery-output",
        "incidentBoundary": EXECUTOR.incident_boundary(),
        "approval": {"notBeforeUtc": "2026-10-01T01:00:00Z", "expiresAtUtc": "2026-10-01T04:00:00Z"},
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

    def test_incident_cannot_be_relaxed(self):
        value = request()
        value["incidentBoundary"]["destroyCompletedAddressCount"] = 89
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
    def test_apply_address_inventory_is_parsed(self):
        stdout = b"\n".join([
            b'module.vpc.aws_subnet.private[\"us-east-1b\"]: Destroying... [id=redacted]',
            b'module.vpc.aws_subnet.private[\"us-east-1a\"]: Destroying... [id=redacted]',
            b'module.vpc.aws_subnet.private[\"us-east-1a\"]: Destruction complete after 1s',
        ])
        started, completed = EXECUTOR.parse_apply_addresses(stdout)
        self.assertEqual(len(started), 2)
        self.assertEqual(completed, {'module.vpc.aws_subnet.private["us-east-1a"]'})

    def test_raw_attribute_is_selected_by_index(self):
        state = {"resources": [{
            "module": "module.vpc", "mode": "managed", "type": "aws_subnet", "name": "private",
            "instances": [
                {"index_key": "us-east-1a", "attributes": {"id": "subnet-a"}},
                {"index_key": "us-east-1b", "attributes": {"id": "subnet-b"}},
            ],
        }]}
        self.assertEqual(EXECUTOR.raw_attribute(state, "module.vpc", "aws_subnet", "private", "us-east-1b", "id"), "subnet-b")


if __name__ == "__main__":
    unittest.main()

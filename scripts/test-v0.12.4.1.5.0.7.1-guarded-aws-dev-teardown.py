#!/usr/bin/env python3
"""Offline tests for the guarded aws-dev teardown control plane."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXECUTOR_PATH = ROOT / "scripts/execute-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"


def load_executor():
    spec = importlib.util.spec_from_file_location("guarded_aws_dev_teardown_under_test", EXECUTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_executor()


def plan_request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1-aws-dev-teardown-plan-request-v1",
        "operation": EXECUTOR.PLAN_CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "123456789012",
        "expectedTerraformVersion": "1.14.3",
        "privateSemanticRecoveryRequestPath": "/private/recovery-request.json",
        "privateSemanticRecoveryOutputDirectory": "/private/recovery-output",
        "privateTeardownPlanOutputDirectory": "/private/teardown-plan-output",
        "recoveryBoundary": EXECUTOR.recovery_boundary(),
        "approval": {
            "notBeforeUtc": "2026-10-01T01:00:00Z",
            "expiresAtUtc": "2026-10-01T02:00:00Z",
            "planReviewExpiresAtUtc": "2026-10-01T05:00:00Z",
        },
        "executionBoundary": EXECUTOR.plan_execution_boundary(),
    }


def destroy_request() -> dict:
    return {
        "schemaVersion": "v0.12.4.1.5.0.7.1-aws-dev-teardown-destroy-request-v1",
        "operation": EXECUTOR.DESTROY_CONFIRMATION,
        "repository": "SterlingAureum/startup-devops-baseline",
        "trustedRef": "refs/heads/main",
        "expectedMainCommit": "1" * 40,
        "expectedAwsAccountId": "123456789012",
        "expectedTerraformVersion": "1.14.3",
        "privateTeardownPlanRequestPath": "/private/plan-request.json",
        "privateTeardownPlanOutputDirectory": "/private/plan-output",
        "privateDestroyOutputDirectory": "/private/destroy-output",
        "planBoundary": {
            "privatePlanRequestSha256": "2" * 64,
            "binaryPlanSha256": "3" * 64,
            "planJsonSha256": "4" * 64,
            "planTextSha256": "5" * 64,
            "addressInventorySha256": "6" * 64,
            "planRecordSha256": "7" * 64,
            "managedDeleteCount": 90,
            "dataChangeCount": 3,
            "resourceDriftCount": 0,
            "importCount": 0,
            "humanReviewed": True,
            "planReviewExpiresAtUtc": "2026-10-01T05:00:00Z",
        },
        "approval": {"notBeforeUtc": "2026-10-01T02:00:00Z", "expiresAtUtc": "2026-10-01T05:00:00Z"},
        "executionBoundary": EXECUTOR.destroy_execution_boundary(),
    }


class RequestTests(unittest.TestCase):
    def test_plan_request_exact(self):
        self.assertEqual(EXECUTOR.validate_plan_request(plan_request())["operation"], EXECUTOR.PLAN_CONFIRMATION)

    def test_plan_request_rejects_apply(self):
        value = plan_request()
        value["executionBoundary"]["terraformApply"] = True
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "execution boundary"):
            EXECUTOR.validate_plan_request(value)

    def test_plan_window_is_bounded(self):
        value = plan_request()
        value["approval"]["expiresAtUtc"] = "2026-10-01T02:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "at most one hour"):
            EXECUTOR.validate_plan_request(value)

    def test_destroy_request_exact(self):
        self.assertEqual(EXECUTOR.validate_destroy_request(destroy_request())["operation"], EXECUTOR.DESTROY_CONFIRMATION)

    def test_destroy_requires_human_review(self):
        value = destroy_request()
        value["planBoundary"]["humanReviewed"] = False
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "review boundary"):
            EXECUTOR.validate_destroy_request(value)

    def test_destroy_cannot_outlive_plan(self):
        value = destroy_request()
        value["approval"]["notBeforeUtc"] = "2026-10-01T02:00:01Z"
        value["approval"]["expiresAtUtc"] = "2026-10-01T05:00:01Z"
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "plan review lifetime"):
            EXECUTOR.validate_destroy_request(value)


class PlanGateTests(unittest.TestCase):
    def fixture(self) -> tuple[dict, set[str]]:
        addresses = {f"module.fixture.aws_resource.item[{index}]" for index in range(90)}
        document = {
            "complete": True,
            "errored": False,
            "applyable": True,
            "resource_drift": [],
            "resource_changes": [
                {"address": address, "mode": "managed", "change": {"actions": ["delete"], "importing": None}}
                for address in sorted(addresses)
            ] + [{"address": "data.aws_region.current", "mode": "data", "change": {"actions": ["read"], "importing": None}}],
            "output_changes": {"cluster_name": {"actions": ["delete"]}},
        }
        return document, addresses

    def test_exact_delete_only_plan(self):
        document, addresses = self.fixture()
        inventory = EXECUTOR.destroy_plan_gate(document, addresses)
        self.assertEqual(inventory["managedDeleteCount"], 90)
        self.assertEqual(inventory["dataChangeCount"], 1)

    def test_create_action_is_rejected(self):
        document, addresses = self.fixture()
        document["resource_changes"][0]["change"]["actions"] = ["create"]
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "delete-only"):
            EXECUTOR.destroy_plan_gate(document, addresses)

    def test_missing_managed_delete_is_rejected(self):
        document, addresses = self.fixture()
        document["resource_changes"].pop(0)
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "inventory differs"):
            EXECUTOR.destroy_plan_gate(document, addresses)

    def test_drift_is_rejected(self):
        document, addresses = self.fixture()
        document["resource_drift"] = [{"address": "fixture"}]
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "resource drift"):
            EXECUTOR.destroy_plan_gate(document, addresses)


class HelperTests(unittest.TestCase):
    def test_verification_result_is_command_free(self):
        context = {"request": plan_request(), "request_path": Path("/private/request"), "remaining": 1800}
        original = EXECUTOR.file_sha256
        EXECUTOR.file_sha256 = lambda _path: "8" * 64
        try:
            value = EXECUTOR.redacted_plan_verification(context)
        finally:
            EXECUTOR.file_sha256 = original
        self.assertEqual(value["operational_commands_executed"], [])
        self.assertFalse(value["terraform_plan_authorized"])
        self.assertFalse(value["terraform_apply_authorized"])

    def test_absent_vpc_success_shape(self):
        calls = []

        def runner(arguments, _environment, _timeout, _cwd):
            calls.append(arguments)
            return subprocess.CompletedProcess(arguments, 0, b'{"Vpcs": []}', b"")

        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            EXECUTOR.run_expected_absent(output, "vpc", ["aws", "ec2", "describe-vpcs"], {b"InvalidVpcID.NotFound"}, {}, output, runner)
        self.assertEqual(len(calls), 1)

    def test_active_approval_requires_fifteen_minutes(self):
        value = destroy_request()
        now = datetime(2026, 10, 1, 4, 50, 1, tzinfo=timezone.utc)
        with self.assertRaisesRegex(EXECUTOR.TeardownError, "less than 15 minutes"):
            EXECUTOR.require_active_approval(value, now, "Destroy")


if __name__ == "__main__":
    unittest.main()

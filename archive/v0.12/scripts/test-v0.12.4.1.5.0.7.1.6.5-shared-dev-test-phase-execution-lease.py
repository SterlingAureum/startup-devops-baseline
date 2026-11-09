#!/usr/bin/env python3
"""Offline tests for single-use shared teardown phase execution leases."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_private_preflight as PRIVATE
import aws_two_wave_teardown_receipt_approval as APPROVAL
from aws_two_wave_teardown_core import TeardownGateError


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.5-shared-dev-test-phase-execution-lease"
FIXTURE_PATH = ROOT / f"delivery/examples/{PREFIX}-fixtures.json"
REQUEST = LEASE.REQUEST


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load(
    ROOT / "scripts/exercise-v0.12.4.1.5.0.7.1.6.5-shared-dev-test-phase-execution-lease.py",
    "phase_execution_lease_cli_under_test",
)


class PhaseExecutionLeaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text())
        approval_fixture_path = ROOT / self.fixture["sourceApprovalFixture"]
        approval_fixture = json.loads(approval_fixture_path.read_text())
        preflight_fixture_path = ROOT / approval_fixture["sourcePreflightFixture"]
        preflight_fixture = json.loads(preflight_fixture_path.read_text())
        source = preflight_fixture[approval_fixture["sourceCase"]]
        preflight = PRIVATE.verify_private_bundle(
            REQUEST.canonical_bytes(source["request"]),
            REQUEST.canonical_bytes(source["evidence"]),
            expected_request_sha256=REQUEST.sha256(source["request"]),
            expected_evidence_sha256=REQUEST.sha256(source["evidence"]),
            now_utc=preflight_fixture["verificationClockUtc"],
        )
        self.receipt = preflight["receipt"]
        self.receipt_sha = preflight["receiptSha256"]
        self.approval_temp, approval_root = self.private_store(("receipts", "approvals"))
        self.addCleanup(self.approval_temp.cleanup)
        self.approval_store = APPROVAL.PrivateReceiptApprovalStore(approval_root)
        self.approval_store.persist_receipt(
            preflight,
            expected_result_sha256=REQUEST.sha256(preflight),
            now_utc=approval_fixture["persistenceClockUtc"],
        )
        approval_text = APPROVAL.approval_text(self.receipt)
        timing = approval_fixture["approvalTiming"]
        approval_request = {
            "schemaVersion": APPROVAL.APPROVAL_REQUEST_SCHEMA,
            "receiptSha256": self.receipt_sha,
            "environment": self.receipt["environment"],
            "stateKey": self.receipt["stateKey"],
            "phase": self.receipt["phase"],
            "attemptNumber": self.receipt["attemptNumber"],
            "controlPlaneCommit": self.receipt["controlPlaneCommit"],
            "requestedAuthority": self.receipt["requestedAuthority"],
            "createdAtUtc": timing["createdAtUtc"],
            "notBeforeUtc": timing["notBeforeUtc"],
            "expiresAtUtc": timing["expiresAtUtc"],
            "approvalText": approval_text,
            "approvalTextSha256": APPROVAL.text_sha256(approval_text),
            "humanApproved": True,
            "oneAttemptOnly": True,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
        }
        approval_result = self.approval_store.record_approval(
            approval_request,
            expected_approval_request_sha256=REQUEST.sha256(approval_request),
            expected_receipt_sha256=self.receipt_sha,
            now_utc=approval_fixture["approvalClockUtc"],
        )
        self.approval_record = approval_result["approvalRecord"]
        self.approval_record_sha = approval_result["approvalRecordSha256"]
        self.execution_now = self.fixture["executionClockUtc"]
        self.completed_at = self.fixture["completionClockUtc"]

    @staticmethod
    def private_store(names):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        root.chmod(0o700)
        for name in names:
            child = root / name
            child.mkdir()
            child.chmod(0o700)
        return temporary, root

    def execution_store(self):
        temporary, root = self.private_store(("claims", "outcomes"))
        return temporary, root, LEASE.PrivateExecutionLeaseStore(root)

    def execution_request(self):
        timing = self.fixture["executionTiming"]
        return {
            "schemaVersion": LEASE.EXECUTION_REQUEST_SCHEMA,
            "receiptSha256": self.receipt_sha,
            "approvalRecordSha256": self.approval_record_sha,
            "environment": self.approval_record["environment"],
            "stateKey": self.approval_record["stateKey"],
            "phase": self.approval_record["phase"],
            "attemptNumber": self.approval_record["attemptNumber"],
            "controlPlaneCommit": self.approval_record["controlPlaneCommit"],
            "requestedAuthority": self.approval_record["requestedAuthority"],
            "executionSpecSha256": self.fixture["executionSpecSha256"],
            "createdAtUtc": timing["createdAtUtc"],
            "notBeforeUtc": timing["notBeforeUtc"],
            "expiresAtUtc": timing["expiresAtUtc"],
            "humanReviewed": True,
            "oneAttemptOnly": True,
            "simulationOnly": True,
            "liveExecutionAuthorized": False,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
        }

    def run_once(self, store, *, request=None, driver=None, completed=None):
        value = self.execution_request() if request is None else request
        return LEASE.run_once_fixed_fake(
            approval_store=self.approval_store,
            execution_store=store,
            execution_request=value,
            expected_execution_request_sha256=REQUEST.sha256(value),
            expected_receipt_sha256=self.receipt_sha,
            expected_approval_record_sha256=self.approval_record_sha,
            now_utc=self.execution_now,
            completed_at_utc=self.completed_at if completed is None else completed,
            driver=LEASE.FixedFakePhaseDriver() if driver is None else driver,
        )

    def single_input(self, value):
        temporary = tempfile.TemporaryDirectory()
        directory = Path(temporary.name)
        directory.chmod(0o700)
        path = directory / "execution-request.json"
        path.write_bytes(REQUEST.canonical_bytes(value))
        path.chmod(0o600)
        return temporary, path

    def test_success_writes_content_addressed_claim_and_outcome(self):
        temporary, root, store = self.execution_store()
        try:
            result = self.run_once(store)
            claim = root / "claims" / f"{self.approval_record_sha}.claim.json"
            outcome = root / "outcomes" / f"{self.approval_record_sha}.outcome.json"
            self.assertEqual(claim.stat().st_mode & 0o777, 0o600)
            self.assertEqual(outcome.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["claimSha256"], REQUEST.sha256(json.loads(claim.read_bytes())))
            self.assertEqual(result["outcomeSha256"], REQUEST.sha256(json.loads(outcome.read_bytes())))
            self.assertTrue(result["approvalConsumedByLease"])
            self.assertFalse(result["liveCommandExecuted"])
            self.assertFalse(result["executionPerformed"])
        finally:
            temporary.cleanup()

    def test_claim_is_durable_before_driver_call(self):
        temporary, root, store = self.execution_store()
        try:
            driver = LEASE.FixedFakePhaseDriver()
            original = driver.call

            def observed(request):
                claim = root / "claims" / f"{self.approval_record_sha}.claim.json"
                self.assertTrue(claim.is_file())
                self.assertEqual(json.loads(claim.read_bytes())["status"], "approval-consumed-before-fixed-fake-call")
                return original(request)

            driver.call = observed
            self.run_once(store, driver=driver)
            self.assertEqual(len(driver.calls), 1)
        finally:
            temporary.cleanup()

    def test_success_cannot_be_replayed(self):
        temporary, _root, store = self.execution_store()
        try:
            self.run_once(store)
            driver = LEASE.FixedFakePhaseDriver()
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                self.run_once(store, driver=driver)
            self.assertEqual(driver.calls, [])
        finally:
            temporary.cleanup()

    def test_failure_records_outcome_and_cannot_be_replayed(self):
        temporary, root, store = self.execution_store()
        try:
            with self.assertRaises(LEASE.ExecutionLeaseStopped) as stopped:
                self.run_once(store, driver=LEASE.FixedFakePhaseDriver(fail=True))
            self.assertTrue(stopped.exception.report["claimCreated"])
            self.assertTrue(stopped.exception.report["outcomeRecorded"])
            outcome = json.loads((root / "outcomes" / f"{self.approval_record_sha}.outcome.json").read_bytes())
            self.assertEqual(outcome["status"], "fixed-fake-phase-failed")
            retry = LEASE.FixedFakePhaseDriver()
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                self.run_once(store, driver=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_claim_without_outcome_blocks_retry(self):
        temporary, root, store = self.execution_store()
        try:
            (root / "claims" / f"{self.approval_record_sha}.claim.json").write_text("partial")
            (root / "claims" / f"{self.approval_record_sha}.claim.json").chmod(0o600)
            driver = LEASE.FixedFakePhaseDriver()
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                self.run_once(store, driver=driver)
            self.assertEqual(driver.calls, [])
        finally:
            temporary.cleanup()

    def test_claim_fsync_uncertainty_preserves_file_and_blocks_retry(self):
        temporary, root, store = self.execution_store()
        try:
            real_fsync = os.fsync
            calls = 0

            def fail_first(descriptor):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError("injected fsync failure")
                return real_fsync(descriptor)

            with patch.object(LEASE.os, "fsync", side_effect=fail_first):
                with self.assertRaises(LEASE.ExecutionLeaseStopped):
                    self.run_once(store)
            self.assertTrue((root / "claims" / f"{self.approval_record_sha}.claim.json").exists())
            driver = LEASE.FixedFakePhaseDriver()
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                self.run_once(store, driver=driver)
            self.assertEqual(driver.calls, [])
        finally:
            temporary.cleanup()

    def test_outcome_write_uncertainty_reports_consumed_attempt(self):
        temporary, _root, store = self.execution_store()
        try:
            store.outcome = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                LEASE.ExecutionLeaseStopped("injected-outcome-write")
            )
            with self.assertRaises(LEASE.ExecutionLeaseStopped) as stopped:
                self.run_once(store)
            self.assertTrue(stopped.exception.report["claimCreated"])
            self.assertEqual(stopped.exception.report["driverCallCount"], 1)
            self.assertFalse(stopped.exception.report["outcomeRecorded"])
        finally:
            temporary.cleanup()

    def test_approval_record_digest_is_required(self):
        with self.assertRaises(TeardownGateError):
            LEASE.validate_approval_record(
                self.approval_record,
                expected_record_sha256="0" * 64,
                expected_receipt_sha256=self.receipt_sha,
                now_utc=self.execution_now,
            )

    def test_approval_record_must_be_active(self):
        with self.assertRaises(TeardownGateError):
            LEASE.validate_approval_record(
                self.approval_record,
                expected_record_sha256=self.approval_record_sha,
                expected_receipt_sha256=self.receipt_sha,
                now_utc=self.approval_record["expiresAtUtc"],
            )

    def test_execution_request_digest_is_required(self):
        with self.assertRaises(TeardownGateError):
            LEASE.validate_execution_request(
                self.execution_request(),
                self.approval_record,
                expected_request_sha256="0" * 64,
                now_utc=self.execution_now,
            )

    def test_all_identity_bindings_are_exact(self):
        for key in ("receiptSha256", "approvalRecordSha256", "environment", "stateKey", "phase", "attemptNumber", "controlPlaneCommit", "requestedAuthority"):
            with self.subTest(key=key):
                value = self.execution_request()
                value[key] = "changed" if key != "attemptNumber" else 2
                with self.assertRaises(TeardownGateError):
                    LEASE.validate_execution_request(value, self.approval_record, expected_request_sha256=REQUEST.sha256(value), now_utc=self.execution_now)

    def test_execution_spec_must_be_sha256(self):
        value = self.execution_request()
        value["executionSpecSha256"] = "not-a-digest"
        with self.assertRaises(TeardownGateError):
            LEASE.validate_execution_request(value, self.approval_record, expected_request_sha256=REQUEST.sha256(value), now_utc=self.execution_now)

    def test_execution_request_requires_review_and_one_attempt(self):
        for key in ("humanReviewed", "oneAttemptOnly"):
            value = self.execution_request()
            value[key] = False
            with self.assertRaises(TeardownGateError):
                LEASE.validate_execution_request(value, self.approval_record, expected_request_sha256=REQUEST.sha256(value), now_utc=self.execution_now)

    def test_execution_request_cannot_authorize_live_or_forbidden_powers(self):
        for key in ("liveExecutionAuthorized", "automaticRetryAuthorized", "automaticRollbackAuthorized", "statePushAuthorized", "backendRetirementAuthorized"):
            with self.subTest(key=key):
                value = self.execution_request()
                value[key] = True
                with self.assertRaises(TeardownGateError):
                    LEASE.validate_execution_request(value, self.approval_record, expected_request_sha256=REQUEST.sha256(value), now_utc=self.execution_now)

    def test_execution_request_must_be_simulation_only(self):
        value = self.execution_request()
        value["simulationOnly"] = False
        with self.assertRaises(TeardownGateError):
            LEASE.validate_execution_request(value, self.approval_record, expected_request_sha256=REQUEST.sha256(value), now_utc=self.execution_now)

    def test_execution_request_rejects_future_expired_and_overlong_windows(self):
        mutations = (
            ("notBeforeUtc", "2026-10-09T00:14:00Z"),
            ("expiresAtUtc", self.execution_now),
            ("expiresAtUtc", "2026-10-09T00:28:00Z"),
        )
        for key, changed in mutations:
            with self.subTest(key=key, changed=changed):
                value = self.execution_request()
                value[key] = changed
                with self.assertRaises(TeardownGateError):
                    LEASE.validate_execution_request(value, self.approval_record, expected_request_sha256=REQUEST.sha256(value), now_utc=self.execution_now)

    def test_completion_must_remain_inside_execution_window(self):
        temporary, _root, store = self.execution_store()
        try:
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                self.run_once(store, completed=self.execution_request()["expiresAtUtc"])
        finally:
            temporary.cleanup()

    def test_exact_fixed_fake_type_is_required_before_claim(self):
        class OtherDriver(LEASE.FixedFakePhaseDriver):
            pass

        temporary, root, store = self.execution_store()
        try:
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                self.run_once(store, driver=OtherDriver())
            self.assertEqual(list((root / "claims").iterdir()), [])
        finally:
            temporary.cleanup()

    def test_execution_store_requires_exact_directories(self):
        temporary, root = self.private_store(("claims", "outcomes"))
        try:
            extra = root / "retry"
            extra.mkdir()
            extra.chmod(0o700)
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                LEASE.PrivateExecutionLeaseStore(root)
        finally:
            temporary.cleanup()

    def test_execution_store_rejects_mode_drift(self):
        temporary, root = self.private_store(("claims", "outcomes"))
        try:
            root.chmod(0o755)
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                LEASE.PrivateExecutionLeaseStore(root)
        finally:
            root.chmod(0o700)
            temporary.cleanup()

    def test_execution_store_rejects_unexpected_record_name(self):
        temporary, root = self.private_store(("claims", "outcomes"))
        try:
            path = root / "claims" / "retry.json"
            path.write_text("{}")
            path.chmod(0o600)
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                LEASE.PrivateExecutionLeaseStore(root)
        finally:
            temporary.cleanup()

    def test_result_and_stop_reports_are_redacted(self):
        temporary, _root, store = self.execution_store()
        try:
            result = self.run_once(store)
            raw = json.dumps(result)
            for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-"):
                self.assertNotIn(marker, raw)
            stop = LEASE.ExecutionLeaseStopped("fixture", claim_created=True).report
            self.assertFalse(stop["privatePathEmitted"])
            self.assertFalse(stop["privateResourceIdentityEmitted"])
        finally:
            temporary.cleanup()

    def test_cli_exercises_fixed_fake_once(self):
        execution_temp, execution_root, _store = self.execution_store()
        input_temp, input_path = self.single_input(self.execution_request())
        try:
            result = CLI.run(
                [
                    "--approval-store-directory", str(self.approval_store.root),
                    "--execution-store-directory", str(execution_root),
                    "--execution-request-file", str(input_path),
                    "--expected-execution-request-sha256", REQUEST.sha256(self.execution_request()),
                    "--expected-receipt-sha256", self.receipt_sha,
                    "--expected-approval-record-sha256", self.approval_record_sha,
                    "--confirm", CLI.CONFIRMATION,
                ],
                now_utc=self.execution_now,
            )
            self.assertEqual(result["driverCallCount"], 1)
            self.assertTrue(result["approvalConsumedByLease"])
        finally:
            input_temp.cleanup()
            execution_temp.cleanup()

    def test_cli_confirmation_is_exact(self):
        execution_temp, execution_root, _store = self.execution_store()
        input_temp, input_path = self.single_input(self.execution_request())
        try:
            with self.assertRaises(LEASE.ExecutionLeaseStopped):
                CLI.run(
                    [
                        "--approval-store-directory", str(self.approval_store.root),
                        "--execution-store-directory", str(execution_root),
                        "--execution-request-file", str(input_path),
                        "--expected-execution-request-sha256", REQUEST.sha256(self.execution_request()),
                        "--expected-receipt-sha256", self.receipt_sha,
                        "--expected-approval-record-sha256", self.approval_record_sha,
                        "--confirm", "wrong",
                    ],
                    now_utc=self.execution_now,
                )
            self.assertEqual(list((execution_root / "claims").iterdir()), [])
        finally:
            input_temp.cleanup()
            execution_temp.cleanup()


if __name__ == "__main__":
    unittest.main()

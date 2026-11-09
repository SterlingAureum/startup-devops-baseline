#!/usr/bin/env python3
"""Offline tests for the durable lease-owned command-registry composition."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_lease_registry_composition as COMPOSITION
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_private_preflight as PRIVATE
import aws_two_wave_teardown_receipt_approval as APPROVAL
import aws_two_wave_teardown_registry_runner as RUNNER


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.9-shared-dev-test-lease-registry-composition"
FIXTURE = json.loads((ROOT / f"delivery/examples/{PREFIX}-fixtures.json").read_text())
REQUEST = LEASE.REQUEST


class LeaseRegistryCompositionTests(unittest.TestCase):
    def setUp(self):
        driver_fixture = json.loads((ROOT / FIXTURE["sourcePhaseDriverFixture"]).read_text())
        approval_fixture = json.loads((ROOT / driver_fixture["sourceApprovalFixture"]).read_text())
        preflight_fixture = json.loads((ROOT / approval_fixture["sourcePreflightFixture"]).read_text())
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
        approval_timing = approval_fixture["approvalTiming"]
        approval_request = {
            "schemaVersion": APPROVAL.APPROVAL_REQUEST_SCHEMA,
            "receiptSha256": self.receipt_sha,
            "environment": self.receipt["environment"],
            "stateKey": self.receipt["stateKey"],
            "phase": self.receipt["phase"],
            "attemptNumber": self.receipt["attemptNumber"],
            "controlPlaneCommit": self.receipt["controlPlaneCommit"],
            "requestedAuthority": self.receipt["requestedAuthority"],
            "createdAtUtc": approval_timing["createdAtUtc"],
            "notBeforeUtc": approval_timing["notBeforeUtc"],
            "expiresAtUtc": approval_timing["expiresAtUtc"],
            "approvalText": approval_text,
            "approvalTextSha256": APPROVAL.text_sha256(approval_text),
            "humanApproved": True,
            "oneAttemptOnly": True,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
        }
        approval = self.approval_store.record_approval(
            approval_request,
            expected_approval_request_sha256=REQUEST.sha256(approval_request),
            expected_receipt_sha256=self.receipt_sha,
            now_utc=approval_fixture["approvalClockUtc"],
        )
        self.approval_record = approval["approvalRecord"]
        self.approval_record_sha = approval["approvalRecordSha256"]
        self.execution_timing = driver_fixture["executionTiming"]
        self.execution_clock = driver_fixture["executionClockUtc"]
        self.completion_clock = driver_fixture["completionClockUtc"]

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
            "executionSpecSha256": DRIVERS.execution_spec_sha256(
                self.approval_record["environment"], self.approval_record["phase"]
            ),
            "createdAtUtc": self.execution_timing["createdAtUtc"],
            "notBeforeUtc": self.execution_timing["notBeforeUtc"],
            "expiresAtUtc": self.execution_timing["expiresAtUtc"],
            "humanReviewed": True,
            "oneAttemptOnly": True,
            "simulationOnly": True,
            "liveExecutionAuthorized": False,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
        }

    def private_bindings(self, request):
        spec = DRIVERS.phase_driver_spec(request["environment"], request["phase"])
        value = {name: format(index + 20, "064x") for index, name in enumerate(spec["requiredPrivateBindings"])}
        value["receiptSha256"] = self.receipt_sha
        value["approvalRecordSha256"] = self.approval_record_sha
        value["executionRequestSha256"] = REQUEST.sha256(request)
        return value

    def run_once(self, store, *, request=None, private_bindings=None, backend=None, completed=None):
        value = self.execution_request() if request is None else request
        bound = self.private_bindings(value) if private_bindings is None else private_bindings
        return COMPOSITION.run_lease_owned_registry_once(
            approval_store=self.approval_store,
            execution_store=store,
            execution_request=value,
            expected_execution_request_sha256=REQUEST.sha256(value),
            expected_receipt_sha256=self.receipt_sha,
            expected_approval_record_sha256=self.approval_record_sha,
            private_bindings=bound,
            now_utc=self.execution_clock,
            completed_at_utc=self.completion_clock if completed is None else completed,
            backend=RUNNER.FixedFakeRegistryBackend() if backend is None else backend,
        )

    def test_success_writes_durable_claim_then_outcome(self):
        temporary, root, store = self.execution_store()
        try:
            backend = RUNNER.FixedFakeRegistryBackend()
            result = self.run_once(store, backend=backend)
            claim_path = root / "claims" / f"{self.approval_record_sha}.claim.json"
            outcome_path = root / "outcomes" / f"{self.approval_record_sha}.outcome.json"
            claim = json.loads(claim_path.read_bytes())
            outcome = json.loads(outcome_path.read_bytes())
            self.assertEqual(claim_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(outcome_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(claim["status"], "approval-consumed-before-fixed-fake-phase-dispatch")
            self.assertEqual(outcome["status"], "claimed-registry-composition-succeeded")
            self.assertEqual(result["claimSha256"], REQUEST.sha256(claim))
            self.assertEqual(result["outcomeSha256"], REQUEST.sha256(outcome))
            self.assertEqual(result["backendCallCount"], 7)
            self.assertEqual([row["operationId"] for row in backend.calls], list(DRIVERS.PHASE_OPERATIONS["wave-one-plan"]))
            self.assertFalse(result["liveCommandExecuted"])
        finally:
            temporary.cleanup()

    def test_claim_is_durable_before_first_registry_call(self):
        temporary, root, store = self.execution_store()
        try:
            backend = RUNNER.FixedFakeRegistryBackend()
            original = backend.call

            def observed(**kwargs):
                claim_path = root / "claims" / f"{self.approval_record_sha}.claim.json"
                self.assertTrue(claim_path.is_file())
                self.assertEqual(json.loads(claim_path.read_bytes())["approvalConsumedByLease"], True)
                return original(**kwargs)

            backend.call = observed
            self.run_once(store, backend=backend)
            self.assertEqual(len(backend.calls), 7)
        finally:
            temporary.cleanup()

    def test_success_cannot_be_replayed(self):
        temporary, _root, store = self.execution_store()
        try:
            self.run_once(store)
            retry = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                self.run_once(store, backend=retry)
            self.assertEqual(retry.calls, [])
            self.assertFalse(retry.used)
        finally:
            temporary.cleanup()

    def test_failed_operation_records_outcome_and_cannot_be_replayed(self):
        temporary, root, store = self.execution_store()
        try:
            failed_id = "select-exact-non-network-destroy-scope"
            backend = RUNNER.FixedFakeRegistryBackend(fail_at=failed_id)
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped) as stopped:
                self.run_once(store, backend=backend)
            self.assertEqual(stopped.exception.report["backendCallCount"], 5)
            self.assertTrue(stopped.exception.report["claimCreated"])
            self.assertTrue(stopped.exception.report["outcomeRecorded"])
            outcome = json.loads((root / "outcomes" / f"{self.approval_record_sha}.outcome.json").read_bytes())
            self.assertEqual(outcome["failedOperationId"], failed_id)
            self.assertFalse(outcome["terminalSuccess"])
            retry = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                self.run_once(store, backend=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_malformed_response_records_outcome_and_cannot_be_replayed(self):
        temporary, root, store = self.execution_store()
        try:
            operation = DRIVERS.PHASE_OPERATIONS["wave-one-plan"][2]
            backend = RUNNER.FixedFakeRegistryBackend(malformed_at=operation)
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped) as stopped:
                self.run_once(store, backend=backend)
            self.assertEqual(stopped.exception.report["backendCallCount"], 3)
            self.assertTrue((root / "outcomes" / f"{self.approval_record_sha}.outcome.json").is_file())
            retry = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                self.run_once(store, backend=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_all_caller_controlled_inputs_are_validated_before_claim(self):
        cases = []
        request = self.execution_request()
        changed = self.private_bindings(request)
        changed.pop("stateInventorySha256")
        cases.append((request, changed, RUNNER.FixedFakeRegistryBackend()))
        changed = self.private_bindings(request)
        changed["receiptSha256"] = "f" * 64
        cases.append((request, changed, RUNNER.FixedFakeRegistryBackend()))
        changed_request = copy.deepcopy(request)
        changed_request["executionSpecSha256"] = "0" * 64
        cases.append((changed_request, self.private_bindings(changed_request), RUNNER.FixedFakeRegistryBackend()))

        class OtherBackend(RUNNER.FixedFakeRegistryBackend):
            pass

        cases.append((request, self.private_bindings(request), OtherBackend()))
        for value, bound, backend in cases:
            temporary, root, store = self.execution_store()
            try:
                with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                    self.run_once(store, request=value, private_bindings=bound, backend=backend)
                self.assertEqual(list((root / "claims").iterdir()), [])
                self.assertEqual(backend.calls, [])
            finally:
                temporary.cleanup()

    def test_claim_fsync_uncertainty_blocks_dispatch_and_replay(self):
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

            backend = RUNNER.FixedFakeRegistryBackend()
            with patch.object(LEASE.os, "fsync", side_effect=fail_first):
                with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                    self.run_once(store, backend=backend)
            self.assertEqual(backend.calls, [])
            self.assertTrue((root / "claims" / f"{self.approval_record_sha}.claim.json").exists())
            retry = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                self.run_once(store, backend=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_success_outcome_write_uncertainty_consumes_attempt(self):
        temporary, _root, store = self.execution_store()
        try:
            store.outcome = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                LEASE.ExecutionLeaseStopped("injected-outcome-write")
            )
            backend = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped) as stopped:
                self.run_once(store, backend=backend)
            self.assertTrue(stopped.exception.report["claimCreated"])
            self.assertEqual(stopped.exception.report["backendCallCount"], 7)
            self.assertFalse(stopped.exception.report["outcomeRecorded"])
            retry = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                self.run_once(store, backend=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_failure_outcome_write_uncertainty_consumes_attempt(self):
        temporary, _root, store = self.execution_store()
        try:
            store.outcome = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                LEASE.ExecutionLeaseStopped("injected-outcome-write")
            )
            backend = RUNNER.FixedFakeRegistryBackend(fail_at="verify-environment-context")
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped) as stopped:
                self.run_once(store, backend=backend)
            self.assertEqual(stopped.exception.report["stage"], "lease-registry-failure-outcome-write-uncertain")
            self.assertEqual(stopped.exception.report["backendCallCount"], 1)
            self.assertFalse(stopped.exception.report["outcomeRecorded"])
        finally:
            temporary.cleanup()

    def test_completion_must_be_inside_execution_window_before_claim(self):
        temporary, root, store = self.execution_store()
        try:
            backend = RUNNER.FixedFakeRegistryBackend()
            with self.assertRaises(COMPOSITION.LeaseRegistryCompositionStopped):
                self.run_once(store, backend=backend, completed=self.execution_timing["expiresAtUtc"])
            self.assertEqual(list((root / "claims").iterdir()), [])
            self.assertEqual(backend.calls, [])
        finally:
            temporary.cleanup()

    def test_fixture_digests_are_stable(self):
        temporary, root, store = self.execution_store()
        try:
            result = self.run_once(store)
            claim = json.loads((root / "claims" / f"{self.approval_record_sha}.claim.json").read_bytes())
            outcome = json.loads((root / "outcomes" / f"{self.approval_record_sha}.outcome.json").read_bytes())
            self.assertEqual(REQUEST.sha256(claim), FIXTURE["expectedClaimSha256"])
            self.assertEqual(result["runnerResultSha256"], FIXTURE["expectedRunnerResultSha256"])
            self.assertEqual(REQUEST.sha256(outcome), FIXTURE["expectedOutcomeSha256"])
            self.assertEqual(REQUEST.sha256(result), FIXTURE["expectedResultSha256"])
        finally:
            temporary.cleanup()

    def test_result_outcome_and_stop_reports_are_redacted(self):
        temporary, root, store = self.execution_store()
        try:
            result = self.run_once(store)
            outcome = json.loads((root / "outcomes" / f"{self.approval_record_sha}.outcome.json").read_bytes())
            stop = COMPOSITION.LeaseRegistryCompositionStopped("fixture", phase="wave-one-plan").report
            raw = json.dumps([result, outcome, stop], sort_keys=True).lower()
            for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-"):
                self.assertNotIn(marker, raw)
            self.assertNotIn("privatebindings", raw)
            self.assertFalse(stop["privatePathEmitted"])
            self.assertFalse(stop["privateResourceIdentityEmitted"])
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()

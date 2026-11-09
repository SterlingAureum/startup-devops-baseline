#!/usr/bin/env python3
"""Offline tests for closed shared dev/test teardown phase drivers."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_private_preflight as PRIVATE
import aws_two_wave_teardown_receipt_approval as APPROVAL
from aws_two_wave_teardown_core import TeardownGateError


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.6-shared-dev-test-phase-drivers"
FIXTURE_PATH = ROOT / f"delivery/examples/{PREFIX}-fixtures.json"
REQUEST = LEASE.REQUEST


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load(
    ROOT / f"scripts/exercise-{PREFIX}.py",
    "shared_phase_driver_cli_under_test",
)


class SharedPhaseDriverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text())
        approval_fixture = json.loads((ROOT / self.fixture["sourceApprovalFixture"]).read_text())
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
        approved = self.approval_store.record_approval(
            approval_request,
            expected_approval_request_sha256=REQUEST.sha256(approval_request),
            expected_receipt_sha256=self.receipt_sha,
            now_utc=approval_fixture["approvalClockUtc"],
        )
        self.approval_record = approved["approvalRecord"]
        self.approval_record_sha = approved["approvalRecordSha256"]

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
            "executionSpecSha256": DRIVERS.execution_spec_sha256(
                self.approval_record["environment"], self.approval_record["phase"]
            ),
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

    def run_once(self, store, *, request=None, transport=None):
        value = self.execution_request() if request is None else request
        return DRIVERS.run_reviewed_phase_spec_once(
            approval_store=self.approval_store,
            execution_store=store,
            execution_request=value,
            expected_execution_request_sha256=REQUEST.sha256(value),
            expected_receipt_sha256=self.receipt_sha,
            expected_approval_record_sha256=self.approval_record_sha,
            now_utc=self.fixture["executionClockUtc"],
            completed_at_utc=self.fixture["completionClockUtc"],
            transport=DRIVERS.FixedFakePhaseTransport() if transport is None else transport,
        )

    def single_input(self, value):
        temporary = tempfile.TemporaryDirectory()
        directory = Path(temporary.name)
        directory.chmod(0o700)
        path = directory / "execution-request.json"
        path.write_bytes(REQUEST.canonical_bytes(value))
        path.chmod(0o600)
        return temporary, path

    def test_all_dev_test_phase_specs_are_closed_and_unique(self):
        digests = set()
        for environment in ("aws-dev", "aws-test"):
            for phase, operations in DRIVERS.PHASE_OPERATIONS.items():
                with self.subTest(environment=environment, phase=phase):
                    value = DRIVERS.phase_driver_spec(environment, phase)
                    self.assertEqual(value["operationIds"], list(operations))
                    self.assertTrue(value["simulationOnly"])
                    self.assertFalse(value["liveBackendAvailable"])
                    DRIVERS.validate_phase_driver_spec(value, environment=environment, phase=phase)
                    digests.add(DRIVERS.execution_spec_sha256(environment, phase))
        self.assertEqual(len(digests), 16)
        self.assertEqual(sum(map(len, DRIVERS.PHASE_OPERATIONS.values())), 49)
        self.assertEqual(
            {key: len(value) for key, value in DRIVERS.PHASE_OPERATIONS.items()},
            self.fixture["phaseOperationCounts"],
        )

    def test_dev_test_specs_separate_state_root_and_backend(self):
        dev = DRIVERS.phase_driver_spec("aws-dev", "wave-one-plan")
        test = DRIVERS.phase_driver_spec("aws-test", "wave-one-plan")
        for key in ("stateKey", "terraformRootRelativePath", "backendConfigRelativePath"):
            self.assertNotEqual(dev[key], test[key])
        for key in set(dev) - {"environment", "stateKey", "terraformRootRelativePath", "backendConfigRelativePath"}:
            self.assertEqual(dev[key], test[key])

    def test_prod_and_unknown_phase_are_rejected(self):
        for environment, phase in (("aws-prod", "wave-one-plan"), ("aws-dev", "unknown")):
            with self.subTest(environment=environment, phase=phase):
                with self.assertRaises(TeardownGateError):
                    DRIVERS.phase_driver_spec(environment, phase)

    def test_every_top_level_spec_mutation_is_rejected(self):
        original = DRIVERS.phase_driver_spec("aws-dev", "wave-one-plan")
        for key in original:
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                if isinstance(changed[key], bool):
                    changed[key] = not changed[key]
                elif isinstance(changed[key], list):
                    changed[key] = list(reversed(changed[key]))
                else:
                    changed[key] = f"changed-{changed[key]}"
                with self.assertRaises(TeardownGateError):
                    DRIVERS.validate_phase_driver_spec(changed, environment="aws-dev", phase="wave-one-plan")

    def test_success_dispatches_exact_order_after_durable_claim(self):
        temporary, root, store = self.execution_store()
        try:
            transport = DRIVERS.FixedFakePhaseTransport()
            original = transport.call

            def observed(request):
                claim = root / "claims" / f"{self.approval_record_sha}.claim.json"
                self.assertTrue(claim.is_file())
                self.assertEqual(json.loads(claim.read_bytes())["status"], "approval-consumed-before-fixed-fake-phase-dispatch")
                return original(request)

            transport.call = observed
            result = self.run_once(store, transport=transport)
            expected = list(DRIVERS.PHASE_OPERATIONS["wave-one-plan"])
            self.assertEqual([call["operationId"] for call in transport.calls], expected)
            self.assertEqual([call["operationIndex"] for call in transport.calls], list(range(len(expected))))
            self.assertEqual(result["operationCallCount"], len(expected))
            self.assertFalse(result["liveCommandExecuted"])
            self.assertFalse(result["executionPerformed"])
            outcome = root / "outcomes" / f"{self.approval_record_sha}.outcome.json"
            self.assertEqual(outcome.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(outcome.read_bytes())["status"], "fixed-fake-phase-driver-succeeded")
        finally:
            temporary.cleanup()

    def test_operation_request_is_bound_to_spec_and_execution_request(self):
        temporary, _root, store = self.execution_store()
        try:
            request = self.execution_request()
            transport = DRIVERS.FixedFakePhaseTransport()
            result = self.run_once(store, request=request, transport=transport)
            first = transport.calls[0]
            self.assertEqual(first["executionSpecSha256"], request["executionSpecSha256"])
            self.assertEqual(first["executionRequestSha256"], REQUEST.sha256(request))
            self.assertEqual(first["operationCount"], 7)
            self.assertEqual(result["operationManifestSha256"], json.loads(
                (_root / "outcomes" / f"{self.approval_record_sha}.outcome.json").read_bytes()
            )["operationManifestSha256"])
        finally:
            temporary.cleanup()

    def test_success_cannot_be_replayed(self):
        temporary, _root, store = self.execution_store()
        try:
            self.run_once(store)
            retry = DRIVERS.FixedFakePhaseTransport()
            with self.assertRaises(DRIVERS.PhaseDriverStopped):
                self.run_once(store, transport=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_failure_stops_at_first_operation_and_blocks_retry(self):
        temporary, root, store = self.execution_store()
        try:
            failed_id = "select-exact-non-network-destroy-scope"
            transport = DRIVERS.FixedFakePhaseTransport(fail_at=failed_id)
            with self.assertRaises(DRIVERS.PhaseDriverStopped) as stopped:
                self.run_once(store, transport=transport)
            self.assertEqual(stopped.exception.report["operationCallCount"], 5)
            self.assertTrue(stopped.exception.report["outcomeRecorded"])
            self.assertEqual(transport.calls[-1]["operationId"], failed_id)
            outcome = json.loads((root / "outcomes" / f"{self.approval_record_sha}.outcome.json").read_bytes())
            self.assertEqual(outcome["failedOperationId"], failed_id)
            self.assertFalse(outcome["terminalSuccess"])
            retry = DRIVERS.FixedFakePhaseTransport()
            with self.assertRaises(DRIVERS.PhaseDriverStopped):
                self.run_once(store, transport=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_malformed_response_after_claim_blocks_retry(self):
        temporary, root, store = self.execution_store()
        try:
            transport = DRIVERS.FixedFakePhaseTransport()
            transport.call = lambda request: {"changed": request["operationId"]}
            with self.assertRaises(DRIVERS.PhaseDriverStopped) as stopped:
                self.run_once(store, transport=transport)
            self.assertTrue(stopped.exception.report["claimCreated"])
            self.assertEqual(list((root / "outcomes").iterdir()), [])
            retry = DRIVERS.FixedFakePhaseTransport()
            with self.assertRaises(DRIVERS.PhaseDriverStopped):
                self.run_once(store, transport=retry)
            self.assertEqual(retry.calls, [])
        finally:
            temporary.cleanup()

    def test_spec_digest_mismatch_stops_before_claim(self):
        temporary, root, store = self.execution_store()
        try:
            value = self.execution_request()
            value["executionSpecSha256"] = "0" * 64
            transport = DRIVERS.FixedFakePhaseTransport()
            with self.assertRaises(DRIVERS.PhaseDriverStopped):
                self.run_once(store, request=value, transport=transport)
            self.assertEqual(list((root / "claims").iterdir()), [])
            self.assertEqual(transport.calls, [])
        finally:
            temporary.cleanup()

    def test_exact_transport_type_is_required_before_claim(self):
        class OtherTransport(DRIVERS.FixedFakePhaseTransport):
            pass

        temporary, root, store = self.execution_store()
        try:
            with self.assertRaises(DRIVERS.PhaseDriverStopped):
                self.run_once(store, transport=OtherTransport())
            self.assertEqual(list((root / "claims").iterdir()), [])
        finally:
            temporary.cleanup()

    def test_outcome_write_uncertainty_consumes_attempt(self):
        temporary, _root, store = self.execution_store()
        try:
            store.outcome = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                LEASE.ExecutionLeaseStopped("injected-outcome-write")
            )
            with self.assertRaises(DRIVERS.PhaseDriverStopped) as stopped:
                self.run_once(store)
            self.assertTrue(stopped.exception.report["claimCreated"])
            self.assertEqual(stopped.exception.report["operationCallCount"], 7)
            self.assertFalse(stopped.exception.report["outcomeRecorded"])
        finally:
            temporary.cleanup()

    def test_result_and_stop_reports_are_redacted(self):
        temporary, _root, store = self.execution_store()
        try:
            result = self.run_once(store)
            raw = json.dumps(result)
            for marker in ("/home/", "/tmp/", "arn:aws", "vpc-", "sg-", "eni-"):
                self.assertNotIn(marker, raw)
            stopped = DRIVERS.PhaseDriverStopped("fixture", phase="wave-one-plan").report
            self.assertFalse(stopped["privatePathEmitted"])
            self.assertFalse(stopped["privateResourceIdentityEmitted"])
        finally:
            temporary.cleanup()

    def test_cli_runs_only_the_exact_fixed_fake_phase(self):
        execution_temp, execution_root, _store = self.execution_store()
        request = self.execution_request()
        input_temp, input_path = self.single_input(request)
        try:
            result = CLI.run(
                [
                    "--approval-store-directory", str(self.approval_store.root),
                    "--execution-store-directory", str(execution_root),
                    "--execution-request-file", str(input_path),
                    "--expected-execution-request-sha256", REQUEST.sha256(request),
                    "--expected-receipt-sha256", self.receipt_sha,
                    "--expected-approval-record-sha256", self.approval_record_sha,
                    "--confirm", CLI.CONFIRMATION,
                ],
                now_utc=self.fixture["executionClockUtc"],
            )
            self.assertEqual(result["operationCallCount"], 7)
            self.assertTrue(result["approvalConsumedByLease"])
            self.assertFalse(result["liveCommandExecuted"])
        finally:
            input_temp.cleanup()
            execution_temp.cleanup()

    def test_cli_confirmation_is_exact(self):
        execution_temp, execution_root, _store = self.execution_store()
        request = self.execution_request()
        input_temp, input_path = self.single_input(request)
        try:
            with self.assertRaises(DRIVERS.PhaseDriverStopped):
                CLI.run(
                    [
                        "--approval-store-directory", str(self.approval_store.root),
                        "--execution-store-directory", str(execution_root),
                        "--execution-request-file", str(input_path),
                        "--expected-execution-request-sha256", REQUEST.sha256(request),
                        "--expected-receipt-sha256", self.receipt_sha,
                        "--expected-approval-record-sha256", self.approval_record_sha,
                        "--confirm", "wrong",
                    ],
                    now_utc=self.fixture["executionClockUtc"],
                )
            self.assertEqual(list((execution_root / "claims").iterdir()), [])
        finally:
            input_temp.cleanup()
            execution_temp.cleanup()


if __name__ == "__main__":
    unittest.main()

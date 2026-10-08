#!/usr/bin/env python3
"""Offline tests for append-only teardown receipts and phase approvals."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

import aws_two_wave_teardown_private_preflight as PRIVATE
import aws_two_wave_teardown_receipt_approval as ADAPTER


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "v0.12.4.1.5.0.7.1.6.4-shared-dev-test-two-wave-teardown-receipt-approval"
FIXTURE_PATH = ROOT / f"delivery/examples/{PREFIX}-fixtures.json"
PREFLIGHT_FIXTURE_PATH = ROOT / "delivery/examples/v0.12.4.1.5.0.7.1.6.3-shared-dev-test-two-wave-teardown-private-preflight-fixtures.json"
REQUEST = ADAPTER.REQUEST


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLI = load(ROOT / "scripts/approval-v0.12.4.1.5.0.7.1.6.4-shared-dev-test-two-wave-teardown.py", "receipt_approval_cli_under_test")


class ReceiptApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE_PATH.read_text())
        preflight_fixture = json.loads(PREFLIGHT_FIXTURE_PATH.read_text())
        source = preflight_fixture[self.fixture["sourceCase"]]
        self.preflight_result = PRIVATE.verify_private_bundle(
            REQUEST.canonical_bytes(source["request"]),
            REQUEST.canonical_bytes(source["evidence"]),
            expected_request_sha256=REQUEST.sha256(source["request"]),
            expected_evidence_sha256=REQUEST.sha256(source["evidence"]),
            now_utc=preflight_fixture["verificationClockUtc"],
        )
        self.receipt = self.preflight_result["receipt"]
        self.receipt_sha = self.preflight_result["receiptSha256"]
        self.persist_now = self.fixture["persistenceClockUtc"]
        self.approve_now = self.fixture["approvalClockUtc"]

    def private_store(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        root.chmod(0o700)
        for name in ("receipts", "approvals"):
            child = root / name
            child.mkdir()
            child.chmod(0o700)
        return temporary, root

    def approval_request(self):
        timing = self.fixture["approvalTiming"]
        text = ADAPTER.approval_text(self.receipt)
        return {
            "schemaVersion": ADAPTER.APPROVAL_REQUEST_SCHEMA,
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
            "approvalText": text,
            "approvalTextSha256": ADAPTER.text_sha256(text),
            "humanApproved": True,
            "oneAttemptOnly": True,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
        }

    def persist(self, store):
        return store.persist_receipt(
            self.preflight_result,
            expected_result_sha256=REQUEST.sha256(self.preflight_result),
            now_utc=self.persist_now,
        )

    def approve(self, store, approval=None):
        value = self.approval_request() if approval is None else approval
        return store.record_approval(
            value,
            expected_approval_request_sha256=REQUEST.sha256(value),
            expected_receipt_sha256=self.receipt_sha,
            now_utc=self.approve_now,
        )

    def single_input(self, name, value):
        temporary = tempfile.TemporaryDirectory()
        directory = Path(temporary.name)
        directory.chmod(0o700)
        path = directory / name
        path.write_bytes(REQUEST.canonical_bytes(value))
        path.chmod(0o600)
        return temporary, path

    def test_receipt_persistence_is_content_addressed_and_redacted(self):
        temporary, root = self.private_store()
        try:
            result = self.persist(ADAPTER.PrivateReceiptApprovalStore(root))
            path = root / "receipts" / f"{self.receipt_sha}.receipt.json"
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_bytes()), self.receipt)
            self.assertFalse(result["approvalRecorded"])
            self.assertFalse(result["executionPerformed"])
        finally:
            temporary.cleanup()

    def test_receipt_cannot_be_overwritten(self):
        temporary, root = self.private_store()
        try:
            store = ADAPTER.PrivateReceiptApprovalStore(root)
            self.persist(store)
            path = root / "receipts" / f"{self.receipt_sha}.receipt.json"
            original = path.read_bytes()
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                self.persist(store)
            self.assertEqual(path.read_bytes(), original)
        finally:
            temporary.cleanup()

    def test_preflight_result_digest_is_required(self):
        temporary, root = self.private_store()
        try:
            store = ADAPTER.PrivateReceiptApprovalStore(root)
            with self.assertRaises(ADAPTER.TeardownGateError):
                store.persist_receipt(self.preflight_result, expected_result_sha256="0" * 64, now_utc=self.persist_now)
        finally:
            temporary.cleanup()

    def test_tampered_receipt_content_is_rejected(self):
        temporary, root = self.private_store()
        try:
            value = copy.deepcopy(self.preflight_result)
            value["receipt"]["phase"] = "wave-two-plan"
            with self.assertRaises(ADAPTER.TeardownGateError):
                ADAPTER.PrivateReceiptApprovalStore(root).persist_receipt(value, expected_result_sha256=REQUEST.sha256(value), now_utc=self.persist_now)
        finally:
            temporary.cleanup()

    def test_expired_receipt_is_not_persisted(self):
        temporary, root = self.private_store()
        try:
            with self.assertRaises(ADAPTER.TeardownGateError):
                ADAPTER.PrivateReceiptApprovalStore(root).persist_receipt(self.preflight_result, expected_result_sha256=REQUEST.sha256(self.preflight_result), now_utc=self.receipt["expiresAtUtc"])
            self.assertEqual(list((root / "receipts").iterdir()), [])
        finally:
            temporary.cleanup()

    def test_store_requires_exact_root_directories(self):
        temporary, root = self.private_store()
        try:
            extra = root / "unexpected"
            extra.mkdir()
            extra.chmod(0o700)
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                ADAPTER.PrivateReceiptApprovalStore(root)
        finally:
            temporary.cleanup()

    def test_store_rejects_root_mode_drift(self):
        temporary, root = self.private_store()
        try:
            root.chmod(0o755)
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                ADAPTER.PrivateReceiptApprovalStore(root)
        finally:
            temporary.cleanup()

    def test_store_rejects_child_mode_drift(self):
        temporary, root = self.private_store()
        try:
            (root / "approvals").chmod(0o755)
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                ADAPTER.PrivateReceiptApprovalStore(root)
        finally:
            temporary.cleanup()

    def test_store_rejects_unexpected_record_name(self):
        temporary, root = self.private_store()
        try:
            path = root / "receipts" / "latest.json"
            path.write_bytes(b"{}\n")
            path.chmod(0o600)
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                ADAPTER.PrivateReceiptApprovalStore(root)
        finally:
            temporary.cleanup()

    def test_approval_record_consumes_receipt_once(self):
        temporary, root = self.private_store()
        try:
            store = ADAPTER.PrivateReceiptApprovalStore(root)
            self.persist(store)
            result = self.approve(store)
            record = result["approvalRecord"]
            path = root / "approvals" / f"{self.receipt_sha}.approval.json"
            self.assertEqual(json.loads(path.read_bytes()), record)
            self.assertEqual(result["approvalRecordSha256"], REQUEST.sha256(record))
            self.assertTrue(record["receiptConsumedByApproval"])
            self.assertFalse(record["approvalConsumedByExecutor"])
            self.assertFalse(record["executionPerformed"])
        finally:
            temporary.cleanup()

    def test_second_approval_is_rejected_without_overwrite(self):
        temporary, root = self.private_store()
        try:
            store = ADAPTER.PrivateReceiptApprovalStore(root)
            self.persist(store)
            self.approve(store)
            path = root / "approvals" / f"{self.receipt_sha}.approval.json"
            original = path.read_bytes()
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                self.approve(store)
            self.assertEqual(path.read_bytes(), original)
        finally:
            temporary.cleanup()

    def test_unpersisted_receipt_cannot_be_approved(self):
        temporary, root = self.private_store()
        try:
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                self.approve(ADAPTER.PrivateReceiptApprovalStore(root))
        finally:
            temporary.cleanup()

    def test_approval_identity_bindings_are_exact(self):
        mutations = {
            "receiptSha256": "0" * 64,
            "environment": "aws-test",
            "stateKey": "environments/test/terraform.tfstate",
            "phase": "wave-two-plan",
            "attemptNumber": 2,
            "controlPlaneCommit": "0" * 40,
            "requestedAuthority": "terraform-apply",
        }
        for key, replacement in mutations.items():
            with self.subTest(key=key):
                approval = self.approval_request()
                approval[key] = replacement
                with self.assertRaises(ADAPTER.TeardownGateError):
                    ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_approval_statement_and_digest_are_exact(self):
        approval = self.approval_request()
        approval["approvalText"] += " WITH RETRY"
        approval["approvalTextSha256"] = ADAPTER.text_sha256(approval["approvalText"])
        with self.assertRaises(ADAPTER.TeardownGateError):
            ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)
        approval = self.approval_request()
        approval["approvalTextSha256"] = "0" * 64
        with self.assertRaises(ADAPTER.TeardownGateError):
            ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_approval_must_be_human_and_single_attempt(self):
        for key in ("humanApproved", "oneAttemptOnly"):
            with self.subTest(key=key):
                approval = self.approval_request()
                approval[key] = False
                with self.assertRaises(ADAPTER.TeardownGateError):
                    ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_approval_forbidden_authorities_remain_false(self):
        for key in ("automaticRetryAuthorized", "automaticRollbackAuthorized", "statePushAuthorized", "backendRetirementAuthorized"):
            with self.subTest(key=key):
                approval = self.approval_request()
                approval[key] = True
                with self.assertRaises(ADAPTER.TeardownGateError):
                    ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_future_approval_is_rejected(self):
        approval = self.approval_request()
        approval["notBeforeUtc"] = "2026-10-09T00:12:01Z"
        with self.assertRaises(ADAPTER.TeardownGateError):
            ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_expired_approval_is_rejected(self):
        approval = self.approval_request()
        approval["expiresAtUtc"] = self.approve_now
        with self.assertRaises(ADAPTER.TeardownGateError):
            ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_approval_window_over_fifteen_minutes_is_rejected(self):
        approval = self.approval_request()
        approval["expiresAtUtc"] = "2026-10-09T00:27:01Z"
        with self.assertRaises(ADAPTER.TeardownGateError):
            ADAPTER.validate_approval_request(approval, self.receipt, now_utc=self.approve_now)

    def test_approval_cannot_outlive_receipt(self):
        approval = self.approval_request()
        approval["notBeforeUtc"] = "2026-10-09T01:00:00Z"
        approval["expiresAtUtc"] = "2026-10-09T01:06:00Z"
        with self.assertRaises(ADAPTER.TeardownGateError):
            ADAPTER.validate_approval_request(approval, self.receipt, now_utc="2026-10-09T01:00:00Z")

    def test_approval_record_is_redacted(self):
        temporary, root = self.private_store()
        try:
            store = ADAPTER.PrivateReceiptApprovalStore(root)
            self.persist(store)
            serialized = json.dumps(self.approve(store), sort_keys=True)
            self.assertNotIn("/home/", serialized)
            self.assertNotIn("vpc-", serialized)
            self.assertNotIn("sg-", serialized)
        finally:
            temporary.cleanup()

    def test_strict_single_private_file_rejects_extra_entry(self):
        temporary, path = self.single_input("result.json", self.preflight_result)
        try:
            extra = path.parent / "extra"
            extra.write_bytes(b"{}\n")
            extra.chmod(0o600)
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                ADAPTER.StrictSinglePrivateFile.read(path)
        finally:
            temporary.cleanup()

    def test_cli_persists_then_records_approval(self):
        store_tmp, root = self.private_store()
        result_tmp, result_path = self.single_input("preflight-result.json", self.preflight_result)
        approval = self.approval_request()
        approval_tmp, approval_path = self.single_input("approval-request.json", approval)
        try:
            persisted = CLI.run([
                "persist-receipt",
                "--store-directory", str(root),
                "--preflight-result-file", str(result_path),
                "--expected-preflight-result-sha256", REQUEST.sha256(self.preflight_result),
                "--confirm", CLI.PERSIST_CONFIRMATION,
            ], now_utc=self.persist_now)
            self.assertEqual(persisted["receiptSha256"], self.receipt_sha)
            approved = CLI.run([
                "record-approval",
                "--store-directory", str(root),
                "--approval-request-file", str(approval_path),
                "--expected-approval-request-sha256", REQUEST.sha256(approval),
                "--expected-receipt-sha256", self.receipt_sha,
                "--confirm", CLI.APPROVAL_CONFIRMATION,
            ], now_utc=self.approve_now)
            self.assertFalse(approved["approvalRecord"]["executionPerformed"])
        finally:
            approval_tmp.cleanup()
            result_tmp.cleanup()
            store_tmp.cleanup()

    def test_cli_confirmation_is_exact(self):
        store_tmp, root = self.private_store()
        result_tmp, result_path = self.single_input("preflight-result.json", self.preflight_result)
        try:
            with self.assertRaises(ADAPTER.ReceiptApprovalStopped):
                CLI.run([
                    "persist-receipt",
                    "--store-directory", str(root),
                    "--preflight-result-file", str(result_path),
                    "--expected-preflight-result-sha256", REQUEST.sha256(self.preflight_result),
                    "--confirm", "persist-and-execute",
                ], now_utc=self.persist_now)
        finally:
            result_tmp.cleanup()
            store_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()

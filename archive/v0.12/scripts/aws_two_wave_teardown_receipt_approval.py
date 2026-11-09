#!/usr/bin/env python3
"""Append-only private receipt persistence and phase-approval adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_private_preflight as PRIVATE
from aws_two_wave_teardown_core import TeardownGateError, environment_profile, require


VERSION = "v0.12.4.1.5.0.7.1.6.4"
APPROVAL_REQUEST_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-phase-approval-request-v1"
APPROVAL_RECORD_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-phase-approval-record-v1"
PERSIST_RESULT_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-receipt-persist-result-v1"
APPROVAL_RESULT_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-phase-approval-result-v1"
MAX_APPROVAL_WINDOW_SECONDS = 900
MAX_PRIVATE_FILE_BYTES = 1024 * 1024
ROOT_ENTRIES = {"receipts", "approvals"}
RECEIPT_NAME = re.compile(r"([0-9a-f]{64})\.receipt\.json")
APPROVAL_NAME = re.compile(r"([0-9a-f]{64})\.approval\.json")

RECEIPT_KEYS = {
    "schemaVersion",
    "status",
    "environment",
    "stateKey",
    "phase",
    "attemptNumber",
    "controlPlaneCommit",
    "requestSha256",
    "evidenceSha256",
    "predecessorReceiptSha256",
    "stateInventorySha256",
    "requestedAuthority",
    "observedAtUtc",
    "verifiedAtUtc",
    "expiresAtUtc",
    "privateInputFileCount",
    "privatePathEmitted",
    "privateResourceIdentityEmitted",
    "liveCommandExecuted",
    "executionAuthorized",
    "automaticRetryAuthorized",
    "automaticRollbackAuthorized",
    "statePushAuthorized",
    "backendRetirementAuthorized",
    "nextAction",
}
APPROVAL_REQUEST_KEYS = {
    "schemaVersion",
    "receiptSha256",
    "environment",
    "stateKey",
    "phase",
    "attemptNumber",
    "controlPlaneCommit",
    "requestedAuthority",
    "createdAtUtc",
    "notBeforeUtc",
    "expiresAtUtc",
    "approvalText",
    "approvalTextSha256",
    "humanApproved",
    "oneAttemptOnly",
    "automaticRetryAuthorized",
    "automaticRollbackAuthorized",
    "statePushAuthorized",
    "backendRetirementAuthorized",
}


class ReceiptApprovalStopped(TeardownGateError):
    """Fail-closed local persistence stop without private paths or payloads."""


def _exact_keys(value: Any, keys: set[str], message: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, message)
    return value


def _sha(value: Any, message: str) -> str:
    require(isinstance(value, str) and REQUEST.SHA256.fullmatch(value) is not None, message)
    return value


def _utc(value: Any, message: str) -> datetime:
    require(isinstance(value, str) and REQUEST.UTC.fullmatch(value) is not None, message)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise TeardownGateError(message) from None


def _now(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return _utc(value, "Approval clock must be whole-second UTC")
    require(isinstance(value, datetime) and value.tzinfo is not None, "Approval clock must be timezone-aware")
    normalized = value.astimezone(timezone.utc)
    require(normalized.microsecond == 0, "Approval clock must be whole-second UTC")
    return normalized


def text_sha256(value: str) -> str:
    require(isinstance(value, str) and value, "Approval text is empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def approval_text(receipt: dict[str, Any]) -> str:
    return (
        f"APPROVE ONE {receipt['environment']} {receipt['phase']} ATTEMPT "
        f"{receipt['attemptNumber']} BOUND TO RECEIPT {REQUEST.sha256(receipt)}; "
        "NO AUTOMATIC RETRY"
    )


def validate_receipt_result(value: dict[str, Any], *, now_utc: datetime | str) -> dict[str, Any]:
    result = _exact_keys(value, {"schemaVersion", "receipt", "receiptSha256"}, "Preflight result shape changed")
    require(result["schemaVersion"] == PRIVATE.RESULT_SCHEMA, "Preflight result schema changed")
    receipt = _exact_keys(result["receipt"], RECEIPT_KEYS, "Preflight receipt shape changed")
    receipt_sha = _sha(result["receiptSha256"], "Receipt digest changed")
    require(receipt_sha == REQUEST.sha256(receipt), "Receipt digest does not match content")
    require(receipt["schemaVersion"] == PRIVATE.RECEIPT_SCHEMA, "Receipt schema changed")
    require(receipt["status"] == "shared-two-wave-private-preflight-ready-for-separate-approval", "Receipt status changed")
    profile = environment_profile(receipt["environment"])
    require(receipt["stateKey"] == profile["stateKey"], "Receipt state key changed")
    require(receipt["phase"] in REQUEST.PHASES, "Receipt phase changed")
    phase = REQUEST.PHASES[receipt["phase"]]
    require(receipt["requestedAuthority"] == phase["requestedAuthority"], "Receipt authority changed")
    require(receipt["nextAction"] == phase["nextAction"], "Receipt next action changed")
    require(isinstance(receipt["attemptNumber"], int) and not isinstance(receipt["attemptNumber"], bool) and receipt["attemptNumber"] > 0, "Receipt attempt changed")
    require(isinstance(receipt["controlPlaneCommit"], str) and REQUEST.COMMIT.fullmatch(receipt["controlPlaneCommit"]) is not None, "Receipt commit changed")
    for key in ("requestSha256", "evidenceSha256", "stateInventorySha256"):
        _sha(receipt[key], f"Receipt {key} changed")
    if phase["predecessorRequired"]:
        _sha(receipt["predecessorReceiptSha256"], "Receipt predecessor changed")
    else:
        require(receipt["predecessorReceiptSha256"] is None, "First receipt inherited a predecessor")
    observed = _utc(receipt["observedAtUtc"], "Receipt observation time changed")
    verified = _utc(receipt["verifiedAtUtc"], "Receipt verification time changed")
    expires = _utc(receipt["expiresAtUtc"], "Receipt expiry changed")
    now = _now(now_utc)
    require(observed <= verified <= now < expires, "Receipt is not active")
    require(receipt["privateInputFileCount"] == 2, "Receipt private input count changed")
    for key in (
        "privatePathEmitted",
        "privateResourceIdentityEmitted",
        "liveCommandExecuted",
        "executionAuthorized",
        "automaticRetryAuthorized",
        "automaticRollbackAuthorized",
        "statePushAuthorized",
        "backendRetirementAuthorized",
    ):
        require(receipt[key] is False, f"Receipt safety boundary changed: {key}")
    return receipt


def validate_approval_request(
    value: dict[str, Any],
    receipt: dict[str, Any],
    *,
    now_utc: datetime | str,
) -> dict[str, Any]:
    approval = _exact_keys(value, APPROVAL_REQUEST_KEYS, "Approval request shape changed")
    require(approval["schemaVersion"] == APPROVAL_REQUEST_SCHEMA, "Approval request schema changed")
    receipt_sha = REQUEST.sha256(receipt)
    require(approval["receiptSha256"] == receipt_sha, "Approval receipt binding changed")
    for key in ("environment", "stateKey", "phase", "attemptNumber", "controlPlaneCommit", "requestedAuthority"):
        require(approval[key] == receipt[key], f"Approval {key} binding changed")
    require(approval["approvalText"] == approval_text(receipt), "Approval statement changed")
    require(approval["approvalTextSha256"] == text_sha256(approval["approvalText"]), "Approval statement digest changed")
    require(approval["humanApproved"] is True and approval["oneAttemptOnly"] is True, "Approval must be explicit and single-attempt")
    for key in ("automaticRetryAuthorized", "automaticRollbackAuthorized", "statePushAuthorized", "backendRetirementAuthorized"):
        require(approval[key] is False, f"Approval expanded forbidden authority: {key}")
    verified = _utc(receipt["verifiedAtUtc"], "Receipt verification time changed")
    receipt_expires = _utc(receipt["expiresAtUtc"], "Receipt expiry changed")
    created = _utc(approval["createdAtUtc"], "Approval creation time changed")
    not_before = _utc(approval["notBeforeUtc"], "Approval not-before time changed")
    expires = _utc(approval["expiresAtUtc"], "Approval expiry changed")
    now = _now(now_utc)
    require(verified <= created <= not_before <= now < expires <= receipt_expires, "Approval is outside the receipt lifetime")
    require((expires - not_before).total_seconds() <= MAX_APPROVAL_WINDOW_SECONDS, "Approval window exceeds fifteen minutes")
    return approval


class PrivateReceiptApprovalStore:
    """Owned 0700 append-only receipt and one-approval-per-receipt store."""

    def __init__(self, root: Path):
        require(isinstance(root, Path) and root.is_absolute(), "Receipt store path must be absolute")
        self.root = root
        root_fd = self._open_directory(root, None, "receipt-store-root")
        try:
            require(set(os.listdir(root_fd)) == ROOT_ENTRIES, "Receipt store root entries changed")
            for name in sorted(ROOT_ENTRIES):
                child_fd = self._open_directory(Path(name), root_fd, f"receipt-store-{name}")
                try:
                    pattern = RECEIPT_NAME if name == "receipts" else APPROVAL_NAME
                    require(all(pattern.fullmatch(item) is not None for item in os.listdir(child_fd)), f"Unexpected {name} entry")
                finally:
                    os.close(child_fd)
        except (OSError, TeardownGateError):
            raise ReceiptApprovalStopped("receipt-store-scope-stopped") from None
        finally:
            os.close(root_fd)

    @staticmethod
    def _open_directory(path: Path, parent_fd: int | None, stage: str) -> int:
        try:
            if parent_fd is None:
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            else:
                descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            metadata = os.fstat(descriptor)
            require(stat.S_ISDIR(metadata.st_mode), "Receipt store component is not a directory")
            require(stat.S_IMODE(metadata.st_mode) == 0o700 and metadata.st_uid == os.geteuid(), "Receipt store component scope changed")
            return descriptor
        except (OSError, TeardownGateError):
            raise ReceiptApprovalStopped(stage) from None

    def _open_child(self, name: str) -> tuple[int, int]:
        root_fd = self._open_directory(self.root, None, "receipt-store-root-open")
        try:
            child_fd = self._open_directory(Path(name), root_fd, f"receipt-store-{name}-open")
        except ReceiptApprovalStopped:
            os.close(root_fd)
            raise
        return root_fd, child_fd

    @staticmethod
    def _write_exclusive(directory_fd: int, name: str, value: dict[str, Any]) -> None:
        raw = REQUEST.canonical_bytes(value)
        file_fd = None
        try:
            file_fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            os.fchmod(file_fd, 0o600)
            body, commit_byte = raw[:-1], raw[-1:]
            offset = 0
            while offset < len(body):
                written = os.write(file_fd, body[offset:])
                if written <= 0:
                    raise OSError("short append-only write")
                offset += written
            if os.write(file_fd, commit_byte) != len(commit_byte):
                raise OSError("short append-only commit write")
            os.fsync(file_fd)
        except OSError:
            raise ReceiptApprovalStopped("append-only-write-stopped") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
        try:
            os.fsync(directory_fd)
        except OSError:
            raise ReceiptApprovalStopped("append-only-directory-fsync-stopped") from None

    @staticmethod
    def _read_file(directory_fd: int, name: str) -> dict[str, Any]:
        file_fd = None
        try:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            require(stat.S_ISREG(before.st_mode), "Stored record is not regular")
            require(stat.S_IMODE(before.st_mode) == 0o600 and before.st_uid == os.geteuid() and before.st_nlink == 1, "Stored record scope changed")
            require(0 < before.st_size <= MAX_PRIVATE_FILE_BYTES, "Stored record size changed")
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            opened = os.fstat(file_fd)
            require((opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink, opened.st_size) == (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink, before.st_size), "Stored record raced during open")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(65536, MAX_PRIVATE_FILE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                require(total <= MAX_PRIVATE_FILE_BYTES, "Stored record grew during read")
            after = os.fstat(file_fd)
            require((after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_nlink, after.st_size) == (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink, before.st_size), "Stored record changed during read")
            return PRIVATE.decode_canonical(b"".join(chunks), "Stored record")
        except (OSError, TeardownGateError):
            raise ReceiptApprovalStopped("stored-record-read-stopped") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)

    def persist_receipt(
        self,
        preflight_result: dict[str, Any],
        *,
        expected_result_sha256: str,
        now_utc: datetime | str,
    ) -> dict[str, Any]:
        _sha(expected_result_sha256, "Expected preflight-result digest changed")
        require(REQUEST.sha256(preflight_result) == expected_result_sha256, "Preflight-result digest changed")
        receipt = validate_receipt_result(preflight_result, now_utc=now_utc)
        receipt_sha = preflight_result["receiptSha256"]
        root_fd, receipts_fd = self._open_child("receipts")
        try:
            self._write_exclusive(receipts_fd, f"{receipt_sha}.receipt.json", receipt)
        finally:
            os.close(receipts_fd)
            os.close(root_fd)
        now = _now(now_utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "schemaVersion": PERSIST_RESULT_SCHEMA,
            "status": "private-preflight-receipt-persisted-awaiting-separate-approval",
            "receiptSha256": receipt_sha,
            "preflightResultSha256": expected_result_sha256,
            "environment": receipt["environment"],
            "phase": receipt["phase"],
            "attemptNumber": receipt["attemptNumber"],
            "persistedAtUtc": now,
            "privatePathEmitted": False,
            "receiptOverwritePerformed": False,
            "approvalRecorded": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "review-persisted-receipt-and-create-separate-phase-approval-request",
        }

    def load_receipt(self, receipt_sha256: str, *, now_utc: datetime | str) -> dict[str, Any]:
        receipt_sha = _sha(receipt_sha256, "Expected receipt digest changed")
        root_fd, receipts_fd = self._open_child("receipts")
        try:
            receipt = self._read_file(receipts_fd, f"{receipt_sha}.receipt.json")
        finally:
            os.close(receipts_fd)
            os.close(root_fd)
        require(REQUEST.sha256(receipt) == receipt_sha, "Persisted receipt digest changed")
        validate_receipt_result({"schemaVersion": PRIVATE.RESULT_SCHEMA, "receipt": receipt, "receiptSha256": receipt_sha}, now_utc=now_utc)
        return receipt

    def record_approval(
        self,
        approval_request: dict[str, Any],
        *,
        expected_approval_request_sha256: str,
        expected_receipt_sha256: str,
        now_utc: datetime | str,
    ) -> dict[str, Any]:
        _sha(expected_approval_request_sha256, "Expected approval-request digest changed")
        require(REQUEST.sha256(approval_request) == expected_approval_request_sha256, "Approval-request digest changed")
        receipt = self.load_receipt(expected_receipt_sha256, now_utc=now_utc)
        approval = validate_approval_request(approval_request, receipt, now_utc=now_utc)
        now = _now(now_utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record = {
            "schemaVersion": APPROVAL_RECORD_SCHEMA,
            "status": "phase-approval-recorded-for-future-single-attempt-executor",
            "receiptSha256": expected_receipt_sha256,
            "approvalRequestSha256": expected_approval_request_sha256,
            "approvalTextSha256": approval["approvalTextSha256"],
            "environment": receipt["environment"],
            "stateKey": receipt["stateKey"],
            "phase": receipt["phase"],
            "attemptNumber": receipt["attemptNumber"],
            "controlPlaneCommit": receipt["controlPlaneCommit"],
            "requestedAuthority": receipt["requestedAuthority"],
            "approvedAtUtc": now,
            "expiresAtUtc": approval["expiresAtUtc"],
            "humanApproved": True,
            "oneAttemptOnly": True,
            "receiptConsumedByApproval": True,
            "approvalConsumedByExecutor": False,
            "privatePathEmitted": False,
            "privateResourceIdentityEmitted": False,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "review-private-approval-record-before-designing-separate-phase-executor",
        }
        root_fd, approvals_fd = self._open_child("approvals")
        try:
            self._write_exclusive(approvals_fd, f"{expected_receipt_sha256}.approval.json", record)
        finally:
            os.close(approvals_fd)
            os.close(root_fd)
        return {
            "schemaVersion": APPROVAL_RESULT_SCHEMA,
            "approvalRecord": record,
            "approvalRecordSha256": REQUEST.sha256(record),
        }


class StrictSinglePrivateFile:
    """Read one canonical owned 0600 file from an otherwise empty 0700 dir."""

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        require(isinstance(path, Path) and path.is_absolute(), "Private input path must be absolute")
        reader = PRIVATE.StrictPrivateBundleReader
        directory_fd = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directory = os.fstat(directory_fd)
            require(stat.S_IMODE(directory.st_mode) == 0o700 and directory.st_uid == os.geteuid(), "Private input directory scope changed")
            require(set(os.listdir(directory_fd)) == {path.name}, "Private input directory entries changed")
            raw = reader._read_file(directory_fd, path.name)
            return PRIVATE.decode_canonical(raw, "Private input")
        except (OSError, TeardownGateError, PRIVATE.PrivatePreflightStopped):
            raise ReceiptApprovalStopped("private-single-file-read-stopped") from None
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

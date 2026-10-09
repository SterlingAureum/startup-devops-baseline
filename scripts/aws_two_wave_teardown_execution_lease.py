#!/usr/bin/env python3
"""Single-use local execution lease with a closed fixed-fake phase driver."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
from typing import Any

import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_receipt_approval as APPROVAL
from aws_two_wave_teardown_core import TeardownGateError, require


VERSION = "v0.12.4.1.5.0.7.1.6.5"
EXECUTION_REQUEST_SCHEMA = f"{VERSION}-shared-dev-test-phase-execution-request-v1"
CLAIM_SCHEMA = f"{VERSION}-shared-dev-test-phase-execution-claim-v1"
OUTCOME_SCHEMA = f"{VERSION}-shared-dev-test-phase-execution-outcome-v1"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-phase-execution-result-v1"
MAX_EXECUTION_WINDOW_SECONDS = 900
EXECUTION_ROOT_ENTRIES = {"claims", "outcomes"}
CLAIM_NAME = re.compile(r"([0-9a-f]{64})\.claim\.json")
OUTCOME_NAME = re.compile(r"([0-9a-f]{64})\.outcome\.json")

APPROVAL_RECORD_KEYS = {
    "schemaVersion",
    "status",
    "receiptSha256",
    "approvalRequestSha256",
    "approvalTextSha256",
    "environment",
    "stateKey",
    "phase",
    "attemptNumber",
    "controlPlaneCommit",
    "requestedAuthority",
    "approvedAtUtc",
    "expiresAtUtc",
    "humanApproved",
    "oneAttemptOnly",
    "receiptConsumedByApproval",
    "approvalConsumedByExecutor",
    "privatePathEmitted",
    "privateResourceIdentityEmitted",
    "automaticRetryAuthorized",
    "automaticRollbackAuthorized",
    "statePushAuthorized",
    "backendRetirementAuthorized",
    "liveCommandExecuted",
    "executionPerformed",
    "nextAction",
}
EXECUTION_REQUEST_KEYS = {
    "schemaVersion",
    "receiptSha256",
    "approvalRecordSha256",
    "environment",
    "stateKey",
    "phase",
    "attemptNumber",
    "controlPlaneCommit",
    "requestedAuthority",
    "executionSpecSha256",
    "createdAtUtc",
    "notBeforeUtc",
    "expiresAtUtc",
    "humanReviewed",
    "oneAttemptOnly",
    "simulationOnly",
    "liveExecutionAuthorized",
    "automaticRetryAuthorized",
    "automaticRollbackAuthorized",
    "statePushAuthorized",
    "backendRetirementAuthorized",
}


class ExecutionLeaseStopped(TeardownGateError):
    """Stable stop with no private path, payload or resource identity."""

    def __init__(
        self,
        stage: str,
        *,
        claim_created: bool = False,
        driver_call_count: int = 0,
        outcome_recorded: bool = False,
    ):
        super().__init__("shared-two-wave-execution-lease-stopped")
        self.report = {
            "schemaVersion": f"{VERSION}-shared-dev-test-phase-execution-stop-v1",
            "status": "shared-two-wave-execution-lease-stopped",
            "stage": stage,
            "claimCreated": claim_created,
            "driverCallCount": driver_call_count,
            "outcomeRecorded": outcome_recorded,
            "preservePrivateStores": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "privatePathEmitted": False,
            "privateResourceIdentityEmitted": False,
        }


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
        return _utc(value, "Execution clock must be whole-second UTC")
    require(isinstance(value, datetime) and value.tzinfo is not None, "Execution clock must be timezone-aware")
    result = value.astimezone(timezone.utc)
    require(result.microsecond == 0, "Execution clock must be whole-second UTC")
    return result


def validate_approval_record(
    value: dict[str, Any],
    *,
    expected_record_sha256: str,
    expected_receipt_sha256: str,
    now_utc: datetime | str,
) -> dict[str, Any]:
    record = _exact_keys(value, APPROVAL_RECORD_KEYS, "Approval record shape changed")
    _sha(expected_record_sha256, "Expected approval-record digest changed")
    _sha(expected_receipt_sha256, "Expected receipt digest changed")
    require(REQUEST.sha256(record) == expected_record_sha256, "Approval-record digest changed")
    require(record["schemaVersion"] == APPROVAL.APPROVAL_RECORD_SCHEMA, "Approval record schema changed")
    require(record["status"] == "phase-approval-recorded-for-future-single-attempt-executor", "Approval record status changed")
    require(record["receiptSha256"] == expected_receipt_sha256, "Approval receipt binding changed")
    for key in ("approvalRequestSha256", "approvalTextSha256"):
        _sha(record[key], f"Approval {key} changed")
    require(record["phase"] in REQUEST.PHASES, "Approval phase changed")
    require(record["requestedAuthority"] == REQUEST.PHASES[record["phase"]]["requestedAuthority"], "Approval authority changed")
    require(isinstance(record["attemptNumber"], int) and not isinstance(record["attemptNumber"], bool) and record["attemptNumber"] > 0, "Approval attempt changed")
    require(isinstance(record["controlPlaneCommit"], str) and REQUEST.COMMIT.fullmatch(record["controlPlaneCommit"]) is not None, "Approval commit changed")
    approved = _utc(record["approvedAtUtc"], "Approval time changed")
    expires = _utc(record["expiresAtUtc"], "Approval expiry changed")
    now = _now(now_utc)
    require(approved <= now < expires, "Approval record is not active")
    require(record["humanApproved"] is True and record["oneAttemptOnly"] is True, "Approval is not explicit and single-attempt")
    require(record["receiptConsumedByApproval"] is True and record["approvalConsumedByExecutor"] is False, "Approval consumption boundary changed")
    for key in (
        "privatePathEmitted",
        "privateResourceIdentityEmitted",
        "automaticRetryAuthorized",
        "automaticRollbackAuthorized",
        "statePushAuthorized",
        "backendRetirementAuthorized",
        "liveCommandExecuted",
        "executionPerformed",
    ):
        require(record[key] is False, f"Approval safety boundary changed: {key}")
    require(record["nextAction"] == "review-private-approval-record-before-designing-separate-phase-executor", "Approval next action changed")
    return record


def validate_execution_request(
    value: dict[str, Any],
    approval_record: dict[str, Any],
    *,
    expected_request_sha256: str,
    now_utc: datetime | str,
) -> dict[str, Any]:
    request = _exact_keys(value, EXECUTION_REQUEST_KEYS, "Execution request shape changed")
    _sha(expected_request_sha256, "Expected execution-request digest changed")
    require(REQUEST.sha256(request) == expected_request_sha256, "Execution-request digest changed")
    require(request["schemaVersion"] == EXECUTION_REQUEST_SCHEMA, "Execution request schema changed")
    require(request["approvalRecordSha256"] == REQUEST.sha256(approval_record), "Execution approval-record binding changed")
    for key in ("receiptSha256", "environment", "stateKey", "phase", "attemptNumber", "controlPlaneCommit", "requestedAuthority"):
        require(request[key] == approval_record[key], f"Execution {key} binding changed")
    _sha(request["executionSpecSha256"], "Execution spec digest changed")
    approved = _utc(approval_record["approvedAtUtc"], "Approval time changed")
    approval_expires = _utc(approval_record["expiresAtUtc"], "Approval expiry changed")
    created = _utc(request["createdAtUtc"], "Execution request creation time changed")
    not_before = _utc(request["notBeforeUtc"], "Execution request not-before time changed")
    expires = _utc(request["expiresAtUtc"], "Execution request expiry changed")
    now = _now(now_utc)
    require(approved <= created <= not_before <= now < expires <= approval_expires, "Execution request is outside approval lifetime")
    require((expires - not_before).total_seconds() <= MAX_EXECUTION_WINDOW_SECONDS, "Execution window exceeds fifteen minutes")
    require(request["humanReviewed"] is True and request["oneAttemptOnly"] is True, "Execution request must be reviewed and single-attempt")
    require(request["simulationOnly"] is True and request["liveExecutionAuthorized"] is False, "Execution request escaped fixed-fake scope")
    for key in ("automaticRetryAuthorized", "automaticRollbackAuthorized", "statePushAuthorized", "backendRetirementAuthorized"):
        require(request[key] is False, f"Execution request expanded forbidden authority: {key}")
    return request


class PrivateExecutionLeaseStore:
    """Owned append-only claim/outcome store; a claim permanently spends approval."""

    def __init__(self, root: Path):
        require(isinstance(root, Path) and root.is_absolute(), "Execution store path must be absolute")
        self.root = root
        root_fd = self._open_directory(root, None, "execution-store-root")
        try:
            require(set(os.listdir(root_fd)) == EXECUTION_ROOT_ENTRIES, "Execution store root entries changed")
            for name in sorted(EXECUTION_ROOT_ENTRIES):
                child_fd = self._open_directory(Path(name), root_fd, f"execution-store-{name}")
                try:
                    pattern = CLAIM_NAME if name == "claims" else OUTCOME_NAME
                    require(all(pattern.fullmatch(item) is not None for item in os.listdir(child_fd)), f"Unexpected {name} entry")
                finally:
                    os.close(child_fd)
        except (OSError, TeardownGateError):
            raise ExecutionLeaseStopped("execution-store-scope") from None
        finally:
            os.close(root_fd)

    @staticmethod
    def _open_directory(path: Path, parent_fd: int | None, stage: str) -> int:
        descriptor = None
        try:
            if parent_fd is None:
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            else:
                descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            metadata = os.fstat(descriptor)
            require(stat.S_ISDIR(metadata.st_mode), "Execution store component is not a directory")
            require(stat.S_IMODE(metadata.st_mode) == 0o700 and metadata.st_uid == os.geteuid(), "Execution store component scope changed")
            return descriptor
        except (OSError, TeardownGateError):
            if descriptor is not None:
                os.close(descriptor)
            raise ExecutionLeaseStopped(stage) from None

    def _open_child(self, name: str) -> tuple[int, int]:
        root_fd = self._open_directory(self.root, None, "execution-store-root-open")
        try:
            child_fd = self._open_directory(Path(name), root_fd, f"execution-store-{name}-open")
        except ExecutionLeaseStopped:
            os.close(root_fd)
            raise
        return root_fd, child_fd

    @staticmethod
    def _write_exclusive(directory_fd: int, name: str, value: dict[str, Any], stage: str) -> None:
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
            raise ExecutionLeaseStopped(stage) from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
        try:
            os.fsync(directory_fd)
        except OSError:
            raise ExecutionLeaseStopped(f"{stage}-directory-fsync") from None

    def claim(self, value: dict[str, Any], *, approval_record_sha256: str) -> str:
        claim_sha = REQUEST.sha256(value)
        root_fd, claims_fd = self._open_child("claims")
        try:
            self._write_exclusive(claims_fd, f"{approval_record_sha256}.claim.json", value, "execution-claim-write")
        finally:
            os.close(claims_fd)
            os.close(root_fd)
        return claim_sha

    def outcome(self, value: dict[str, Any], *, approval_record_sha256: str) -> str:
        outcome_sha = REQUEST.sha256(value)
        root_fd, outcomes_fd = self._open_child("outcomes")
        try:
            self._write_exclusive(outcomes_fd, f"{approval_record_sha256}.outcome.json", value, "execution-outcome-write")
        finally:
            os.close(outcomes_fd)
            os.close(root_fd)
        return outcome_sha


class FixedFakePhaseDriver:
    """Closed deterministic one-call driver with no subprocess or backend."""

    def __init__(self, *, fail: bool = False):
        require(isinstance(fail, bool), "Fixed-fake failure mode changed")
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        require(isinstance(request, dict), "Fixed-fake request changed")
        self.calls.append(request)
        return {
            "status": "fixed-fake-failure" if self.fail else "fixed-fake-success",
            "executionRequestSha256": REQUEST.sha256(request),
            "executionSpecSha256": request["executionSpecSha256"],
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
        }


def load_active_approval(
    approval_store: APPROVAL.PrivateReceiptApprovalStore,
    *,
    expected_receipt_sha256: str,
    expected_approval_record_sha256: str,
    now_utc: datetime | str,
) -> dict[str, Any]:
    receipt = approval_store.load_receipt(expected_receipt_sha256, now_utc=now_utc)
    root_fd, approvals_fd = approval_store._open_child("approvals")
    try:
        record = approval_store._read_file(approvals_fd, f"{expected_receipt_sha256}.approval.json")
    finally:
        os.close(approvals_fd)
        os.close(root_fd)
    validate_approval_record(
        record,
        expected_record_sha256=expected_approval_record_sha256,
        expected_receipt_sha256=expected_receipt_sha256,
        now_utc=now_utc,
    )
    for key in ("environment", "stateKey", "phase", "attemptNumber", "controlPlaneCommit", "requestedAuthority"):
        require(record[key] == receipt[key], f"Approval-to-receipt {key} binding changed")
    return record


def run_once_fixed_fake(
    *,
    approval_store: APPROVAL.PrivateReceiptApprovalStore,
    execution_store: PrivateExecutionLeaseStore,
    execution_request: dict[str, Any],
    expected_execution_request_sha256: str,
    expected_receipt_sha256: str,
    expected_approval_record_sha256: str,
    now_utc: datetime | str,
    completed_at_utc: datetime | str,
    driver: FixedFakePhaseDriver,
) -> dict[str, Any]:
    """Spend one approval before exactly one fixed-fake call; never retry."""

    claim_created = False
    call_count = 0
    outcome_recorded = False
    try:
        require(type(approval_store) is APPROVAL.PrivateReceiptApprovalStore, "Approval store type changed")
        require(type(execution_store) is PrivateExecutionLeaseStore, "Execution store type changed")
        require(type(driver) is FixedFakePhaseDriver, "Only the closed fixed-fake driver is accepted")
        approval_record = load_active_approval(
            approval_store,
            expected_receipt_sha256=expected_receipt_sha256,
            expected_approval_record_sha256=expected_approval_record_sha256,
            now_utc=now_utc,
        )
        request = validate_execution_request(
            execution_request,
            approval_record,
            expected_request_sha256=expected_execution_request_sha256,
            now_utc=now_utc,
        )
        claimed_at = _now(now_utc)
        completed_at = _now(completed_at_utc)
        request_expires = _utc(request["expiresAtUtc"], "Execution request expiry changed")
        require(claimed_at <= completed_at < request_expires, "Completion time is outside execution lifetime")
        claim = {
            "schemaVersion": CLAIM_SCHEMA,
            "status": "approval-consumed-before-fixed-fake-call",
            "receiptSha256": expected_receipt_sha256,
            "approvalRecordSha256": expected_approval_record_sha256,
            "executionRequestSha256": expected_execution_request_sha256,
            "executionSpecSha256": request["executionSpecSha256"],
            "environment": request["environment"],
            "stateKey": request["stateKey"],
            "phase": request["phase"],
            "attemptNumber": request["attemptNumber"],
            "controlPlaneCommit": request["controlPlaneCommit"],
            "requestedAuthority": request["requestedAuthority"],
            "claimedAtUtc": claimed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expiresAtUtc": request["expiresAtUtc"],
            "oneAttemptOnly": True,
            "approvalConsumedByLease": True,
            "automaticRetryAuthorized": False,
            "automaticRollbackAuthorized": False,
            "statePushAuthorized": False,
            "backendRetirementAuthorized": False,
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
        }
        claim_sha = execution_store.claim(claim, approval_record_sha256=expected_approval_record_sha256)
        claim_created = True
        response = driver.call(request)
        call_count = len(driver.calls)
        require(call_count == 1, "Fixed-fake driver call count changed")
        response_sha = REQUEST.sha256(response)
        success = response == {
            "status": "fixed-fake-success",
            "executionRequestSha256": expected_execution_request_sha256,
            "executionSpecSha256": request["executionSpecSha256"],
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
        }
        outcome = {
            "schemaVersion": OUTCOME_SCHEMA,
            "status": "fixed-fake-phase-succeeded" if success else "fixed-fake-phase-failed",
            "receiptSha256": expected_receipt_sha256,
            "approvalRecordSha256": expected_approval_record_sha256,
            "executionRequestSha256": expected_execution_request_sha256,
            "executionSpecSha256": request["executionSpecSha256"],
            "claimSha256": claim_sha,
            "driverResponseSha256": response_sha,
            "environment": request["environment"],
            "phase": request["phase"],
            "attemptNumber": request["attemptNumber"],
            "completedAtUtc": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "driverCallCount": 1,
            "terminalSuccess": success,
            "approvalConsumedByLease": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
        }
        try:
            outcome_sha = execution_store.outcome(outcome, approval_record_sha256=expected_approval_record_sha256)
        except ExecutionLeaseStopped:
            raise ExecutionLeaseStopped(
                "execution-outcome-write-uncertain",
                claim_created=True,
                driver_call_count=1,
                outcome_recorded=False,
            ) from None
        outcome_recorded = True
        if not success:
            raise ExecutionLeaseStopped(
                "fixed-fake-phase-failed",
                claim_created=True,
                driver_call_count=1,
                outcome_recorded=True,
            )
        return {
            "schemaVersion": RESULT_SCHEMA,
            "status": "single-use-fixed-fake-phase-exercise-completed",
            "receiptSha256": expected_receipt_sha256,
            "approvalRecordSha256": expected_approval_record_sha256,
            "executionRequestSha256": expected_execution_request_sha256,
            "claimSha256": claim_sha,
            "outcomeSha256": outcome_sha,
            "environment": request["environment"],
            "phase": request["phase"],
            "attemptNumber": request["attemptNumber"],
            "approvalConsumedByLease": True,
            "driverCallCount": 1,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "design-separate-live-phase-driver-bound-to-this-single-use-lease",
        }
    except ExecutionLeaseStopped:
        raise
    except (APPROVAL.ReceiptApprovalStopped, OSError, KeyError, TypeError, ValueError, TeardownGateError):
        raise ExecutionLeaseStopped(
            "single-use-fixed-fake-phase-stopped",
            claim_created=claim_created,
            driver_call_count=call_count,
            outcome_recorded=outcome_recorded,
        ) from None

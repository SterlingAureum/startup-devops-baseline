#!/usr/bin/env python3
"""Durable single-use lease composition for the closed registry runner."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aws_two_wave_teardown_command_registry as REGISTRY
import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_receipt_approval as APPROVAL
import aws_two_wave_teardown_registry_runner as RUNNER
from aws_two_wave_teardown_core import TeardownGateError, require


VERSION = "v0.12.4.1.5.0.7.1.6.9"
OUTCOME_SCHEMA = f"{VERSION}-shared-dev-test-lease-registry-outcome-v1"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-lease-registry-result-v1"
STOP_SCHEMA = f"{VERSION}-shared-dev-test-lease-registry-stop-v1"


class LeaseRegistryCompositionStopped(TeardownGateError):
    """Redacted terminal stop after zero or one durable lease attempt."""

    def __init__(
        self,
        stage: str,
        *,
        phase: str | None = None,
        claim_created: bool = False,
        backend_call_count: int = 0,
        outcome_recorded: bool = False,
        failed_operation_id: str | None = None,
    ):
        super().__init__("shared-two-wave-lease-registry-composition-stopped")
        self.report = {
            "schemaVersion": STOP_SCHEMA,
            "status": "shared-two-wave-lease-registry-composition-stopped",
            "stage": stage,
            "phase": phase,
            "claimCreated": claim_created,
            "backendCallCount": backend_call_count,
            "outcomeRecorded": outcome_recorded,
            "failedOperationId": failed_operation_id,
            "approvalConsumedByLease": claim_created,
            "preservePrivateStores": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "automaticRollbackPerformed": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "privatePathEmitted": False,
            "privateResourceIdentityEmitted": False,
        }


def _phase_claim(
    *,
    request: dict[str, Any],
    receipt_sha256: str,
    approval_record_sha256: str,
    execution_request_sha256: str,
    claimed_at: datetime,
) -> dict[str, Any]:
    spec = DRIVERS.phase_driver_spec(request["environment"], request["phase"])
    spec_sha = REQUEST.sha256(spec)
    require(request["executionSpecSha256"] == spec_sha, "Execution request does not bind the reviewed phase driver spec")
    return {
        "schemaVersion": DRIVERS.CLAIM_SCHEMA,
        "status": "approval-consumed-before-fixed-fake-phase-dispatch",
        "receiptSha256": receipt_sha256,
        "approvalRecordSha256": approval_record_sha256,
        "executionRequestSha256": execution_request_sha256,
        "executionSpecSha256": spec_sha,
        "environment": request["environment"],
        "stateKey": request["stateKey"],
        "phase": request["phase"],
        "attemptNumber": request["attemptNumber"],
        "controlPlaneCommit": request["controlPlaneCommit"],
        "requestedAuthority": request["requestedAuthority"],
        "operationSetSha256": REQUEST.sha256(spec["operationIds"]),
        "operationCount": len(spec["operationIds"]),
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


def _outcome(
    *,
    claim: dict[str, Any],
    claim_sha256: str,
    completed_at: datetime,
    runner_evidence: dict[str, Any],
    terminal_success: bool,
    backend_call_count: int,
    failed_operation_id: str | None,
) -> dict[str, Any]:
    return {
        "schemaVersion": OUTCOME_SCHEMA,
        "status": "claimed-registry-composition-succeeded" if terminal_success else "claimed-registry-composition-failed",
        "receiptSha256": claim["receiptSha256"],
        "approvalRecordSha256": claim["approvalRecordSha256"],
        "executionRequestSha256": claim["executionRequestSha256"],
        "executionSpecSha256": claim["executionSpecSha256"],
        "claimSha256": claim_sha256,
        "runnerEvidenceSha256": REQUEST.sha256(runner_evidence),
        "runnerTerminalStatus": runner_evidence["status"],
        "environment": claim["environment"],
        "phase": claim["phase"],
        "attemptNumber": claim["attemptNumber"],
        "completedAtUtc": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "backendCallCount": backend_call_count,
        "failedOperationId": failed_operation_id,
        "terminalSuccess": terminal_success,
        "approvalConsumedByLease": True,
        "automaticRetryPerformed": False,
        "automaticRepairPerformed": False,
        "automaticRollbackPerformed": False,
        "simulationOnly": True,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }


def run_lease_owned_registry_once(
    *,
    approval_store: APPROVAL.PrivateReceiptApprovalStore,
    execution_store: LEASE.PrivateExecutionLeaseStore,
    execution_request: dict[str, Any],
    expected_execution_request_sha256: str,
    expected_receipt_sha256: str,
    expected_approval_record_sha256: str,
    private_bindings: dict[str, Any],
    now_utc: datetime | str,
    completed_at_utc: datetime | str,
    backend: RUNNER.FixedFakeRegistryBackend,
) -> dict[str, Any]:
    """Consume one durable lease, dispatch the registry once, and record outcome."""

    phase: str | None = None
    claim_created = False
    call_count = 0
    outcome_recorded = False
    failed_operation_id: str | None = None
    try:
        require(type(approval_store) is APPROVAL.PrivateReceiptApprovalStore, "Approval store type changed")
        require(type(execution_store) is LEASE.PrivateExecutionLeaseStore, "Execution store type changed")
        require(type(backend) is RUNNER.FixedFakeRegistryBackend, "Only the exact fixed-fake registry backend is accepted")
        require(backend.used is False and backend.calls == [], "Fixed-fake registry backend instance was already used")
        approval_record = LEASE.load_active_approval(
            approval_store,
            expected_receipt_sha256=expected_receipt_sha256,
            expected_approval_record_sha256=expected_approval_record_sha256,
            now_utc=now_utc,
        )
        request = LEASE.validate_execution_request(
            execution_request,
            approval_record,
            expected_request_sha256=expected_execution_request_sha256,
            now_utc=now_utc,
        )
        phase = request["phase"]
        claimed_at = LEASE._now(now_utc)
        completed_at = LEASE._now(completed_at_utc)
        request_expires = LEASE._utc(request["expiresAtUtc"], "Execution request expiry changed")
        require(claimed_at <= completed_at < request_expires, "Completion time is outside execution lifetime")
        claim = _phase_claim(
            request=request,
            receipt_sha256=expected_receipt_sha256,
            approval_record_sha256=expected_approval_record_sha256,
            execution_request_sha256=expected_execution_request_sha256,
            claimed_at=claimed_at,
        )
        claim_sha = REQUEST.sha256(claim)

        # Validate all caller-controlled dispatch inputs before consuming the lease.
        RUNNER.validate_durable_phase_claim(claim, expected_claim_sha256=claim_sha, now_utc=now_utc)
        RUNNER.validate_phase_private_bindings(claim, private_bindings)
        manifest = REGISTRY.phase_command_manifest(request["environment"], phase)
        operation_requests = RUNNER.build_claimed_operation_requests(
            claim,
            expected_claim_sha256=claim_sha,
            now_utc=now_utc,
        )

        persisted_claim_sha = execution_store.claim(
            claim,
            approval_record_sha256=expected_approval_record_sha256,
        )
        require(persisted_claim_sha == claim_sha, "Persisted phase claim digest changed")
        claim_created = True
        try:
            runner_result = RUNNER.run_claimed_registry_once(
                claim=claim,
                expected_claim_sha256=claim_sha,
                phase_command_manifest=manifest,
                operation_requests=operation_requests,
                private_bindings=private_bindings,
                now_utc=now_utc,
                backend=backend,
            )
            call_count = len(backend.calls)
        except RUNNER.RegistryRunnerStopped as stopped:
            call_count = len(backend.calls)
            failed_operation_id = stopped.report["failedOperationId"]
            outcome = _outcome(
                claim=claim,
                claim_sha256=claim_sha,
                completed_at=completed_at,
                runner_evidence=stopped.report,
                terminal_success=False,
                backend_call_count=call_count,
                failed_operation_id=failed_operation_id,
            )
            try:
                execution_store.outcome(outcome, approval_record_sha256=expected_approval_record_sha256)
                outcome_recorded = True
            except LEASE.ExecutionLeaseStopped:
                raise LeaseRegistryCompositionStopped(
                    "lease-registry-failure-outcome-write-uncertain",
                    phase=phase,
                    claim_created=True,
                    backend_call_count=call_count,
                    outcome_recorded=False,
                    failed_operation_id=failed_operation_id,
                ) from None
            raise LeaseRegistryCompositionStopped(
                "claimed-registry-runner-failed",
                phase=phase,
                claim_created=True,
                backend_call_count=call_count,
                outcome_recorded=True,
                failed_operation_id=failed_operation_id,
            ) from None

        outcome = _outcome(
            claim=claim,
            claim_sha256=claim_sha,
            completed_at=completed_at,
            runner_evidence=runner_result,
            terminal_success=True,
            backend_call_count=call_count,
            failed_operation_id=None,
        )
        try:
            outcome_sha = execution_store.outcome(outcome, approval_record_sha256=expected_approval_record_sha256)
        except LEASE.ExecutionLeaseStopped:
            raise LeaseRegistryCompositionStopped(
                "lease-registry-success-outcome-write-uncertain",
                phase=phase,
                claim_created=True,
                backend_call_count=call_count,
                outcome_recorded=False,
            ) from None
        outcome_recorded = True
        return {
            "schemaVersion": RESULT_SCHEMA,
            "status": "single-use-lease-owned-registry-runner-completed",
            "receiptSha256": expected_receipt_sha256,
            "approvalRecordSha256": expected_approval_record_sha256,
            "executionRequestSha256": expected_execution_request_sha256,
            "executionSpecSha256": claim["executionSpecSha256"],
            "claimSha256": claim_sha,
            "runnerResultSha256": REQUEST.sha256(runner_result),
            "operationManifestSha256": runner_result["operationManifestSha256"],
            "outcomeSha256": outcome_sha,
            "environment": request["environment"],
            "phase": phase,
            "attemptNumber": request["attemptNumber"],
            "backendCallCount": call_count,
            "approvalConsumedByLease": True,
            "outcomeRecorded": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "automaticRollbackPerformed": False,
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "add-a-strict-local-command-boundary-around-this-lease-owned-fixed-fake-composition",
        }
    except LeaseRegistryCompositionStopped:
        raise
    except (LEASE.ExecutionLeaseStopped, APPROVAL.ReceiptApprovalStopped, OSError, KeyError, TypeError, ValueError, TeardownGateError):
        raise LeaseRegistryCompositionStopped(
            "lease-owned-registry-composition-stopped",
            phase=phase,
            claim_created=claim_created,
            backend_call_count=call_count,
            outcome_recorded=outcome_recorded,
            failed_operation_id=failed_operation_id,
        ) from None

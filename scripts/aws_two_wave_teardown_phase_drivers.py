#!/usr/bin/env python3
"""Closed shared dev/test phase-driver specs and fixed-fake dispatch."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_receipt_approval as APPROVAL
from aws_two_wave_teardown_core import TeardownGateError, environment_profile, require


VERSION = "v0.12.4.1.5.0.7.1.6.6"
SPEC_SCHEMA = f"{VERSION}-shared-dev-test-phase-driver-spec-v1"
OPERATION_REQUEST_SCHEMA = f"{VERSION}-shared-dev-test-phase-operation-request-v1"
OPERATION_RESPONSE_SCHEMA = f"{VERSION}-shared-dev-test-phase-operation-response-v1"
CLAIM_SCHEMA = f"{VERSION}-shared-dev-test-phase-driver-claim-v1"
OUTCOME_SCHEMA = f"{VERSION}-shared-dev-test-phase-driver-outcome-v1"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-phase-driver-result-v1"

PHASE_OPERATIONS = {
    "controller-cleanup": (
        "verify-environment-context",
        "observe-controller-owned-inventory",
        "suspend-gitops-reconciliation",
        "delete-controller-owned-kubernetes-resources",
        "verify-controller-owned-absence",
    ),
    "wave-one-plan": (
        "verify-environment-context",
        "snapshot-managed-state",
        "snapshot-state-lock-history",
        "verify-source-manifest",
        "select-exact-non-network-destroy-scope",
        "create-saved-wave-one-plan",
        "render-and-gate-wave-one-plan",
    ),
    "wave-one-apply": (
        "verify-environment-context",
        "verify-reviewed-wave-one-plan-digests",
        "snapshot-pre-apply-state-lock-history",
        "apply-exact-wave-one-saved-plan",
        "snapshot-post-apply-managed-state",
        "verify-exact-network-only-state",
        "verify-wave-one-apply-history-delta",
    ),
    "post-wave-one-inventory": (
        "verify-environment-context",
        "verify-eks-absence",
        "snapshot-network-only-managed-state",
        "inventory-all-vpc-dependency-families",
        "classify-controller-unknown-and-safe-residue",
        "verify-protected-foundation-preserved",
    ),
    "safe-residue-delete": (
        "verify-environment-context",
        "verify-exact-allowlisted-residue-binding",
        "delete-exact-reviewed-safe-residue",
        "verify-exact-residue-absence",
    ),
    "wave-two-plan": (
        "verify-environment-context",
        "snapshot-network-only-managed-state",
        "snapshot-state-lock-history",
        "verify-zero-vpc-dependencies",
        "select-exact-network-destroy-scope",
        "create-saved-wave-two-plan",
        "render-and-gate-wave-two-plan",
    ),
    "wave-two-apply": (
        "verify-environment-context",
        "verify-reviewed-wave-two-plan-digests",
        "snapshot-pre-apply-state-lock-history",
        "apply-exact-wave-two-saved-plan",
        "snapshot-final-managed-state",
        "verify-empty-managed-state",
        "verify-wave-two-apply-history-delta",
    ),
    "final-read-only-audit": (
        "verify-environment-context",
        "verify-empty-managed-state",
        "verify-environment-resource-absence",
        "verify-final-state-lock-history",
        "verify-protected-foundation-preserved",
        "classify-residual-cost-inventory",
    ),
}

PHASE_EFFECTS = {
    "controller-cleanup": "kubernetes-controller-mutation",
    "wave-one-plan": "terraform-saved-plan",
    "wave-one-apply": "terraform-exact-plan-apply",
    "post-wave-one-inventory": "multi-system-read-only",
    "safe-residue-delete": "aws-exact-residue-delete",
    "wave-two-plan": "terraform-saved-plan",
    "wave-two-apply": "terraform-exact-plan-apply",
    "final-read-only-audit": "multi-system-read-only",
}

COMMON_PRIVATE_BINDINGS = (
    "receiptSha256",
    "approvalRecordSha256",
    "executionRequestSha256",
    "stateInventorySha256",
)
PHASE_PRIVATE_BINDINGS = {
    "controller-cleanup": ("controllerInventorySha256",),
    "wave-one-plan": ("stateSnapshotSha256", "historySnapshotSha256", "sourceManifestSha256"),
    "wave-one-apply": ("binaryPlanSha256", "planRecordSha256", "planTextSha256", "planJsonSha256"),
    "post-wave-one-inventory": ("stateSnapshotSha256", "historySnapshotSha256", "dependencyInventorySha256"),
    "safe-residue-delete": ("dependencyInventorySha256", "residueIdentitySha256"),
    "wave-two-plan": ("stateSnapshotSha256", "historySnapshotSha256", "dependencyInventorySha256"),
    "wave-two-apply": ("binaryPlanSha256", "planRecordSha256", "planTextSha256", "planJsonSha256"),
    "final-read-only-audit": ("finalStateSha256", "absenceInventorySha256", "historySnapshotSha256"),
}


class PhaseDriverStopped(TeardownGateError):
    """Redacted terminal stop after zero or one consumed phase attempt."""

    def __init__(
        self,
        stage: str,
        *,
        phase: str | None = None,
        claim_created: bool = False,
        operation_call_count: int = 0,
        outcome_recorded: bool = False,
    ):
        super().__init__("shared-two-wave-phase-driver-stopped")
        self.report = {
            "schemaVersion": f"{VERSION}-shared-dev-test-phase-driver-stop-v1",
            "status": "shared-two-wave-phase-driver-stopped",
            "stage": stage,
            "phase": phase,
            "claimCreated": claim_created,
            "operationCallCount": operation_call_count,
            "outcomeRecorded": outcome_recorded,
            "preservePrivateStores": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "privatePathEmitted": False,
            "privateResourceIdentityEmitted": False,
        }


def phase_driver_spec(environment: str, phase: str) -> dict[str, Any]:
    profile = environment_profile(environment)
    require(phase in REQUEST.PHASES and phase in PHASE_OPERATIONS, "Phase driver is not closed and reviewed")
    short_name = profile["shortName"]
    return {
        "schemaVersion": SPEC_SCHEMA,
        "version": VERSION,
        "environment": environment,
        "stateKey": profile["stateKey"],
        "phase": phase,
        "requestedAuthority": REQUEST.PHASES[phase]["requestedAuthority"],
        "effectClass": PHASE_EFFECTS[phase],
        "terraformRootRelativePath": f"infra/terraform/aws/environments/{short_name}",
        "backendConfigRelativePath": f"infra/terraform/aws/backend-config/{short_name}.s3.tfbackend.example",
        "operationIds": list(PHASE_OPERATIONS[phase]),
        "requiredPrivateBindings": list(COMMON_PRIVATE_BINDINGS + PHASE_PRIVATE_BINDINGS[phase]),
        "oneOperationCallPerId": True,
        "orderedDispatchRequired": True,
        "rawCommandAllowed": False,
        "dynamicCommandTemplateAllowed": False,
        "credentialOrEndpointOverrideAllowed": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "simulationOnly": True,
        "liveBackendAvailable": False,
    }


def execution_spec_sha256(environment: str, phase: str) -> str:
    return REQUEST.sha256(phase_driver_spec(environment, phase))


def validate_phase_driver_spec(value: dict[str, Any], *, environment: str, phase: str) -> dict[str, Any]:
    expected = phase_driver_spec(environment, phase)
    require(value == expected, "Phase driver spec changed")
    return value


class FixedFakePhaseTransport:
    """Closed deterministic transport; never constructs or runs a command."""

    def __init__(self, *, fail_at: str = ""):
        require(isinstance(fail_at, str), "Fixed-fake phase failure selector changed")
        require(not fail_at or any(fail_at in values for values in PHASE_OPERATIONS.values()), "Fixed-fake failure operation is unknown")
        self.fail_at = fail_at
        self.calls: list[dict[str, Any]] = []

    def call(self, operation_request: dict[str, Any]) -> dict[str, Any]:
        require(isinstance(operation_request, dict), "Operation request changed")
        self.calls.append(operation_request)
        failed = operation_request["operationId"] == self.fail_at
        return {
            "schemaVersion": OPERATION_RESPONSE_SCHEMA,
            "status": "fixed-fake-operation-failed" if failed else "fixed-fake-operation-succeeded",
            "environment": operation_request["environment"],
            "phase": operation_request["phase"],
            "operationId": operation_request["operationId"],
            "operationIndex": operation_request["operationIndex"],
            "operationRequestSha256": REQUEST.sha256(operation_request),
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
        }


def _operation_request(
    *,
    spec: dict[str, Any],
    spec_sha256: str,
    execution_request_sha256: str,
    operation_id: str,
    operation_index: int,
) -> dict[str, Any]:
    return {
        "schemaVersion": OPERATION_REQUEST_SCHEMA,
        "environment": spec["environment"],
        "stateKey": spec["stateKey"],
        "phase": spec["phase"],
        "requestedAuthority": spec["requestedAuthority"],
        "executionSpecSha256": spec_sha256,
        "executionRequestSha256": execution_request_sha256,
        "operationId": operation_id,
        "operationIndex": operation_index,
        "operationCount": len(spec["operationIds"]),
        "simulationOnly": True,
        "liveCommandAuthorized": False,
    }


def _response_matches(response: dict[str, Any], request: dict[str, Any], *, success: bool) -> bool:
    return response == {
        "schemaVersion": OPERATION_RESPONSE_SCHEMA,
        "status": "fixed-fake-operation-succeeded" if success else "fixed-fake-operation-failed",
        "environment": request["environment"],
        "phase": request["phase"],
        "operationId": request["operationId"],
        "operationIndex": request["operationIndex"],
        "operationRequestSha256": REQUEST.sha256(request),
        "simulationOnly": True,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }


def _write_outcome(
    *,
    store: LEASE.PrivateExecutionLeaseStore,
    approval_record_sha256: str,
    receipt_sha256: str,
    execution_request_sha256: str,
    spec_sha256: str,
    claim_sha256: str,
    environment: str,
    phase: str,
    attempt_number: int,
    completed_at: datetime,
    operation_manifest: list[dict[str, Any]],
    terminal_success: bool,
    failed_operation_id: str | None,
) -> str:
    outcome = {
        "schemaVersion": OUTCOME_SCHEMA,
        "status": "fixed-fake-phase-driver-succeeded" if terminal_success else "fixed-fake-phase-driver-failed",
        "receiptSha256": receipt_sha256,
        "approvalRecordSha256": approval_record_sha256,
        "executionRequestSha256": execution_request_sha256,
        "executionSpecSha256": spec_sha256,
        "claimSha256": claim_sha256,
        "operationManifestSha256": REQUEST.sha256(operation_manifest),
        "environment": environment,
        "phase": phase,
        "attemptNumber": attempt_number,
        "completedAtUtc": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "operationCallCount": len(operation_manifest),
        "failedOperationId": failed_operation_id,
        "terminalSuccess": terminal_success,
        "approvalConsumedByLease": True,
        "automaticRetryPerformed": False,
        "automaticRepairPerformed": False,
        "simulationOnly": True,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }
    return store.outcome(outcome, approval_record_sha256=approval_record_sha256)


def run_reviewed_phase_spec_once(
    *,
    approval_store: APPROVAL.PrivateReceiptApprovalStore,
    execution_store: LEASE.PrivateExecutionLeaseStore,
    execution_request: dict[str, Any],
    expected_execution_request_sha256: str,
    expected_receipt_sha256: str,
    expected_approval_record_sha256: str,
    now_utc: datetime | str,
    completed_at_utc: datetime | str,
    transport: FixedFakePhaseTransport,
) -> dict[str, Any]:
    """Consume approval, then dispatch the exact ordered phase spec once."""

    phase: str | None = None
    claim_created = False
    call_count = 0
    outcome_recorded = False
    try:
        require(type(approval_store) is APPROVAL.PrivateReceiptApprovalStore, "Approval store type changed")
        require(type(execution_store) is LEASE.PrivateExecutionLeaseStore, "Execution store type changed")
        require(type(transport) is FixedFakePhaseTransport, "Only the closed fixed-fake phase transport is accepted")
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
        spec = phase_driver_spec(request["environment"], phase)
        spec_sha = REQUEST.sha256(spec)
        require(request["executionSpecSha256"] == spec_sha, "Execution request does not bind the reviewed phase driver spec")
        claimed_at = LEASE._now(now_utc)
        completed_at = LEASE._now(completed_at_utc)
        request_expires = LEASE._utc(request["expiresAtUtc"], "Execution request expiry changed")
        require(claimed_at <= completed_at < request_expires, "Completion time is outside execution lifetime")
        claim = {
            "schemaVersion": CLAIM_SCHEMA,
            "status": "approval-consumed-before-fixed-fake-phase-dispatch",
            "receiptSha256": expected_receipt_sha256,
            "approvalRecordSha256": expected_approval_record_sha256,
            "executionRequestSha256": expected_execution_request_sha256,
            "executionSpecSha256": spec_sha,
            "environment": request["environment"],
            "stateKey": request["stateKey"],
            "phase": phase,
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
        claim_sha = execution_store.claim(claim, approval_record_sha256=expected_approval_record_sha256)
        claim_created = True
        operation_manifest: list[dict[str, Any]] = []
        for index, operation_id in enumerate(spec["operationIds"]):
            operation_request = _operation_request(
                spec=spec,
                spec_sha256=spec_sha,
                execution_request_sha256=expected_execution_request_sha256,
                operation_id=operation_id,
                operation_index=index,
            )
            response = transport.call(operation_request)
            call_count = len(transport.calls)
            succeeded = _response_matches(response, operation_request, success=True)
            failed = _response_matches(response, operation_request, success=False)
            require(succeeded or failed, "Fixed-fake operation response changed")
            operation_manifest.append({
                "operationId": operation_id,
                "operationIndex": index,
                "requestSha256": REQUEST.sha256(operation_request),
                "responseSha256": REQUEST.sha256(response),
                "succeeded": succeeded,
            })
            if failed:
                try:
                    _write_outcome(
                        store=execution_store,
                        approval_record_sha256=expected_approval_record_sha256,
                        receipt_sha256=expected_receipt_sha256,
                        execution_request_sha256=expected_execution_request_sha256,
                        spec_sha256=spec_sha,
                        claim_sha256=claim_sha,
                        environment=request["environment"],
                        phase=phase,
                        attempt_number=request["attemptNumber"],
                        completed_at=completed_at,
                        operation_manifest=operation_manifest,
                        terminal_success=False,
                        failed_operation_id=operation_id,
                    )
                    outcome_recorded = True
                except LEASE.ExecutionLeaseStopped:
                    raise PhaseDriverStopped(
                        "phase-driver-failure-outcome-write-uncertain",
                        phase=phase,
                        claim_created=True,
                        operation_call_count=call_count,
                        outcome_recorded=False,
                    ) from None
                raise PhaseDriverStopped(
                    "fixed-fake-phase-operation-failed",
                    phase=phase,
                    claim_created=True,
                    operation_call_count=call_count,
                    outcome_recorded=True,
                )
        require(call_count == len(spec["operationIds"]), "Phase operation call count changed")
        try:
            outcome_sha = _write_outcome(
                store=execution_store,
                approval_record_sha256=expected_approval_record_sha256,
                receipt_sha256=expected_receipt_sha256,
                execution_request_sha256=expected_execution_request_sha256,
                spec_sha256=spec_sha,
                claim_sha256=claim_sha,
                environment=request["environment"],
                phase=phase,
                attempt_number=request["attemptNumber"],
                completed_at=completed_at,
                operation_manifest=operation_manifest,
                terminal_success=True,
                failed_operation_id=None,
            )
        except LEASE.ExecutionLeaseStopped:
            raise PhaseDriverStopped(
                "phase-driver-success-outcome-write-uncertain",
                phase=phase,
                claim_created=True,
                operation_call_count=call_count,
                outcome_recorded=False,
            ) from None
        outcome_recorded = True
        return {
            "schemaVersion": RESULT_SCHEMA,
            "status": "reviewed-fixed-fake-phase-driver-completed",
            "receiptSha256": expected_receipt_sha256,
            "approvalRecordSha256": expected_approval_record_sha256,
            "executionRequestSha256": expected_execution_request_sha256,
            "executionSpecSha256": spec_sha,
            "claimSha256": claim_sha,
            "outcomeSha256": outcome_sha,
            "operationManifestSha256": REQUEST.sha256(operation_manifest),
            "environment": request["environment"],
            "phase": phase,
            "attemptNumber": request["attemptNumber"],
            "operationCallCount": call_count,
            "approvalConsumedByLease": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "implement-separate-live-adapter-for-the-reviewed-operation-ids",
        }
    except PhaseDriverStopped:
        raise
    except (LEASE.ExecutionLeaseStopped, APPROVAL.ReceiptApprovalStopped, OSError, KeyError, TypeError, ValueError, TeardownGateError):
        raise PhaseDriverStopped(
            "reviewed-fixed-fake-phase-driver-stopped",
            phase=phase,
            claim_created=claim_created,
            operation_call_count=call_count,
            outcome_recorded=outcome_recorded,
        ) from None

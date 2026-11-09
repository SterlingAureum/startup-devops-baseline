#!/usr/bin/env python3
"""Fresh-process offline exercise for every shared dev/test teardown phase."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import aws_two_wave_teardown_execution_lease as LEASE
import aws_two_wave_teardown_lease_registry_composition as COMPOSITION
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
import aws_two_wave_teardown_private_preflight as PRIVATE
import aws_two_wave_teardown_receipt_approval as APPROVAL
from aws_two_wave_teardown_core import TeardownGateError, environment_profile, require


VERSION = "v0.12.4.1.5.0.7.1.6.11"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-offline-process-chain-result-v1"
STOP_SCHEMA = f"{VERSION}-shared-dev-test-offline-process-chain-stop-v1"
ENVIRONMENTS = ("aws-dev", "aws-test")
PROCESS_TIMEOUT_SECONDS = 30
COMMAND_FILENAME = (
    "exercise-v0.12.4.1.5.0.7.1.6.10-"
    "shared-dev-test-lease-registry-command.py"
)
CONFIRMATION = "consume-one-reviewed-approval-through-lease-owned-registry-fixed-fake"


class OfflineProcessChainStopped(TeardownGateError):
    """Redacted terminal stop for the disposable synthetic process chain."""

    def __init__(
        self,
        stage: str,
        *,
        environment: str | None = None,
        phase: str | None = None,
        completed_phase_count: int = 0,
        subprocess_call_count: int = 0,
    ):
        super().__init__("shared-two-wave-offline-process-chain-stopped")
        self.report = {
            "schemaVersion": STOP_SCHEMA,
            "status": "shared-two-wave-offline-process-chain-stopped",
            "stage": stage,
            "environment": environment,
            "phase": phase,
            "completedPhaseCount": completed_phase_count,
            "subprocessCallCount": subprocess_call_count,
            "syntheticOnly": True,
            "temporaryPrivateStoresRemoved": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "automaticRollbackPerformed": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "privatePathEmitted": False,
            "privateResourceIdentityEmitted": False,
        }


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _owned_directory(path: Path) -> Path:
    path.mkdir()
    path.chmod(0o700)
    return path


def _write_private(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(REQUEST.canonical_bytes(value))
    path.chmod(0o600)


def _synthetic_receipt(
    *,
    environment: str,
    phase: str,
    attempt_number: int,
    predecessor_receipt_sha256: str | None,
    base_time: datetime,
) -> dict[str, Any]:
    profile = environment_profile(environment)
    phase_policy = REQUEST.PHASES[phase]
    state_inventory_sha = REQUEST.sha256({"environment": environment, "phase": phase, "kind": "synthetic-state"})
    return {
        "schemaVersion": PRIVATE.RECEIPT_SCHEMA,
        "status": "shared-two-wave-private-preflight-ready-for-separate-approval",
        "environment": environment,
        "stateKey": profile["stateKey"],
        "phase": phase,
        "attemptNumber": attempt_number,
        "controlPlaneCommit": "1" * 40,
        "requestSha256": REQUEST.sha256({"environment": environment, "phase": phase, "kind": "synthetic-request"}),
        "evidenceSha256": REQUEST.sha256({"environment": environment, "phase": phase, "kind": "synthetic-evidence"}),
        "predecessorReceiptSha256": predecessor_receipt_sha256,
        "stateInventorySha256": state_inventory_sha,
        "requestedAuthority": phase_policy["requestedAuthority"],
        "observedAtUtc": _utc(base_time - timedelta(seconds=10)),
        "verifiedAtUtc": _utc(base_time),
        "expiresAtUtc": _utc(base_time + timedelta(minutes=15)),
        "privateInputFileCount": 2,
        "privatePathEmitted": False,
        "privateResourceIdentityEmitted": False,
        "liveCommandExecuted": False,
        "executionAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "nextAction": phase_policy["nextAction"],
    }


def _prepare_phase(
    *,
    root: Path,
    environment: str,
    phase: str,
    attempt_number: int,
    predecessor_receipt_sha256: str | None,
    base_time: datetime,
) -> dict[str, Any]:
    approval_root = _owned_directory(root / "approval-store")
    _owned_directory(approval_root / "receipts")
    _owned_directory(approval_root / "approvals")
    execution_root = _owned_directory(root / "execution-store")
    _owned_directory(execution_root / "claims")
    _owned_directory(execution_root / "outcomes")
    request_root = _owned_directory(root / "execution-request")
    bindings_root = _owned_directory(root / "private-bindings")

    approval_store = APPROVAL.PrivateReceiptApprovalStore(approval_root)
    receipt = _synthetic_receipt(
        environment=environment,
        phase=phase,
        attempt_number=attempt_number,
        predecessor_receipt_sha256=predecessor_receipt_sha256,
        base_time=base_time,
    )
    if REQUEST.PHASES[phase]["predecessorRequired"]:
        require(predecessor_receipt_sha256 is not None, "Synthetic predecessor receipt is missing")
    else:
        require(predecessor_receipt_sha256 is None, "First synthetic phase inherited a predecessor")
    receipt_sha = REQUEST.sha256(receipt)
    preflight_result = {
        "schemaVersion": PRIVATE.RESULT_SCHEMA,
        "receipt": receipt,
        "receiptSha256": receipt_sha,
    }
    approval_store.persist_receipt(
        preflight_result,
        expected_result_sha256=REQUEST.sha256(preflight_result),
        now_utc=_utc(base_time),
    )
    approval_text = APPROVAL.approval_text(receipt)
    approval_request = {
        "schemaVersion": APPROVAL.APPROVAL_REQUEST_SCHEMA,
        "receiptSha256": receipt_sha,
        "environment": environment,
        "stateKey": receipt["stateKey"],
        "phase": phase,
        "attemptNumber": attempt_number,
        "controlPlaneCommit": receipt["controlPlaneCommit"],
        "requestedAuthority": receipt["requestedAuthority"],
        "createdAtUtc": _utc(base_time),
        "notBeforeUtc": _utc(base_time),
        "expiresAtUtc": _utc(base_time + timedelta(minutes=10)),
        "approvalText": approval_text,
        "approvalTextSha256": APPROVAL.text_sha256(approval_text),
        "humanApproved": True,
        "oneAttemptOnly": True,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
    }
    approval = approval_store.record_approval(
        approval_request,
        expected_approval_request_sha256=REQUEST.sha256(approval_request),
        expected_receipt_sha256=receipt_sha,
        now_utc=_utc(base_time),
    )
    approval_record_sha = approval["approvalRecordSha256"]
    spec = DRIVERS.phase_driver_spec(environment, phase)
    execution_request = {
        "schemaVersion": LEASE.EXECUTION_REQUEST_SCHEMA,
        "receiptSha256": receipt_sha,
        "approvalRecordSha256": approval_record_sha,
        "environment": environment,
        "stateKey": receipt["stateKey"],
        "phase": phase,
        "attemptNumber": attempt_number,
        "controlPlaneCommit": receipt["controlPlaneCommit"],
        "requestedAuthority": receipt["requestedAuthority"],
        "executionSpecSha256": REQUEST.sha256(spec),
        "createdAtUtc": _utc(base_time),
        "notBeforeUtc": _utc(base_time),
        "expiresAtUtc": _utc(base_time + timedelta(minutes=10)),
        "humanReviewed": True,
        "oneAttemptOnly": True,
        "simulationOnly": True,
        "liveExecutionAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
    }
    execution_request_sha = REQUEST.sha256(execution_request)
    private_bindings = {
        name: REQUEST.sha256({"environment": environment, "phase": phase, "binding": name})
        for name in spec["requiredPrivateBindings"]
    }
    private_bindings.update({
        "receiptSha256": receipt_sha,
        "approvalRecordSha256": approval_record_sha,
        "executionRequestSha256": execution_request_sha,
        "stateInventorySha256": receipt["stateInventorySha256"],
    })
    request_path = request_root / "execution-request.json"
    bindings_path = bindings_root / "private-bindings.json"
    _write_private(request_path, execution_request)
    _write_private(bindings_path, private_bindings)
    return {
        "approvalRoot": approval_root,
        "executionRoot": execution_root,
        "requestPath": request_path,
        "bindingsPath": bindings_path,
        "receiptSha256": receipt_sha,
        "approvalRecordSha256": approval_record_sha,
        "executionRequestSha256": execution_request_sha,
        "privateBindingsSha256": REQUEST.sha256(private_bindings),
    }


def _child_environment() -> dict[str, str]:
    return {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "LANG": "C",
        "LC_ALL": "C",
    }


def run_offline_process_chain(*, repository_root: Path) -> dict[str, Any]:
    """Run all sixteen synthetic phases through fresh fixed command processes."""

    completed: list[dict[str, Any]] = []
    process_count = 0
    environment: str | None = None
    phase: str | None = None
    try:
        require(isinstance(repository_root, Path) and repository_root.is_absolute(), "Repository root must be absolute")
        command_path = repository_root / "scripts" / COMMAND_FILENAME
        require(command_path.is_file() and not command_path.is_symlink(), "Exact fixed-fake command entrypoint is missing")
        base_time = datetime.now(timezone.utc).replace(microsecond=0)
        with tempfile.TemporaryDirectory(prefix="shared-teardown-offline-chain-") as temporary:
            chain_root = Path(temporary)
            chain_root.chmod(0o700)
            for environment in ENVIRONMENTS:
                predecessor: str | None = None
                environment_root = _owned_directory(chain_root / environment)
                for index, phase in enumerate(DRIVERS.PHASE_OPERATIONS):
                    phase_root = _owned_directory(environment_root / f"{index:02d}-{phase}")
                    prepared = _prepare_phase(
                        root=phase_root,
                        environment=environment,
                        phase=phase,
                        attempt_number=index + 1,
                        predecessor_receipt_sha256=predecessor,
                        base_time=base_time,
                    )
                    arguments = [
                        sys.executable,
                        str(command_path),
                        "--approval-store-directory", str(prepared["approvalRoot"]),
                        "--execution-store-directory", str(prepared["executionRoot"]),
                        "--execution-request-file", str(prepared["requestPath"]),
                        "--private-bindings-file", str(prepared["bindingsPath"]),
                        "--expected-execution-request-sha256", prepared["executionRequestSha256"],
                        "--expected-private-bindings-sha256", prepared["privateBindingsSha256"],
                        "--expected-receipt-sha256", prepared["receiptSha256"],
                        "--expected-approval-record-sha256", prepared["approvalRecordSha256"],
                        "--confirm", CONFIRMATION,
                    ]
                    try:
                        child = subprocess.run(
                            arguments,
                            cwd=repository_root,
                            env=_child_environment(),
                            capture_output=True,
                            timeout=PROCESS_TIMEOUT_SECONDS,
                            check=False,
                        )
                    except subprocess.TimeoutExpired:
                        raise OfflineProcessChainStopped(
                            "fixed-command-process-timeout",
                            environment=environment,
                            phase=phase,
                            completed_phase_count=len(completed),
                            subprocess_call_count=process_count + 1,
                        ) from None
                    process_count += 1
                    require(child.returncode == 0, "Fixed command child process failed")
                    require(child.stderr == b"", "Fixed command child stderr changed")
                    result = PRIVATE.decode_canonical(child.stdout, "Fixed command stdout")
                    require(result["schemaVersion"] == COMPOSITION.RESULT_SCHEMA, "Fixed command result schema changed")
                    require(result["environment"] == environment and result["phase"] == phase, "Fixed command result identity changed")
                    require(result["backendCallCount"] == len(DRIVERS.PHASE_OPERATIONS[phase]), "Fixed command call count changed")
                    require(result["liveCommandExecuted"] is False and result["executionPerformed"] is False, "Fixed command gained live execution")
                    claim_path = prepared["executionRoot"] / "claims" / f"{prepared['approvalRecordSha256']}.claim.json"
                    outcome_path = prepared["executionRoot"] / "outcomes" / f"{prepared['approvalRecordSha256']}.outcome.json"
                    require(claim_path.is_file() and outcome_path.is_file(), "Fixed command durable records are missing")
                    claim = PRIVATE.decode_canonical(claim_path.read_bytes(), "Synthetic claim")
                    outcome = PRIVATE.decode_canonical(outcome_path.read_bytes(), "Synthetic outcome")
                    require(REQUEST.sha256(claim) == result["claimSha256"], "Synthetic claim digest changed")
                    require(REQUEST.sha256(outcome) == result["outcomeSha256"], "Synthetic outcome digest changed")
                    completed.append({
                        "environment": environment,
                        "phase": phase,
                        "phaseIndex": index,
                        "receiptSha256": prepared["receiptSha256"],
                        "approvalRecordSha256": prepared["approvalRecordSha256"],
                        "executionRequestSha256": prepared["executionRequestSha256"],
                        "claimSha256": result["claimSha256"],
                        "outcomeSha256": result["outcomeSha256"],
                        "commandStdoutSha256": REQUEST.sha256(result),
                        "backendCallCount": result["backendCallCount"],
                        "syntheticOnly": True,
                        "liveCommandExecuted": False,
                    })
                    predecessor = prepared["receiptSha256"]
        require(len(completed) == 16 and process_count == 16, "Offline process-chain phase count changed")
        total_calls = sum(row["backendCallCount"] for row in completed)
        require(total_calls == 98, "Offline process-chain operation count changed")
        return {
            "schemaVersion": RESULT_SCHEMA,
            "status": "shared-dev-test-fresh-process-chain-completed-offline",
            "environmentOrder": list(ENVIRONMENTS),
            "phaseOrder": list(DRIVERS.PHASE_OPERATIONS),
            "environmentCount": 2,
            "phaseCountPerEnvironment": 8,
            "completedPhaseCount": len(completed),
            "subprocessCallCount": process_count,
            "backendCallCount": total_calls,
            "phaseResultManifestSha256": REQUEST.sha256(completed),
            "phaseResults": completed,
            "freshProcessPerPhase": True,
            "distinctLeaseStorePerPhase": True,
            "credentialEnvironmentForwarded": False,
            "syntheticOnly": True,
            "temporaryPrivateStoresRemoved": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "automaticRollbackPerformed": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "review-offline-process-chain-before-designing-any-live-adapter",
        }
    except OfflineProcessChainStopped:
        raise
    except (APPROVAL.ReceiptApprovalStopped, COMPOSITION.LeaseRegistryCompositionStopped, OSError, KeyError, TypeError, ValueError, TeardownGateError):
        raise OfflineProcessChainStopped(
            "shared-dev-test-offline-process-chain-stopped",
            environment=environment,
            phase=phase,
            completed_phase_count=len(completed),
            subprocess_call_count=process_count,
        ) from None

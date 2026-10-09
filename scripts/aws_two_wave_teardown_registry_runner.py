#!/usr/bin/env python3
"""Claim-bound ordered runner for the closed teardown command registry."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import aws_two_wave_teardown_command_registry as REGISTRY
import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import TeardownGateError, environment_profile, require


VERSION = "v0.12.4.1.5.0.7.1.6.8"
BACKEND_RESPONSE_SCHEMA = f"{VERSION}-shared-dev-test-registry-backend-response-v1"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-claimed-registry-runner-result-v1"
STOP_SCHEMA = f"{VERSION}-shared-dev-test-claimed-registry-runner-stop-v1"

CLAIM_KEYS = {
    "schemaVersion", "status", "receiptSha256", "approvalRecordSha256",
    "executionRequestSha256", "executionSpecSha256", "environment", "stateKey",
    "phase", "attemptNumber", "controlPlaneCommit", "requestedAuthority",
    "operationSetSha256", "operationCount", "claimedAtUtc", "expiresAtUtc",
    "oneAttemptOnly", "approvalConsumedByLease", "automaticRetryAuthorized",
    "automaticRollbackAuthorized", "statePushAuthorized", "backendRetirementAuthorized",
    "simulationOnly", "liveCommandExecuted", "executionPerformed",
}


class RegistryRunnerStopped(TeardownGateError):
    """Redacted terminal stop for the post-claim registry boundary."""

    def __init__(
        self,
        stage: str,
        *,
        phase: str | None = None,
        claim_bound: bool = False,
        backend_call_count: int = 0,
        failed_operation_id: str | None = None,
    ):
        super().__init__("shared-two-wave-claimed-registry-runner-stopped")
        self.report = {
            "schemaVersion": STOP_SCHEMA,
            "status": "shared-two-wave-claimed-registry-runner-stopped",
            "stage": stage,
            "phase": phase,
            "claimBound": claim_bound,
            "backendCallCount": backend_call_count,
            "failedOperationId": failed_operation_id,
            "approvalConsumedByLease": claim_bound,
            "preservePrivateStores": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "automaticRollbackPerformed": False,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "privatePathEmitted": False,
            "privateResourceIdentityEmitted": False,
        }


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
        return _utc(value, "Runner clock must be whole-second UTC")
    require(isinstance(value, datetime) and value.tzinfo is not None, "Runner clock must be timezone-aware")
    result = value.astimezone(timezone.utc)
    require(result.microsecond == 0, "Runner clock must be whole-second UTC")
    return result


def validate_durable_phase_claim(
    value: dict[str, Any],
    *,
    expected_claim_sha256: str,
    now_utc: datetime | str,
) -> dict[str, Any]:
    """Validate the exact already-persisted phase-driver claim value."""

    require(isinstance(value, dict) and set(value) == CLAIM_KEYS, "Durable phase claim shape changed")
    _sha(expected_claim_sha256, "Expected durable claim digest changed")
    require(REQUEST.sha256(value) == expected_claim_sha256, "Durable phase claim digest changed")
    require(value["schemaVersion"] == DRIVERS.CLAIM_SCHEMA, "Durable phase claim schema changed")
    require(value["status"] == "approval-consumed-before-fixed-fake-phase-dispatch", "Durable phase claim status changed")
    for key in ("receiptSha256", "approvalRecordSha256", "executionRequestSha256", "executionSpecSha256", "operationSetSha256"):
        _sha(value[key], f"Durable phase claim {key} changed")
    profile = environment_profile(value["environment"])
    require(value["phase"] in DRIVERS.PHASE_OPERATIONS, "Durable phase claim phase changed")
    spec = DRIVERS.phase_driver_spec(value["environment"], value["phase"])
    require(value["stateKey"] == profile["stateKey"] == spec["stateKey"], "Durable phase claim state key changed")
    require(value["executionSpecSha256"] == REQUEST.sha256(spec), "Durable phase claim driver spec changed")
    require(value["requestedAuthority"] == spec["requestedAuthority"], "Durable phase claim authority changed")
    require(value["operationSetSha256"] == REQUEST.sha256(spec["operationIds"]), "Durable phase operation set changed")
    require(value["operationCount"] == len(spec["operationIds"]), "Durable phase operation count changed")
    require(isinstance(value["attemptNumber"], int) and not isinstance(value["attemptNumber"], bool) and value["attemptNumber"] > 0, "Durable phase attempt changed")
    require(isinstance(value["controlPlaneCommit"], str) and REQUEST.COMMIT.fullmatch(value["controlPlaneCommit"]) is not None, "Durable phase commit changed")
    claimed = _utc(value["claimedAtUtc"], "Durable phase claim time changed")
    expires = _utc(value["expiresAtUtc"], "Durable phase claim expiry changed")
    require(claimed <= _now(now_utc) < expires, "Durable phase claim is not active")
    require(value["oneAttemptOnly"] is True and value["approvalConsumedByLease"] is True, "Durable phase claim consumption boundary changed")
    for key in (
        "automaticRetryAuthorized", "automaticRollbackAuthorized", "statePushAuthorized",
        "backendRetirementAuthorized", "liveCommandExecuted", "executionPerformed",
    ):
        require(value[key] is False, f"Durable phase claim safety boundary changed: {key}")
    require(value["simulationOnly"] is True, "Durable phase claim gained live authority")
    return value


def build_claimed_operation_requests(
    claim: dict[str, Any],
    *,
    expected_claim_sha256: str,
    now_utc: datetime | str,
) -> list[dict[str, Any]]:
    """Build the only operation-request sequence accepted for a durable claim."""

    validated = validate_durable_phase_claim(
        claim,
        expected_claim_sha256=expected_claim_sha256,
        now_utc=now_utc,
    )
    spec = DRIVERS.phase_driver_spec(validated["environment"], validated["phase"])
    spec_sha = REQUEST.sha256(spec)
    return [
        DRIVERS._operation_request(
            spec=spec,
            spec_sha256=spec_sha,
            execution_request_sha256=validated["executionRequestSha256"],
            operation_id=operation_id,
            operation_index=index,
        )
        for index, operation_id in enumerate(spec["operationIds"])
    ]


def validate_phase_private_bindings(claim: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete phase binding set before a lease is consumed."""

    spec = DRIVERS.phase_driver_spec(claim["environment"], claim["phase"])
    required = set(spec["requiredPrivateBindings"])
    require(isinstance(value, dict) and set(value) == required, "Phase private binding names changed")
    for key, digest in value.items():
        _sha(digest, f"Phase private binding digest changed: {key}")
    for key in ("receiptSha256", "approvalRecordSha256", "executionRequestSha256"):
        require(value[key] == claim[key], f"Phase private binding does not match durable claim: {key}")
    return value


class FixedFakeRegistryBackend:
    """Closed deterministic adapter backend; it never constructs or runs a command."""

    def __init__(self, *, fail_at: str = "", malformed_at: str = ""):
        known = set(REGISTRY.OPERATION_TRANSPORTS)
        require(isinstance(fail_at, str) and (not fail_at or fail_at in known), "Fixed-fake failure selector changed")
        require(isinstance(malformed_at, str) and (not malformed_at or malformed_at in known), "Fixed-fake malformed selector changed")
        require(not fail_at or not malformed_at or fail_at != malformed_at, "Fixed-fake selectors overlap")
        self.fail_at = fail_at
        self.malformed_at = malformed_at
        self.calls: list[dict[str, Any]] = []
        self.used = False

    def call(
        self,
        *,
        selection: dict[str, Any],
        operation_request: dict[str, Any],
        private_bindings: dict[str, str],
        claim_sha256: str,
    ) -> dict[str, Any]:
        operation_id = operation_request["operationId"]
        call = {
            "operationId": operation_id,
            "operationIndex": operation_request["operationIndex"],
            "operationRequestSha256": REQUEST.sha256(operation_request),
            "adapterEntrySha256": REQUEST.sha256(selection["adapterEntry"]),
            "privateBindingSetSha256": REQUEST.sha256(private_bindings),
            "claimSha256": claim_sha256,
        }
        self.calls.append(call)
        failed = operation_id == self.fail_at
        response = {
            "schemaVersion": BACKEND_RESPONSE_SCHEMA,
            "status": "fixed-fake-registry-call-failed" if failed else "fixed-fake-registry-call-succeeded",
            "environment": operation_request["environment"],
            "phase": operation_request["phase"],
            "operationId": operation_id,
            "operationIndex": operation_request["operationIndex"],
            "operationRequestSha256": call["operationRequestSha256"],
            "claimSha256": claim_sha256,
            "adapterEntrySha256": call["adapterEntrySha256"],
            "privateBindingSetSha256": call["privateBindingSetSha256"],
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
        }
        if operation_id == self.malformed_at:
            response["executionPerformed"] = True
        return response


def _expected_response(
    *,
    selection: dict[str, Any],
    operation_request: dict[str, Any],
    private_bindings: dict[str, str],
    claim_sha256: str,
    success: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": BACKEND_RESPONSE_SCHEMA,
        "status": "fixed-fake-registry-call-succeeded" if success else "fixed-fake-registry-call-failed",
        "environment": operation_request["environment"],
        "phase": operation_request["phase"],
        "operationId": operation_request["operationId"],
        "operationIndex": operation_request["operationIndex"],
        "operationRequestSha256": REQUEST.sha256(operation_request),
        "claimSha256": claim_sha256,
        "adapterEntrySha256": REQUEST.sha256(selection["adapterEntry"]),
        "privateBindingSetSha256": REQUEST.sha256(private_bindings),
        "simulationOnly": True,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }


def run_claimed_registry_once(
    *,
    claim: dict[str, Any],
    expected_claim_sha256: str,
    phase_command_manifest: dict[str, Any],
    operation_requests: list[dict[str, Any]],
    private_bindings: dict[str, Any],
    now_utc: datetime | str,
    backend: FixedFakeRegistryBackend,
) -> dict[str, Any]:
    """Validate every input, then dispatch one ordered fixed-fake registry pass."""

    phase: str | None = None
    claim_bound = False
    call_count = 0
    try:
        require(type(backend) is FixedFakeRegistryBackend, "Only the exact fixed-fake registry backend is accepted")
        require(backend.used is False and backend.calls == [], "Fixed-fake registry backend instance was already used")
        validated_claim = validate_durable_phase_claim(
            claim,
            expected_claim_sha256=expected_claim_sha256,
            now_utc=now_utc,
        )
        claim_bound = True
        phase = validated_claim["phase"]
        environment = validated_claim["environment"]
        manifest = REGISTRY.validate_phase_command_manifest(
            phase_command_manifest,
            environment=environment,
            phase=phase,
        )
        bindings = validate_phase_private_bindings(validated_claim, private_bindings)
        expected_requests = build_claimed_operation_requests(
            validated_claim,
            expected_claim_sha256=expected_claim_sha256,
            now_utc=now_utc,
        )
        require(isinstance(operation_requests, list) and operation_requests == expected_requests, "Claimed operation request order or content changed")
        selections = [REGISTRY.validate_operation_request_for_adapter(request) for request in operation_requests]
        require([row["operationId"] for row in selections] == manifest["operationIds"], "Registry selection order changed")
        require(
            [REQUEST.sha256(row["adapterEntry"]) for row in selections] == manifest["adapterEntrySha256s"],
            "Registry adapter entry binding changed",
        )
        backend.used = True
        operation_manifest: list[dict[str, Any]] = []
        for request, selection in zip(operation_requests, selections, strict=True):
            entry = selection["adapterEntry"]
            selected_bindings = {name: bindings[name] for name in entry["requiredPrivateBindings"]}
            response = backend.call(
                selection=selection,
                operation_request=request,
                private_bindings=selected_bindings,
                claim_sha256=expected_claim_sha256,
            )
            call_count = len(backend.calls)
            succeeded = response == _expected_response(
                selection=selection,
                operation_request=request,
                private_bindings=selected_bindings,
                claim_sha256=expected_claim_sha256,
                success=True,
            )
            failed = response == _expected_response(
                selection=selection,
                operation_request=request,
                private_bindings=selected_bindings,
                claim_sha256=expected_claim_sha256,
                success=False,
            )
            if not (succeeded or failed):
                raise RegistryRunnerStopped(
                    "fixed-fake-registry-response-malformed",
                    phase=phase,
                    claim_bound=True,
                    backend_call_count=call_count,
                    failed_operation_id=request["operationId"],
                )
            operation_manifest.append({
                "operationId": request["operationId"],
                "operationIndex": request["operationIndex"],
                "requestSha256": REQUEST.sha256(request),
                "adapterEntrySha256": REQUEST.sha256(entry),
                "privateBindingSetSha256": REQUEST.sha256(selected_bindings),
                "responseSha256": REQUEST.sha256(response),
                "succeeded": succeeded,
            })
            if failed:
                raise RegistryRunnerStopped(
                    "fixed-fake-registry-operation-failed",
                    phase=phase,
                    claim_bound=True,
                    backend_call_count=call_count,
                    failed_operation_id=request["operationId"],
                )
        require(call_count == manifest["operationCount"], "Registry backend call count changed")
        return {
            "schemaVersion": RESULT_SCHEMA,
            "status": "claimed-fixed-fake-registry-runner-completed",
            "claimSha256": expected_claim_sha256,
            "executionRequestSha256": validated_claim["executionRequestSha256"],
            "executionSpecSha256": validated_claim["executionSpecSha256"],
            "phaseCommandManifestSha256": REQUEST.sha256(manifest),
            "commandRegistrySha256": manifest["commandRegistrySha256"],
            "operationManifestSha256": REQUEST.sha256(operation_manifest),
            "environment": environment,
            "phase": phase,
            "attemptNumber": validated_claim["attemptNumber"],
            "operationCallCount": call_count,
            "approvalConsumedByLease": True,
            "automaticRetryPerformed": False,
            "automaticRepairPerformed": False,
            "automaticRollbackPerformed": False,
            "simulationOnly": True,
            "liveCommandExecuted": False,
            "executionPerformed": False,
            "nextAction": "compose-this-runner-inside-the-durable-lease-before-adding-any-live-backend",
        }
    except RegistryRunnerStopped:
        raise
    except (KeyError, TypeError, ValueError, TeardownGateError):
        raise RegistryRunnerStopped(
            "claimed-registry-runner-pre-dispatch-stopped" if call_count == 0 else "claimed-registry-runner-stopped",
            phase=phase,
            claim_bound=claim_bound,
            backend_call_count=call_count,
        ) from None

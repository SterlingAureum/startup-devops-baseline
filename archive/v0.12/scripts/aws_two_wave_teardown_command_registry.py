#!/usr/bin/env python3
"""Closed command-adapter registry for shared dev/test teardown operations."""

from __future__ import annotations

from typing import Any

import aws_two_wave_teardown_phase_drivers as DRIVERS
import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import environment_profile, require


VERSION = "v0.12.4.1.5.0.7.1.6.7"
REGISTRY_SCHEMA = f"{VERSION}-shared-dev-test-command-adapter-registry-v1"
ENTRY_SCHEMA = f"{VERSION}-shared-dev-test-command-adapter-entry-v1"
MANIFEST_SCHEMA = f"{VERSION}-shared-dev-test-command-adapter-manifest-v1"

TRANSPORT_POLICIES = {
    "identity-read": ("read-only", 60, "canonical-json"),
    "kubernetes-read": ("read-only", 120, "canonical-json"),
    "kubernetes-mutation": ("mutation", 900, "canonical-json"),
    "terraform-read": ("read-only", 300, "private-artifacts"),
    "terraform-plan": ("local-artifact-write", 1800, "private-artifacts"),
    "terraform-apply": ("mutation", 10800, "private-artifacts"),
    "s3-history-read": ("read-only", 300, "canonical-json"),
    "aws-read": ("read-only", 900, "canonical-json"),
    "aws-exact-delete": ("mutation", 900, "canonical-json"),
    "git-read": ("read-only", 60, "canonical-json"),
    "local-gate": ("local-validation", 60, "canonical-json"),
    "composite-read": ("read-only", 1800, "private-artifacts"),
}

OPERATION_TRANSPORTS = {
    "verify-environment-context": "identity-read",
    "observe-controller-owned-inventory": "kubernetes-read",
    "suspend-gitops-reconciliation": "kubernetes-mutation",
    "delete-controller-owned-kubernetes-resources": "kubernetes-mutation",
    "verify-controller-owned-absence": "kubernetes-read",
    "snapshot-managed-state": "terraform-read",
    "snapshot-state-lock-history": "s3-history-read",
    "verify-source-manifest": "git-read",
    "select-exact-non-network-destroy-scope": "local-gate",
    "create-saved-wave-one-plan": "terraform-plan",
    "render-and-gate-wave-one-plan": "terraform-read",
    "verify-reviewed-wave-one-plan-digests": "local-gate",
    "snapshot-pre-apply-state-lock-history": "s3-history-read",
    "apply-exact-wave-one-saved-plan": "terraform-apply",
    "snapshot-post-apply-managed-state": "terraform-read",
    "verify-exact-network-only-state": "local-gate",
    "verify-wave-one-apply-history-delta": "local-gate",
    "verify-eks-absence": "aws-read",
    "snapshot-network-only-managed-state": "terraform-read",
    "inventory-all-vpc-dependency-families": "composite-read",
    "classify-controller-unknown-and-safe-residue": "local-gate",
    "verify-protected-foundation-preserved": "local-gate",
    "verify-exact-allowlisted-residue-binding": "local-gate",
    "delete-exact-reviewed-safe-residue": "aws-exact-delete",
    "verify-exact-residue-absence": "aws-read",
    "verify-zero-vpc-dependencies": "local-gate",
    "select-exact-network-destroy-scope": "local-gate",
    "create-saved-wave-two-plan": "terraform-plan",
    "render-and-gate-wave-two-plan": "terraform-read",
    "verify-reviewed-wave-two-plan-digests": "local-gate",
    "apply-exact-wave-two-saved-plan": "terraform-apply",
    "snapshot-final-managed-state": "terraform-read",
    "verify-empty-managed-state": "local-gate",
    "verify-wave-two-apply-history-delta": "local-gate",
    "verify-environment-resource-absence": "composite-read",
    "verify-final-state-lock-history": "s3-history-read",
    "classify-residual-cost-inventory": "composite-read",
}

OPERATION_EXTRA_BINDINGS = {
    "suspend-gitops-reconciliation": ("controllerInventorySha256",),
    "delete-controller-owned-kubernetes-resources": ("controllerInventorySha256",),
    "create-saved-wave-one-plan": ("stateSnapshotSha256", "sourceManifestSha256"),
    "render-and-gate-wave-one-plan": ("stateSnapshotSha256",),
    "apply-exact-wave-one-saved-plan": ("binaryPlanSha256", "planRecordSha256"),
    "inventory-all-vpc-dependency-families": ("stateSnapshotSha256",),
    "delete-exact-reviewed-safe-residue": ("dependencyInventorySha256", "residueIdentitySha256"),
    "create-saved-wave-two-plan": ("stateSnapshotSha256", "dependencyInventorySha256"),
    "render-and-gate-wave-two-plan": ("stateSnapshotSha256", "dependencyInventorySha256"),
    "apply-exact-wave-two-saved-plan": ("binaryPlanSha256", "planRecordSha256"),
    "verify-environment-resource-absence": ("absenceInventorySha256",),
    "classify-residual-cost-inventory": ("absenceInventorySha256",),
}


def _operation_phases(operation_id: str) -> list[str]:
    return [phase for phase, operations in DRIVERS.PHASE_OPERATIONS.items() if operation_id in operations]


def adapter_entry(operation_id: str) -> dict[str, Any]:
    require(operation_id in OPERATION_TRANSPORTS, "Operation ID is not present in the closed command registry")
    transport = OPERATION_TRANSPORTS[operation_id]
    effect, timeout, output = TRANSPORT_POLICIES[transport]
    return {
        "schemaVersion": ENTRY_SCHEMA,
        "operationId": operation_id,
        "allowedPhases": _operation_phases(operation_id),
        "adapterId": f"shared-teardown.{transport}.{operation_id}.v1",
        "transportKind": transport,
        "effectClass": effect,
        "timeoutSeconds": timeout,
        "outputPolicy": output,
        "requiredPrivateBindings": list(
            DRIVERS.COMMON_PRIVATE_BINDINGS + OPERATION_EXTRA_BINDINGS.get(operation_id, ())
        ),
        "rawCommandAccepted": False,
        "dynamicCommandTemplateAccepted": False,
        "credentialOrEndpointOverrideAccepted": False,
        "environmentFallbackAccepted": False,
        "automaticRetryAuthorized": False,
        "automaticRepairAuthorized": False,
        "implementedLive": False,
    }


def command_registry() -> dict[str, Any]:
    expected = {operation for values in DRIVERS.PHASE_OPERATIONS.values() for operation in values}
    require(set(OPERATION_TRANSPORTS) == expected, "Command registry does not exactly cover the reviewed operation IDs")
    entries = [adapter_entry(operation) for operation in sorted(expected)]
    return {
        "schemaVersion": REGISTRY_SCHEMA,
        "version": VERSION,
        "operationIdCount": len(entries),
        "phaseOperationCallCount": sum(len(values) for values in DRIVERS.PHASE_OPERATIONS.values()),
        "entries": entries,
        "rawCommandAccepted": False,
        "dynamicCommandTemplateAccepted": False,
        "credentialOrEndpointOverrideAccepted": False,
        "liveBackendAvailable": False,
        "subprocessAvailable": False,
        "simulationOnly": True,
    }


def command_registry_sha256() -> str:
    return REQUEST.sha256(command_registry())


def validate_command_registry(value: dict[str, Any]) -> dict[str, Any]:
    expected = command_registry()
    require(value == expected, "Command adapter registry changed")
    return value


def phase_command_manifest(environment: str, phase: str) -> dict[str, Any]:
    profile = environment_profile(environment)
    spec = DRIVERS.phase_driver_spec(environment, phase)
    entries = [adapter_entry(operation) for operation in spec["operationIds"]]
    return {
        "schemaVersion": MANIFEST_SCHEMA,
        "version": VERSION,
        "environment": environment,
        "stateKey": profile["stateKey"],
        "phase": phase,
        "phaseDriverSpecSha256": REQUEST.sha256(spec),
        "commandRegistrySha256": command_registry_sha256(),
        "terraformRootRelativePath": spec["terraformRootRelativePath"],
        "backendConfigRelativePath": spec["backendConfigRelativePath"],
        "operationIds": list(spec["operationIds"]),
        "adapterEntrySha256s": [REQUEST.sha256(entry) for entry in entries],
        "operationCount": len(entries),
        "orderedDispatchRequired": True,
        "oneCallPerOperationId": True,
        "claimBeforeFirstCommandRequired": True,
        "stopAtFirstFailure": True,
        "rawCommandAccepted": False,
        "dynamicCommandTemplateAccepted": False,
        "credentialOrEndpointOverrideAccepted": False,
        "automaticRetryAuthorized": False,
        "automaticRepairAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "liveBackendAvailable": False,
        "simulationOnly": True,
    }


def validate_phase_command_manifest(value: dict[str, Any], *, environment: str, phase: str) -> dict[str, Any]:
    expected = phase_command_manifest(environment, phase)
    require(value == expected, "Phase command manifest changed")
    return value


def validate_operation_request_for_adapter(request: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "schemaVersion", "environment", "stateKey", "phase", "requestedAuthority",
        "executionSpecSha256", "executionRequestSha256", "operationId", "operationIndex",
        "operationCount", "simulationOnly", "liveCommandAuthorized",
    }
    require(isinstance(request, dict) and set(request) == keys, "Operation request shape changed")
    manifest = phase_command_manifest(request["environment"], request["phase"])
    index = request["operationIndex"]
    require(isinstance(index, int) and not isinstance(index, bool), "Operation index changed")
    require(0 <= index < manifest["operationCount"], "Operation index is outside the phase manifest")
    require(request["stateKey"] == manifest["stateKey"], "Operation state key changed")
    require(request["operationId"] == manifest["operationIds"][index], "Operation ID is not at the reviewed phase index")
    require(request["operationCount"] == manifest["operationCount"], "Operation count changed")
    require(request["executionSpecSha256"] == manifest["phaseDriverSpecSha256"], "Operation request driver spec changed")
    require(isinstance(request["executionRequestSha256"], str) and REQUEST.SHA256.fullmatch(request["executionRequestSha256"]) is not None, "Execution request digest changed")
    require(request["requestedAuthority"] == REQUEST.PHASES[request["phase"]]["requestedAuthority"], "Operation authority changed")
    require(request["schemaVersion"] == DRIVERS.OPERATION_REQUEST_SCHEMA, "Operation request schema changed")
    require(request["simulationOnly"] is True and request["liveCommandAuthorized"] is False, "Command registry cannot accept live authority")
    return {
        "schemaVersion": f"{VERSION}-shared-dev-test-command-adapter-selection-v1",
        "environment": request["environment"],
        "phase": request["phase"],
        "operationId": request["operationId"],
        "operationIndex": index,
        "phaseCommandManifestSha256": REQUEST.sha256(manifest),
        "adapterEntry": adapter_entry(request["operationId"]),
        "simulationOnly": True,
        "liveBackendAvailable": False,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }

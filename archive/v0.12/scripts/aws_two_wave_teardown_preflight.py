#!/usr/bin/env python3
"""Command-free request verification for the shared dev/test teardown lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from aws_two_wave_teardown_core import SAFE_RESIDUE_CATEGORIES, TeardownGateError, environment_profile, require


VERSION = "v0.12.4.1.5.0.7.1.6.2"
REQUEST_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-teardown-request-v1"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-teardown-preflight-result-v1"
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

AUTHORITY_KEYS = {
    "liveReadAuthorized",
    "controllerMutationAuthorized",
    "terraformPlanAuthorized",
    "terraformApplyAuthorized",
    "directAwsMutationAuthorized",
    "statePushAuthorized",
    "automaticRetryAuthorized",
    "automaticRollbackAuthorized",
    "backendRetirementAuthorized",
}
REQUEST_KEYS = {
    "schemaVersion",
    "environment",
    "stateKey",
    "phase",
    "attemptNumber",
    "controlPlaneCommit",
    "createdAtUtc",
    "notBeforeUtc",
    "expiresAtUtc",
    "inputEvidenceSha256",
    "predecessorReceiptSha256",
    "state",
    "reviewedPlan",
    "safeResidue",
    "authority",
}
STATE_KEYS = {
    "managedAddressInventorySha256",
    "managedAddressCount",
    "networkAddressCount",
    "nonNetworkAddressCount",
    "remoteStateReady",
}
PLAN_KEYS = {
    "wave",
    "binaryPlanSha256",
    "planRecordSha256",
    "humanReviewed",
    "managedDeleteCount",
    "planReviewExpiresAtUtc",
}
RESIDUE_KEYS = {"category", "identitySha256", "exactBound", "deletionAuthorized"}

PHASES = {
    "controller-cleanup": {
        "requestedAuthority": "kubernetes-controller-mutation",
        "maxWindowSeconds": 3600,
        "stateShape": "mixed",
        "predecessorRequired": False,
        "reviewedPlanWave": None,
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-controller-cleanup-approval",
    },
    "wave-one-plan": {
        "requestedAuthority": "terraform-plan",
        "maxWindowSeconds": 3600,
        "stateShape": "mixed",
        "predecessorRequired": True,
        "reviewedPlanWave": None,
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-wave-one-plan-approval",
    },
    "wave-one-apply": {
        "requestedAuthority": "terraform-apply",
        "maxWindowSeconds": 10800,
        "stateShape": "mixed",
        "predecessorRequired": True,
        "reviewedPlanWave": "non-network",
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-exact-wave-one-apply-approval",
    },
    "post-wave-one-inventory": {
        "requestedAuthority": "aws-read-only",
        "maxWindowSeconds": 3600,
        "stateShape": "network-only",
        "predecessorRequired": True,
        "reviewedPlanWave": None,
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-post-wave-one-inventory-approval",
    },
    "safe-residue-delete": {
        "requestedAuthority": "aws-exact-residue-delete",
        "maxWindowSeconds": 3600,
        "stateShape": "network-only",
        "predecessorRequired": True,
        "reviewedPlanWave": None,
        "safeResidueRequired": True,
        "nextAction": "obtain-separate-exact-safe-residue-delete-approval",
    },
    "wave-two-plan": {
        "requestedAuthority": "terraform-plan",
        "maxWindowSeconds": 3600,
        "stateShape": "network-only",
        "predecessorRequired": True,
        "reviewedPlanWave": None,
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-wave-two-plan-approval",
    },
    "wave-two-apply": {
        "requestedAuthority": "terraform-apply",
        "maxWindowSeconds": 10800,
        "stateShape": "network-only",
        "predecessorRequired": True,
        "reviewedPlanWave": "network",
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-exact-wave-two-apply-approval",
    },
    "final-read-only-audit": {
        "requestedAuthority": "multi-system-read-only",
        "maxWindowSeconds": 3600,
        "stateShape": "empty",
        "predecessorRequired": True,
        "reviewedPlanWave": None,
        "safeResidueRequired": False,
        "nextAction": "obtain-separate-final-read-only-audit-approval",
    },
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact_keys(value: Any, keys: set[str], message: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, message)
    return value


def _sha(value: Any, message: str) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, message)
    return value


def _utc(value: Any, message: str) -> datetime:
    require(isinstance(value, str) and UTC.fullmatch(value) is not None, message)
    try:
        result = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise TeardownGateError(message) from None
    return result


def _now(value: datetime | str) -> datetime:
    if isinstance(value, str):
        return _utc(value, "Verification clock must be whole-second UTC")
    require(isinstance(value, datetime) and value.tzinfo is not None, "Verification clock must be timezone-aware")
    normalized = value.astimezone(timezone.utc)
    require(normalized.microsecond == 0, "Verification clock must be whole-second UTC")
    return normalized


def _gate_state(value: Any, shape: str) -> dict[str, Any]:
    state = _exact_keys(value, STATE_KEYS, "State binding shape changed")
    _sha(state["managedAddressInventorySha256"], "State inventory binding must be SHA-256")
    for key in ("managedAddressCount", "networkAddressCount", "nonNetworkAddressCount"):
        require(isinstance(state[key], int) and not isinstance(state[key], bool) and state[key] >= 0, "State counts must be nonnegative integers")
    require(state["managedAddressCount"] == state["networkAddressCount"] + state["nonNetworkAddressCount"], "State counts do not reconcile")
    require(state["remoteStateReady"] is True, "Remote state must be activated before teardown preflight")
    if shape == "mixed":
        require(state["networkAddressCount"] > 0 and state["nonNetworkAddressCount"] > 0, "Initial teardown phases require network and non-network state")
    elif shape == "network-only":
        require(state["managedAddressCount"] > 0 and state["managedAddressCount"] == state["networkAddressCount"] and state["nonNetworkAddressCount"] == 0, "Network phase state must contain only network addresses")
    elif shape == "empty":
        require(state["managedAddressCount"] == state["networkAddressCount"] == state["nonNetworkAddressCount"] == 0, "Final audit requires empty managed state")
    else:
        raise TeardownGateError("Unknown state-shape policy")
    return state


def _gate_plan(value: Any, expected_wave: str | None, state: dict[str, Any], now: datetime, expires: datetime) -> dict[str, Any] | None:
    if expected_wave is None:
        require(value is None, "Reviewed plan is accepted only for apply phases")
        return None
    plan = _exact_keys(value, PLAN_KEYS, "Reviewed plan binding shape changed")
    require(plan["wave"] == expected_wave, "Reviewed plan wave changed")
    _sha(plan["binaryPlanSha256"], "Binary plan binding must be SHA-256")
    _sha(plan["planRecordSha256"], "Plan record binding must be SHA-256")
    require(plan["humanReviewed"] is True, "Saved plan must be human reviewed")
    expected_count = state["nonNetworkAddressCount"] if expected_wave == "non-network" else state["networkAddressCount"]
    require(plan["managedDeleteCount"] == expected_count and expected_count > 0, "Reviewed plan delete count changed")
    review_expires = _utc(plan["planReviewExpiresAtUtc"], "Plan review expiry must be whole-second UTC")
    require(now < review_expires and expires <= review_expires, "Request exceeds reviewed-plan lifetime")
    return plan


def _gate_residue(value: Any, required: bool) -> dict[str, Any] | None:
    if not required:
        require(value is None, "Safe residue binding is accepted only for its delete phase")
        return None
    residue = _exact_keys(value, RESIDUE_KEYS, "Safe residue binding shape changed")
    require(residue["category"] in SAFE_RESIDUE_CATEGORIES, "Safe residue category is not allowlisted")
    _sha(residue["identitySha256"], "Safe residue identity must be SHA-256 only")
    require(residue["exactBound"] is True, "Safe residue must be exactly bound")
    require(residue["deletionAuthorized"] is False, "Preflight cannot authorize safe-residue deletion")
    return residue


def verify_request(request: dict[str, Any], *, now_utc: datetime | str) -> dict[str, Any]:
    """Verify one private request and return a redacted, non-authorizing preflight."""

    value = _exact_keys(request, REQUEST_KEYS, "Request shape changed")
    require(value["schemaVersion"] == REQUEST_SCHEMA, "Request schema changed")
    profile = environment_profile(value["environment"])
    require(value["stateKey"] == profile["stateKey"], "Environment state key changed")
    require(isinstance(value["phase"], str) and value["phase"] in PHASES, "Teardown phase changed")
    phase = PHASES[value["phase"]]
    require(isinstance(value["attemptNumber"], int) and not isinstance(value["attemptNumber"], bool) and value["attemptNumber"] > 0, "Attempt number must be positive")
    require(isinstance(value["controlPlaneCommit"], str) and COMMIT.fullmatch(value["controlPlaneCommit"]) is not None, "Control-plane commit must be exact")
    _sha(value["inputEvidenceSha256"], "Input evidence binding must be SHA-256")

    now = _now(now_utc)
    created = _utc(value["createdAtUtc"], "Creation time must be whole-second UTC")
    not_before = _utc(value["notBeforeUtc"], "Not-before time must be whole-second UTC")
    expires = _utc(value["expiresAtUtc"], "Expiry time must be whole-second UTC")
    require(created <= not_before <= now < expires, "Request is not active at the verification clock")
    require((expires - not_before).total_seconds() <= phase["maxWindowSeconds"], "Request window exceeds phase maximum")

    predecessor = value["predecessorReceiptSha256"]
    if phase["predecessorRequired"]:
        _sha(predecessor, "Phase requires an exact predecessor receipt")
    else:
        require(predecessor is None, "First phase cannot inherit a predecessor receipt")

    state = _gate_state(value["state"], phase["stateShape"])
    plan = _gate_plan(value["reviewedPlan"], phase["reviewedPlanWave"], state, now, expires)
    residue = _gate_residue(value["safeResidue"], phase["safeResidueRequired"])
    authority = _exact_keys(value["authority"], AUTHORITY_KEYS, "Authority shape changed")
    require(all(item is False for item in authority.values()), "Request verification cannot carry live authority")

    return {
        "schemaVersion": RESULT_SCHEMA,
        "status": "shared-two-wave-teardown-request-inputs-verified",
        "environment": value["environment"],
        "stateKey": value["stateKey"],
        "phase": value["phase"],
        "attemptNumber": value["attemptNumber"],
        "controlPlaneCommit": value["controlPlaneCommit"],
        "requestSha256": sha256(value),
        "inputEvidenceSha256": value["inputEvidenceSha256"],
        "predecessorReceiptSha256": predecessor,
        "managedAddressInventorySha256": state["managedAddressInventorySha256"],
        "managedAddressCount": state["managedAddressCount"],
        "remoteStateActivationRequiredByProfile": profile["remoteStateActivationRequired"],
        "remoteStateReady": True,
        "reviewedBinaryPlanSha256": None if plan is None else plan["binaryPlanSha256"],
        "safeResidueIdentitySha256": None if residue is None else residue["identitySha256"],
        "requestedAuthority": phase["requestedAuthority"],
        "verifiedAtUtc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiresAtUtc": value["expiresAtUtc"],
        "remainingApprovalSeconds": int((expires - now).total_seconds()),
        "privateResourceIdentityEmitted": False,
        "liveCommandExecuted": False,
        "executionAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "nextAction": phase["nextAction"],
    }

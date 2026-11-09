#!/usr/bin/env python3
"""Guarded local private-evidence reader and redacted teardown receipt builder."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any

import aws_two_wave_teardown_preflight as REQUEST
from aws_two_wave_teardown_core import TeardownGateError, require


VERSION = "v0.12.4.1.5.0.7.1.6.3"
EVIDENCE_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-teardown-phase-evidence-v1"
RECEIPT_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-teardown-preflight-receipt-v1"
RESULT_SCHEMA = f"{VERSION}-shared-dev-test-two-wave-teardown-private-preflight-result-v1"
MAX_PRIVATE_FILE_BYTES = 1024 * 1024
MAX_EVIDENCE_AGE_SECONDS = 900
PRIVATE_FILENAMES = {"request.json", "evidence.json"}
EVIDENCE_KEYS = {
    "schemaVersion",
    "environment",
    "stateKey",
    "phase",
    "controlPlaneCommit",
    "observedAtUtc",
    "stateInventorySha256",
    "facts",
}

FACT_KEYS = {
    "controller-cleanup": {
        "controllerInventorySha256",
        "controllerOwnedResourceCount",
        "reconciliationTargetBound",
        "backupDeletionRequested",
    },
    "wave-one-plan": {
        "stateSnapshotSha256",
        "historySnapshotSha256",
        "sourceManifestSha256",
        "networkAddressCount",
        "nonNetworkAddressCount",
    },
    "wave-one-apply": {
        "binaryPlanSha256",
        "planRecordSha256",
        "planTextSha256",
        "planJsonSha256",
        "humanReviewed",
        "managedDeleteCount",
    },
    "post-wave-one-inventory": {
        "stateSnapshotSha256",
        "historySnapshotSha256",
        "eksAbsent",
        "networkAddressCount",
        "nonNetworkAddressCount",
    },
    "safe-residue-delete": {
        "dependencyInventorySha256",
        "residueCategory",
        "residueIdentitySha256",
        "exactBound",
        "deletionAlreadyAttempted",
    },
    "wave-two-plan": {
        "stateSnapshotSha256",
        "historySnapshotSha256",
        "dependencyInventorySha256",
        "safeResidueCount",
        "unknownDependencyCount",
        "controllerOwnedDependencyCount",
    },
    "wave-two-apply": {
        "binaryPlanSha256",
        "planRecordSha256",
        "planTextSha256",
        "planJsonSha256",
        "humanReviewed",
        "managedDeleteCount",
    },
    "final-read-only-audit": {
        "finalStateSha256",
        "absenceInventorySha256",
        "historySnapshotSha256",
        "managedStateAddressCount",
        "protectedFoundationPreserved",
    },
}


class PrivatePreflightStopped(TeardownGateError):
    """Fail-closed local preflight error without private bytes or paths."""


def _exact_keys(value: Any, keys: set[str], message: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, message)
    return value


def _sha(value: Any, message: str) -> str:
    require(isinstance(value, str) and REQUEST.SHA256.fullmatch(value) is not None, message)
    return value


def _nonnegative_integer(value: Any, message: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, message)
    return value


def _utc(value: Any, message: str) -> datetime:
    require(isinstance(value, str) and REQUEST.UTC.fullmatch(value) is not None, message)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise TeardownGateError(message) from None


def decode_canonical(raw: bytes, label: str) -> dict[str, Any]:
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_PRIVATE_FILE_BYTES, f"{label} byte size changed")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TeardownGateError(f"{label} is not canonical JSON") from None
    require(isinstance(value, dict) and REQUEST.canonical_bytes(value) == raw, f"{label} is not canonical JSON")
    return value


def _gate_common_evidence(evidence: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    value = _exact_keys(evidence, EVIDENCE_KEYS, "Phase evidence shape changed")
    require(value["schemaVersion"] == EVIDENCE_SCHEMA, "Phase evidence schema changed")
    for key in ("environment", "stateKey", "phase", "controlPlaneCommit"):
        require(value[key] == request[key], f"Phase evidence {key} binding changed")
    require(value["phase"] in FACT_KEYS, "Phase evidence type changed")
    require(value["stateInventorySha256"] == request["state"]["managedAddressInventorySha256"], "Phase evidence state inventory changed")
    _sha(value["stateInventorySha256"], "Phase evidence state inventory must be SHA-256")
    observed = _utc(value["observedAtUtc"], "Phase evidence observation time changed")
    created = _utc(request["createdAtUtc"], "Request creation time changed")
    age = (created - observed).total_seconds()
    require(0 <= age <= MAX_EVIDENCE_AGE_SECONDS, "Phase evidence is future-dated or stale")
    facts = _exact_keys(value["facts"], FACT_KEYS[value["phase"]], "Phase facts shape changed")
    return facts


def _gate_phase_facts(phase: str, facts: dict[str, Any], request: dict[str, Any]) -> None:
    state = request["state"]
    if phase == "controller-cleanup":
        _sha(facts["controllerInventorySha256"], "Controller inventory must be SHA-256")
        _nonnegative_integer(facts["controllerOwnedResourceCount"], "Controller resource count changed")
        require(facts["reconciliationTargetBound"] is True, "Reconciliation target is not bound")
        require(facts["backupDeletionRequested"] is True, "Disposable dev/test backup cleanup must be explicit")
    elif phase == "wave-one-plan":
        for key in ("stateSnapshotSha256", "historySnapshotSha256", "sourceManifestSha256"):
            _sha(facts[key], f"{key} must be SHA-256")
        require(facts["networkAddressCount"] == state["networkAddressCount"], "Wave-one network count changed")
        require(facts["nonNetworkAddressCount"] == state["nonNetworkAddressCount"], "Wave-one non-network count changed")
    elif phase in ("wave-one-apply", "wave-two-apply"):
        plan = request["reviewedPlan"]
        require(isinstance(plan, dict), "Apply evidence requires a reviewed plan")
        for key in ("binaryPlanSha256", "planRecordSha256", "planTextSha256", "planJsonSha256"):
            _sha(facts[key], f"{key} must be SHA-256")
        require(facts["binaryPlanSha256"] == plan["binaryPlanSha256"], "Binary plan evidence changed")
        require(facts["planRecordSha256"] == plan["planRecordSha256"], "Plan record evidence changed")
        require(facts["humanReviewed"] is True, "Apply evidence is not human reviewed")
        require(facts["managedDeleteCount"] == plan["managedDeleteCount"], "Apply evidence delete count changed")
    elif phase == "post-wave-one-inventory":
        for key in ("stateSnapshotSha256", "historySnapshotSha256"):
            _sha(facts[key], f"{key} must be SHA-256")
        require(facts["eksAbsent"] is True, "Post-wave-one evidence requires EKS absence")
        require(facts["networkAddressCount"] == state["networkAddressCount"], "Post-wave-one network count changed")
        require(facts["nonNetworkAddressCount"] == 0, "Post-wave-one evidence contains non-network state")
    elif phase == "safe-residue-delete":
        residue = request["safeResidue"]
        require(isinstance(residue, dict), "Residue evidence requires an exact request binding")
        _sha(facts["dependencyInventorySha256"], "Dependency inventory must be SHA-256")
        _sha(facts["residueIdentitySha256"], "Residue identity must be SHA-256")
        require(facts["residueCategory"] == residue["category"], "Residue category changed")
        require(facts["residueIdentitySha256"] == residue["identitySha256"], "Residue identity changed")
        require(facts["exactBound"] is True and facts["deletionAlreadyAttempted"] is False, "Residue deletion evidence is not fresh and exact")
    elif phase == "wave-two-plan":
        for key in ("stateSnapshotSha256", "historySnapshotSha256", "dependencyInventorySha256"):
            _sha(facts[key], f"{key} must be SHA-256")
        for key in ("safeResidueCount", "unknownDependencyCount", "controllerOwnedDependencyCount"):
            require(_nonnegative_integer(facts[key], f"{key} changed") == 0, "Wave-two plan requires zero remaining dependencies")
    elif phase == "final-read-only-audit":
        for key in ("finalStateSha256", "absenceInventorySha256", "historySnapshotSha256"):
            _sha(facts[key], f"{key} must be SHA-256")
        require(_nonnegative_integer(facts["managedStateAddressCount"], "Final managed-state count changed") == 0, "Final audit requires empty managed state")
        require(facts["protectedFoundationPreserved"] is True, "Final audit must preserve the shared foundation")
    else:
        raise TeardownGateError("Unsupported phase evidence")


def verify_private_bundle(
    request_raw: bytes,
    evidence_raw: bytes,
    *,
    expected_request_sha256: str,
    expected_evidence_sha256: str,
    now_utc: datetime | str,
) -> dict[str, Any]:
    """Verify canonical private inputs and return only a redacted receipt."""

    _sha(expected_request_sha256, "Expected request digest changed")
    _sha(expected_evidence_sha256, "Expected evidence digest changed")
    request = decode_canonical(request_raw, "Request")
    evidence = decode_canonical(evidence_raw, "Evidence")
    request_digest = REQUEST.sha256(request)
    evidence_digest = REQUEST.sha256(evidence)
    require(request_digest == expected_request_sha256, "Private request digest changed")
    require(evidence_digest == expected_evidence_sha256, "Private evidence digest changed")
    require(request["inputEvidenceSha256"] == evidence_digest, "Request does not bind the private evidence")
    preflight = REQUEST.verify_request(request, now_utc=now_utc)
    facts = _gate_common_evidence(evidence, request)
    _gate_phase_facts(request["phase"], facts, request)

    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "status": "shared-two-wave-private-preflight-ready-for-separate-approval",
        "environment": request["environment"],
        "stateKey": request["stateKey"],
        "phase": request["phase"],
        "attemptNumber": request["attemptNumber"],
        "controlPlaneCommit": request["controlPlaneCommit"],
        "requestSha256": request_digest,
        "evidenceSha256": evidence_digest,
        "predecessorReceiptSha256": request["predecessorReceiptSha256"],
        "stateInventorySha256": request["state"]["managedAddressInventorySha256"],
        "requestedAuthority": preflight["requestedAuthority"],
        "observedAtUtc": evidence["observedAtUtc"],
        "verifiedAtUtc": preflight["verifiedAtUtc"],
        "expiresAtUtc": preflight["expiresAtUtc"],
        "privateInputFileCount": 2,
        "privatePathEmitted": False,
        "privateResourceIdentityEmitted": False,
        "liveCommandExecuted": False,
        "executionAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "nextAction": preflight["nextAction"],
    }
    return {
        "schemaVersion": RESULT_SCHEMA,
        "receipt": receipt,
        "receiptSha256": REQUEST.sha256(receipt),
    }


class StrictPrivateBundleReader:
    """Read exactly two owned canonical 0600 files through one owned 0700 dir."""

    def __init__(self, directory: Path):
        require(isinstance(directory, Path) and directory.is_absolute(), "Private bundle directory must be absolute")
        self.directory = directory

    @staticmethod
    def _read_file(directory_fd: int, name: str) -> bytes:
        file_fd = None
        try:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            require(stat.S_ISREG(before.st_mode), "Private input is not a regular file")
            require(stat.S_IMODE(before.st_mode) == 0o600, "Private input mode changed")
            require(before.st_uid == os.geteuid() and before.st_nlink == 1, "Private input ownership changed")
            require(0 < before.st_size <= MAX_PRIVATE_FILE_BYTES, "Private input size changed")
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            opened = os.fstat(file_fd)
            require(
                (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink, opened.st_size)
                == (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink, before.st_size),
                "Private input raced during open",
            )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(65536, MAX_PRIVATE_FILE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                require(total <= MAX_PRIVATE_FILE_BYTES, "Private input grew during read")
            after = os.fstat(file_fd)
            require(
                (after.st_dev, after.st_ino, after.st_mode, after.st_uid, after.st_nlink, after.st_size)
                == (before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink, before.st_size),
                "Private input changed during read",
            )
            return b"".join(chunks)
        except (OSError, TeardownGateError):
            raise PrivatePreflightStopped("private-input-read-stopped") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)

    def read(self) -> dict[str, bytes]:
        directory_fd = None
        try:
            directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            metadata = os.fstat(directory_fd)
            require(stat.S_ISDIR(metadata.st_mode), "Private bundle is not a directory")
            require(stat.S_IMODE(metadata.st_mode) == 0o700 and metadata.st_uid == os.geteuid(), "Private bundle scope changed")
            require(set(os.listdir(directory_fd)) == PRIVATE_FILENAMES, "Private bundle entries changed")
            request_raw = self._read_file(directory_fd, "request.json")
            evidence_raw = self._read_file(directory_fd, "evidence.json")
            return {"request": request_raw, "evidence": evidence_raw}
        except PrivatePreflightStopped:
            raise
        except (OSError, TeardownGateError):
            raise PrivatePreflightStopped("private-bundle-read-stopped") from None
        finally:
            if directory_fd is not None:
                os.close(directory_fd)


class SystemUtcClock:
    """Return one whole-second UTC reading and reject reuse."""

    def __init__(self):
        self._read = False

    def now(self) -> str:
        require(self._read is False, "System UTC clock may be read only once")
        self._read = True
        return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

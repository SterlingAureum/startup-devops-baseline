#!/usr/bin/env python3
"""Offline repository checker for append-only teardown receipt approvals."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.4-shared-dev-test-two-wave-teardown-receipt-approval"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module import failed: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    fixture_path = root / f"delivery/examples/{PREFIX}-fixtures.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.4_SHARED_DEV_TEST_TWO_WAVE_TEARDOWN_RECEIPT_APPROVAL.md"
    core_path = root / "scripts/aws_two_wave_teardown_receipt_approval.py"
    entrypoint_path = root / "scripts/approval-v0.12.4.1.5.0.7.1.6.4-shared-dev-test-two-wave-teardown.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.4", "version changed")
    require(contract["implementationBaselineCommit"] == "4511ddfe067b202e693a7d4f928c969bc8bdfd48", "baseline changed")
    store = contract["store"]
    require(store["rootMode"] == "0700" and store["childDirectoryMode"] == "0700" and store["recordMode"] == "0600", "private modes changed")
    require(store["exactRootDirectories"] == ["receipts", "approvals"], "store inventory changed")
    for key in ("receiptFilenameBoundToReceiptSha256", "approvalFilenameBoundToReceiptSha256", "exclusiveCreateRequired", "overwriteRejected", "fileFsyncRequired", "directoryFsyncRequired", "partialWritePreservedForReview"):
        require(store[key] is True, f"append-only control disabled: {key}")
    require(store["automaticRepair"] is False, "automatic repair enabled")
    persistence = contract["receiptPersistence"]
    for key in ("callerResultSha256Required", "receiptContentSha256Required", "activeReceiptRequired", "redactedReceiptRequired", "onePersistentCopyPerReceipt"):
        require(persistence[key] is True, f"receipt control disabled: {key}")
    require(persistence["approvalCreatedByPersistence"] is False, "persistence gained approval authority")
    approval = contract["approval"]
    require(approval["maximumWindowSeconds"] == 900, "approval window changed")
    for key in ("exactReceiptBindingRequired", "exactEnvironmentBindingRequired", "exactStateKeyBindingRequired", "exactPhaseBindingRequired", "exactAttemptBindingRequired", "exactControlPlaneCommitBindingRequired", "exactRequestedAuthorityBindingRequired", "canonicalApprovalStatementRequired", "humanApprovedRequired", "oneAttemptOnlyRequired", "cannotOutliveReceipt", "oneApprovalPerReceipt", "receiptConsumedByApproval"):
        require(approval[key] is True, f"approval binding disabled: {key}")
    require(approval["approvalConsumedByExecutor"] is False, "approval already consumed by an executor")
    entrypoint = contract["entrypoint"]
    require(entrypoint["path"] == str(entrypoint_path.relative_to(root)), "entrypoint changed")
    require(entrypoint["commands"] == ["persist-receipt", "record-approval"], "entrypoint commands changed")
    for key in ("readsHostUtcOncePerCommand", "readsOnlyPrivateLocalFiles", "writesOnlyPrivateLocalRecords"):
        require(entrypoint[key] is True, f"local entrypoint control disabled: {key}")
    for key in ("invokesSubprocess", "liveCommandExecuted", "executionPerformed"):
        require(entrypoint[key] is False, f"entrypoint gained execution: {key}")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["approvalMayBeRecorded"] is True, "local approval recording disabled")
    require(all(value is False for key, value in authority.items() if key != "approvalMayBeRecorded"), "execution authority pre-granted")
    require(not executor_path.exists(), "receipt approval checkpoint must not expose an executor")

    combined_source = core_path.read_text() + "\n" + entrypoint_path.read_text()
    for forbidden in ("import subprocess", "from subprocess", "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl "):
        require(forbidden not in combined_source, f"receipt approval source contains forbidden marker: {forbidden}")
    adapter = load_module(core_path, "receipt_approval_for_check")
    fixture = json.loads(fixture_path.read_text())
    source_fixture = json.loads((root / fixture["sourcePreflightFixture"]).read_text())
    source = source_fixture[fixture["sourceCase"]]
    preflight = adapter.PRIVATE.verify_private_bundle(
        adapter.REQUEST.canonical_bytes(source["request"]),
        adapter.REQUEST.canonical_bytes(source["evidence"]),
        expected_request_sha256=adapter.REQUEST.sha256(source["request"]),
        expected_evidence_sha256=adapter.REQUEST.sha256(source["evidence"]),
        now_utc=source_fixture["verificationClockUtc"],
    )
    receipt = adapter.validate_receipt_result(preflight, now_utc=fixture["persistenceClockUtc"])
    text = adapter.approval_text(receipt)
    timing = fixture["approvalTiming"]
    request = {
        "schemaVersion": adapter.APPROVAL_REQUEST_SCHEMA,
        "receiptSha256": preflight["receiptSha256"],
        "environment": receipt["environment"],
        "stateKey": receipt["stateKey"],
        "phase": receipt["phase"],
        "attemptNumber": receipt["attemptNumber"],
        "controlPlaneCommit": receipt["controlPlaneCommit"],
        "requestedAuthority": receipt["requestedAuthority"],
        "createdAtUtc": timing["createdAtUtc"],
        "notBeforeUtc": timing["notBeforeUtc"],
        "expiresAtUtc": timing["expiresAtUtc"],
        "approvalText": text,
        "approvalTextSha256": adapter.text_sha256(text),
        "humanApproved": True,
        "oneAttemptOnly": True,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
    }
    adapter.validate_approval_request(request, receipt, now_utc=fixture["approvalClockUtc"])
    require(receipt["environment"] == fixture["expectedEnvironment"], "fixture environment changed")
    require(receipt["phase"] == fixture["expectedPhase"], "fixture phase changed")
    require(receipt["requestedAuthority"] == fixture["expectedRequestedAuthority"], "fixture authority changed")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("append-only private store", "exclusive creation", "same receipt cannot produce a second approval", "implements no executor", "historical private execution evidence remains outside required ci"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.4"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.4 - Shared dev/test teardown receipt approval"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, entrypoint_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "receipt approval source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, entrypoint_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"approvalMayBeRecorded": True, "executorCount": 0, "liveCommandExecuted": False, "privateStoreDirectoryCount": 2, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Shared receipt approval check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

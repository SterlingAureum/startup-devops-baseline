#!/usr/bin/env python3
"""Offline repository checker for guarded private teardown preflight."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.3-shared-dev-test-two-wave-teardown-private-preflight"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.3_SHARED_DEV_TEST_TWO_WAVE_TEARDOWN_PRIVATE_PREFLIGHT.md"
    core_path = root / "scripts/aws_two_wave_teardown_private_preflight.py"
    entrypoint_path = root / "scripts/preflight-v0.12.4.1.5.0.7.1.6.3-shared-dev-test-two-wave-teardown.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.3", "version changed")
    require(contract["implementationBaselineCommit"] == "b662cd830f21ab3a6fc45f1527a24efb5817acad", "baseline changed")
    bundle = contract["privateBundle"]
    require(bundle["directoryMode"] == "0700" and bundle["fileMode"] == "0600", "private mode boundary changed")
    require(bundle["exactFiles"] == ["request.json", "evidence.json"], "private file inventory changed")
    require(bundle["maximumFileBytes"] == 1048576, "private file bound changed")
    for key in ("ownerRequired", "regularFileRequired", "singleHardLinkRequired", "symlinkRejected", "canonicalJsonRequired", "callerDigestRequired", "requestBindsEvidenceDigest"):
        require(bundle[key] is True, f"private bundle control disabled: {key}")
    evidence = contract["phaseEvidence"]
    require(evidence["phaseCount"] == 8 and evidence["maximumEvidenceAgeSeconds"] == 900, "phase evidence scope changed")
    require(all(value is True for key, value in evidence.items() if key not in ("phaseCount", "maximumEvidenceAgeSeconds")), "phase evidence binding weakened")
    receipt = contract["receipt"]
    require(receipt == {
        "redactedOnly": True,
        "sha256Returned": True,
        "futurePredecessorBindingSupported": True,
        "persistedByPreflight": False,
        "privatePathEmitted": False,
        "privateResourceIdentityEmitted": False,
        "executionAuthorized": False,
    }, "receipt boundary changed")
    entrypoint = contract["entrypoint"]
    require(entrypoint["path"] == str(entrypoint_path.relative_to(root)) and entrypoint["command"] == "verify", "entrypoint changed")
    require(entrypoint["confirmation"] == "observe-reviewed-shared-two-wave-private-preflight", "confirmation changed")
    require(entrypoint["readsHostUtcOnce"] is True and entrypoint["readsOnlyPrivateLocalFiles"] is True, "local read boundary changed")
    require(entrypoint["writesReceipt"] is False and entrypoint["invokesSubprocess"] is False and entrypoint["liveCommandExecuted"] is False, "entrypoint gained execution")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    require(all(value is False for value in contract["authority"].values()), "authority pre-granted")
    require(not executor_path.exists(), "private preflight checkpoint must not expose an executor")

    combined_source = core_path.read_text() + "\n" + entrypoint_path.read_text()
    for forbidden in ("import subprocess", "from subprocess", "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl "):
        require(forbidden not in combined_source, f"private preflight contains forbidden marker: {forbidden}")
    private = load_module(core_path, "private_preflight_for_check")
    fixture = json.loads(fixture_path.read_text())
    require(set(private.FACT_KEYS) == set(private.REQUEST.PHASES), "phase evidence implementation changed")
    for name in ("devWaveOnePlan", "testWaveTwoApply"):
        item = fixture[name]
        request = item["request"]
        phase_evidence = item["evidence"]
        result = private.verify_private_bundle(
            private.REQUEST.canonical_bytes(request),
            private.REQUEST.canonical_bytes(phase_evidence),
            expected_request_sha256=private.REQUEST.sha256(request),
            expected_evidence_sha256=private.REQUEST.sha256(phase_evidence),
            now_utc=fixture["verificationClockUtc"],
        )
        require(result["receipt"]["executionAuthorized"] is False, f"fixture gained authority: {name}")
        require(result["receiptSha256"] == private.REQUEST.sha256(result["receipt"]), f"receipt digest changed: {name}")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("strictly scoped local private evidence", "exactly `request.json` and `evidence.json`", "does not persist the receipt", "historical private evidence remains outside required ci", "grants no live"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.3"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.3 - Shared dev/test private teardown preflight"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, entrypoint_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "private preflight source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, entrypoint_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "executorCount": 0, "phaseEvidenceCount": 8, "privateFileCount": 2, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Shared private teardown preflight check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline repository checker for shared dev/test teardown request preflight."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.2-shared-dev-test-two-wave-teardown-request-preflight"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("two_wave_preflight_for_check", path)
    require(spec is not None and spec.loader is not None, "preflight import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    fixture_path = root / f"delivery/examples/{PREFIX}-fixtures.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.2_SHARED_DEV_TEST_TWO_WAVE_TEARDOWN_REQUEST_PREFLIGHT.md"
    adapter_path = root / "scripts/aws_two_wave_teardown_preflight.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.2", "version changed")
    require(contract["implementationBaselineCommit"] == "684015fb2c8988f42420cdd5852016a191ca9a49", "baseline changed")
    adapter = contract["adapter"]
    require(adapter["path"] == "scripts/aws_two_wave_teardown_preflight.py" and adapter["commandFree"] is True, "adapter boundary changed")
    require(adapter["supportedLiveProfiles"] == ["aws-dev", "aws-test"] and adapter["rejectedLiveProfiles"] == ["aws-prod"], "profile boundary changed")
    require(adapter["phaseCount"] == 8 and len(contract["phases"]) == 8, "phase inventory changed")
    for key in ("oneEnvironmentPerRequest", "onePhasePerRequest", "oneAttemptPerRequest", "exactStateKeyBinding", "exactControlPlaneCommitBinding", "exactInputEvidenceBinding", "exactPredecessorReceiptBinding", "remoteStateReadyRequired", "redactedResultOnly"):
        require(adapter[key] is True, f"request binding changed: {key}")
    require(contract["timeBoundary"] == {
        "planInventoryAndCleanupMaximumSeconds": 3600,
        "savedPlanApplyMaximumSeconds": 10800,
        "wholeSecondUtcRequired": True,
        "notBeforeEnforced": True,
        "expiryEnforced": True,
        "applyCannotOutlivePlanReview": True,
    }, "time boundary changed")
    require(all(contract["stateBoundary"].values()), "state boundary weakened")
    require(all(contract["applyBoundary"].values()), "apply boundary weakened")
    residue = contract["residueBoundary"]
    require(all(residue[key] is True for key in residue if key != "preflightDeletionAuthorized"), "residue binding weakened")
    require(residue["preflightDeletionAuthorized"] is False, "residue deletion pre-authorized")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    for section in ("packageProducer", "authority"):
        require(all(value is False for value in contract[section].values()), f"non-execution boundary changed: {section}")
    require(not executor_path.exists(), "preflight checkpoint must not expose an executor")

    source = adapter_path.read_text()
    for forbidden in ("import subprocess", "from subprocess", "import os", "from os", "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl "):
        require(forbidden not in source, f"command-free adapter contains forbidden marker: {forbidden}")
    module = load_module(adapter_path)
    require(list(module.PHASES) == contract["phases"], "implementation phase order changed")
    fixture = json.loads(fixture_path.read_text())
    clock = fixture["verificationClockUtc"]
    dev = module.verify_request(fixture["devWaveOnePlanRequest"], now_utc=clock)
    test = module.verify_request(fixture["testWaveTwoApplyRequest"], now_utc=clock)
    require(dev["environment"] == "aws-dev" and dev["requestedAuthority"] == "terraform-plan", "dev fixture changed")
    require(test["environment"] == "aws-test" and test["requestedAuthority"] == "terraform-apply", "test fixture changed")
    require(dev["executionAuthorized"] is False and test["executionAuthorized"] is False, "fixture gained authority")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("one environment, one phase", "rejects `aws-prod`", "does not grant deletion authority", "historical private execution evidence remains outside required ci", "exposes no executor", "grants no live"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.2"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.2 - Shared dev/test teardown request preflight"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, adapter_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "preflight source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (adapter_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "executorCount": 0, "environmentProfileCount": 2, "phaseCount": 8, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Shared teardown request preflight check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

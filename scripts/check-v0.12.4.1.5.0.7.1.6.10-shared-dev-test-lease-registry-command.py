#!/usr/bin/env python3
"""Offline repository checker for the strict lease-registry command."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.10-shared-dev-test-lease-registry-command"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.10_SHARED_DEV_TEST_LEASE_REGISTRY_COMMAND.md"
    composition_path = root / "scripts/aws_two_wave_teardown_lease_registry_composition.py"
    entrypoint_path = root / f"scripts/exercise-{PREFIX}.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    live_executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.10", "version changed")
    require(contract["implementationBaselineCommit"] == "281630a970695d6a902766812aa96938859fc54d", "baseline changed")
    profiles = contract["profiles"]
    require(profiles["supported"] == ["aws-dev", "aws-test"] and profiles["rejected"] == ["aws-prod"], "profile boundary changed")
    require(profiles["phaseCount"] == 8 and profiles["stateAndBackendIsolationInherited"] is True, "phase coverage changed")
    private = contract["privateInputs"]
    require(private["fileCount"] == 2, "private file count changed")
    for key, value in private.items():
        if key != "fileCount":
            require(value is True, f"private input control disabled: {key}")
    command = contract["commandBoundary"]
    require(command["path"] == str(entrypoint_path.relative_to(root)), "command path changed")
    require(command["confirmation"] == "consume-one-reviewed-approval-through-lease-owned-registry-fixed-fake", "confirmation changed")
    for key in ("readsHostUtcOnce", "invokesLeaseOwnedComposition", "exactFixedFakeBackendOnly", "genericRedactedFailure"):
        require(command[key] is True, f"command control disabled: {key}")
    for key in ("rawCommandArgumentAvailable", "failureInjectionArgumentAvailable", "credentialOrEndpointArgumentAvailable", "liveSwitchAvailable", "retrySwitchAvailable"):
        require(command[key] is False, f"unsafe command argument enabled: {key}")
    lifecycle = contract["leaseLifecycle"]
    for key in ("durableClaimBeforeFirstBackendCall", "writesOnlyPrivateClaimAndOutcomeRecords", "successReplayRejected", "failureReplayRejected", "claimOrOutcomeUncertaintyConsumesAttempt"):
        require(lifecycle[key] is True, f"lease lifecycle disabled: {key}")
    for key in ("automaticRetryAuthorized", "automaticRepairAuthorized", "automaticRollbackAuthorized"):
        require(lifecycle[key] is False, f"automatic recovery enabled: {key}")
    boundary = contract["implementationBoundary"]
    for key, value in boundary.items():
        require(value is False, f"command gained live capability: {key}")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["fixedFakeCommandExerciseAuthorized"] is True, "fixed-fake command disabled")
    require(all(value is False for key, value in authority.items() if key != "fixedFakeCommandExerciseAuthorized"), "live authority pre-granted")
    require(not live_executor_path.exists(), "command checkpoint must not expose a live executor")

    combined = composition_path.read_text() + "\n" + entrypoint_path.read_text()
    for forbidden in (
        "import subprocess", "from subprocess", "import boto3", "from boto3", "botocore",
        "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl ",
        "AWS_ACCESS_KEY",
    ):
        require(forbidden not in combined, f"command source contains forbidden marker: {forbidden}")
    cli = load_module(entrypoint_path, "lease_registry_command_for_check")
    require(cli.CONFIRMATION == command["confirmation"], "command confirmation constant changed")
    option_strings = {
        option
        for action in cli.parser()._actions
        for option in action.option_strings
        if option != "-h" and option != "--help"
    }
    require(option_strings == {
        "--approval-store-directory", "--execution-store-directory",
        "--execution-request-file", "--private-bindings-file",
        "--expected-execution-request-sha256", "--expected-private-bindings-sha256",
        "--expected-receipt-sha256", "--expected-approval-record-sha256", "--confirm",
    }, "command argument surface changed")

    fixture = json.loads(fixture_path.read_text())
    require(fixture["expectedEnvironment"] == "aws-dev" and fixture["expectedPhase"] == "wave-one-plan", "fixture case changed")
    require(fixture["expectedBackendCallCount"] == 7 and fixture["privateInputFileCount"] == 2 and fixture["hostClockReadCount"] == 1, "fixture counts changed")
    for key in ("expectedPrivateBindingsSha256", "expectedCommandResultSha256"):
        require(isinstance(fixture[key], str) and re.fullmatch(r"[0-9a-f]{64}", fixture[key]) is not None, f"fixture digest changed: {key}")
    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in (
        "distinct owned `0700` directory", "host utc once", "cannot accept a raw command",
        "stops on the existing claim before registry backend dispatch", "no automatic retry",
    ):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.10"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.10 - Shared dev/test lease registry command"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, entrypoint_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "command source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (entrypoint_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "privateInputFileCount": 2,
        "hostClockReadCount": 1,
        "fixedFakeOnly": True,
        "liveBackendAvailable": False,
        "liveCommandExecuted": False,
        "trackedFileCount": len(tracked_paths),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Lease registry command check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

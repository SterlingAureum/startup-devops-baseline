#!/usr/bin/env python3
"""Offline repository checker for the complete shared dev/test process chain."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.11_SHARED_DEV_TEST_OFFLINE_PROCESS_CHAIN.md"
    implementation_path = root / "scripts/aws_two_wave_teardown_offline_process_chain.py"
    entrypoint_path = root / f"scripts/exercise-{PREFIX}.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    live_executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.11", "version changed")
    require(contract["implementationBaselineCommit"] == "80bc9ee7981018da332554a2fa1ff6cee4e2440e", "baseline changed")
    fixture = json.loads(fixture_path.read_text())
    coverage = contract["coverage"]
    require(coverage["environmentOrder"] == fixture["expectedEnvironmentOrder"] == ["aws-dev", "aws-test"], "environment order changed")
    require(coverage["phaseOrder"] == fixture["expectedPhaseOrder"], "phase order changed")
    require(coverage["environmentCount"] == 2 and coverage["phaseCountPerEnvironment"] == 8, "coverage changed")
    require(coverage["freshProcessCount"] == 16 and coverage["fixedFakeBackendCallCount"] == 98, "process counts changed")
    require(sum(fixture["expectedBackendCallsByPhase"].values()) == 49, "phase call counts changed")

    process_boundary = contract["processBoundary"]
    for key in ("exactPredecessorCommandOnly", "freshProcessPerPhase", "fixedThirtySecondTimeout", "credentialEnvironmentForwarded"):
        expected = key != "credentialEnvironmentForwarded"
        require(process_boundary[key] is expected, f"process boundary changed: {key}")
    for key in ("shellAvailable", "callerRepositoryRootAvailable", "rawCommandArgumentAvailable", "failureInjectionArgumentAvailable", "liveSwitchAvailable", "retrySwitchAvailable"):
        require(process_boundary[key] is False, f"unsafe process surface enabled: {key}")
    private = contract["privateStoreBoundary"]
    for key in ("distinctApprovalStorePerPhase", "distinctExecutionStorePerPhase", "distinctRequestDirectoryPerPhase", "distinctBindingDirectoryPerPhase", "owned0700Directories", "owned0600CanonicalFiles", "temporaryStoresRemovedAtTerminalExit"):
        require(private[key] is True, f"private store control disabled: {key}")
    require(private["privatePathsEmitted"] is False and private["privateResourceIdentitiesEmitted"] is False, "private identity emission enabled")
    lifecycle = contract["lifecycle"]
    for key in ("syntheticReceiptAndApprovalOnly", "predecessorReceiptBoundPerEnvironment", "durableClaimAndOutcomeVerifiedPerPhase", "stopAtFirstFailure"):
        require(lifecycle[key] is True, f"lifecycle control disabled: {key}")
    for key in ("automaticRetryAuthorized", "automaticRepairAuthorized", "automaticRollbackAuthorized"):
        require(lifecycle[key] is False, f"automatic recovery enabled: {key}")
    boundary = contract["implementationBoundary"]
    require(boundary["subprocessAvailableInOfflineHarness"] is True, "offline subprocess boundary changed")
    require(all(value is False for key, value in boundary.items() if key != "subprocessAvailableInOfflineHarness"), "live capability enabled")
    authority = contract["authority"]
    require(authority["syntheticFixedFakeProcessExerciseAuthorized"] is True, "synthetic process exercise disabled")
    require(all(value is False for key, value in authority.items() if key != "syntheticFixedFakeProcessExerciseAuthorized"), "live authority pre-granted")
    require(not live_executor_path.exists(), "offline checkpoint must not expose a live executor")

    implementation = implementation_path.read_text()
    entrypoint = entrypoint_path.read_text()
    require(implementation.count("subprocess.run(") == 1, "subprocess call surface changed")
    require("shell=True" not in implementation and "shell=" not in implementation, "shell execution enabled")
    for forbidden in ("import boto3", "from boto3", "botocore", "os.system", "terraform apply", "terraform plan", "aws ec2", "kubectl ", "AWS_ACCESS_KEY"):
        require(forbidden not in implementation + "\n" + entrypoint, f"source contains forbidden live marker: {forbidden}")
    chain = load_module(implementation_path, "offline_process_chain_for_check")
    cli = load_module(entrypoint_path, "offline_process_chain_cli_for_check")
    require(chain.COMMAND_FILENAME == "exercise-v0.12.4.1.5.0.7.1.6.10-shared-dev-test-lease-registry-command.py", "child command changed")
    require(chain.PROCESS_TIMEOUT_SECONDS == 30, "process timeout changed")
    require(chain.ENVIRONMENTS == ("aws-dev", "aws-test"), "environment order changed")
    require(chain._child_environment() == {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "LANG": "C", "LC_ALL": "C"}, "child environment changed")
    require(cli.CONFIRMATION == "run-sixteen-synthetic-fixed-fake-phase-processes", "confirmation changed")
    option_strings = {
        option
        for action in cli.parser()._actions
        for option in action.option_strings
        if option not in ("-h", "--help")
    }
    require(option_strings == {"--confirm"}, "CLI argument surface changed")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("16 child processes", "98 deterministic fake backend calls", "without a shell", "minimal replacement environment", "no automatic retry"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.11"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.11 - Shared dev/test offline process chain"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, implementation_path, entrypoint_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "process-chain source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path, implementation_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (entrypoint_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "environmentCount": 2,
        "phaseCountPerEnvironment": 8,
        "freshProcessCount": 16,
        "fixedFakeBackendCallCount": 98,
        "credentialEnvironmentForwarded": False,
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
        parser.exit(1, f"Offline process-chain check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

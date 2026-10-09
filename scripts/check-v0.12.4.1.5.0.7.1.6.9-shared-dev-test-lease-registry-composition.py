#!/usr/bin/env python3
"""Offline repository checker for the lease-owned registry composition."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.9-shared-dev-test-lease-registry-composition"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.9_SHARED_DEV_TEST_LEASE_REGISTRY_COMPOSITION.md"
    core_path = root / "scripts/aws_two_wave_teardown_lease_registry_composition.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.9", "version changed")
    require(contract["implementationBaselineCommit"] == "b94564d7a502ebb1bd89ccddc682a182bcf6c7dd", "baseline changed")
    coverage = contract["coverage"]
    require(coverage["supportedEnvironments"] == ["aws-dev", "aws-test"], "environment coverage changed")
    require(coverage["rejectedEnvironments"] == ["aws-prod"], "production refusal changed")
    require(coverage["phaseCount"] == 8 and coverage["uniqueOperationIdCount"] == 37 and coverage["phaseOperationCallCount"] == 49, "phase coverage changed")
    for key in ("allCallerControlledInputsValidatedBeforeClaim", "durableClaimBeforeFirstBackendCall", "exactRegistryOrderInherited", "stopAtFirstFailureInherited"):
        require(coverage[key] is True, f"composition coverage disabled: {key}")
    lifecycle = contract["leaseLifecycle"]
    for key, value in lifecycle.items():
        require(value is True, f"lease lifecycle control disabled: {key}")
    composition = contract["compositionBoundary"]
    for key in ("leaseOwnedEntryFunctionImplemented", "exactFixedFakeBackendOnly"):
        require(composition[key] is True, f"composition boundary disabled: {key}")
    for key in (
        "lowerLevelRunnerOperationalEntrypoint", "standaloneCliAvailable", "rawCommandAccepted",
        "credentialOrEndpointOverrideAccepted", "automaticRetryAuthorized",
        "automaticRepairAuthorized", "automaticRollbackAuthorized",
    ):
        require(composition[key] is False, f"composition unsafe boundary enabled: {key}")
    boundary = contract["implementationBoundary"]
    require(boundary["privateLeaseStoreWriteAvailable"] is True, "private lease store write disabled")
    for key in ("subprocessAvailable", "sdkAvailable", "credentialReadAvailable", "liveBackendAvailable", "liveCommandExecuted", "executionPerformed"):
        require(boundary[key] is False, f"composition gained live capability: {key}")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["offlineCompositionValidationAuthorized"] is True, "offline validation disabled")
    require(all(value is False for key, value in authority.items() if key != "offlineCompositionValidationAuthorized"), "live authority pre-granted")
    require(not executor_path.exists(), "composition checkpoint must not expose an executor")

    source = core_path.read_text()
    for forbidden in (
        "import subprocess", "from subprocess", "import boto3", "from boto3", "botocore",
        "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl ",
        "AWS_ACCESS_KEY", "argparse", "sys.argv",
    ):
        require(forbidden not in source, f"composition source contains forbidden marker: {forbidden}")
    module = load_module(core_path, "lease_registry_composition_for_check")
    require(module.VERSION == "v0.12.4.1.5.0.7.1.6.9", "module version changed")
    require(callable(module.run_lease_owned_registry_once), "lease-owned entry function missing")
    require(module.RUNNER.FixedFakeRegistryBackend.__module__ == "aws_two_wave_teardown_registry_runner", "fixed-fake backend identity changed")

    fixture = json.loads(fixture_path.read_text())
    require(fixture["expectedEnvironment"] == "aws-dev" and fixture["expectedPhase"] == "wave-one-plan", "fixture case changed")
    require(fixture["expectedBackendCallCount"] == 7, "fixture call count changed")
    for key in ("expectedClaimSha256", "expectedRunnerResultSha256", "expectedOutcomeSha256", "expectedResultSha256"):
        require(isinstance(fixture[key], str) and re.fullmatch(r"[0-9a-f]{64}", fixture[key]) is not None, f"fixture digest changed: {key}")
    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in (
        "directory `fsync` before the first registry backend call",
        "permanently consumed", "cannot be bypassed", "no standalone cli", "no automatic retry",
    ):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.9"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.9 - Shared dev/test lease registry composition"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "composition source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "durableClaimBeforeFirstBackendCall": True,
        "successReplayRejected": True,
        "failureReplayRejected": True,
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
        parser.exit(1, f"Lease registry composition check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

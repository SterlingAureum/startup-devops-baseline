#!/usr/bin/env python3
"""Offline repository checker for closed shared dev/test phase drivers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.6-shared-dev-test-phase-drivers"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.6_SHARED_DEV_TEST_PHASE_DRIVERS.md"
    core_path = root / "scripts/aws_two_wave_teardown_phase_drivers.py"
    entrypoint_path = root / f"scripts/exercise-{PREFIX}.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    live_executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.6", "version changed")
    require(contract["implementationBaselineCommit"] == "3d6dfda64d2992a5caa488ba1c640ffa13a63678", "baseline changed")
    profiles = contract["profiles"]
    require(profiles["supported"] == ["aws-dev", "aws-test"], "supported profiles changed")
    require(profiles["rejected"] == ["aws-prod"], "production refusal changed")
    for key in ("exactStateKeyRequired", "exactTerraformRootRequired", "exactBackendConfigDeclarationRequired", "crossEnvironmentSpecRejected"):
        require(profiles[key] is True, f"profile binding disabled: {key}")
    phases = contract["phaseSpecs"]
    require(phases["phaseCount"] == 8 and phases["totalOperationCount"] == 49, "phase inventory changed")
    for key in ("orderedClosedOperationIds", "executionSpecSha256Required", "requestedAuthorityBindingRequired", "effectClassBindingRequired", "requiredPrivateDigestNamesBound"):
        require(phases[key] is True, f"phase spec binding disabled: {key}")
    for key in ("rawCommandAllowed", "dynamicCommandTemplateAllowed", "credentialOrEndpointOverrideAllowed"):
        require(phases[key] is False, f"phase spec gained unsafe input: {key}")
    lease = contract["leaseIntegration"]
    for key in ("immutableApprovalRevalidated", "executionRequestRevalidated", "exactExecutionSpecSha256Required", "durableExclusiveClaimBeforeFirstOperation", "oneApprovalAttemptOnly", "claimOnlyBlocksRetry", "failureOutcomeBlocksRetry", "successOutcomeBlocksRetry", "outcomeUncertaintyBlocksRetry"):
        require(lease[key] is True, f"lease control disabled: {key}")
    require(lease["automaticRetry"] is False and lease["automaticRepair"] is False and lease["automaticRollback"] is False, "automatic recovery enabled")
    transport = contract["transport"]
    for key in ("fixedFakeOnly", "exactTypeRequired", "oneCallPerOperationId", "orderedDispatchRequired", "stopAtFirstFailure"):
        require(transport[key] is True, f"transport control disabled: {key}")
    for key in ("subprocessAvailable", "sdkAvailable", "credentialReadAvailable", "liveBackendAvailable", "liveCommandExecuted", "executionPerformed"):
        require(transport[key] is False, f"transport gained live capability: {key}")
    entrypoint = contract["entrypoint"]
    require(entrypoint["path"] == str(entrypoint_path.relative_to(root)), "entrypoint changed")
    require(entrypoint["confirmation"] == "consume-one-approval-for-reviewed-fixed-fake-phase-driver", "entrypoint confirmation changed")
    require(entrypoint["readsHostUtcOnce"] is True and entrypoint["readsOnlyPrivateLocalFiles"] is True and entrypoint["writesOnlyPrivateLocalRecords"] is True, "entrypoint local boundary changed")
    require(entrypoint["invokesSubprocess"] is False and entrypoint["liveCommandExecuted"] is False and entrypoint["executionPerformed"] is False, "entrypoint gained execution")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["fixedFakeDriverExerciseAuthorized"] is True, "fixed fake disabled")
    require(all(value is False for key, value in authority.items() if key != "fixedFakeDriverExerciseAuthorized"), "live authority pre-granted")
    require(not live_executor_path.exists(), "phase-driver checkpoint must not expose a live executor")

    combined = core_path.read_text() + "\n" + entrypoint_path.read_text()
    for forbidden in (
        "import subprocess", "from subprocess", "import boto3", "from boto3", "botocore",
        "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl ",
        "AWS_ACCESS_KEY",
    ):
        require(forbidden not in combined, f"phase-driver source contains forbidden marker: {forbidden}")

    drivers = load_module(core_path, "shared_phase_drivers_for_check")
    fixture = json.loads(fixture_path.read_text())
    require(list(drivers.PHASE_OPERATIONS) == [
        "controller-cleanup", "wave-one-plan", "wave-one-apply", "post-wave-one-inventory",
        "safe-residue-delete", "wave-two-plan", "wave-two-apply", "final-read-only-audit",
    ], "phase order changed")
    require({key: len(value) for key, value in drivers.PHASE_OPERATIONS.items()} == fixture["phaseOperationCounts"], "operation counts changed")
    require(sum(map(len, drivers.PHASE_OPERATIONS.values())) == 49, "total operation count changed")
    digests = set()
    for environment in profiles["supported"]:
        for phase in drivers.PHASE_OPERATIONS:
            value = drivers.phase_driver_spec(environment, phase)
            require(drivers.validate_phase_driver_spec(value, environment=environment, phase=phase) == value, "canonical phase spec changed")
            require(value["operationIds"] == list(drivers.PHASE_OPERATIONS[phase]), "operation order changed")
            require(value["simulationOnly"] is True and value["liveBackendAvailable"] is False, "phase spec gained live backend")
            digests.add(drivers.execution_spec_sha256(environment, phase))
    require(len(digests) == 16, "environment/phase specs are not uniquely bound")
    require(drivers.execution_spec_sha256(fixture["expectedEnvironment"], fixture["expectedPhase"]) == fixture["expectedExecutionSpecSha256"], "fixture execution spec digest changed")
    try:
        drivers.phase_driver_spec("aws-prod", "wave-one-plan")
    except Exception as error:
        require(type(error).__name__ == "TeardownGateError", "production refusal error changed")
    else:
        raise ContractError("production phase spec became available")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("49 ordered operation ids", "remains rejected", "exclusive durable claim", "forbid retry or repair", "no aws, terraform, kubernetes, s3 or state command"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.6"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.6 - Shared dev/test phase drivers"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, entrypoint_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "phase-driver source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, entrypoint_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "environmentProfileCount": 2,
        "phaseSpecCount": 8,
        "operationIdCount": 49,
        "fixedFakeOnly": True,
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
        parser.exit(1, f"Shared phase-driver check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

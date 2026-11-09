#!/usr/bin/env python3
"""Offline repository checker for the claim-bound command-registry runner."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.8-shared-dev-test-claimed-registry-runner"
NOW = "2026-10-09T10:05:00Z"


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


def sample_claim(module, environment: str, phase: str) -> dict:
    spec = module.DRIVERS.phase_driver_spec(environment, phase)
    return {
        "schemaVersion": module.DRIVERS.CLAIM_SCHEMA,
        "status": "approval-consumed-before-fixed-fake-phase-dispatch",
        "receiptSha256": "1" * 64,
        "approvalRecordSha256": "2" * 64,
        "executionRequestSha256": "3" * 64,
        "executionSpecSha256": module.REQUEST.sha256(spec),
        "environment": environment,
        "stateKey": spec["stateKey"],
        "phase": phase,
        "attemptNumber": 1,
        "controlPlaneCommit": "4" * 40,
        "requestedAuthority": spec["requestedAuthority"],
        "operationSetSha256": module.REQUEST.sha256(spec["operationIds"]),
        "operationCount": len(spec["operationIds"]),
        "claimedAtUtc": "2026-10-09T10:00:00Z",
        "expiresAtUtc": "2026-10-09T10:15:00Z",
        "oneAttemptOnly": True,
        "approvalConsumedByLease": True,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
        "simulationOnly": True,
        "liveCommandExecuted": False,
        "executionPerformed": False,
    }


def sample_bindings(module, claim: dict) -> dict[str, str]:
    spec = module.DRIVERS.phase_driver_spec(claim["environment"], claim["phase"])
    result = {name: format(index + 10, "064x") for index, name in enumerate(spec["requiredPrivateBindings"])}
    for key in ("receiptSha256", "approvalRecordSha256", "executionRequestSha256"):
        result[key] = claim[key]
    return result


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    fixture_path = root / f"delivery/examples/{PREFIX}-fixtures.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.8_SHARED_DEV_TEST_CLAIMED_REGISTRY_RUNNER.md"
    core_path = root / "scripts/aws_two_wave_teardown_registry_runner.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.8", "version changed")
    require(contract["implementationBaselineCommit"] == "d759cb6232638c36ebbea6c91f43969d4ad6042b", "baseline changed")
    coverage = contract["coverage"]
    require(coverage["supportedEnvironments"] == ["aws-dev", "aws-test"], "environment coverage changed")
    require(coverage["rejectedEnvironments"] == ["aws-prod"], "production refusal changed")
    require(coverage["phaseCount"] == 8 and coverage["environmentPhaseRunCount"] == 16, "phase coverage changed")
    require(coverage["phaseOperationCallCountAcrossEnvironments"] == 98, "call coverage changed")
    for key in (
        "durableClaimDigestBound", "manifestDigestBound", "operationOrderBoundBeforeFirstCall",
        "privateBindingNamesAndDigestsBoundBeforeFirstCall", "claimCommonBindingsMatched",
        "stopAtFirstFailure", "malformedResponseRejected",
    ):
        require(coverage[key] is True, f"runner binding disabled: {key}")
    backend = contract["backend"]
    for key in ("exactFixedFakeTypeRequired", "singleBackendInstanceUse", "oneCallPerOperationId", "perOperationBindingSubsetRequired"):
        require(backend[key] is True, f"backend invariant disabled: {key}")
    for key in ("rawCommandAccepted", "dynamicCommandTemplateAccepted", "credentialOrEndpointOverrideAccepted", "automaticRetryAuthorized", "automaticRepairAuthorized"):
        require(backend[key] is False, f"unsafe backend input enabled: {key}")
    replay = contract["replayBoundary"]
    require(replay == {
        "durableClaimMustAlreadyExist": True,
        "runnerCreatesClaim": False,
        "runnerOwnsDurableReplayPrevention": False,
        "leaseStoreRemainsReplayAuthority": True,
        "standaloneLiveEntrypointAvailable": False,
    }, "durable replay ownership changed")
    boundary = contract["implementationBoundary"]
    require(boundary["claimedRegistryRunnerImplemented"] is True and boundary["fixedFakeBackendImplemented"] is True, "runner implementation disabled")
    for key in ("subprocessAvailable", "sdkAvailable", "credentialReadAvailable", "filesystemWriteAvailable", "liveBackendAvailable", "liveCommandExecuted", "executionPerformed"):
        require(boundary[key] is False, f"runner gained live capability: {key}")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["offlineRunnerValidationAuthorized"] is True, "offline validation disabled")
    require(all(value is False for key, value in authority.items() if key != "offlineRunnerValidationAuthorized"), "live authority pre-granted")
    require(not executor_path.exists(), "runner checkpoint must not expose an executor")

    source = core_path.read_text()
    for forbidden in (
        "import subprocess", "from subprocess", "import boto3", "from boto3", "botocore",
        "import os", "from pathlib", "open(", "os.system", "shell=True", "terraform apply",
        "terraform plan", "aws ec2", "kubectl ", "AWS_ACCESS_KEY",
    ):
        require(forbidden not in source, f"runner source contains forbidden marker: {forbidden}")

    module = load_module(core_path, "claimed_registry_runner_for_check")
    fixture = json.loads(fixture_path.read_text())
    phase_count = 0
    call_count = 0
    for environment in coverage["supportedEnvironments"]:
        for phase, operations in module.DRIVERS.PHASE_OPERATIONS.items():
            claim = sample_claim(module, environment, phase)
            claim_sha = module.REQUEST.sha256(claim)
            requests = module.build_claimed_operation_requests(claim, expected_claim_sha256=claim_sha, now_utc=NOW)
            fake = module.FixedFakeRegistryBackend()
            result = module.run_claimed_registry_once(
                claim=claim,
                expected_claim_sha256=claim_sha,
                phase_command_manifest=module.REGISTRY.phase_command_manifest(environment, phase),
                operation_requests=requests,
                private_bindings=sample_bindings(module, claim),
                now_utc=NOW,
                backend=fake,
            )
            require([row["operationId"] for row in fake.calls] == list(operations), "backend operation order changed")
            require(result["operationCallCount"] == len(operations), "result call count changed")
            require(result["liveCommandExecuted"] is False and result["executionPerformed"] is False, "runner gained execution")
            phase_count += 1
            call_count += len(fake.calls)
    require(phase_count == fixture["environmentPhaseRunCount"], "fixture phase count changed")
    require(call_count == fixture["phaseOperationCallCountAcrossEnvironments"], "fixture call count changed")

    claim = sample_claim(module, fixture["expectedEnvironment"], fixture["expectedPhase"])
    claim_sha = module.REQUEST.sha256(claim)
    fake = module.FixedFakeRegistryBackend()
    result = module.run_claimed_registry_once(
        claim=claim,
        expected_claim_sha256=claim_sha,
        phase_command_manifest=module.REGISTRY.phase_command_manifest(claim["environment"], claim["phase"]),
        operation_requests=module.build_claimed_operation_requests(claim, expected_claim_sha256=claim_sha, now_utc=NOW),
        private_bindings=sample_bindings(module, claim),
        now_utc=NOW,
        backend=fake,
    )
    require(result["claimSha256"] == fixture["expectedClaimSha256"], "claim fixture digest changed")
    require(result["phaseCommandManifestSha256"] == fixture["expectedPhaseCommandManifestSha256"], "manifest fixture digest changed")
    require(result["operationManifestSha256"] == fixture["expectedOperationManifestSha256"], "operation fixture digest changed")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("before its first backend call", "durable lease remains the replay authority", "not a standalone execution entrypoint", "no subprocess", "no automatic retry"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.8"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.8 - Shared dev/test claimed registry runner"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "claimed runner source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "environmentPhaseRunCount": phase_count,
        "phaseOperationCallCountAcrossEnvironments": call_count,
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
        parser.exit(1, f"Claimed registry runner check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

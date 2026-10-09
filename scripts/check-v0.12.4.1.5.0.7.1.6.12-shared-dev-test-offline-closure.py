#!/usr/bin/env python3
"""Validate the frozen offline teardown proof and explicit live-readiness gap."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.12-shared-dev-test-offline-closure"
BASELINE = "5c6b4d446d2fcf9be75cc0c82cf0edcb40909cd4"
FROZEN_MANIFEST_SHA256 = "17ab60904ee78b936bc4d57f4d7e36c47db7adf081bbca6e43a450567782ca11"
FROZEN_PATHS = [
    "scripts/aws_two_wave_teardown_core.py",
    "scripts/aws_two_wave_teardown_preflight.py",
    "scripts/aws_two_wave_teardown_private_preflight.py",
    "scripts/aws_two_wave_teardown_receipt_approval.py",
    "scripts/aws_two_wave_teardown_execution_lease.py",
    "scripts/aws_two_wave_teardown_phase_drivers.py",
    "scripts/aws_two_wave_teardown_command_registry.py",
    "scripts/aws_two_wave_teardown_registry_runner.py",
    "scripts/aws_two_wave_teardown_lease_registry_composition.py",
    "scripts/exercise-v0.12.4.1.5.0.7.1.6.10-shared-dev-test-lease-registry-command.py",
    "scripts/aws_two_wave_teardown_offline_process_chain.py",
    "scripts/exercise-v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain.py",
    "delivery/contracts/v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain.json",
    "delivery/examples/v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain-fixtures.json",
    "docs/V0.12.4.1.5.0.7.1.6.11_SHARED_DEV_TEST_OFFLINE_PROCESS_CHAIN.md",
    "scripts/check-v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain.py",
    "scripts/test-v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain.py",
    "scripts/validate-v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain.sh",
]
GAP_IDS = [
    "live-command-adapters",
    "runtime-cloud-identity-binding",
    "live-toolchain-and-backend-binding",
    "live-output-and-eventual-consistency-contracts",
    "live-partial-failure-recovery",
    "fresh-aws-test-and-prod-qualification",
    "remote-state-backend-retirement",
]


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_contract(contract: dict, fixture: dict) -> dict:
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.12", "version changed")
    require(contract["status"] == "shared-dev-test-offline-chain-frozen-live-readiness-explicit", "status changed")
    require(contract["repository"] == "SterlingAureum/startup-devops-baseline", "repository changed")
    require(contract["implementationBaselineCommit"] == BASELINE, "baseline changed")
    require(contract["predecessor"] == "delivery/contracts/v0.12.4.1.5.0.7.1.6.11-shared-dev-test-offline-process-chain.json", "predecessor changed")
    frozen = contract["frozenArtifacts"]
    require(len(frozen) == fixture["expectedFrozenArtifactCount"] == 18, "frozen artifact count changed")
    require(list(frozen) == FROZEN_PATHS, "frozen artifact inventory changed")
    frozen_manifest_sha = hashlib.sha256(
        json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    require(frozen_manifest_sha == FROZEN_MANIFEST_SHA256, "frozen artifact manifest changed")
    for path, digest in frozen.items():
        require(not Path(path).is_absolute() and ".." not in Path(path).parts, "frozen artifact path escaped repository")
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, f"invalid frozen digest: {path}")

    proof = contract["offlineProof"]
    require(proof["supportedEnvironments"] == fixture["expectedEnvironmentOrder"] == ["aws-dev", "aws-test"], "offline environment boundary changed")
    require(proof["rejectedEnvironment"] == "aws-prod", "production exclusion changed")
    require(proof["phaseCountPerEnvironment"] == fixture["expectedPhaseCountPerEnvironment"] == 8, "phase count changed")
    require(proof["freshProcessCount"] == fixture["expectedFreshProcessCount"] == 16, "process count changed")
    require(proof["fixedFakeBackendCallCount"] == fixture["expectedFixedFakeBackendCallCount"] == 98, "backend call count changed")
    for key in ("durableSingleUseLeaseVerified", "stopAtFirstFailureVerified"):
        require(proof[key] is True, f"offline proof disabled: {key}")
    for key in ("credentialEnvironmentForwarded", "privateResourceIdentityEmitted", "liveCommandExecuted"):
        require(proof[key] is False, f"offline safety boundary changed: {key}")

    gaps = contract["liveReadinessGaps"]
    require([gap["id"] for gap in gaps] == fixture["expectedLiveReadinessGapIds"] == GAP_IDS, "live-readiness gap inventory changed")
    require(len(gaps) == fixture["expectedLiveReadinessGapCount"] == 7, "live-readiness gap count changed")
    for gap in gaps:
        require(gap == {
            "id": gap["id"],
            "status": "not-implemented",
            "blocksOfflineClosure": False,
            "blocksLiveExecutionClaim": True,
        }, f"live-readiness gap relaxed: {gap['id']}")

    state = contract["stateBackendBoundary"]
    require(state == {
        "applicationTeardownMayDeleteRemoteStateBackend": False,
        "backendRetirementRequiresSeparatePlanReviewAndApproval": True,
        "stateHistoryRetentionPolicyRequired": True,
        "automaticBackendRetirementAuthorized": False,
    }, "remote-state backend boundary changed")
    implementation = contract["implementationBoundary"]
    require(implementation == {
        "runtimeSourceAdded": False,
        "commandEntrypointAdded": False,
        "subprocessAdded": False,
        "sdkAdded": False,
        "credentialReadAdded": False,
        "liveBackendAdded": False,
        "liveCommandExecuted": False,
    }, "runtime or live implementation boundary changed")
    require(implementation["runtimeSourceAdded"] == fixture["expectedRuntimeSourceAdded"], "runtime fixture changed")
    require(implementation["commandEntrypointAdded"] == fixture["expectedCommandEntrypointAdded"], "entrypoint fixture changed")
    authority = contract["authority"]
    require(authority == {
        "offlineClosureValidationAuthorized": True,
        "livePhaseExecutionAuthorized": False,
        "controllerMutationAuthorized": False,
        "terraformPlanAuthorized": False,
        "terraformApplyAuthorized": False,
        "directAwsMutationAuthorized": False,
        "statePushAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "backendRetirementAuthorized": False,
    }, "closure authority boundary changed")
    require(contract["ciBoundary"] == {
        "activeClosureContract": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    require(contract["nextCheckpoint"] == "perform-v0.12-scope-closure-without-live-adapter-expansion", "next checkpoint changed")
    return {
        "frozenArtifactCount": len(frozen),
        "liveReadinessGapCount": len(gaps),
        "offlineClosureReady": True,
        "liveExecutionReady": False,
        "liveCommandExecuted": False,
    }


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    fixture_path = root / f"delivery/examples/{PREFIX}-fixtures.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.12_SHARED_DEV_TEST_OFFLINE_CLOSURE.md"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    contract = json.loads(contract_path.read_text())
    fixture = json.loads(fixture_path.read_text())
    result = validate_contract(contract, fixture)

    for relative, digest in contract["frozenArtifacts"].items():
        path = root / relative
        require(path.is_file() and not path.is_symlink(), f"frozen artifact missing or linked: {relative}")
        require(file_sha256(path) == digest, f"frozen artifact digest changed: {relative}")
    for forbidden in (
        root / "scripts/aws_two_wave_teardown_offline_closure.py",
        root / f"scripts/exercise-{PREFIX}.py",
        root / f"scripts/execute-{PREFIX}.py",
    ):
        require(not forbidden.exists(), f"closure checkpoint gained runtime source: {forbidden.name}")

    serialized = json.dumps({"contract": contract, "fixture": fixture}, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized, re.IGNORECASE) is None, f"closure evidence contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in (
        "freezes 18 active artifacts",
        "seven capabilities remain deliberately unimplemented",
        "blocks a claim of live execution readiness",
        "application teardown cannot delete its remote-state s3 backend",
        "adds no runtime module",
    ):
        require(phrase in document, f"closure documentation missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.12"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.12 - Shared dev/test offline closure"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "closure source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    result["trackedFileCount"] = len(tracked_paths)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Offline closure check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

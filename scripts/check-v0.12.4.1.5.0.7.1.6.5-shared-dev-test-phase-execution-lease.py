#!/usr/bin/env python3
"""Offline repository checker for the single-use phase execution lease."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.5-shared-dev-test-phase-execution-lease"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.5_SHARED_DEV_TEST_PHASE_EXECUTION_LEASE.md"
    core_path = root / "scripts/aws_two_wave_teardown_execution_lease.py"
    entrypoint_path = root / "scripts/exercise-v0.12.4.1.5.0.7.1.6.5-shared-dev-test-phase-execution-lease.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    live_executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.5", "version changed")
    require(contract["implementationBaselineCommit"] == "fea06699cbe355e85e96074d97d4f601bebcbda0", "baseline changed")
    approval = contract["approvalInput"]
    require(all(value is True for value in approval.values()), "approval input binding weakened")
    request = contract["executionRequest"]
    require(request["maximumWindowSeconds"] == 900, "execution window changed")
    for key in ("callerDigestRequired", "executionSpecSha256Required", "humanReviewedRequired", "oneAttemptOnlyRequired", "cannotOutliveApproval", "simulationOnly"):
        require(request[key] is True, f"execution request control disabled: {key}")
    require(request["liveExecutionAuthorized"] is False, "live execution pre-authorized")
    store = contract["executionStore"]
    require(store["rootMode"] == "0700" and store["childDirectoryMode"] == "0700" and store["recordMode"] == "0600", "execution store modes changed")
    require(store["exactRootDirectories"] == ["claims", "outcomes"], "execution store inventory changed")
    for key in ("claimFilenameBoundToApprovalRecordSha256", "outcomeFilenameBoundToApprovalRecordSha256", "exclusiveCreateRequired", "claimFsyncBeforeDriverCall", "fileFsyncRequired", "directoryFsyncRequired", "overwriteRejected", "partialWritePreservedForReview"):
        require(store[key] is True, f"execution store control disabled: {key}")
    require(store["automaticRepair"] is False, "automatic repair enabled")
    single = contract["singleUseBoundary"]
    for key in ("approvalRecordRemainsImmutable", "claimRepresentsExecutorConsumption", "oneClaimPerApprovalRecord", "claimExistsBeforeDriverCall", "claimWithoutOutcomeBlocksRetry", "failureOutcomeBlocksRetry", "successOutcomeBlocksRetry"):
        require(single[key] is True, f"single-use control disabled: {key}")
    require(single["automaticRetry"] is False and single["automaticRollback"] is False, "automatic recovery enabled")
    driver = contract["driver"]
    require(driver["fixedFakeOnly"] is True and driver["exactTypeRequired"] is True and driver["callCount"] == 1, "fixed-fake boundary changed")
    for key in ("subprocessAvailable", "sdkAvailable", "credentialReadAvailable", "liveBackendAvailable", "liveCommandExecuted", "executionPerformed"):
        require(driver[key] is False, f"driver gained live capability: {key}")
    entrypoint = contract["entrypoint"]
    require(entrypoint["path"] == str(entrypoint_path.relative_to(root)), "entrypoint changed")
    require(entrypoint["command"] == "fixed-fake-exercise-only", "entrypoint command changed")
    require(entrypoint["confirmation"] == "consume-one-reviewed-approval-with-fixed-fake-only", "entrypoint confirmation changed")
    for key in ("readsHostUtcOnce", "readsOnlyPrivateLocalFiles", "writesOnlyPrivateLocalRecords"):
        require(entrypoint[key] is True, f"entrypoint local boundary disabled: {key}")
    for key in ("invokesSubprocess", "liveCommandExecuted", "executionPerformed"):
        require(entrypoint[key] is False, f"entrypoint gained execution: {key}")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["fixedFakeExerciseAuthorized"] is True, "fixed fake disabled")
    require(all(value is False for key, value in authority.items() if key != "fixedFakeExerciseAuthorized"), "live authority pre-granted")
    require(not live_executor_path.exists(), "lease checkpoint must not expose a live executor")

    combined = core_path.read_text() + "\n" + entrypoint_path.read_text()
    for forbidden in (
        "import subprocess",
        "from subprocess",
        "import boto3",
        "from boto3",
        "botocore",
        "os.system",
        "shell=True",
        "terraform apply",
        "terraform plan",
        "aws ec2",
        "kubectl ",
        "AWS_ACCESS_KEY",
    ):
        require(forbidden not in combined, f"lease source contains forbidden marker: {forbidden}")

    lease = load_module(core_path, "execution_lease_for_check")
    fixture = json.loads(fixture_path.read_text())
    approval_fixture = json.loads((root / fixture["sourceApprovalFixture"]).read_text())
    require(fixture["expectedExecutionStoreDirectories"] == ["claims", "outcomes"], "fixture store inventory changed")
    require(fixture["expectedEnvironment"] == "aws-dev", "fixture environment changed")
    require(fixture["expectedPhase"] == "wave-one-plan", "fixture phase changed")
    require(fixture["expectedRequestedAuthority"] == "terraform-plan", "fixture authority changed")
    require(lease.REQUEST.SHA256.fullmatch(fixture["executionSpecSha256"]) is not None, "fixture execution spec digest changed")
    timing = fixture["executionTiming"]
    require(timing["notBeforeUtc"] == fixture["executionClockUtc"], "fixture execution clock changed")
    require(timing["expiresAtUtc"] <= approval_fixture["approvalTiming"]["expiresAtUtc"], "fixture outlives approval")
    fake = lease.FixedFakePhaseDriver()
    request_shape = {
        "schemaVersion": lease.EXECUTION_REQUEST_SCHEMA,
        "receiptSha256": "1" * 64,
        "approvalRecordSha256": "2" * 64,
        "environment": fixture["expectedEnvironment"],
        "stateKey": "environments/dev/terraform.tfstate",
        "phase": fixture["expectedPhase"],
        "attemptNumber": 1,
        "controlPlaneCommit": "3" * 40,
        "requestedAuthority": fixture["expectedRequestedAuthority"],
        "executionSpecSha256": fixture["executionSpecSha256"],
        "createdAtUtc": timing["createdAtUtc"],
        "notBeforeUtc": timing["notBeforeUtc"],
        "expiresAtUtc": timing["expiresAtUtc"],
        "humanReviewed": True,
        "oneAttemptOnly": True,
        "simulationOnly": True,
        "liveExecutionAuthorized": False,
        "automaticRetryAuthorized": False,
        "automaticRollbackAuthorized": False,
        "statePushAuthorized": False,
        "backendRetirementAuthorized": False,
    }
    response = fake.call(request_shape)
    require(len(fake.calls) == 1 and response["simulationOnly"] is True, "fixed-fake call boundary changed")
    require(response["liveCommandExecuted"] is False and response["executionPerformed"] is False, "fixed fake gained effects")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("immutable approval consumption", "claim becomes durable before the fixed-fake driver", "claim without outcome", "retry is forbidden", "no aws, terraform, kubernetes, s3, state"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.5"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.5 - Shared dev/test phase execution lease"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, entrypoint_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "execution lease source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, entrypoint_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "approvalConsumptionModel": "exclusive-claim",
        "driverCallCount": 1,
        "fixedFakeOnly": True,
        "liveCommandExecuted": False,
        "privateExecutionStoreDirectoryCount": 2,
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
        parser.exit(1, f"Shared phase execution lease check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline repository checker for the shared dev/test two-wave teardown core."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.1-shared-dev-test-two-wave-teardown-core"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_core(path: Path):
    spec = importlib.util.spec_from_file_location("two_wave_teardown_core_for_check", path)
    require(spec is not None and spec.loader is not None, "core import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    fixture_path = root / f"delivery/examples/{PREFIX}-fixtures.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.1_SHARED_DEV_TEST_TWO_WAVE_TEARDOWN_CORE.md"
    core_path = root / "scripts/aws_two_wave_teardown_core.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["implementationBaselineCommit"] == "f42fe1d14bdb0b9152c6abab4b0c1039f86e43da", "baseline changed")
    core_contract = contract["core"]
    require(core_contract["path"] == "scripts/aws_two_wave_teardown_core.py" and core_contract["commandFree"] is True, "core boundary changed")
    require(core_contract["supportedLiveProfiles"] == ["aws-dev", "aws-test"] and core_contract["rejectedLiveProfiles"] == ["aws-prod"], "profile boundary changed")
    for key in ("requiresNetworkShellInWaveOneInput", "requiresNonNetworkAddressesInWaveOneInput", "waveOneDeletesAllAndOnlyNonNetworkAddresses", "postWaveOneStateEqualsPriorNetworkAddresses", "waveTwoDeletesAllAndOnlyRemainingNetworkAddresses", "finalManagedStateMustBeEmpty"):
        require(core_contract[key] is True, f"core gate changed: {key}")
    require(len(contract["gates"]) == 8, "gate inventory changed")
    dependency = contract["dependencyBoundary"]
    require(dependency["requiredInventoryFamilyCount"] == 12 and dependency["eksMustBeAbsent"] is True, "dependency inventory changed")
    require(dependency["controllerOwnedDependencyCount"] == 0 and dependency["unknownDependencyCount"] == 0, "dependency fail-closed boundary changed")
    require(dependency["safeResidueDeletionAuthorizedByInventory"] is False and dependency["waveTwoRequiresZeroSafeResidues"] is True, "residue authority changed")
    require(dependency["stateBackendMustRemainPreserved"] is True and dependency["runtimeIdentitiesMustRemainPreserved"] is True, "foundation boundary changed")
    require(contract["historyBoundary"] == {
        "planStateObjectVersionDelta": 0,
        "applyStateObjectVersionDelta": 1,
        "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1,
        "lockDeleteMarkerDelta": 1,
        "lockLatestVersionCount": 0,
        "lockLatestDeleteMarkerCount": 1,
    }, "history boundary changed")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    for section in ("packageProducer", "authority"):
        require(all(value is False for value in contract[section].values()), f"non-execution boundary changed: {section}")
    require(not executor_path.exists(), "core checkpoint must not expose an executor")

    source = core_path.read_text()
    for forbidden in ("import subprocess", "from subprocess", "import os", "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl"):
        require(forbidden not in source, f"command-free core contains forbidden marker: {forbidden}")
    core = load_core(core_path)
    fixture = json.loads(fixture_path.read_text())
    require(fixture["environments"] == ["aws-dev", "aws-test"], "fixture environment matrix changed")
    for environment in fixture["environments"]:
        core.environment_profile(environment)
    wave_one = core.gate_wave_one_plan(fixture["waveOnePlan"], fixture["initialManagedAddresses"])
    require(wave_one["managedDeleteCount"] == 2 and len(wave_one["retainedNetworkAddresses"]) == 2, "wave-one fixture changed")
    post = core.gate_post_wave_one_state(fixture["initialManagedAddresses"], fixture["postWaveOneManagedAddresses"])
    inventory = dict(fixture["dependencyInventory"])
    for environment in fixture["environments"]:
        inventory["environment"] = environment
        result = core.gate_dependency_inventory(inventory, environment, post["remainingManagedCount"])
        require(result["waveTwoEligible"] is True, "dependency fixture changed")
        wave_two = core.gate_wave_two_plan(fixture["waveTwoPlan"], fixture["postWaveOneManagedAddresses"], result)
        require(wave_two["managedDeleteCount"] == 2, "wave-two fixture changed")
    core.gate_history_delta(fixture["planHistoryBefore"], fixture["planHistoryAfter"], state_write_expected=False)
    core.gate_history_delta(fixture["planHistoryAfter"], fixture["applyHistoryAfter"], state_write_expected=True)
    core.gate_final_state(fixture["finalManagedAddresses"])

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("does not implement an operational executor", "rejects `aws-prod`", "recognition does not grant deletion authority", "active operational source code", "grants no live"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.1"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.1 - Shared dev/test two-wave teardown core"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "core source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "executorCount": 0, "environmentProfileCount": 2, "gateCount": 8, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Shared two-wave teardown core check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

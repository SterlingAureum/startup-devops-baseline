#!/usr/bin/env python3
"""Offline repository checker for the shared dev/test command-adapter registry."""

from __future__ import annotations

from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6.7-shared-dev-test-command-adapter-registry"


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
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6.7_SHARED_DEV_TEST_COMMAND_ADAPTER_REGISTRY.md"
    core_path = root / "scripts/aws_two_wave_teardown_command_registry.py"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6.7", "version changed")
    require(contract["implementationBaselineCommit"] == "3922c626f53aa966005aa72ae8a2fbe9a13b3f03", "baseline changed")
    coverage = contract["coverage"]
    require(coverage["supportedEnvironments"] == ["aws-dev", "aws-test"], "environment coverage changed")
    require(coverage["rejectedEnvironments"] == ["aws-prod"], "production refusal changed")
    require(coverage["phaseCount"] == 8 and coverage["uniqueOperationIdCount"] == 37 and coverage["phaseOperationCallCount"] == 49, "operation coverage changed")
    for key in ("exactReviewedOperationCoverage", "unknownOperationRejected", "crossPhaseOperationRejected", "operationOrderBound"):
        require(coverage[key] is True, f"coverage control disabled: {key}")
    entry = contract["adapterEntry"]
    for key in ("exactAdapterIdRequired", "transportKindRequired", "effectClassRequired", "timeoutRequired", "outputPolicyRequired", "requiredPrivateBindingNamesBound"):
        require(entry[key] is True, f"adapter binding disabled: {key}")
    for key in ("rawCommandAccepted", "dynamicCommandTemplateAccepted", "credentialOrEndpointOverrideAccepted", "environmentFallbackAccepted", "automaticRetryAuthorized", "automaticRepairAuthorized"):
        require(entry[key] is False, f"adapter unsafe input enabled: {key}")
    manifest = contract["phaseManifest"]
    for key in ("phaseDriverSpecSha256Required", "commandRegistrySha256Required", "adapterEntrySha256sRequired", "environmentStateKeyBound", "terraformRootBound", "backendConfigDeclarationBound", "claimBeforeFirstCommandRequired", "oneCallPerOperationId", "orderedDispatchRequired", "stopAtFirstFailure"):
        require(manifest[key] is True, f"manifest binding disabled: {key}")
    for key in ("automaticRetryAuthorized", "automaticRollbackAuthorized", "statePushAuthorized", "backendRetirementAuthorized"):
        require(manifest[key] is False, f"manifest authority enabled: {key}")
    boundary = contract["implementationBoundary"]
    require(boundary["registryImplemented"] is True and boundary["operationRequestSelectionImplemented"] is True, "registry implementation disabled")
    for key in ("subprocessAvailable", "sdkAvailable", "credentialReadAvailable", "liveBackendAvailable", "liveCommandExecuted", "executionPerformed"):
        require(boundary[key] is False, f"registry gained live capability: {key}")
    require(contract["ciBoundary"] == {
        "activeOperationalSource": True,
        "rootStructureValidationRequired": True,
        "historicalPrivateEvidenceLoaded": False,
        "liveCommandExecuted": False,
    }, "CI boundary changed")
    authority = contract["authority"]
    require(authority["registryValidationAuthorized"] is True, "registry validation disabled")
    require(all(value is False for key, value in authority.items() if key != "registryValidationAuthorized"), "live authority pre-granted")
    require(not executor_path.exists(), "registry checkpoint must not expose an executor")

    source = core_path.read_text()
    for forbidden in (
        "import subprocess", "from subprocess", "import boto3", "from boto3", "botocore",
        "os.system", "shell=True", "terraform apply", "terraform plan", "aws ec2", "kubectl ",
        "AWS_ACCESS_KEY",
    ):
        require(forbidden not in source, f"registry source contains forbidden marker: {forbidden}")

    registry_module = load_module(core_path, "shared_command_registry_for_check")
    fixture = json.loads(fixture_path.read_text())
    registry = registry_module.command_registry()
    require(registry_module.validate_command_registry(registry) == registry, "registry validation changed")
    require(registry_module.command_registry_sha256() == fixture["expectedCommandRegistrySha256"], "registry digest changed")
    require(registry["operationIdCount"] == fixture["uniqueOperationIdCount"], "fixture operation count changed")
    require(registry["phaseOperationCallCount"] == fixture["phaseOperationCallCount"], "fixture call count changed")
    require(Counter(row["transportKind"] for row in registry["entries"]) == fixture["transportKindCounts"], "transport counts changed")
    require(Counter(row["effectClass"] for row in registry["entries"]) == fixture["effectClassCounts"], "effect counts changed")
    manifest_value = registry_module.phase_command_manifest(fixture["expectedEnvironment"], fixture["expectedPhase"])
    require(registry_module.REQUEST.sha256(manifest_value) == fixture["expectedPhaseManifestSha256"], "phase manifest digest changed")
    digests = set()
    for environment in coverage["supportedEnvironments"]:
        for phase in registry_module.DRIVERS.PHASE_OPERATIONS:
            value = registry_module.phase_command_manifest(environment, phase)
            require(registry_module.validate_phase_command_manifest(value, environment=environment, phase=phase) == value, "phase manifest changed")
            require(value["operationIds"] == list(registry_module.DRIVERS.PHASE_OPERATIONS[phase]), "phase operation order changed")
            require(value["liveBackendAvailable"] is False and value["simulationOnly"] is True, "phase manifest gained live backend")
            digests.add(registry_module.REQUEST.sha256(value))
    require(len(digests) == 16, "environment/phase manifests are not uniquely bound")
    try:
        registry_module.phase_command_manifest("aws-prod", "wave-one-plan")
    except Exception as error:
        require(type(error).__name__ == "TeardownGateError", "production refusal error changed")
    else:
        raise ContractError("production command manifest became available")

    serialized_fixture = json.dumps(fixture, sort_keys=True)
    for pattern in (r"arn:aws", r"/home/", r"/tmp/", r"\bvpc-[0-9a-f]+\b", r"\bsg-[0-9a-f]+\b", r"\beni-[0-9a-f]+\b", r"\b\d{12}\b"):
        require(re.search(pattern, serialized_fixture, re.IGNORECASE) is None, f"fixture contains private identity marker: {pattern}")
    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("37 unique reviewed operation ids", "raw command", "claim-before-command", "no subprocess", "no free-form command"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6.7"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6.7 - Shared dev/test command-adapter registry"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{PREFIX}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, fixture_path, document_path, core_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "registry source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, fixture_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (core_path, checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {
        "environmentProfileCount": 2,
        "phaseManifestCount": 8,
        "uniqueOperationIdCount": 37,
        "phaseOperationCallCount": 49,
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
        parser.exit(1, f"Shared command-adapter registry check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline repository checker for partial aws-dev teardown recovery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import stat
import subprocess


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_repository(root: Path) -> dict:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.2_AWS_DEV_PARTIAL_TEARDOWN_RECOVERY.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.sh"
    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == "v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery-v1", "schema changed")
    require(contract["implementationBaselineCommit"] == "8bdb9289a8b612d987dc5a2e555bd16ca4a542b9", "baseline changed")
    require(contract["incident"]["destroyCompletedAddressCount"] == 88 and contract["incident"]["pendingManagedAddressCount"] == 2, "incident counts changed")
    require(contract["incident"]["failureCode"] == "DependencyViolation" and contract["incident"]["applyCompleteMarkerPresent"] is False, "incident failure changed")
    require(contract["verifyPhase"]["operationalCommandsAllowed"] is False, "verify command boundary changed")
    require(contract["executePhase"]["terraformMutationAllowed"] is False and contract["executePhase"]["awsMutationAllowed"] is False, "recovery mutation boundary changed")
    require(contract["successBoundary"]["managedStateAddressCount"] == 2 and contract["successBoundary"]["finalCleanupAuthorized"] is False, "success boundary changed")
    example = json.loads(example_path.read_text())
    require(example["operation"] == "inspect-partial-aws-dev-teardown-read-only", "example operation changed")
    require(example["incidentBoundary"]["applyStdoutSha256"] == "533d6d9c1be7f4b816e4cf0eff28b918c8c737eda71290d066b38e6523868168", "example incident changed")
    require(all(example["executionBoundary"][key] is False for key in ("terraformInit", "terraformPlan", "terraformApply", "terraformDestroy", "statePush", "directAwsMutation", "automaticRetry", "automaticRollback")), "example mutation authority changed")
    executor = executor_path.read_text()
    for marker in ("validate_incident", "parse_apply_addresses", "terraform-state-pull-partial-recovery", "network-interfaces-partial-recovery", '"terraform_apply_executed_by_recovery": False'):
        require(marker in executor, f"executor control missing: {marker}")
    for forbidden in ('["terraform", "plan"', '["terraform", "apply"', '["terraform", "destroy"', '"state", "push"', '"force-unlock"', "shell=True"):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")
    document = " ".join(document_path.read_text().split())
    for phrase in ("88 of 90 managed addresses", "not eligible for reuse", "Final cleanup requires"):
        require(phrase in document, f"document boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.2"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.2 - AWS dev partial teardown recovery"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", "test-v0.12.4.1.5.0.7.1.2-aws-dev-partial-teardown-recovery.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")
    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "partial recovery source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "mutationCommandExposed": False, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Partial-teardown recovery check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline repository checker for the guarded aws-dev teardown."""

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
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.json"
    plan_example_path = root / "delivery/examples/v0.12.4.1.5.0.7.1-aws-dev-teardown-plan-request.example.json"
    destroy_example_path = root / "delivery/examples/v0.12.4.1.5.0.7.1-aws-dev-teardown-destroy-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1_GUARDED_AWS_DEV_TEARDOWN.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.sh"
    contract = json.loads(contract_path.read_text())
    require(contract == {
        "schemaVersion": "v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown-v1",
        "version": "v0.12.4.1.5.0.7.1",
        "status": "guarded-aws-dev-teardown-ready-offline",
        "repository": "SterlingAureum/startup-devops-baseline",
        "implementationBaselineCommit": "dcd1c05c74e2ae8afc0d75e8482eb475c1dec112",
        "recordedRecovery": contract["recordedRecovery"], "planPhase": contract["planPhase"],
        "destroyPhase": contract["destroyPhase"], "successBoundary": contract["successBoundary"],
    }, "contract top-level shape changed")
    require(contract["recordedRecovery"] == {
        "privateRecoveryRequestSha256": "d20b549187fb360ac4b9ad45d0233bc1657b43b84cb0b2915e29d3ec7d552d4e",
        "privateRecoveryEvidenceSha256": "e064b6ce9460e3f9e0a0d87bfc5b1622f3a18b828c9b27fb93dffac8b492d0d1",
        "privateRecoveryResultSha256": "9006818a0806e5c9693c9766a2ec73c814e7038bdfa0707e2531d0a13bec18c6",
        "liveStateSha256": "0de88b8e306055c714fdd92c2192b575055bde56e0dc7b96c2de6a0c164b7bf9",
        "stateAddressInventorySha256": "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691",
        "normalizedCheckResultsSha256": "cce879cf1dc7519f44b5a75d6802b9ef517712c1483688c0fc98184266ce11a1",
        "stateSerial": 9, "managedStateAddressCount": 90, "dataStateAddressCount": 13,
        "totalStateAddressCount": 103, "semanticStateEqual": True,
        "environmentCreated": True, "unexplainedAddressCount": 0,
    }, "recorded recovery changed")
    require(contract["planPhase"]["verifyIsCommandFree"] is True and contract["planPhase"]["terraformInitAllowed"] is False and contract["planPhase"]["terraformApplyAllowed"] is False, "plan safety boundary changed")
    require(contract["destroyPhase"]["humanReviewRequired"] is True and contract["destroyPhase"]["separateApprovalRequired"] is True and contract["destroyPhase"]["exactSavedPlanApplyOnly"] is True, "destroy review boundary changed")
    require(contract["destroyPhase"]["terraformInitAllowed"] is False and contract["destroyPhase"]["terraformPlanAllowed"] is False and contract["destroyPhase"]["unsavedDestroyAllowed"] is False, "destroy command boundary changed")
    require(contract["successBoundary"] == {
        "status": "aws-dev-guarded-teardown-completed", "managedStateAddressCount": 0,
        "remainingDataAddressesMustBePriorSubset": True, "canonicalStateDeleteMarkerAllowed": False,
        "eksClusterMustBeAbsent": True, "vpcMustBeAbsent": True,
        "automaticRetryAllowed": False, "automaticRollbackAllowed": False,
    }, "success boundary changed")

    plan_example = json.loads(plan_example_path.read_text())
    destroy_example = json.loads(destroy_example_path.read_text())
    require(plan_example["operation"] == "plan-reviewed-aws-dev-remote-state-teardown", "plan example operation changed")
    require(plan_example["executionBoundary"]["terraformInit"] is False and plan_example["executionBoundary"]["terraformApply"] is False, "plan example authority changed")
    require(destroy_example["operation"] == "destroy-reviewed-aws-dev-with-exact-saved-plan", "destroy example operation changed")
    require(destroy_example["planBoundary"]["humanReviewed"] is True and destroy_example["executionBoundary"]["terraformPlan"] is False, "destroy example authority changed")

    executor = executor_path.read_text()
    for marker in (
        '"terraform", "plan", "-destroy"', '"terraform", "apply", "-input=false", "-auto-approve", str(binary)',
        "SEMANTIC.semantic_state", "destroy_plan_gate", "run_expected_absent", '"managed_state_address_count": 0',
        "preserve all private evidence and do not retry automatically",
    ):
        require(marker in executor, f"executor control missing: {marker}")
    for forbidden in ('["terraform", "destroy"', '"terraform", "init"', "shell=True", '"state", "push"', '"force-unlock"'):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")

    document = " ".join(document_path.read_text().split())
    for phrase in ("does not require `.7` to be rolled back", "Both verification phases are command-free", "applies only the exact saved binary plan", "do not retry automatically"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1 - Guarded AWS dev teardown"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", "test-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, plan_example_path, destroy_example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "guarded teardown source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, plan_example_path, destroy_example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Guarded aws-dev teardown contract check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

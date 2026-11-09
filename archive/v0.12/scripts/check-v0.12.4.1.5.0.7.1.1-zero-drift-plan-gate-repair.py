#!/usr/bin/env python3
"""Offline checker for the aws-dev zero-drift plan-gate repair."""

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
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.7.1.1-zero-drift-plan-gate-repair.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.1_ZERO_DRIFT_PLAN_GATE_REPAIR.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.7.1.1-zero-drift-plan-gate-repair.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.7.1.1-zero-drift-plan-gate-repair.sh"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py"
    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == "v0.12.4.1.5.0.7.1.1-zero-drift-plan-gate-repair-v1", "schema changed")
    require(contract["implementationBaselineCommit"] == "26ec4bbe7ff846846ce4944d7dcc0eda50908ba5", "baseline changed")
    require(contract["stoppedAttempt"] == {
        "privatePlanRequestSha256": "d0cde1633201e3f0c70f181aeee8d54d8330bf5370d078564fa8569ac5450654",
        "planJsonSha256": "7413b40be49d5b359b829f44a76e855246bbafe8128bc9859ed6d50721f68871",
        "complete": True, "errored": False, "applyable": True,
        "resourceDriftFieldPresent": False, "resourceDriftCount": 0,
        "resourceDriftAddressSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "terraformApplyExecuted": False, "infrastructureDestroyed": False,
    }, "stopped attempt changed")
    require(contract["repairBoundary"] == {
        "omittedResourceDriftAccepted": True, "explicitEmptyResourceDriftAccepted": True,
        "nonListResourceDriftAccepted": False, "nonEmptyResourceDriftAccepted": False,
        "stoppedSavedPlanReusable": False, "automaticRetryAllowed": False,
        "freshPlanRequestRequired": True, "freshPlanOutputRequired": True,
    }, "repair boundary changed")
    executor = executor_path.read_text()
    require('drift = document.get("resource_drift", [])' in executor, "empty-list default missing")
    require('require(isinstance(drift, list) and not drift' in executor, "non-list or non-empty rejection missing")
    require("test_omitted_empty_drift_collection_is_accepted" in test_path.read_text(), "omission regression test missing")
    document = " ".join(document_path.read_text().split())
    for phrase in ("misclassified as drift", "not eligible for review or apply", "attempt-02 plan output directory"):
        require(phrase in document, f"document boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.7.1.1-zero-drift-plan-gate-repair"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.1"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", "check-v0.12.4.1.5.0.7.1.1-zero-drift-plan-gate-repair.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")
    tracked_paths = [contract_path, document_path, checker_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "repair source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "stoppedPlanReusable": False, "regressionCount": 4}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Zero-drift plan-gate repair check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

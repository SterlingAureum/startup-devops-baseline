#!/usr/bin/env python3
"""Offline repository checker for EKS-SG delete-response recovery."""

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
    prefix = "v0.12.4.1.5.0.7.1.5.1-aws-dev-eks-sg-delete-response-recovery"
    contract_path = root / f"delivery/contracts/{prefix}.json"
    recovery_example_path = root / f"delivery/examples/{prefix}-request.example.json"
    final_example_path = root / "delivery/examples/v0.12.4.1.5.0.7.1.5.1-aws-dev-vpc-final-apply-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.5.1_AWS_DEV_EKS_SG_DELETE_RESPONSE_RECOVERY.md"
    checker_path = root / f"scripts/check-{prefix}.py"
    executor_path = root / f"scripts/execute-{prefix}.py"
    test_path = root / f"scripts/test-{prefix}.py"
    validator_path = root / f"scripts/validate-{prefix}.sh"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{prefix}-v1", "schema changed")
    require(contract["implementationBaselineCommit"] == "2366976f4a40fc397bf45e0d71f7be0a9ce72d5f", "baseline changed")
    incident = contract["incident"]
    require(incident["privatePrepareRequestSha256"] == "15e178bf565b80c50e441829955291bedcf430035c01b8e94d843731e729b625", "incident request changed")
    require(incident["deleteSecurityGroupStdoutSha256"] == "fe1cb2564af4e2ea11993e6a2608d1bbcda6c1006bf5d4a15fb9809a25fe03f3", "delete response changed")
    require(incident["deleteReturn"] is True and incident["deleteResponseGroupIdBound"] is True, "delete success boundary changed")
    require(incident["postDeleteAbsenceEvidenceCreated"] is False and incident["vpcSavedPlanCreated"] is False, "incident stop boundary changed")
    require(contract["repair"]["retrySecurityGroupDelete"] is False, "delete retry boundary changed")
    require(contract["recoveryPhase"]["directAwsMutationAllowed"] is False and contract["recoveryPhase"]["terraformApplyAllowed"] is False, "recovery mutation boundary changed")
    require(contract["finalPhase"]["exactSavedPlanApplyOnly"] is True and contract["successBoundary"]["managedStateAddressCount"] == 0, "final boundary changed")

    recovery = json.loads(recovery_example_path.read_text())
    final = json.loads(final_example_path.read_text())
    require(recovery["operation"] == "verify-deleted-eks-security-group-and-plan-vpc-destroy", "recovery operation changed")
    require(recovery["incidentBoundary"]["deleteSecurityGroupStdoutSha256"] == incident["deleteSecurityGroupStdoutSha256"], "recovery evidence binding changed")
    require(recovery["executionBoundary"]["securityGroupDelete"] is False and recovery["executionBoundary"]["terraformSavedDestroyPlan"] is True, "recovery authority changed")
    require(final["operation"] == "apply-reviewed-vpc-only-recovery-plan", "final operation changed")
    require(final["planBoundary"]["managedDeleteCount"] == 1 and final["planBoundary"]["humanReviewed"] is True, "final review boundary changed")
    require(final["executionBoundary"]["terraformExactSavedPlanApply"] is True and final["executionBoundary"]["securityGroupDelete"] is False, "final authority changed")

    executor = executor_path.read_text()
    base_executor = (root / "scripts/execute-v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup.py").read_text()
    for marker in (
        "validate_delete_security_group_response", 'document.get("Return") is True',
        '"terraform", "plan", "-destroy"',
        '"terraform", "apply", "-input=false", "-auto-approve", str(binary)',
        "validate_incident", "run_expected_missing", "securityGroupDeleteRetried",
        "preserve all private evidence and do not retry automatically",
    ):
        require(marker in executor or marker in base_executor, f"control missing: {marker}")
    require('["aws", "ec2", "delete-security-group"' not in executor, "recovery exposes security-group delete command")
    for forbidden in ('["terraform", "destroy"', '"terraform", "init"', '"state", "push"', '"force-unlock"', '"delete-vpc"', "shell=True"):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")

    document = " ".join(document_path.read_text().split())
    for phrase in ("does not retry", "verifies the security group is absent", "creates a saved destroy plan", "human review"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", prefix),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.5.1"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.5.1 - AWS dev EKS-SG delete-response recovery"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{prefix}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, recovery_example_path, final_example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "delete-response recovery source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, recovery_example_path, final_example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "trackedFileCount": len(tracked_paths), "securityGroupDeleteRetryPathCount": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"EKS-SG delete-response recovery check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

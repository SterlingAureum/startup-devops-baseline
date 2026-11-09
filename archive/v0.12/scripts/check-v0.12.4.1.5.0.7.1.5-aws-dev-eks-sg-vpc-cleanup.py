#!/usr/bin/env python3
"""Offline repository checker for final EKS-SG/VPC cleanup."""

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
    prefix = "v0.12.4.1.5.0.7.1.5-aws-dev-eks-sg-vpc-cleanup"
    contract_path = root / f"delivery/contracts/{prefix}.json"
    prepare_example_path = root / f"delivery/examples/{prefix}-prepare-request.example.json"
    apply_example_path = root / f"delivery/examples/{prefix}-apply-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.5_AWS_DEV_EKS_SG_VPC_CLEANUP.md"
    checker_path = root / f"scripts/check-{prefix}.py"
    executor_path = root / f"scripts/execute-{prefix}.py"
    test_path = root / f"scripts/test-{prefix}.py"
    validator_path = root / f"scripts/validate-{prefix}.sh"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{prefix}-v1", "schema changed")
    require(contract["implementationBaselineCommit"] == "b48b745ef5acfac6f29bc54acfed8208b7601463", "baseline changed")
    recovery = contract["recovery"]
    require(recovery["privateRecoveryResultSha256"] == "ae13d7213582e1ce7ee40f13d3d6a4015d3ebe44f59b6cfc7bfd57905f80a7c3", "recovery result changed")
    require(recovery["managedStateAddressCount"] == 1 and recovery["targetIsEksClusterSecurityGroup"] is True, "recovery resource boundary changed")
    require(recovery["targetMatchesFormerEniSecurityGroup"] is True and recovery["targetHasCrossGroupReference"] is False, "security-group safety boundary changed")
    require(contract["preparePhase"]["exactOrphanSecurityGroupDeleteAllowed"] is True and contract["preparePhase"]["otherAwsMutationAllowed"] is False, "prepare AWS authority changed")
    require(contract["preparePhase"]["terraformApplyAllowed"] is False and contract["finalPhase"]["exactSavedPlanApplyOnly"] is True, "Terraform authority changed")
    require(contract["successBoundary"]["managedStateAddressCount"] == 0 and contract["successBoundary"]["vpcMustBeAbsent"] is True, "success boundary changed")

    prepare = json.loads(prepare_example_path.read_text())
    final = json.loads(apply_example_path.read_text())
    require(prepare["operation"] == "delete-bound-orphan-eks-security-group-and-plan-vpc-destroy", "prepare operation changed")
    require(prepare["recoveryBoundary"]["targetSecurityGroupIdSha256"] == "e8a820dca7c3ab7408210f6779341938441519de137870e67278175c10f4d637", "security-group binding changed")
    require(prepare["executionBoundary"]["exactSecurityGroupDelete"] is True and prepare["executionBoundary"]["otherAwsMutation"] is False and prepare["executionBoundary"]["terraformApply"] is False, "prepare example authority changed")
    require(final["operation"] == "apply-reviewed-vpc-only-final-cleanup", "final operation changed")
    require(final["planBoundary"]["managedDeleteCount"] == 1 and final["planBoundary"]["humanReviewed"] is True, "final review boundary changed")
    require(final["executionBoundary"]["terraformExactSavedPlanApply"] is True and final["executionBoundary"]["terraformPlan"] is False and final["executionBoundary"]["directAwsMutation"] is False, "final example authority changed")

    executor = executor_path.read_text()
    for marker in (
        '"delete-security-group"', '"terraform", "plan", "-destroy"',
        '"terraform", "apply", "-input=false", "-auto-approve", str(binary)',
        "validate_security_group", "vpc_plan_gate", "PENDING_ADDRESSES",
        '"managed_state_address_count": 0',
        "preserve all private evidence and do not retry automatically",
    ):
        require(marker in executor, f"executor control missing: {marker}")
    require(executor.count('"delete-security-group"') == 1, "security-group delete path count changed")
    for forbidden in ('["terraform", "destroy"', '"terraform", "init"', '"state", "push"', '"force-unlock"', '"delete-vpc"', "shell=True"):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")

    document = " ".join(document_path.read_text().split())
    for phrase in ("two separate approvals", "deletes only that bound orphan EKS security group", "applies only that reviewed binary plan", "No init"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", prefix),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.5"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.5 - AWS dev EKS-SG/VPC cleanup"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{prefix}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, prepare_example_path, apply_example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "EKS-SG/VPC cleanup source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, prepare_example_path, apply_example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "trackedFileCount": len(tracked_paths), "directAwsDeletePathCount": 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"EKS-SG/VPC cleanup check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

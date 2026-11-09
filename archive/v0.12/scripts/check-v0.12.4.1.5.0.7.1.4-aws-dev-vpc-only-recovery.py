#!/usr/bin/env python3
"""Offline repository checker for AWS-dev VPC-only recovery."""

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
    prefix = "v0.12.4.1.5.0.7.1.4-aws-dev-vpc-only-recovery"
    contract_path = root / f"delivery/contracts/{prefix}.json"
    example_path = root / f"delivery/examples/{prefix}-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.4_AWS_DEV_VPC_ONLY_RECOVERY.md"
    checker_path = root / f"scripts/check-{prefix}.py"
    executor_path = root / f"scripts/execute-{prefix}.py"
    test_path = root / f"scripts/test-{prefix}.py"
    validator_path = root / f"scripts/validate-{prefix}.sh"

    contract = json.loads(contract_path.read_text())
    require(contract["schemaVersion"] == f"{prefix}-v1", "schema changed")
    require(contract["implementationBaselineCommit"] == "184a892f990c62f61b37ae4266465ff23950f003", "baseline changed")
    incident = contract["incident"]
    require(incident["completedManagedDeleteCount"] == 1 and incident["subnetDestroyed"] is True and incident["vpcPending"] is True, "incident address boundary changed")
    require(incident["failureOperation"] == "DeleteVpc" and incident["failureCode"] == "DependencyViolation", "incident failure changed")
    require(contract["verifyPhase"]["operationalCommandsAllowed"] is False, "verify command boundary changed")
    require(contract["executePhase"]["terraformMutationAllowed"] is False and contract["executePhase"]["awsMutationAllowed"] is False, "recovery mutation boundary changed")
    require(contract["successBoundary"]["managedStateAddressCount"] == 1 and contract["successBoundary"]["onlyManagedAddress"] == "module.vpc.aws_vpc.this", "success state boundary changed")
    require(contract["successBoundary"]["cleanupAuthorized"] is False, "cleanup authority changed")

    example = json.loads(example_path.read_text())
    require(example["operation"] == "inspect-failed-vpc-only-final-cleanup-read-only", "example operation changed")
    require(example["incidentBoundary"]["applyStdoutSha256"] == "48aab2cedc8a3249cd03863cd8739f2364bd467355864dceb55e69aad66cec7a", "example incident changed")
    require(example["incidentBoundary"]["pendingAddress"] == "module.vpc.aws_vpc.this", "example pending address changed")
    for key in ("terraformInit", "terraformPlan", "terraformApply", "terraformDestroy", "statePush", "directAwsMutation", "directS3Mutation", "automaticRetry", "automaticRollback"):
        require(example["executionBoundary"][key] is False, f"example mutation authority changed: {key}")

    executor = executor_path.read_text()
    for marker in (
        "validate_incident", "parse_apply_addresses", "terraform-state-pull-vpc-only-recovery",
        "network-interfaces-vpc-only-recovery", "vpc-endpoints-vpc-only-recovery",
        "transit-gateway-attachments-vpc-only-recovery", "load-balancers-vpc-only-recovery",
        '"terraform_apply_executed_by_recovery": False',
        "preserve all private evidence and do not retry automatically",
    ):
        require(marker in executor, f"executor control missing: {marker}")
    for forbidden in (
        '["terraform", "plan"', '["terraform", "apply"', '["terraform", "destroy"',
        '"delete-vpc"', '"delete-subnet"', '"delete-network-interface"',
        '"state", "push"', '"force-unlock"', "shell=True",
    ):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")

    document = " ".join(document_path.read_text().split())
    for phrase in ("not eligible for reuse", "one managed address", "Private resource identities remain", "No init"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", prefix),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.4"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.4 - AWS dev VPC-only recovery"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", f"test-{prefix}.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "VPC-only recovery source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "trackedFileCount": len(tracked_paths), "mutationCommandExposed": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"VPC-only recovery check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

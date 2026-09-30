#!/usr/bin/env python3
"""Offline contract checker for aws-dev post-create qualification."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


BASELINE = "5d56911e2cd3510e313c2835e11667e092628482"
RECOVERY_REQUEST = "d20b549187fb360ac4b9ad45d0233bc1657b43b84cb0b2915e29d3ec7d552d4e"
RECOVERY_EVIDENCE = "e064b6ce9460e3f9e0a0d87bfc5b1622f3a18b828c9b27fb93dffac8b492d0d1"
RECOVERY_RESULT = "9006818a0806e5c9693c9766a2ec73c814e7038bdfa0707e2531d0a13bec18c6"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text())


def changed(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    result = copy.deepcopy(value)
    cursor: Any = result
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return result


def validate_contract(value: Any) -> None:
    require(isinstance(value, dict), "contract must be an object")
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.7-aws-dev-post-create-qualification-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.7", "version drift")
    require(value.get("status") == "aws-dev-post-create-qualification-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == BASELINE, "baseline drift")
    require(value.get("recordedRecovery") == {
        "privateRecoveryRequestSha256": RECOVERY_REQUEST,
        "privateRecoveryEvidenceSha256": RECOVERY_EVIDENCE,
        "privateRecoveryResultSha256": RECOVERY_RESULT,
        "liveStateSha256": "0de88b8e306055c714fdd92c2192b575055bde56e0dc7b96c2de6a0c164b7bf9",
        "stateAddressInventorySha256": "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691",
        "normalizedCheckResultsSha256": "cce879cf1dc7519f44b5a75d6802b9ef517712c1483688c0fc98184266ce11a1",
        "stateSerial": 9,
        "managedStateAddressCount": 90,
        "reviewedDataStateAddressCount": 6,
        "priorStateDataAddressCount": 7,
        "totalStateAddressCount": 103,
        "checkResultCount": 28,
        "checkPassStatusCount": 56,
        "semanticStateEqual": True,
        "environmentCreated": True,
        "eksClusterActive": True,
        "unexplainedAddressCount": 0,
    }, "recorded recovery drift")
    require(value.get("verifyPhase") == {
        "operationalCommandsAllowed": False,
        "protectedMainMustBeExactAndClean": True,
        "privateRecoveryEvidenceMustMatch": True,
        "privateQualificationOutputMustBeNew": True,
        "maximumApprovalWindowMinutes": 60,
        "minimumRemainingMinutes": 15,
    }, "verify phase drift")
    require(value.get("executePhase") == {
        "requiredConfirmationVariable": "CONFIRM_AWS_DEV_POST_CREATE_QUALIFICATION",
        "requiredConfirmationValue": "qualify-recovered-aws-dev-for-gitops-resume",
        "awsIdentityReadAllowed": True,
        "eksClusterReadAllowed": True,
        "eksNodegroupReadAllowed": True,
        "eksAddonReadAllowed": True,
        "privateKubeconfigWriteAllowed": True,
        "kubernetesApiReadAllowed": True,
        "expectedKubernetesMinor": "1.36",
        "expectedNodegroup": "startup-devops-baseline-dev-general",
        "expectedNodeCount": 4,
        "expectedManagedAddonCount": 4,
        "argocdNamespaceMustBeAbsent": True,
    }, "execute phase drift")
    require(value.get("prohibitedOperations") == {
        "terraformCommandAllowed": False,
        "stateMutationAllowed": False,
        "awsMutationAllowed": False,
        "kubernetesPersistentMutationAllowed": False,
        "argocdOperationAllowed": False,
        "helmOperationAllowed": False,
        "externalSecretsPreflightAllowed": False,
        "secretValueReadAllowed": False,
        "automaticRetryAllowed": False,
        "automaticRollbackAllowed": False,
        "automaticTeardownAllowed": False,
    }, "prohibited operations drift")
    require(value.get("successBoundary") == {
        "status": "aws-dev-post-create-qualified-for-gitops-bootstrap",
        "gitopsBootstrapExecuted": False,
        "externalSecretsPreflightExecuted": False,
        "nextAction": "obtain-separate-aws-dev-gitops-bootstrap-approval-before-external-secrets-preflight-resume",
    }, "success boundary drift")
    require(value.get("successor") == {
        "scope": "guarded-aws-dev-gitops-bootstrap-and-root-convergence",
        "requiresSeparateApproval": True,
        "authorizedByThisCheckpoint": False,
    }, "successor drift")


def validate_repository(root: Path) -> dict[str, Any]:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.7-aws-dev-post-create-qualification.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.7-aws-dev-post-create-qualification-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.7_AWS_DEV_POST_CREATE_QUALIFICATION.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.sh"
    contract = load(contract_path)
    validate_contract(contract)

    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("recordedRecovery", "privateRecoveryRequestSha256"), "0" * 64),
        (("recordedRecovery", "privateRecoveryEvidenceSha256"), "0" * 64),
        (("recordedRecovery", "privateRecoveryResultSha256"), "0" * 64),
        (("recordedRecovery", "semanticStateEqual"), False),
        (("recordedRecovery", "environmentCreated"), False),
        (("recordedRecovery", "totalStateAddressCount"), 102),
        (("verifyPhase", "operationalCommandsAllowed"), True),
        (("verifyPhase", "maximumApprovalWindowMinutes"), 120),
        (("executePhase", "expectedNodeCount"), 2),
        (("executePhase", "argocdNamespaceMustBeAbsent"), False),
        (("prohibitedOperations", "terraformCommandAllowed"), True),
        (("prohibitedOperations", "awsMutationAllowed"), True),
        (("prohibitedOperations", "kubernetesPersistentMutationAllowed"), True),
        (("prohibitedOperations", "externalSecretsPreflightAllowed"), True),
        (("prohibitedOperations", "automaticRetryAllowed"), True),
        (("successBoundary", "gitopsBootstrapExecuted"), True),
        (("successor", "authorizedByThisCheckpoint"), True),
    ]
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(changed(contract, path, replacement))
        except (AttributeError, ContractError, KeyError, TypeError):
            continue
        raise ContractError(f"fail-open mutation {index}")

    example = load(example_path)
    require(example.get("schemaVersion") == "v0.12.4.1.5.0.7-aws-dev-post-create-qualification-request-v1", "example schema drift")
    require(example.get("operation") == "qualify-recovered-aws-dev-for-gitops-resume", "example operation drift")
    require(example.get("recoveryBoundary", {}).get("privateRecoveryResultSha256") == RECOVERY_RESULT, "example recovery result drift")
    require(example.get("recoveryBoundary", {}).get("semanticStateEqual") is True, "example semantic boundary drift")
    boundary = example.get("executionBoundary", {})
    require(all(boundary.get(key) is True for key in ("awsIdentityRead", "eksClusterRead", "eksNodegroupRead", "eksAddonRead", "privateKubeconfigWrite", "kubernetesApiRead")), "example read authority drift")
    require(all(boundary.get(key) is False for key in ("terraformCommand", "stateMutation", "awsMutation", "kubernetesPersistentMutation", "argocdOperation", "helmOperation", "externalSecretsPreflight", "secretValueRead", "automaticRetry", "automaticRollback", "automaticTeardown")), "example mutation authority drift")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "does not run Terraform",
        "requires the `argocd` namespace to remain absent",
        "do not retry automatically",
        "Only after GitOps convergence may the existing External Secrets",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")

    executor = executor_path.read_text()
    for marker in (
        "validate_recovery_result",
        "require_nodegroup",
        "require_nodes",
        '"aws", "eks", "update-kubeconfig"',
        '"get", "--raw=/readyz"',
        '"get", "namespace", "argocd", "--ignore-not-found"',
        '"gitops_bootstrap_executed": False',
        '"external_secrets_preflight_executed": False',
    ):
        require(marker in executor, f"executor control missing: {marker}")
    for forbidden in (
        '["terraform",',
        '"apply", "--server-side"',
        '"delete",',
        '"patch",',
        '"helm",',
        "shell=True",
    ):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")

    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.7-aws-dev-post-create-qualification"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7 - AWS dev post-create qualification"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7"),
        (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh", "test-v0.12.4.1.5.0.7-aws-dev-post-create-qualification.py"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "post-create qualification source tracking drift")
    modes: dict[str, str] = {}
    for line in tracked:
        metadata, path = line.split("\t", 1)
        modes[path] = metadata.split()[0]
    for path in (contract_path, example_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode drift: {path.name}")
    for path in (checker_path, executor_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode drift: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"mutationCount": len(mutations), "liveCommandExecuted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = validate_repository(args.root.resolve(strict=True))
    print(f"v0.12.4.1.5.0.7 post-create qualification contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

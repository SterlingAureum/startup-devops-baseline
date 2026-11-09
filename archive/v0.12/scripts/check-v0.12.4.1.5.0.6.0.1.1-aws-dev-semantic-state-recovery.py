#!/usr/bin/env python3
"""Offline contract checker for aws-dev semantic-state recovery."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


BASELINE = "e7c218b9d11f64f2af419786fd3c45c51ea289b0"
PRIOR_REQUEST = "66935f15b045fa641334b4ffa4c47abcc6c0b16a5b3fcb7e7d0aee8f3aa65fe9"
PRESERVED_STATE = "d3960815889c8d192ffc09b19a98a11f965ed660670ce87d07701944bce3e205"
PULLED_STATE = "5e227aeae2e3c0f27afb688319252f91f7f56653d4f05535bf6e1b17908bfdee"
INVENTORY = "0bf45e067a30633472416fcef468381e11c90d13cfabe96eeb50f6bc2e602691"
NORMALIZED_CHECKS = "cce879cf1dc7519f44b5a75d6802b9ef517712c1483688c0fc98184266ce11a1"


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
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.6.0.1.1", "version drift")
    require(value.get("status") == "aws-dev-semantic-state-recovery-ready-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == BASELINE, "baseline drift")
    require(value.get("incidentEvidence") == {
        "privatePriorRecoveryRequestSha256": PRIOR_REQUEST,
        "priorRecoveryStoppedBeforeStateList": True,
        "preservedStateSha256": PRESERVED_STATE,
        "priorPulledStateSha256": PULLED_STATE,
        "stateSerial": 9,
        "stateLineageSha256": "e7607c625b0ce10f80d09715b8bfb43b6e0a251a82aeabe08f52fb4296ed0391",
        "managedStateAddressCount": 90,
        "dataStateAddressCount": 13,
        "totalStateAddressCount": 103,
        "stateAddressInventorySha256": INVENTORY,
        "onlyChangedTopLevelField": "check_results",
        "normalizedCheckResultsSha256": NORMALIZED_CHECKS,
        "checkResultCount": 28,
        "checkPassStatusCount": 56,
        "semanticStateEqual": True,
        "unexplainedAddressCount": 0,
    }, "incident evidence drift")
    require(value.get("verifyPhase") == {
        "operationalCommandsAllowed": False,
        "protectedMainMustBeExactAndClean": True,
        "priorRecoveryRequestAndOutputMustMatch": True,
        "originalApplyEvidenceMustMatch": True,
        "stateSemanticEqualityMustHold": True,
        "checkResultsComparedAsUnorderedSemanticCollections": True,
        "recoveryOutputMustBeNew": True,
    }, "verify boundary drift")
    require(value.get("executePhase") == {
        "requiredConfirmationVariable": "CONFIRM_AWS_DEV_SEMANTIC_STATE_RECOVERY",
        "requiredConfirmationValue": "recover-aws-dev-post-apply-with-semantic-state-equality",
        "awsIdentityReadAllowed": True,
        "eksDescribeClusterAllowed": True,
        "s3ObjectHistoryReadAllowed": True,
        "terraformStateReadAllowed": True,
        "terraformInitAllowed": False,
        "terraformPlanAllowed": False,
        "terraformApplyAllowed": False,
        "terraformDestroyAllowed": False,
        "expectedManagedStateAddressCount": 90,
        "expectedDataStateAddressCount": 13,
        "expectedTotalStateAddressCount": 103,
        "eksClusterMustBeActive": True,
    }, "execute boundary drift")
    require(value.get("stateAndLockBoundary") == {
        "liveStateMustBeSemanticallyEqual": True,
        "stateObjectVersionDeltaFromPreApplyMustBePositive": True,
        "stateDeleteMarkerDeltaMustBe": 0,
        "nativeLockObjectVersionDeltaFromPreApplyMustBe": 1,
        "nativeLockDeleteMarkerDeltaFromPreApplyMustBe": 1,
        "nativeLockMustBeAbsent": True,
        "statePushAllowed": False,
        "stateMigrationAllowed": False,
        "directS3MutationAllowed": False,
        "forceUnlockAllowed": False,
    }, "state boundary drift")
    require(value.get("failureBoundary") == {
        "automaticRetryAllowed": False,
        "automaticRollbackAllowed": False,
        "automaticDestroyAllowed": False,
        "allPrivateEvidenceMustBePreserved": True,
    }, "failure boundary drift")
    require(value.get("successor") == {
        "version": "v0.12.4.1.5.0.7",
        "scope": "aws-dev-post-create-qualification-and-external-secrets-preflight-resume",
        "requiresSeparateApproval": True,
        "authorizedByThisCheckpoint": False,
    }, "successor drift")


def validate_repository(root: Path) -> dict[str, Any]:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.json"
    example_path = root / "delivery/examples/v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-request.example.json"
    document_path = root / "docs/V0.12.4.1.5.0.6.0.1.1_AWS_DEV_SEMANTIC_STATE_RECOVERY.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.py"
    executor_path = root / "scripts/execute-v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.py"
    test_path = root / "scripts/test-v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery.sh"
    contract = load(contract_path)
    validate_contract(contract)
    mutations = [
        (("implementationBaselineCommit",), "0" * 40),
        (("incidentEvidence", "privatePriorRecoveryRequestSha256"), "0" * 64),
        (("incidentEvidence", "priorRecoveryStoppedBeforeStateList"), False),
        (("incidentEvidence", "preservedStateSha256"), "0" * 64),
        (("incidentEvidence", "priorPulledStateSha256"), "0" * 64),
        (("incidentEvidence", "stateSerial"), 10),
        (("incidentEvidence", "managedStateAddressCount"), 89),
        (("incidentEvidence", "dataStateAddressCount"), 12),
        (("incidentEvidence", "totalStateAddressCount"), 102),
        (("incidentEvidence", "onlyChangedTopLevelField"), "resources"),
        (("incidentEvidence", "normalizedCheckResultsSha256"), "0" * 64),
        (("incidentEvidence", "checkPassStatusCount"), 55),
        (("incidentEvidence", "semanticStateEqual"), False),
        (("verifyPhase", "operationalCommandsAllowed"), True),
        (("verifyPhase", "checkResultsComparedAsUnorderedSemanticCollections"), False),
        (("executePhase", "terraformApplyAllowed"), True),
        (("executePhase", "terraformPlanAllowed"), True),
        (("executePhase", "expectedTotalStateAddressCount"), 96),
        (("stateAndLockBoundary", "liveStateMustBeSemanticallyEqual"), False),
        (("stateAndLockBoundary", "directS3MutationAllowed"), True),
        (("failureBoundary", "automaticRetryAllowed"), True),
        (("successor", "authorizedByThisCheckpoint"), True),
    ]
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(changed(contract, path, replacement))
        except (AttributeError, ContractError, KeyError, TypeError):
            continue
        raise ContractError(f"fail-open mutation {index}")

    example = load(example_path)
    require(example.get("schemaVersion") == "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery-request-v1", "example schema drift")
    require(example.get("operation") == "recover-aws-dev-post-apply-with-semantic-state-equality", "example operation drift")
    evidence = example.get("evidenceBoundary", {})
    require(evidence.get("privatePriorRecoveryRequestSha256") == PRIOR_REQUEST, "example prior request drift")
    require(evidence.get("priorPulledStateSha256") == PULLED_STATE, "example pulled state drift")
    require(evidence.get("normalizedCheckResultsSha256") == NORMALIZED_CHECKS, "example normalized check drift")
    require(evidence.get("semanticStateEqual") is True and evidence.get("unexplainedAddressCount") == 0, "example semantic boundary drift")
    boundary = example.get("executionBoundary", {})
    require(all(boundary.get(key) is True for key in ("awsIdentityRead", "eksDescribeCluster", "s3ObjectHistoryRead", "terraformVersionRead", "terraformStatePull", "terraformStateList", "terraformShowState")), "example read authority drift")
    require(all(boundary.get(key) is False for key in ("terraformInit", "terraformPlan", "terraformApply", "terraformDestroy", "statePush", "stateMigration", "directS3Mutation", "forceUnlock", "iamPolicyAttachment", "kubernetesCommand", "secretValueRead", "automaticRetry", "automaticRollback")), "example mutation authority drift")

    document = " ".join(document_path.read_text().split())
    for phrase in ("only changed top-level field is `check_results`", "28 check-result entries", "56 `pass` statuses", "No infrastructure or state drift was found", "never executes Terraform init, plan, apply or destroy"):
        require(phrase in document, f"document boundary missing: {phrase}")
    executor = executor_path.read_text()
    for marker in ('normalize_unordered', 'semantic_state(prior_state) == semantic_state(preserved_state)', 'semantic_state(state_document) == semantic_state(prior["prior_state"])', 'listed == incident["expected_addresses"]', '"operational_commands_executed": []', '"terraform_apply_executed_by_recovery": False'):
        require(marker in executor, f"executor control missing: {marker}")
    for forbidden in ('["terraform", "apply"', '["terraform", "plan"', '["terraform", "init"', '["terraform", "destroy"', 'force-unlock', '-migrate-state', 'shell=True'):
        require(forbidden not in executor, f"forbidden executable path found: {forbidden}")
    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.6.0.1.1-aws-dev-semantic-state-recovery"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.6.0.1.1 - AWS dev semantic-state recovery"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.6.0.1.1"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, example_path, document_path, checker_path, executor_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "semantic recovery source tracking drift")
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
    print(f"v0.12.4.1.5.0.6.0.1.1 semantic-state recovery contract and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

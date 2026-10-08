#!/usr/bin/env python3
"""Offline repository checker for generalized teardown hardening design."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import subprocess


PREFIX = "v0.12.4.1.5.0.7.1.6-generalized-multi-environment-teardown-hardening-design"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def validate_contract(contract: dict) -> None:
    require(contract["schemaVersion"] == f"{PREFIX}-v1", "schema changed")
    require(contract["version"] == "v0.12.4.1.5.0.7.1.6", "version changed")
    require(contract["status"] == "generalized-multi-environment-teardown-hardening-design-ready-offline", "status changed")
    require(contract["implementationBaselineCommit"] == "db1ff0c46ea8b0fe900f57679f56bdc34ba6c7aa", "baseline changed")

    assessment = contract["currentAssessment"]
    for key in ("sharedTerraformModulesPresent", "independentEnvironmentRootsPresent", "independentRemoteStateKeysPresent", "legacyDevTestDependencyConvergencePresent", "v012GuardedTeardownIsDevSpecific"):
        require(assessment[key] is True, f"current assessment changed: {key}")
    require(assessment["generalizedExecutorImplemented"] is False, "design falsely claims implementation")
    require(assessment["postHardeningLiveValidationCompleted"] is False, "design falsely claims live validation")

    backend = contract["backendBoundary"]
    require(backend["foundationRoot"] == "infra/terraform/aws/state-bootstrap", "backend root changed")
    require(backend["stateKeys"] == {
        "dev": "environments/dev/terraform.tfstate",
        "test": "environments/test/terraform.tfstate",
        "prod": "environments/prod/terraform.tfstate",
    }, "environment state keys changed")
    for key in ("s3NativeLockfileRequired", "stateBucketPreventDestroy", "stateKmsKeyPreventDestroy", "successfulEnvironmentTeardownWritesEmptyState", "backendRetirementRequiresSeparateDesignAndApproval"):
        require(backend[key] is True, f"backend protection changed: {key}")
    for key in ("stateBucketForceDestroy", "ordinaryEnvironmentTeardownMayDestroyBackend", "ordinaryEnvironmentTeardownMayDeleteStateObject", "ordinaryEnvironmentTeardownMayDeleteStateHistory", "ordinaryEnvironmentTeardownMayDestroyRuntimeIdentities"):
        require(backend[key] is False, f"backend destruction boundary changed: {key}")
    require(contract["remoteStateActivation"] == {
        "aws-dev": "live-s3-state-evidence-recorded",
        "aws-test": "separate-activation-and-migration-required-before-live-acceptance",
        "aws-prod": "static-key-declared-with-no-v0.12-live-activation-requirement",
    }, "remote-state activation claims changed")

    profiles = contract["environmentProfiles"]
    require(set(profiles) == {"aws-dev", "aws-test", "aws-prod"}, "environment matrix changed")
    require(profiles["aws-dev"]["terraformRoot"].endswith("/dev"), "dev root changed")
    require(profiles["aws-test"]["terraformRoot"].endswith("/test"), "test root changed")
    require(profiles["aws-prod"]["terraformRoot"].endswith("/prod"), "prod root changed")
    require(profiles["aws-dev"]["applicationBackupDeletionAllowed"] is True, "dev backup policy changed")
    require(profiles["aws-test"]["applicationBackupDeletionAllowed"] is True, "test backup policy changed")
    require(profiles["aws-prod"]["applicationBackupDeletionAllowed"] is False, "prod backup policy changed")
    require(profiles["aws-test"]["remoteStateActivationRequiredBeforeLiveCreate"] is True, "test remote-state prerequisite changed")
    require(profiles["aws-prod"]["remoteStateActivationRequiredBeforeLiveCreate"] is True, "prod remote-state prerequisite changed")
    require([profiles[name]["secretRecoveryWindowDays"] for name in ("aws-dev", "aws-test", "aws-prod")] == [0, 7, 30], "secret recovery matrix changed")
    require(profiles["aws-prod"]["liveCreateAllowedAfterSeparateApproval"] is False, "prod create boundary changed")
    require(profiles["aws-prod"]["liveTeardownAllowedAfterImplementationAndSeparateApproval"] is False, "prod teardown boundary changed")

    require(contract["dependencyClasses"] == {
        "terraformManaged": "remain-owned-by-the-reviewed-saved-plan",
        "controllerOwned": "remove-through-the-owning-controller-before-terraform",
        "safeCloudResidue": "exact-identity-read-only-inventory-then-separate-delete-approval",
        "protectedFoundation": "exclude-from-environment-teardown-and-residual-cost-failure",
        "unknown": "fail-closed-with-no-delete-or-retry",
    }, "dependency classification changed")
    require(len(contract["requiredDependencyInventory"]) == 12, "dependency inventory changed")
    require(contract["futurePhaseOrder"] == [
        "command-free-request-verification",
        "approved-controller-owned-cleanup",
        "read-only-state-and-cloud-inventory",
        "reviewed-non-network-saved-destroy-plan",
        "separately-approved-exact-non-network-plan-apply",
        "post-cluster-read-only-vpc-dependency-inventory",
        "optional-separately-approved-exact-safe-residue-cleanup",
        "fresh-reviewed-network-only-saved-destroy-plan",
        "separately-approved-exact-network-plan-apply",
        "empty-state-absence-and-residual-cost-evidence",
    ], "phase order changed")

    plan = contract["planAndRecoveryBoundary"]
    for key in ("twoWaveTeardownRequired", "firstWaveRetainsNetworkShell", "secondWaveRequiresFreshPlan", "humanReviewRequiredForEverySavedPlan", "exactSavedPlanApplyOnly"):
        require(plan[key] is True, f"plan control changed: {key}")
    for key in ("partiallyAppliedPlanReusable", "automaticRetryAllowed", "automaticRollbackAllowed", "unknownDependencyDeleteAllowed", "terraformStateMutationAllowed", "forceUnlockAllowed"):
        require(plan[key] is False, f"fail-closed boundary changed: {key}")

    acceptance = contract["releaseAcceptance"]
    require(acceptance["offlineMatrixRequiredFor"] == ["aws-dev", "aws-test", "aws-prod"], "offline matrix changed")
    require(acceptance["devCleanCycleRequired"] is True and acceptance["testPromotionAndTeardownRequired"] is True, "live acceptance changed")
    require(acceptance["prodLiveApplyRequired"] is False and acceptance["prodLiveDestroyRequired"] is False, "prod live boundary changed")
    require(acceptance["incidentRecoveryDuringAcceptanceAllowed"] is False and acceptance["manualStateEditingAllowed"] is False, "acceptance safety changed")

    ci = contract["auditAndCiBoundary"]
    require(ci["historicalExecutionEvidenceRemainsOnDemand"] is True, "audit separation changed")
    require(ci["activeOperationalSourceValidatorsMayJoinCiAfterImplementation"] is True, "future source validation boundary changed")
    for key in ("historicalExecutionEvidenceRequiredCi", "privateEvidenceAllowedInCi", "thisDesignValidatorRequiredCi", "thisDesignValidatorWorkflowBound"):
        require(ci[key] is False, f"CI boundary changed: {key}")
    for section in ("packageProducer", "authority"):
        require(all(value is False for value in contract[section].values()), f"non-execution boundary changed: {section}")
    require(contract["nextCheckpoint"] == "implement-offline-shared-dev-test-two-wave-teardown-core", "next checkpoint changed")


def backend_values(path: Path) -> dict[str, str]:
    values = {}
    for key in ("key", "use_lockfile"):
        match = re.search(rf"^\s*{key}\s*=\s*(.+?)\s*$", path.read_text(), re.MULTILINE)
        require(match is not None, f"backend field missing: {path.name}:{key}")
        values[key] = match.group(1).strip().strip('"')
    return values


def validate_repository(root: Path) -> dict:
    contract_path = root / f"delivery/contracts/{PREFIX}.json"
    document_path = root / "docs/V0.12.4.1.5.0.7.1.6_GENERALIZED_MULTI_ENVIRONMENT_TEARDOWN_HARDENING_DESIGN.md"
    checker_path = root / f"scripts/check-{PREFIX}.py"
    test_path = root / f"scripts/test-{PREFIX}.py"
    validator_path = root / f"scripts/validate-{PREFIX}.sh"
    executor_path = root / f"scripts/execute-{PREFIX}.py"

    contract = json.loads(contract_path.read_text())
    validate_contract(contract)
    require(not executor_path.exists(), "design checkpoint must not expose an executor")

    for environment in ("dev", "test", "prod"):
        root_path = root / f"infra/terraform/aws/environments/{environment}"
        require(root_path.is_dir(), f"environment root missing: {environment}")
        values = backend_values(root / f"infra/terraform/aws/backend-config/{environment}.s3.tfbackend.example")
        require(values == {"key": f"environments/{environment}/terraform.tfstate", "use_lockfile": "true"}, f"backend isolation changed: {environment}")

    bootstrap = (root / "infra/terraform/aws/state-bootstrap/main.tf").read_text()
    for key in ("environments/dev/terraform.tfstate", "environments/test/terraform.tfstate", "environments/prod/terraform.tfstate"):
        require(key in bootstrap, f"bootstrap state key missing: {key}")
    require("force_destroy = false" in bootstrap, "state bucket force-destroy protection changed")
    require(bootstrap.count("prevent_destroy = true") == 2, "state bucket/KMS prevent-destroy protection changed")

    prod_variables = (root / "infra/terraform/aws/environments/prod/variables.tf").read_text()
    require("condition     = !var.cnpg_backup_force_destroy" in prod_variables, "prod backup deletion guard changed")
    legacy_destroy = (root / "scripts/destroy-aws-dev.sh").read_text()
    require('if [[ "${AWS_ENVIRONMENT}" == "aws-prod" ]]' in legacy_destroy, "prod destroy refusal changed")
    require("converge-aws-destroy-dependencies.sh" in legacy_destroy, "legacy dependency convergence missing")
    guarded_executor = (root / "scripts/execute-v0.12.4.1.5.0.7.1-guarded-aws-dev-teardown.py").read_text()
    require('"terraform", "apply", "-input=false", "-auto-approve", str(binary)' in guarded_executor, "reviewed exact-plan baseline changed")

    document = " ".join(document_path.read_text().split()).lower()
    for phrase in ("design only", "never delete the backend bucket", "two-wave teardown model", "aws-prod remains static or prod-like only", "not wired to a workflow or the root ci validator"):
        require(phrase in document, f"documentation boundary missing: {phrase}")
    for path, marker in (
        (root / "README.md", PREFIX),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.7.1.6"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.7.1.6 - Generalized multi-environment teardown hardening design"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")
    root_ci = (root / "scripts/validate-v0.12.3.3-ci-feedback-efficiency-closure.sh").read_text()
    require(PREFIX not in root_ci, "design validator is bound to root CI")
    workflows = root / ".github/workflows"
    if workflows.exists():
        for path in workflows.glob("*.y*ml"):
            require(PREFIX not in path.read_text(), f"design validator is workflow-bound: {path.name}")

    tracked_paths = [contract_path, document_path, checker_path, test_path, validator_path]
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]], capture_output=True, text=True, check=True).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "design source tracking changed")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    for path in (contract_path, document_path):
        require(modes[str(path.relative_to(root))] == "100644", f"non-executable mode changed: {path.name}")
    for path in (checker_path, test_path, validator_path):
        require(modes[str(path.relative_to(root))] == "100755", f"executable Git mode changed: {path.name}")
        require(stat.S_IMODE(path.stat().st_mode) & stat.S_IXUSR, f"owner execute bit missing: {path.name}")
    return {"liveCommandExecuted": False, "executorCount": 0, "environmentProfileCount": 3, "trackedFileCount": len(tracked_paths)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = validate_repository(args.root.resolve())
    except (ContractError, KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Generalized teardown design check failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

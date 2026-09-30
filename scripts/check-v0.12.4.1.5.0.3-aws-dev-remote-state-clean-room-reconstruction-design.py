#!/usr/bin/env python3
"""Validate the offline aws-dev remote-state clean-room reconstruction design."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess


class DesignError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DesignError(message)


def load_object(path: Path) -> dict:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def validate_contract(value: dict) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.5.0.3", "version drift")
    require(value.get("status") == "aws-dev-remote-state-clean-room-reconstruction-designed-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "125cceb62d47bffdbc254299621debd98f3cfb18", "main baseline drift")
    require(value.get("designedAtDate") == "2026-09-30", "design date drift")

    incident = value.get("triggerIncident", {})
    require(incident == {
        "operation": "v0.12.4.1.5-external-secrets-live-preflight",
        "privateRequestSha256": "972f46b1e2acfeb2db3a77022460b939da47ab8d1e9f11a372d2a256e0c99810",
        "awsIdentityStdoutSha256": "36a77793e07eb1d0d19b232cce865c755f843c4c322f086076442e144fab397c",
        "awsIdentityStderrSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "eksClusterStdoutSha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "eksClusterStderrSha256": "672606c6a94de1c10cf28d7ef8156e74166da9e38e9b4e8df89dac247dadbfdd",
        "eksErrorCode": "ResourceNotFoundException",
        "awsIdentityReadSucceeded": True,
        "kubernetesCommandStarted": False,
        "serverSideDryRunStarted": False,
        "persistentMutationExecuted": False,
        "automaticRetryPerformed": False,
        "conclusion": "aws-dev-live-baseline-absent",
    }, "incident evidence drift")

    posture = value.get("currentStatePosture", {})
    require(posture == {
        "bootstrapRemoteBackendEstablished": True,
        "bootstrapStateKey": "bootstrap/terraform.tfstate",
        "devStateKey": "environments/dev/terraform.tfstate",
        "devBackendDeclaration": "local",
        "oldCreateEntrypoint": "scripts/apply-aws-dev.sh",
        "oldCreatePathMayBeReused": False,
        "currentDevBackendPath": "infra/terraform/aws/environments/dev/backend.tf",
        "privateBackendExamplePath": "infra/terraform/aws/backend-config/dev.s3.tfbackend.example",
        "stateBootstrapOutput": "backend_configuration.dev",
    }, "current state posture drift")

    backend = value.get("cleanRoomBackendRequirements", {})
    require(backend.get("partialS3BackendRequired") is True, "partial backend disabled")
    require(backend.get("exactRemoteKey") == "environments/dev/terraform.tfstate", "dev state key drift")
    require(backend.get("privateConfigOutsideRepository") is True and backend.get("privateConfigMode") == "0600", "private backend config boundary drift")
    require(backend.get("expectedPrivateConfigFields") == ["bucket", "key", "region", "encrypt", "kms_key_id", "use_lockfile", "allowed_account_ids"], "backend field inventory drift")
    for key in ("nativeLockfileRequired", "remoteStateObjectMustBeProvenAbsent", "remoteLockObjectMustBeProvenAbsent", "localStateMustBeAbsentOrEmpty", "privateStagedTerraformSourceRequired", "sourceManifestRequired", "stateBootstrapFoundationMustBeReadOnlyValidated"):
        require(backend.get(key) is True, f"clean-room control disabled: {key}")
    require(backend.get("dynamodbLockingAllowed") is False, "DynamoDB locking enabled")
    require(backend.get("localStateMigrationAllowed") is False, "local state migration enabled")
    require(backend.get("terraformInitMode") == "-reconfigure", "Terraform init mode drift")
    require(backend.get("stagedSourceScope") == "infra/terraform/aws", "staged source scope drift")

    sequence = value.get("reconstructionSequence", [])
    require(len(sequence) == 14 and len(set(sequence)) == 14, "reconstruction sequence drift")
    require(sequence[0] == "record-redacted-missing-environment-evidence", "sequence start drift")
    require(sequence[2] == "run-separately-approved-read-only-clean-room-preflight", "preflight order drift")
    require(sequence[3:6] == ["produce-saved-create-plan", "human-review-private-create-plan", "apply-exact-reviewed-saved-plan-once"], "plan/apply order drift")
    require(sequence[8] == "converge-root-applications-with-external-secrets-2.8.0", "baseline convergence order drift")
    require(sequence[-2:] == ["review-and-execute-environment-teardown", "complete-residual-resource-and-cost-audit"], "teardown order drift")

    approvals = value.get("separateApprovalStages", [])
    require(len(approvals) == 10 and len(set(approvals)) == 10, "approval inventory drift")
    for required in ("clean-room-read-only-preflight", "saved-create-plan", "exact-saved-plan-apply", "environment-teardown", "residual-resource-and-cost-audit"):
        require(required in approvals, f"approval stage missing: {required}")

    require(value.get("costBoundary") == {
        "maximumActiveEksRehearsalEnvironments": 1,
        "maximumSessionHours": 8,
        "maximumReviewedBudgetUsd": 50,
        "privateEstimateRequired": True,
        "automaticTeardown": False,
        "teardownRequiresSeparateApproval": True,
    }, "cost boundary drift")
    require(value.get("v0125ScopeAdjustment") == {
        "minimalAwsDevRemoteStateRebuildBroughtForward": True,
        "databaseRecoveryStillV0125": True,
        "measuredRtoRpoStillV0125": True,
        "fullDisasterRecoveryStillV0125": True,
    }, "v0.12.5 scope boundary drift")

    forbidden = value.get("forbiddenOperations", [])
    require(len(forbidden) == 14 and len(set(forbidden)) == 14, "forbidden operation inventory drift")
    for required in ("reuse-old-local-state-create-path", "terraform-init-migrate-state", "terraform-state-push", "unsaved-terraform-apply", "automatic-terraform-retry", "automatic-teardown", "direct-s3-state-mutation", "force-unlock", "secret-value-read", "gitops-version-pin-mutation", "argocd-sync"):
        require(required in forbidden, f"forbidden operation missing: {required}")
    gate = value.get("overallGate", {})
    require(isinstance(gate, dict) and len(gate) == 9, "overall gate inventory drift")
    require(all(item is False for item in gate.values()), "live authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1.5.0.4-guarded-aws-dev-remote-state-clean-room-preflight", "next checkpoint drift")


def mutate(value: dict, path: list[str], replacement: object) -> dict:
    candidate = deepcopy(value)
    cursor = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def validate_repository(root: Path) -> dict:
    contract_path = root / "delivery/contracts/v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design.json"
    document_path = root / "docs/V0.12.4.1.5.0.3_AWS_DEV_REMOTE_STATE_CLEAN_ROOM_RECONSTRUCTION_DESIGN.md"
    checker_path = root / "scripts/check-v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design.py"
    validator_path = root / "scripts/validate-v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design.sh"
    contract = load_object(contract_path)
    validate_contract(contract)

    mutations = [
        (["protectedMainBaselineCommit"], "0" * 40),
        (["triggerIncident", "privateRequestSha256"], "0" * 64),
        (["triggerIncident", "eksErrorCode"], "AccessDeniedException"),
        (["triggerIncident", "awsIdentityReadSucceeded"], False),
        (["triggerIncident", "kubernetesCommandStarted"], True),
        (["triggerIncident", "serverSideDryRunStarted"], True),
        (["triggerIncident", "persistentMutationExecuted"], True),
        (["triggerIncident", "automaticRetryPerformed"], True),
        (["currentStatePosture", "oldCreatePathMayBeReused"], True),
        (["cleanRoomBackendRequirements", "exactRemoteKey"], "bootstrap/terraform.tfstate"),
        (["cleanRoomBackendRequirements", "privateConfigOutsideRepository"], False),
        (["cleanRoomBackendRequirements", "nativeLockfileRequired"], False),
        (["cleanRoomBackendRequirements", "dynamodbLockingAllowed"], True),
        (["cleanRoomBackendRequirements", "remoteStateObjectMustBeProvenAbsent"], False),
        (["cleanRoomBackendRequirements", "localStateMustBeAbsentOrEmpty"], False),
        (["cleanRoomBackendRequirements", "localStateMigrationAllowed"], True),
        (["cleanRoomBackendRequirements", "terraformInitMode"], "-migrate-state"),
        (["cleanRoomBackendRequirements", "privateStagedTerraformSourceRequired"], False),
        (["costBoundary", "maximumActiveEksRehearsalEnvironments"], 2),
        (["costBoundary", "maximumSessionHours"], 24),
        (["costBoundary", "automaticTeardown"], True),
        (["costBoundary", "teardownRequiresSeparateApproval"], False),
        (["v0125ScopeAdjustment", "databaseRecoveryStillV0125"], False),
        (["overallGate", "repositoryBackendChanged"], True),
        (["overallGate", "awsCommandExecuted"], True),
        (["overallGate", "terraformInitExecuted"], True),
        (["overallGate", "terraformApplyExecuted"], True),
        (["overallGate", "environmentCreated"], True),
        (["overallGate", "livePreflightRetried"], True),
        (["nextCheckpoint"], "v0.12.4.1.5.1-external-secrets-pin"),
    ]
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(mutate(contract, path, replacement))
        except (DesignError, KeyError, TypeError, AttributeError):
            continue
        raise DesignError(f"fail-open mutation {index}")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "does not currently exist",
        "outside the current S3/KMS and native lockfile control plane",
        "initialization uses `-reconfigure`, not `-migrate-state`",
        "complete `infra/terraform/aws` tree",
        "At most one EKS rehearsal environment",
        "Database recovery, measured RTO/RPO",
    ):
        require(phrase in document, f"design boundary missing: {phrase}")

    dev_backend = (root / "infra/terraform/aws/environments/dev/backend.tf").read_text()
    require('backend "s3"' not in dev_backend, "design checkpoint changed dev backend")
    require("local backend" in dev_backend, "current dev backend posture changed")
    bootstrap_backend = (root / "infra/terraform/aws/state-bootstrap/backend.tf").read_text()
    require('backend "s3" {}' in bootstrap_backend, "bootstrap partial backend missing")
    example = (root / "infra/terraform/aws/backend-config/dev.s3.tfbackend.example").read_text()
    require('key                 = "environments/dev/terraform.tfstate"' in example, "dev backend example key drift")
    require("use_lockfile        = true" in example, "native lockfile example disabled")
    require("dynamodb_table" not in example, "DynamoDB locking introduced")
    require((root / "scripts/apply-aws-dev.sh").is_file(), "historical create entrypoint missing")

    executor = (root / "scripts/execute-v0.12.4.1.5-external-secrets-live-preflight.py").read_text()
    eks_index = executor.index('"eks-cluster"')
    kubectl_index = executor.index('"kubectl-context"')
    dry_run_index = executor.index('"server-side-dry-run"')
    require(eks_index < kubectl_index < dry_run_index, "failed-preflight command order drift")

    for path, marker in (
        (root / "README.md", "v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design"),
        (root / "docs/ROADMAP.md", "v0.12.4.1.5.0.3 - AWS dev remote-state clean-room reconstruction design"),
        (root / "CHANGELOG.md", "## v0.12.4.1.5.0.3"),
    ):
        require(marker in path.read_text(), f"repository marker missing: {marker}")

    tracked_paths = [contract_path, document_path, checker_path, validator_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    require(len(tracked) == len(tracked_paths), "design source tracking drift")
    modes = {}
    for line in tracked:
        metadata, path = line.split("\t", 1)
        modes[path] = metadata.split()[0]
    require(modes[str(contract_path.relative_to(root))] == "100644", "contract mode drift")
    require(modes[str(document_path.relative_to(root))] == "100644", "document mode drift")
    require(modes[str(checker_path.relative_to(root))] == "100755", "checker Git mode drift")
    require(modes[str(validator_path.relative_to(root))] == "100755", "validator Git mode drift")
    require(stat.S_IMODE(checker_path.stat().st_mode) & 0o100, "checker owner execute bit missing")
    require(stat.S_IMODE(validator_path.stat().st_mode) & 0o100, "validator owner execute bit missing")
    return {"mutationCount": len(mutations), "liveCommandExecuted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = validate_repository(args.root.resolve(strict=True))
    print(f"v0.12.4.1.5.0.3 aws-dev remote-state clean-room reconstruction design and {report['mutationCount']} fail-closed mutations passed offline; no live command was executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

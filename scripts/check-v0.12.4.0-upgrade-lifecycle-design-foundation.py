#!/usr/bin/env python3
"""Validate the offline v0.12.4.0 upgrade-lifecycle design foundation."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from typing import Any


class UpgradeFoundationError(ValueError):
    """Raised when an upgrade-lifecycle boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise UpgradeFoundationError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


EXPECTED_INVENTORY = {
    "source": "repository-declarations-not-live-observation",
    "eksMinor": "1.36",
    "managedNodeAmiType": "AL2023_x86_64_STANDARD",
    "terraformVersionConstraint": ">= 1.8.0, < 2.0.0",
    "awsProviderConstraint": "~> 6.0",
    "tlsProviderConstraint": "~> 4.0",
    "managedAddons": ["aws-ebs-csi-driver", "coredns", "kube-proxy", "vpc-cni"],
    "managedAddonVersionsPinned": False,
    "argocd": "v3.5.2",
    "platformCharts": {
        "argo-rollouts": "2.41.1",
        "aws-load-balancer-controller": "1.14.0",
        "cert-manager": "v1.21.0",
        "cloudnative-pg": "0.29.0",
        "external-secrets": "2.8.0",
        "karpenter": "1.14.0",
        "karpenter-crd": "1.14.0",
        "kube-prometheus-stack": "88.5.0",
        "plugin-barman-cloud": "0.7.0",
    },
    "postgresqlImageMajor": 17,
}

EXPECTED_PHASES = [
    "freeze-current-live-inventory",
    "review-official-compatibility-matrix",
    "scan-deprecated-and-removed-apis",
    "prove-backup-and-rebuild-readiness",
    "upgrade-eks-control-plane-one-minor",
    "converge-managed-node-groups",
    "converge-eks-managed-addons",
    "converge-karpenter-and-cluster-controllers",
    "converge-platform-controllers",
    "qualify-data-plane-and-services",
    "record-rollback-or-rebuild-decision",
]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.0-upgrade-lifecycle-design-foundation-v1", "schema drift")
    require(value.get("version") == "v0.12.4.0", "version drift")
    require(value.get("status") == "upgrade-lifecycle-design-foundation-delivered-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "e236f4a867a0064c950cf223fae33a113c5d7140", "baseline drift")
    require(value.get("inventoryBoundary") == EXPECTED_INVENTORY, "inventory drift")
    require(value.get("candidateSelection") == {
        "status": "not-selected",
        "targetEksMinor": None,
        "managedAddonVersions": {},
        "platformVersions": {},
        "officialCompatibilityEvidenceReviewed": False,
        "selectionRequiresSeparateIncrement": True,
    }, "candidate selection drift")
    require(value.get("upgradeInvariants") == {
        "oneEksMinorAtATime": True,
        "environmentOrder": ["aws-dev", "aws-test"],
        "awsProdLiveUpgradeInV0124": False,
        "controlPlaneBeforeManagedNodes": True,
        "managedNodesBeforeManagedAddonsAndClients": True,
        "databaseMajorUpgradeCombinedWithEksUpgrade": False,
        "maximumConcurrentDisposableEksEnvironments": 1,
        "freshApprovalRequiredPerLivePhase": True,
        "automaticRetry": False,
        "automaticRollback": False,
    }, "upgrade invariant drift")
    require(value.get("orderedPhases") == EXPECTED_PHASES, "phase order drift")
    require(value.get("deprecatedApiPreflight") == {
        "repositoryManifestScanRequired": True,
        "helmRenderedManifestScanRequired": True,
        "liveApiUsageObservationRequiredBeforeExecution": True,
        "targetMinorRemovalCheckRequired": True,
        "unknownOrUnresolvedApiBlocksUpgrade": True,
    }, "deprecated API gate drift")
    require(value.get("recoveryModel") == {
        "eksControlPlaneDowngradeIsPrimaryRecovery": False,
        "gitopsRollbackAllowedOnlyWhenTargetApiCompatible": True,
        "forwardFixPreferredAfterControlPlaneUpgrade": True,
        "cleanRoomRebuildDecisionRequired": True,
        "remoteStateRequiredForRebuild": True,
        "stateRestoreOrPushAutomaticallyAuthorized": False,
    }, "recovery model drift")
    evidence = value.get("requiredFutureEvidence")
    require(isinstance(evidence, list) and len(evidence) == 9, "future evidence inventory drift")
    require(len(evidence) == len(set(evidence)), "duplicate future evidence")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and len(boundary) == 15, "execution boundary drift")
    require(all(item is False for item in boundary.values()), "live authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1-version-inventory-and-candidate-matrix", "next checkpoint drift")
    require(value.get("deferred") == {
        "cleanRoomInfrastructureAndGitopsRebuild": "v0.12.5",
        "databaseRecoveryAndMeasuredRtoRpo": "v0.12.5",
        "productionLiveUpgrade": "separate-future-approval-not-v0.12.4",
        "integratedDevTestProdCommercialRehearsal": "v1.0-rc.3",
        "repositoryPhysicalRestructure": "v1.0",
        "repositoryWideHumanReview": "v1.0",
    }, "deferred scope drift")
    require(value.get("packageProducer") == {
        "runsAws": False,
        "runsTerraform": False,
        "runsKubernetes": False,
        "mutatesGithub": False,
    }, "package producer drift")


def require_chart(root: Path, filename: str, chart: str, version: str) -> None:
    text = (root / "clusters/aws/base/platform" / filename).read_text()
    require(f"chart: {chart}" in text, f"chart identity drift: {chart}")
    require(f"targetRevision: {version}" in text, f"chart version drift: {chart}")


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.4.0-upgrade-lifecycle-design-foundation.json"
    document_path = root / "docs/V0.12.4.0_UPGRADE_LIFECYCLE_DESIGN_FOUNDATION.md"
    checker_path = root / "scripts/check-v0.12.4.0-upgrade-lifecycle-design-foundation.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutations: list[dict[str, Any]] = []
    for path, replacement in (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("inventoryBoundary", "eksMinor"), "1.37"),
        (("inventoryBoundary", "managedAddonVersionsPinned"), True),
        (("candidateSelection", "status"), "approved"),
        (("candidateSelection", "targetEksMinor"), "1.37"),
        (("candidateSelection", "officialCompatibilityEvidenceReviewed"), True),
        (("upgradeInvariants", "oneEksMinorAtATime"), False),
        (("upgradeInvariants", "environmentOrder"), ["aws-test", "aws-dev"]),
        (("upgradeInvariants", "awsProdLiveUpgradeInV0124"), True),
        (("upgradeInvariants", "databaseMajorUpgradeCombinedWithEksUpgrade"), True),
        (("upgradeInvariants", "automaticRetry"), True),
        (("orderedPhases",), list(reversed(EXPECTED_PHASES))),
        (("deprecatedApiPreflight", "unknownOrUnresolvedApiBlocksUpgrade"), False),
        (("recoveryModel", "eksControlPlaneDowngradeIsPrimaryRecovery"), True),
        (("recoveryModel", "stateRestoreOrPushAutomaticallyAuthorized"), True),
        (("executionBoundary", "eksUpgradeAuthorized"), True),
        (("executionBoundary", "terraformApplyAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.3-live-upgrade"),
    ):
        candidate = deepcopy(contract)
        cursor = candidate
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = replacement
        mutations.append(candidate)
    for index, candidate in enumerate(mutations, 1):
        try:
            validate_contract(candidate)
        except (AttributeError, KeyError, TypeError, UpgradeFoundationError):
            continue
        raise UpgradeFoundationError(f"fail-open mutation {index}")

    foundation = load(root / "delivery/contracts/v0.12.0-production-readiness-foundation.json")
    require(foundation.get("upgradeAndRecovery") == {
        "compatibilityMatrixRequired": True,
        "deprecatedApiPreflightRequired": True,
        "eksOneMinorAtATime": True,
        "databaseMajorUpgradeCombinedWithEksUpgrade": False,
        "rollbackOrRebuildDecisionRequired": True,
        "cleanRoomUsesRemoteState": True,
        "rtoRpoApprovedBeforeLiveExercise": True,
        "rtoRpoMeasuredFromEvidence": True,
        "defaultAvailabilityModel": "single-region-multi-az-rebuildable",
        "crossRegionActiveActiveRequired": False,
    }, "v0.12.0 upgrade/recovery foundation drift")

    for environment in ("dev", "test", "prod"):
        tfvars = (root / f"infra/terraform/aws/environments/{environment}/terraform.tfvars.example").read_text()
        require('eks_cluster_version = "1.36"' in tfvars, f"{environment} EKS declaration drift")
        versions = (root / f"infra/terraform/aws/environments/{environment}/versions.tf").read_text()
        require('required_version = ">= 1.8.0, < 2.0.0"' in versions, f"{environment} Terraform floor drift")
        require('version = "~> 6.0"' in versions, f"{environment} AWS provider drift")
        require('version = "~> 4.0"' in versions, f"{environment} TLS provider drift")
    dev_tfvars = (root / "infra/terraform/aws/environments/dev/terraform.tfvars.example").read_text()
    require('eks_node_ami_type       = "AL2023_x86_64_STANDARD"' in dev_tfvars, "node AMI declaration drift")

    eks_module = (root / "infra/terraform/aws/modules/eks/main.tf").read_text()
    for addon in EXPECTED_INVENTORY["managedAddons"]:
        require(f'"{addon}"' in eks_module, f"managed add-on missing: {addon}")
    require("addon_version" not in eks_module, "managed add-on pinning changed without matrix review")

    bootstrap = (root / "scripts/bootstrap-eks-argocd.sh").read_text()
    require('ARGOCD_VERSION="${ARGOCD_VERSION:-v3.5.2}"' in bootstrap, "Argo CD declaration drift")
    for filename, chart, version in (
        ("argo-rollouts.yaml", "argo-rollouts", "2.41.1"),
        ("aws-load-balancer-controller.yaml", "aws-load-balancer-controller", "1.14.0"),
        ("cert-manager.yaml", "cert-manager", "v1.21.0"),
        ("cloudnative-pg.yaml", "cloudnative-pg", "0.29.0"),
        ("external-secrets.yaml", "external-secrets", "2.8.0"),
        ("karpenter.yaml", "karpenter", "1.14.0"),
        ("karpenter-crd.yaml", "karpenter-crd", "1.14.0"),
        ("monitoring.yaml", "kube-prometheus-stack", "88.5.0"),
        ("barman-cloud-plugin.yaml", "plugin-barman-cloud", "0.7.0"),
    ):
        require_chart(root, filename, chart, version)
    postgres = (root / "clusters/aws/base/data-platform/postgresql/cluster.yaml").read_text()
    require("ghcr.io/cloudnative-pg/postgresql:17." in postgres, "PostgreSQL major drift")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "does not select a target EKS minor",
        "repository declarations, not a claim about current live runtime state",
        "versions are not pinned in Terraform",
        "exactly one next EKS minor",
        "Downgrading an EKS control plane is not the primary recovery path",
        "PostgreSQL major upgrade never shares the EKS upgrade window",
        "v0.12.4.1",
    ):
        require(phrase in document, f"design document boundary missing: {phrase}")
    readme = (root / "README.md").read_text()
    require("v0.12.4.0-upgrade-lifecycle-design-foundation" in readme, "README checkpoint missing")
    roadmap = (root / "docs/ROADMAP.md").read_text()
    require("v0.12.4.0 - upgrade-lifecycle design foundation" in roadmap, "roadmap increment missing")

    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", str(contract_path.relative_to(root)), str(document_path.relative_to(root)), str(checker_path.relative_to(root))],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "upgrade-foundation source tracking drift")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    require(modes[str(contract_path.relative_to(root))] == "100644", "contract mode drift")
    require(modes[str(document_path.relative_to(root))] == "100644", "document mode drift")
    require(modes[str(checker_path.relative_to(root))] == "100755", "checker mode drift")
    print(f"v0.12.4.0 upgrade-lifecycle foundation and {len(mutations)} fail-closed mutations passed offline.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_repository(args.root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

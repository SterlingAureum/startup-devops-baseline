#!/usr/bin/env python3
"""Validate the offline v0.12.4.1 official compatibility matrix."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


class CompatibilityMatrixError(ValueError):
    """Raised when a reviewed compatibility or authority boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CompatibilityMatrixError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def require_checker_worktree_mode(mode: int) -> None:
    """Require a regular owner-executable file without pinning umask bits."""
    require(stat.S_ISREG(mode), "checker worktree file type drift")
    require(bool(mode & stat.S_IXUSR), "checker owner-executable bit missing")


EXPECTED_REASONS = [
    "provisional-eks-1.37-not-listed-on-reviewed-amazon-eks-standard-support-page",
    "managed-addon-exact-versions-and-target-compatibility-unresolved",
    "external-secrets-2.8-end-of-life",
    "platform-chart-application-mappings-and-official-supportedness-unresolved",
]

EXPECTED_ADDONS = ["aws-ebs-csi-driver", "coredns", "kube-proxy", "vpc-cni"]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1-official-compatibility-matrix-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1", "version drift")
    require(value.get("status") == "official-compatibility-matrix-reviewed-upgrade-blocked", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "397e079433942e222c09f34c7e0b83e28b179f8f", "baseline drift")
    require(value.get("reviewBoundary") == {
        "reviewedAtDate": "2026-09-28",
        "officialSourcesOnly": True,
        "runtimeNetworkLookupRequired": False,
        "repositoryDeclarationsAreNotLiveObservation": True,
        "upstreamKubernetesAvailabilityDoesNotAuthorizeEksSelection": True,
    }, "review boundary drift")

    sources = value.get("officialSources")
    require(isinstance(sources, dict) and len(sources) == 11, "official source inventory drift")
    require(all(isinstance(url, str) and url.startswith("https://") for url in sources.values()), "non-HTTPS source")
    require(all("docs.aws.amazon.com" in sources[key] for key in ("eksStandardSupport", "eksUpgrade", "eksAddonCompatibility", "eksRollback")), "AWS source drift")

    require(value.get("eksCandidateGate") == {
        "currentRepositoryMinor": "1.36",
        "provisionalNextMinor": "1.37",
        "provisionalNextMinorListedOnReviewedEksStandardSupportPage": False,
        "targetEksMinorSelected": False,
        "selectionStatus": "blocked-awaiting-amazon-eks-availability",
        "oneMinorAtATime": True,
        "upstreamReleaseIsInsufficientEvidence": True,
    }, "EKS candidate gate drift")

    matrix = value.get("currentCompatibilityMatrix")
    require(isinstance(matrix, dict) and len(matrix) == 9, "component matrix drift")
    require(matrix.get("argocd", {}).get("kubernetes136Status") == "officially-tested", "Argo CD status drift")
    require(matrix.get("certManager", {}).get("kubernetes136Status") == "officially-tested", "cert-manager status drift")
    require(matrix.get("cloudNativePg") == {
        "repositoryChartVersion": "0.29.0",
        "resolvedApplicationVersion": "1.30.0",
        "kubernetes136Status": "officially-supported",
        "supportStatus": "current-compatible",
    }, "CloudNativePG mapping drift")
    require(matrix.get("karpenter", {}).get("minimumVersionForKubernetes136") == "1.13.0", "Karpenter floor drift")
    require(matrix.get("karpenter", {}).get("repositoryVersion") == "1.14.0", "Karpenter pin drift")
    require(matrix.get("externalSecrets") == {
        "repositoryVersion": "2.8.0",
        "kubernetes136Status": "compatible",
        "supportStatus": "end-of-life",
        "supportEndedAtDate": "2026-08-07",
    }, "External Secrets review drift")
    unresolved = {"awsLoadBalancerController", "argoRollouts", "kubePrometheusStack", "barmanCloudPlugin"}
    require(all(matrix[name]["kubernetes136Status"] == "unresolved" for name in unresolved), "unresolved compatibility became implicit")

    require(value.get("managedAddonGate") == {
        "addons": EXPECTED_ADDONS,
        "repositoryVersionsPinned": False,
        "exactInstalledVersionsKnown": False,
        "candidateVersionsSelected": False,
        "liveResolutionRequiredBeforeUpgrade": True,
        "officialResolutionCommandTemplate": "aws eks describe-addon-versions --addon-name <addon> --kubernetes-version <target-minor>",
        "automaticAddonUpgradeExpected": False,
    }, "managed add-on gate drift")
    require(value.get("platformSupportednessRepair") == {
        "externalSecretsCurrentLine": "2.8",
        "externalSecretsReviewedCandidateLine": "2.11",
        "sequentialMinorPath": ["2.8", "2.9", "2.10", "2.11"],
        "exactTargetPatchSelected": False,
        "separateFromEksControlPlaneUpgrade": True,
        "versionMutationAuthorized": False,
        "unresolvedChartMappingsMustClose": True,
    }, "platform repair boundary drift")
    require(value.get("conditionalEksRollback") == {
        "availableWhenAwsEligibilityChecksPass": True,
        "primaryRecovery": False,
        "automatic": False,
        "freshApprovalRequired": True,
        "maximumMinorDistance": 1,
        "eligibilityWindowDays": 7,
        "previousVersionMustRemainSupported": True,
        "managedNodesAndAddonsHandledSeparately": True,
        "applicationAndStateRollbackIncluded": False,
    }, "rollback boundary drift")
    require(value.get("overallGate") == {
        "status": "blocked",
        "reasons": EXPECTED_REASONS,
        "eksUpgradeAuthorized": False,
        "platformVersionChangeAuthorized": False,
    }, "overall gate drift")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and len(boundary) == 14, "execution boundary drift")
    require(all(item is False for item in boundary.values()), "execution authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1.1-platform-supportedness-repair-design", "next checkpoint drift")
    require(value.get("packageProducer") == {
        "runsAws": False,
        "runsTerraform": False,
        "runsKubernetes": False,
        "mutatesGithub": False,
    }, "package producer drift")


def set_path(value: dict[str, Any], path: tuple[str, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def require_chart(root: Path, filename: str, chart: str, version: str) -> None:
    text = (root / "clusters/aws/base/platform" / filename).read_text()
    require(f"chart: {chart}" in text, f"chart identity drift: {chart}")
    require(f"targetRevision: {version}" in text, f"chart version drift: {chart}")


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.4.1-official-compatibility-matrix.json"
    document_path = root / "docs/V0.12.4.1_OFFICIAL_COMPATIBILITY_MATRIX.md"
    checker_path = root / "scripts/check-v0.12.4.1-official-compatibility-matrix.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutation_specs = (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("reviewBoundary", "runtimeNetworkLookupRequired"), True),
        (("reviewBoundary", "upstreamKubernetesAvailabilityDoesNotAuthorizeEksSelection"), False),
        (("eksCandidateGate", "provisionalNextMinorListedOnReviewedEksStandardSupportPage"), True),
        (("eksCandidateGate", "targetEksMinorSelected"), True),
        (("eksCandidateGate", "selectionStatus"), "approved"),
        (("currentCompatibilityMatrix", "cloudNativePg", "resolvedApplicationVersion"), "1.29.0"),
        (("currentCompatibilityMatrix", "externalSecrets", "supportStatus"), "supported"),
        (("currentCompatibilityMatrix", "awsLoadBalancerController", "kubernetes136Status"), "compatible"),
        (("managedAddonGate", "exactInstalledVersionsKnown"), True),
        (("managedAddonGate", "candidateVersionsSelected"), True),
        (("managedAddonGate", "automaticAddonUpgradeExpected"), True),
        (("platformSupportednessRepair", "sequentialMinorPath"), ["2.8", "2.11"]),
        (("platformSupportednessRepair", "separateFromEksControlPlaneUpgrade"), False),
        (("platformSupportednessRepair", "versionMutationAuthorized"), True),
        (("conditionalEksRollback", "primaryRecovery"), True),
        (("conditionalEksRollback", "automatic"), True),
        (("conditionalEksRollback", "eligibilityWindowDays"), 30),
        (("overallGate", "status"), "ready"),
        (("overallGate", "eksUpgradeAuthorized"), True),
        (("executionBoundary", "awsReadAuthorized"), True),
        (("executionBoundary", "versionDeclarationMutationAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.2-live-eks-upgrade"),
    )
    for index, (path, replacement) in enumerate(mutation_specs, 1):
        try:
            validate_contract(set_path(contract, path, replacement))
        except (AttributeError, KeyError, TypeError, CompatibilityMatrixError):
            continue
        raise CompatibilityMatrixError(f"fail-open mutation {index}")

    predecessor = load(root / "delivery/contracts/v0.12.4.0-upgrade-lifecycle-design-foundation.json")
    require(predecessor.get("nextCheckpoint") == "v0.12.4.1-version-inventory-and-candidate-matrix", "predecessor handoff drift")
    require(predecessor.get("inventoryBoundary", {}).get("eksMinor") == "1.36", "predecessor EKS inventory drift")
    require(predecessor.get("candidateSelection", {}).get("targetEksMinor") is None, "predecessor selected target unexpectedly")

    for environment in ("dev", "test", "prod"):
        tfvars = (root / f"infra/terraform/aws/environments/{environment}/terraform.tfvars.example").read_text()
        require('eks_cluster_version = "1.36"' in tfvars, f"{environment} EKS declaration drift")
    eks_module = (root / "infra/terraform/aws/modules/eks/main.tf").read_text()
    for addon in EXPECTED_ADDONS:
        require(f'"{addon}"' in eks_module, f"managed add-on missing: {addon}")
    require("addon_version" not in eks_module, "managed add-on pin changed during offline review")
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

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "deliberately **blocked**, not failed",
        "does not list the provisional next minor, 1.37",
        "chart `0.29.0` resolves to application `1.30.0`",
        "compatible with Kubernetes 1.36 but is no longer a supported release line",
        "2.8 -> 2.9 -> 2.10 -> 2.11",
        "conditional recovery option, not the primary or automatic recovery path",
        "v0.12.4.1.1-platform-supportedness-repair-design",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    readme = (root / "README.md").read_text()
    require("v0.12.4.1-official-compatibility-matrix" in readme, "README checkpoint missing")
    roadmap = (root / "docs/ROADMAP.md").read_text()
    require("v0.12.4.1 - official compatibility matrix" in roadmap, "roadmap increment missing")
    changelog = (root / "CHANGELOG.md").read_text()
    require("## v0.12.4.1" in changelog, "changelog entry missing")

    tracked_paths = [contract_path, document_path, checker_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "compatibility matrix source tracking drift")
    modes = {line.split("\t", 1)[1]: line.split()[0] for line in tracked}
    require(modes[str(contract_path.relative_to(root))] == "100644", "contract mode drift")
    require(modes[str(document_path.relative_to(root))] == "100644", "document mode drift")
    require(modes[str(checker_path.relative_to(root))] == "100755", "checker mode drift")
    require_checker_worktree_mode(checker_path.stat().st_mode)

    for accepted_mode in (0o755, 0o775):
        require_checker_worktree_mode(stat.S_IFREG | accepted_mode)
    for rejected_mode in (0o644, 0o664):
        try:
            require_checker_worktree_mode(stat.S_IFREG | rejected_mode)
        except CompatibilityMatrixError:
            continue
        raise CompatibilityMatrixError(f"non-executable worktree mode accepted: {oct(rejected_mode)}")

    print(
        f"v0.12.4.1 official compatibility matrix and {len(mutation_specs)} "
        "fail-closed mutations passed offline; 0755/0775 executable modes accepted."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_repository(args.root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the offline v0.12.4.1.1 platform supportedness repair design."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


class SupportednessDesignError(ValueError):
    """Raised when a supportedness or execution boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SupportednessDesignError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def require_checker_worktree_mode(mode: int) -> None:
    require(stat.S_ISREG(mode), "checker worktree file type drift")
    require(bool(mode & stat.S_IXUSR), "checker owner-executable bit missing")


EXPECTED_MAPPINGS = {
    "awsLoadBalancerController": {
        "repositoryChartVersion": "1.14.0",
        "resolvedApplicationVersion": "v2.14.0",
        "mappingStatus": "resolved",
        "kubernetes136Decision": "requires-render-and-runtime-qualification",
        "versionCandidateSelected": False,
    },
    "argoRollouts": {
        "repositoryChartVersion": "2.41.1",
        "resolvedApplicationVersion": "v1.9.1",
        "mappingStatus": "resolved",
        "kubernetes136Decision": "requires-render-and-runtime-qualification",
        "maintainerSupportPolicy": "latest-upstream-release-only",
        "versionCandidateSelected": False,
    },
    "kubePrometheusStack": {
        "repositoryChartVersion": "88.5.0",
        "resolvedPrometheusOperatorVersion": "v0.93.0",
        "declaredKubernetesFloor": ">=1.25.0-0",
        "mappingStatus": "resolved",
        "kubernetes136Decision": "chart-metadata-compatible-crd-proof-required",
        "versionCandidateSelected": False,
    },
    "barmanCloudPlugin": {
        "repositoryChartVersion": "0.7.0",
        "resolvedApplicationVersion": "v0.13.0",
        "mappingStatus": "resolved",
        "kubernetes136Decision": "requires-cnpg-backup-restore-qualification",
        "versionCandidateSelected": False,
    },
}

EXPECTED_HOP_EVIDENCE = [
    "signed-chart-metadata-and-digest",
    "release-notes-and-breaking-change-review",
    "repository-api-and-custom-resource-inventory",
    "helm-render-and-crd-diff",
    "server-side-dry-run-in-disposable-environment",
    "secret-refresh-and-rotation-qualification",
    "argocd-sync-health-and-observability-qualification",
    "rollback-or-forward-fix-decision",
]

EXPECTED_BLOCKS = [
    "external-secrets-2.8-remains-end-of-life-in-repository",
    "exact-platform-repair-candidates-and-digests-not-selected",
    "managed-addon-installed-and-target-versions-not-live-resolved",
    "provisional-eks-1.37-not-selected",
]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.1-platform-supportedness-repair-design-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.1", "version drift")
    require(value.get("status") == "platform-supportedness-repair-designed-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "f9d90c05410c881023000650361b58023fa26d93", "baseline drift")
    require(value.get("reviewBoundary") == {
        "reviewedAtDate": "2026-09-28",
        "repositoryDeclarationsAreNotLiveObservation": True,
        "runtimeNetworkLookupRequired": False,
        "chartMetadataResolutionIsNotUpgradeAuthorization": True,
        "compatibilityAndMaintainerSupportAreSeparateDecisions": True,
    }, "review boundary drift")
    require(value.get("resolvedChartMappings") == EXPECTED_MAPPINGS, "resolved chart mapping drift")

    repair = value.get("externalSecretsRepair")
    require(repair == {
        "currentRepositoryVersion": "2.8.0",
        "currentSupportStatus": "end-of-life",
        "reviewedDestinationLine": "2.11",
        "exactDestinationPatchSelected": False,
        "orderedMinorPath": ["2.8", "2.9", "2.10", "2.11"],
        "oneMinorPerReviewedChange": True,
        "combineWithEksControlPlaneUpgrade": False,
        "combineWithAnotherControllerUpgrade": False,
        "requiredPerHopEvidence": EXPECTED_HOP_EVIDENCE,
        "versionDeclarationMutationAuthorized": False,
    }, "External Secrets repair drift")

    qualification = value.get("controllerQualificationDesign")
    require(isinstance(qualification, dict), "controller qualification missing")
    require(qualification.get("sharedRules") == {
        "oneControllerPerChangeWindow": True,
        "exactCandidateAndDigestRequired": True,
        "renderedManifestDiffRequired": True,
        "crdDiffRequiredWhenPresent": True,
        "liveQualificationRequiresFreshApproval": True,
        "combineWithEksControlPlaneUpgrade": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }, "shared controller rules drift")
    require(qualification.get("awsLoadBalancerController") == [
        "iam-policy-diff",
        "crd-and-targetgroupbinding-diff",
        "ingress-alb-and-service-nlb-qualification",
    ], "Load Balancer Controller gate drift")
    require(qualification.get("argoRollouts") == [
        "no-active-rollout-or-promotion-at-upgrade",
        "rollout-crd-and-analysis-template-diff",
        "canary-pause-promote-abort-qualification",
    ], "Argo Rollouts gate drift")
    require(qualification.get("kubePrometheusStack") == [
        "explicit-prometheus-operator-crd-handling",
        "prometheus-rule-and-servicemonitor-render-diff",
        "alerts-dashboards-and-target-health-qualification",
    ], "monitoring gate drift")
    require(qualification.get("barmanCloudPlugin") == [
        "cloudnativepg-plugin-compatibility-review",
        "objectstore-and-cluster-reference-diff",
        "successful-backup-and-restore-rehearsal",
    ], "Barman Cloud gate drift")

    require(value.get("candidateSelectionPolicy") == {
        "blindLatestUpgradeAllowed": False,
        "exactPatchSelectionRequiresSeparateCheckpoint": True,
        "signedOrPublisherControlledMetadataRequired": True,
        "releaseNotesRequired": True,
        "repositoryPinChangesInThisIncrement": False,
        "currentPinsRemainFrozen": True,
    }, "candidate policy drift")
    require(value.get("remainingUpgradeBlocks") == EXPECTED_BLOCKS, "remaining block drift")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and len(boundary) == 14, "execution boundary drift")
    require(all(item is False for item in boundary.values()), "live authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1.2-external-secrets-supportedness-repair-plan", "next checkpoint drift")
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
    contract_path = root / "delivery/contracts/v0.12.4.1.1-platform-supportedness-repair-design.json"
    document_path = root / "docs/V0.12.4.1.1_PLATFORM_SUPPORTEDNESS_REPAIR_DESIGN.md"
    checker_path = root / "scripts/check-v0.12.4.1.1-platform-supportedness-repair-design.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutation_specs = (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("reviewBoundary", "runtimeNetworkLookupRequired"), True),
        (("reviewBoundary", "chartMetadataResolutionIsNotUpgradeAuthorization"), False),
        (("resolvedChartMappings", "awsLoadBalancerController", "resolvedApplicationVersion"), "v3.0.0"),
        (("resolvedChartMappings", "argoRollouts", "resolvedApplicationVersion"), "v1.9.0"),
        (("resolvedChartMappings", "argoRollouts", "versionCandidateSelected"), True),
        (("resolvedChartMappings", "kubePrometheusStack", "resolvedPrometheusOperatorVersion"), "v0.92.0"),
        (("resolvedChartMappings", "barmanCloudPlugin", "mappingStatus"), "unresolved"),
        (("externalSecretsRepair", "currentSupportStatus"), "supported"),
        (("externalSecretsRepair", "exactDestinationPatchSelected"), True),
        (("externalSecretsRepair", "orderedMinorPath"), ["2.8", "2.11"]),
        (("externalSecretsRepair", "oneMinorPerReviewedChange"), False),
        (("externalSecretsRepair", "combineWithEksControlPlaneUpgrade"), True),
        (("externalSecretsRepair", "versionDeclarationMutationAuthorized"), True),
        (("controllerQualificationDesign", "sharedRules", "oneControllerPerChangeWindow"), False),
        (("controllerQualificationDesign", "sharedRules", "liveQualificationRequiresFreshApproval"), False),
        (("controllerQualificationDesign", "sharedRules", "automaticRetry"), True),
        (("candidateSelectionPolicy", "blindLatestUpgradeAllowed"), True),
        (("candidateSelectionPolicy", "repositoryPinChangesInThisIncrement"), True),
        (("remainingUpgradeBlocks",), EXPECTED_BLOCKS[:-1]),
        (("executionBoundary", "awsReadAuthorized"), True),
        (("executionBoundary", "kubernetesMutationAuthorized"), True),
        (("executionBoundary", "controllerUpgradeAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.2-live-upgrade"),
    )
    for index, (path, replacement) in enumerate(mutation_specs, 1):
        try:
            validate_contract(set_path(contract, path, replacement))
        except (AttributeError, KeyError, TypeError, SupportednessDesignError):
            continue
        raise SupportednessDesignError(f"fail-open mutation {index}")

    predecessor = load(root / "delivery/contracts/v0.12.4.1-official-compatibility-matrix.json")
    require(predecessor.get("nextCheckpoint") == "v0.12.4.1.1-platform-supportedness-repair-design", "predecessor handoff drift")
    require(predecessor.get("overallGate", {}).get("status") == "blocked", "predecessor gate drift")
    require(predecessor.get("currentCompatibilityMatrix", {}).get("externalSecrets", {}).get("supportStatus") == "end-of-life", "predecessor ESO status drift")

    for filename, chart, version in (
        ("aws-load-balancer-controller.yaml", "aws-load-balancer-controller", "1.14.0"),
        ("argo-rollouts.yaml", "argo-rollouts", "2.41.1"),
        ("monitoring.yaml", "kube-prometheus-stack", "88.5.0"),
        ("barman-cloud-plugin.yaml", "plugin-barman-cloud", "0.7.0"),
        ("external-secrets.yaml", "external-secrets", "2.8.0"),
    ):
        require_chart(root, filename, chart, version)

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "Chart metadata resolution is not upgrade authorization",
        "Compatibility and maintainer support are separate decisions",
        "AWS Load Balancer Controller chart `1.14.0`",
        "controller `v2.14.0`",
        "Argo Rollouts chart `2.41.1`",
        "Rollouts `v1.9.1`",
        "Prometheus Operator `v0.93.0`",
        "Barman Cloud plugin `v0.13.0`",
        "2.8 -> 2.9 -> 2.10 -> 2.11",
        "One controller is changed per window",
        "No automatic retry or automatic rollback is allowed",
        "v0.12.4.1.2-external-secrets-supportedness-repair-plan",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    readme = (root / "README.md").read_text()
    require("v0.12.4.1.1-platform-supportedness-repair-design" in readme, "README checkpoint missing")
    roadmap = (root / "docs/ROADMAP.md").read_text()
    require("v0.12.4.1.1 - platform supportedness repair design" in roadmap, "roadmap increment missing")
    changelog = (root / "CHANGELOG.md").read_text()
    require("## v0.12.4.1.1" in changelog, "changelog entry missing")

    tracked_paths = [contract_path, document_path, checker_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "supportedness source tracking drift")
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
        except SupportednessDesignError:
            continue
        raise SupportednessDesignError(f"non-executable worktree mode accepted: {oct(rejected_mode)}")

    print(
        f"v0.12.4.1.1 platform supportedness repair design and {len(mutation_specs)} "
        "fail-closed mutations passed offline; repository version pins remain unchanged."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_repository(args.root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

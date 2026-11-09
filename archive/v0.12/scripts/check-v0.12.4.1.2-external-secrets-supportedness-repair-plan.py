#!/usr/bin/env python3
"""Validate the offline v0.12.4.1.2 External Secrets repair plan."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


class ExternalSecretsRepairPlanError(ValueError):
    """Raised when the reviewed plan or authority boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExternalSecretsRepairPlanError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def require_checker_worktree_mode(mode: int) -> None:
    require(stat.S_ISREG(mode), "checker worktree file type drift")
    require(bool(mode & stat.S_IXUSR), "checker owner-executable bit missing")


EXPECTED_LINES = [
    {
        "line": "2.8",
        "kubernetesCompatibility": "1.35-1.36",
        "releasedAtDate": "2026-07-18",
        "endOfLifeAtDate": "2026-08-07",
        "role": "current-repository-source",
    },
    {
        "line": "2.9",
        "kubernetesCompatibility": "1.36",
        "releasedAtDate": "2026-08-07",
        "endOfLifeAtDate": "2026-08-28",
        "role": "required-eol-bridge",
    },
    {
        "line": "2.10",
        "kubernetesCompatibility": "1.36",
        "releasedAtDate": "2026-08-28",
        "endOfLifeAtDate": "2026-09-18",
        "role": "required-eol-bridge",
    },
    {
        "line": "2.11",
        "kubernetesCompatibility": "1.36",
        "releasedAtDate": "2026-09-18",
        "endOfLifeAtDate": None,
        "role": "supported-destination",
    },
]

EXPECTED_HOPS = [
    {
        "hop": 1,
        "fromVersion": "2.8.0",
        "toVersion": "2.9.0",
        "chartReleaseTag": "helm-chart-2.9.0",
        "applicationReleaseTag": "v2.9.0",
        "steadyStateAllowed": False,
    },
    {
        "hop": 2,
        "fromVersion": "2.9.0",
        "toVersion": "2.10.0",
        "chartReleaseTag": "helm-chart-2.10.0",
        "applicationReleaseTag": "v2.10.0",
        "steadyStateAllowed": False,
    },
    {
        "hop": 3,
        "fromVersion": "2.10.0",
        "toVersion": "2.11.0",
        "chartReleaseTag": "helm-chart-2.11.0",
        "applicationReleaseTag": "v2.11.0",
        "steadyStateAllowed": True,
    },
]

EXPECTED_GATES = [
    "verify-publisher-chart-and-application-identity",
    "review-release-notes-and-breaking-changes",
    "render-exact-repository-values-offline",
    "diff-crds-rbac-webhooks-deployments-and-serviceaccount-behavior",
    "prove-no-cluster-scoped-or-pushsecret-expansion",
    "server-side-dry-run-in-disposable-aws-dev",
    "verify-argocd-sync-health-and-three-deployments-ready",
    "verify-irsa-and-namespace-scoped-rbac",
    "verify-secretstore-and-externalsecret-ready",
    "verify-awscurrent-refresh-without-secret-value-disclosure",
    "record-observability-and-forward-fix-or-rollback-decision",
]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.2-external-secrets-supportedness-repair-plan-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.2", "version drift")
    require(value.get("status") == "external-secrets-supportedness-repair-planned-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "7e7262e8b6ba77208f0712e5fd8244945f95b3c0", "baseline drift")
    require(value.get("reviewBoundary") == {
        "reviewedAtDate": "2026-09-29",
        "officialSourcesOnly": True,
        "runtimeNetworkLookupRequired": False,
        "repositoryDeclarationsAreNotLiveObservation": True,
        "candidateSelectionIsNotVersionMutationAuthority": True,
    }, "review boundary drift")
    sources = value.get("officialSources")
    require(isinstance(sources, dict) and len(sources) == 3, "official source inventory drift")
    require(all(isinstance(url, str) and url.startswith("https://") for url in sources.values()), "non-HTTPS source")

    support = value.get("supportReview")
    require(support == {
        "kubernetesMinor": "1.36",
        "publisherPolicy": "only-current-minor-supported",
        "currentSupportedLine": "2.11",
        "currentSupportedLineReleasedAtDate": "2026-09-18",
        "currentSupportedLineEndOfLife": "release-of-2.12",
        "upgradeOneMinorAtATimeRecommended": True,
        "nonProductionValidationRecommended": True,
        "lines": EXPECTED_LINES,
    }, "support review drift")
    require(value.get("selectedHopCandidates") == EXPECTED_HOPS, "selected hop drift")

    inventory = value.get("repositoryScopeInventory")
    require(inventory == {
        "operatorApplicationPath": "clusters/aws/base/platform/external-secrets.yaml",
        "currentChartVersion": "2.8.0",
        "installCrds": True,
        "serverSideApply": True,
        "scopedRbac": True,
        "scopedNamespace": "startup-apps",
        "serviceAccountCreatedByChart": False,
        "customResourceApiVersion": "external-secrets.io/v1",
        "customResources": [
            {"kind": "ExternalSecret", "count": 1, "scope": "namespaced"},
            {"kind": "SecretStore", "count": 1, "scope": "namespaced"},
        ],
        "clusterScopedCustomResourcesEnabled": False,
        "pushSecretEnabled": False,
        "staticAwsCredentialsCommitted": False,
        "irsaAnnotationInjectedOutsideChart": True,
    }, "repository scope inventory drift")

    proof = value.get("artifactProofRequiredBeforeMutation")
    require(proof == {
        "publisherChartPackageRequiredForEveryHop": True,
        "chartSha256RequiredForEveryHop": True,
        "chartAndApplicationReleaseTagsMustMatchCandidate": True,
        "chartApplicationLifecyclesTreatedSeparately": True,
        "chartMetadataRequired": ["name", "version", "appVersion", "kubeVersion"],
        "renderedManifestRequiredForEveryHop": True,
        "renderedManifestSha256RequiredForEveryHop": True,
        "crdInventoryAndDiffRequiredForEveryHop": True,
        "valuesSchemaAndRepositoryValuesCompatibilityRequired": True,
        "artifactProofProducedByThisIncrement": False,
    }, "artifact proof boundary drift")
    require(value.get("perHopGates") == EXPECTED_GATES, "per-hop gate drift")
    require(value.get("sequencing") == {
        "hopOrder": ["2.8.0-to-2.9.0", "2.9.0-to-2.10.0", "2.10.0-to-2.11.0"],
        "oneHopPerPullRequest": True,
        "oneHopPerLiveApprovalWindow": True,
        "intermediateBridgeMustConvergeBeforeNextHop": True,
        "intermediateBridgeMayRemainSteadyState": False,
        "environmentOrder": ["aws-dev", "aws-test"],
        "awsProdExecutionInV012412": False,
        "combineWithEksOrOtherControllerUpgrade": False,
        "automaticProgression": False,
    }, "sequencing drift")
    require(value.get("recoveryBoundary") == {
        "gitopsRollbackOnlyToLastQualifiedHop": True,
        "rollbackRequiresFreshApproval": True,
        "rollbackMustRemainApiAndCrdCompatible": True,
        "secretValuesBackedUpOrPublishedAsEvidence": False,
        "directKubernetesSecretMutationAuthorized": False,
        "automaticRetry": False,
        "automaticRollback": False,
    }, "recovery boundary drift")
    require(value.get("overallGate") == {
        "status": "blocked-awaiting-artifact-and-render-proof",
        "exactCandidatesSelected": True,
        "chartDigestsCaptured": False,
        "renderAndCrdDiffCompleted": False,
        "repositoryVersionChanged": False,
        "liveUpgradeAuthorized": False,
    }, "overall gate drift")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and len(boundary) == 14, "execution boundary drift")
    require(all(item is False for item in boundary.values()), "live authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1.3-external-secrets-artifact-and-render-proof", "next checkpoint drift")
    require(value.get("packageProducer") == {
        "runsNetworkDownloads": False,
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


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.4.1.2-external-secrets-supportedness-repair-plan.json"
    document_path = root / "docs/V0.12.4.1.2_EXTERNAL_SECRETS_SUPPORTEDNESS_REPAIR_PLAN.md"
    checker_path = root / "scripts/check-v0.12.4.1.2-external-secrets-supportedness-repair-plan.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutation_specs = (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("reviewBoundary", "runtimeNetworkLookupRequired"), True),
        (("reviewBoundary", "candidateSelectionIsNotVersionMutationAuthority"), False),
        (("supportReview", "currentSupportedLine"), "2.10"),
        (("supportReview", "upgradeOneMinorAtATimeRecommended"), False),
        (("supportReview", "lines"), EXPECTED_LINES[:-1]),
        (("selectedHopCandidates",), [EXPECTED_HOPS[2]]),
        (("repositoryScopeInventory", "currentChartVersion"), "2.11.0"),
        (("repositoryScopeInventory", "clusterScopedCustomResourcesEnabled"), True),
        (("repositoryScopeInventory", "pushSecretEnabled"), True),
        (("repositoryScopeInventory", "staticAwsCredentialsCommitted"), True),
        (("artifactProofRequiredBeforeMutation", "chartSha256RequiredForEveryHop"), False),
        (("artifactProofRequiredBeforeMutation", "chartApplicationLifecyclesTreatedSeparately"), False),
        (("artifactProofRequiredBeforeMutation", "crdInventoryAndDiffRequiredForEveryHop"), False),
        (("artifactProofRequiredBeforeMutation", "artifactProofProducedByThisIncrement"), True),
        (("perHopGates",), EXPECTED_GATES[:-1]),
        (("sequencing", "oneHopPerPullRequest"), False),
        (("sequencing", "intermediateBridgeMayRemainSteadyState"), True),
        (("sequencing", "environmentOrder"), ["aws-test", "aws-dev"]),
        (("sequencing", "awsProdExecutionInV012412"), True),
        (("sequencing", "automaticProgression"), True),
        (("recoveryBoundary", "secretValuesBackedUpOrPublishedAsEvidence"), True),
        (("recoveryBoundary", "directKubernetesSecretMutationAuthorized"), True),
        (("recoveryBoundary", "automaticRollback"), True),
        (("overallGate", "status"), "ready"),
        (("overallGate", "repositoryVersionChanged"), True),
        (("executionBoundary", "networkArtifactDownloadAuthorized"), True),
        (("executionBoundary", "versionDeclarationMutationAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.1.4-live-external-secrets-upgrade"),
    )
    for index, (path, replacement) in enumerate(mutation_specs, 1):
        try:
            validate_contract(set_path(contract, path, replacement))
        except (AttributeError, KeyError, TypeError, ExternalSecretsRepairPlanError):
            continue
        raise ExternalSecretsRepairPlanError(f"fail-open mutation {index}")

    predecessor = load(root / "delivery/contracts/v0.12.4.1.1-platform-supportedness-repair-design.json")
    require(predecessor.get("nextCheckpoint") == "v0.12.4.1.2-external-secrets-supportedness-repair-plan", "predecessor handoff drift")
    require(predecessor.get("externalSecretsRepair", {}).get("orderedMinorPath") == ["2.8", "2.9", "2.10", "2.11"], "predecessor path drift")
    require(predecessor.get("externalSecretsRepair", {}).get("versionDeclarationMutationAuthorized") is False, "predecessor authority drift")

    operator = (root / "clusters/aws/base/platform/external-secrets.yaml").read_text()
    for marker in (
        "targetRevision: 2.8.0",
        "installCRDs: true",
        "createClusterExternalSecret: false",
        "createClusterSecretStore: false",
        "createClusterGenerator: false",
        "createClusterPushSecret: false",
        "createPushSecret: false",
        "createSecretStore: true",
        "scopedRBAC: true",
        "scopedNamespace: startup-apps",
        "processClusterExternalSecret: false",
        "processClusterPushSecret: false",
        "processClusterStore: false",
        "processClusterGenerator: false",
        "processPushSecret: false",
        "serviceAccount:",
        "create: false",
        "ServerSideApply=true",
    ):
        require(marker in operator, f"operator scope drift: {marker}")
    require("latest" not in operator.lower(), "floating chart version accepted")
    require("eks.amazonaws.com/role-arn" not in operator, "private IRSA identity committed")

    resource_dir = root / "clusters/aws/base/security/external-secrets/startup-apps"
    external_documents = []
    for path in sorted(resource_dir.glob("*.yaml")):
        text = path.read_text()
        if "apiVersion: external-secrets.io/v1" in text:
            external_documents.append((path.name, text))
    require(len(external_documents) == 2, "External Secrets custom resource inventory drift")
    kinds = sorted(
        line.split(":", 1)[1].strip()
        for _, text in external_documents
        for line in text.splitlines()
        if line.startswith("kind:")
    )
    require(kinds == ["ExternalSecret", "SecretStore"], "External Secrets kind inventory drift")
    for _, text in external_documents:
        require("namespace: startup-apps" in text, "non-namespaced External Secrets resource")
        require("ClusterSecretStore" not in text, "cluster store introduced")
        require("PushSecret" not in text, "PushSecret introduced")
        require("accessKeyIDSecretRef" not in text and "secretAccessKeySecretRef" not in text, "static AWS credential introduced")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "2.8.0 -> 2.9.0 -> 2.10.0 -> 2.11.0",
        "Candidate selection is not version mutation authority",
        "required bridge releases, not acceptable steady states",
        "ESO and its Helm chart have separate release lifecycles",
        "exactly two namespaced `external-secrets.io/v1` custom resources",
        "One hop is allowed per PR and per approval window",
        "blocked-awaiting-artifact-and-render-proof",
        "v0.12.4.1.3-external-secrets-artifact-and-render-proof",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    readme = (root / "README.md").read_text()
    require("v0.12.4.1.2-external-secrets-supportedness-repair-plan" in readme, "README checkpoint missing")
    roadmap = (root / "docs/ROADMAP.md").read_text()
    require("v0.12.4.1.2 - External Secrets supportedness repair plan" in roadmap, "roadmap increment missing")
    changelog = (root / "CHANGELOG.md").read_text()
    require("## v0.12.4.1.2" in changelog, "changelog entry missing")

    tracked_paths = [contract_path, document_path, checker_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "repair plan source tracking drift")
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
        except ExternalSecretsRepairPlanError:
            continue
        raise ExternalSecretsRepairPlanError(f"non-executable worktree mode accepted: {oct(rejected_mode)}")

    print(
        f"v0.12.4.1.2 External Secrets repair plan and {len(mutation_specs)} "
        "fail-closed mutations passed offline; chart 2.8.0 remains pinned."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    validate_repository(args.root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

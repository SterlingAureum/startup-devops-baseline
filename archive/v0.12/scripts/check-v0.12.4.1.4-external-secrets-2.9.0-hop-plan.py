#!/usr/bin/env python3
"""Validate the offline External Secrets 2.9.0 first-hop plan."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


class FirstHopPlanError(ValueError):
    """Raised when the reviewed first-hop boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FirstHopPlanError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def require_checker_worktree_mode(mode: int) -> None:
    require(stat.S_ISREG(mode), "checker worktree file type drift")
    require(bool(mode & stat.S_IXUSR), "checker owner-executable bit missing")


EXPECTED_RELEASE_CHANGES = [
    ("external-secret-optional-strategy-default-removal", "compatible-explicit-values"),
    ("secret-template-from-target-restriction", "not-exercised"),
    ("controller-runtime-upgrade", "requires-live-convergence-proof"),
    ("optional-scheduler-and-runtime-class-values", "not-enabled"),
    ("aws-replication-delete-fixes", "outside-active-read-path"),
]

EXPECTED_PREFLIGHT = [
    "verify-exact-aws-account-region-cluster-and-kubernetes-minor",
    "verify-protected-main-and-private-request-digests",
    "verify-argo-applications-synced-healthy-and-operation-free",
    "verify-live-source-chart-and-three-v2.8.0-deployment-images",
    "verify-controller-irsa-and-namespace-scoped-rbac",
    "verify-secretstore-and-externalsecret-ready",
    "verify-awscurrent-reference-without-reading-secret-values",
    "verify-no-deleting-resources-or-unknown-finalizers",
    "verify-private-2.9.0-chart-and-render-digests",
    "run-exact-full-render-server-side-dry-run-with-name-only-output",
    "verify-server-side-dry-run-created-no-persistent-object-or-secret-change",
]


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.4-external-secrets-2.9.0-hop-plan-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.4", "version drift")
    require(value.get("status") == "external-secrets-2.9.0-first-hop-planned-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "b426a9cb39788503c2f9769529c80a85af792122", "baseline drift")
    require(value.get("reviewedAtDate") == "2026-09-29", "review date drift")

    require(value.get("releaseIdentity") == {
        "sourceChartVersion": "2.8.0",
        "sourceApplicationVersion": "v2.8.0",
        "targetChartVersion": "2.9.0",
        "targetApplicationVersion": "v2.9.0",
        "targetApplicationReleaseCommit": "378bdb622ed9712ef4a58370f6a17af033b7d343",
        "targetApplicationPublishedAtUtc": "2026-08-07T16:37:22Z",
        "targetChartReleaseCommit": "cc5bfbc2234ace9cb0caff4ea89c435cf517b27b",
        "targetChartPublishedAtUtc": "2026-08-08T12:43:21Z",
        "targetChartSha256": "da2d5c126a103b4c1b16a9dc1c168c4332a3687144e88ac070e594f81a0b6578",
        "targetRenderedManifestSha256": "880e6805213cf77cd89cf0e60e03624bc01c74d23a2c61693a1be2a5ce2ca8bb",
    }, "release identity drift")

    sources = value.get("officialSources")
    require(isinstance(sources, dict) and len(sources) == 5, "official source inventory drift")
    require(all(isinstance(url, str) and url.startswith("https://github.com/external-secrets/external-secrets/") for url in sources.values()), "official source drift")

    review = value.get("releaseNoteReview")
    require(isinstance(review, dict), "release review missing")
    require(review.get("announcedManualMigrationRequired") is False, "manual migration review drift")
    changes = review.get("repositoryRelevantChanges")
    require(isinstance(changes, list) and len(changes) == 5, "release change inventory drift")
    require([(item.get("change"), item.get("repositoryDisposition")) for item in changes] == EXPECTED_RELEASE_CHANGES, "release disposition drift")
    require(all(isinstance(item.get("effect"), str) and item["effect"] for item in changes), "release effect missing")
    require(all(isinstance(item.get("reason"), str) and item["reason"] for item in changes), "release reason missing")
    require(review.get("securityFixesIncluded") is True, "security review drift")
    require(review.get("dependencyAndControllerRuntimeChangesRequireObservation") is True, "runtime observation weakened")
    require(review.get("staticCompatibilityIsNotLiveQualification") is True, "static proof promoted to live proof")

    require(value.get("firstHopScope") == {
        "environment": "aws-dev",
        "cluster": "startup-devops-baseline-dev",
        "region": "us-east-1",
        "kubernetesMinor": "1.36",
        "operatorApplication": "external-secrets",
        "resourceApplication": "external-secrets-startup-apps",
        "operatorApplicationPath": "clusters/aws/base/platform/external-secrets.yaml",
        "allowedFutureGitMutation": {
            "path": "clusters/aws/base/platform/external-secrets.yaml",
            "field": "spec.source.targetRevision",
            "from": "2.8.0",
            "to": "2.9.0",
        },
        "oneHopPerPullRequest": True,
        "awsTestIncluded": False,
        "awsProdIncluded": False,
        "otherControllerUpgradeIncluded": False,
    }, "first-hop scope drift")

    stages = value.get("approvalStages")
    require(isinstance(stages, list) and len(stages) == 4, "approval stage inventory drift")
    require([item.get("stage") for item in stages] == [
        "live-preflight-and-server-dry-run",
        "reviewed-gitops-pin-and-automatic-argo-sync",
        "post-sync-read-only-qualification",
        "conditional-reviewed-git-revert",
    ], "approval stage order drift")
    require(all(item.get("requiresFreshProtectedMainRequest") is True and item.get("requiresBoundedUtcWindow") is True for item in stages), "fresh approval boundary weakened")
    require([item.get("mayPersistKubernetesObjects") for item in stages] == [False, True, False, True], "persistent mutation boundary drift")
    require([item.get("mayChangeGit") for item in stages] == [False, True, False, True], "Git mutation boundary drift")

    require(value.get("preflightRequirements") == EXPECTED_PREFLIGHT, "preflight requirement drift")
    require(value.get("serverSideDryRunBoundary") == {
        "commandShape": "kubectl apply --server-side --dry-run=server --field-manager=v0.12.4.1.5-external-secrets-preflight -o name -f <private-verified-2.9.0-render.yaml>",
        "privateRenderRequired": True,
        "exactRenderSha256Required": "880e6805213cf77cd89cf0e60e03624bc01c74d23a2c61693a1be2a5ce2ca8bb",
        "stdoutMayContainOnlyResourceIdentities": True,
        "stderrMustBeEmpty": True,
        "kubectlDiffForbidden": True,
        "nonDryRunApplyForbidden": True,
        "persistentMutationForbidden": True,
    }, "server-side dry-run boundary drift")

    require(value.get("futureGitopsExecution") == {
        "pinMutationIsLiveBecauseAutomatedSyncIsEnabled": True,
        "mergeRequiresLiveApproval": True,
        "directHelmUpgradeForbidden": True,
        "directKubectlApplyForbidden": True,
        "manualArgoSyncNotRequired": True,
        "automaticRetryForbidden": True,
        "automaticProgressionToTwoTenForbidden": True,
        "qualificationTimeoutSeconds": 1200,
    }, "future GitOps execution drift")

    qualification = value.get("postSyncQualification")
    require(isinstance(qualification, dict) and len(qualification) == 17, "post-sync qualification drift")
    require(qualification.get("expectedDeploymentImages") == ["ghcr.io/external-secrets/external-secrets:v2.9.0"], "image target drift")
    for name in (
        "operatorApplicationMustBeSyncedHealthy", "resourceApplicationMustBeSyncedHealthy",
        "threeDeploymentsMustBeAvailable", "mainControllerIrsaMustBeUnchanged",
        "namespaceScopedRbacMustBeUnchanged", "renderedObjectInventoryMustRemainExact",
        "forbiddenClusterOrPushResourcesMustRemainAbsent", "v1MustRemainServedAndStorage",
        "secretStoreMustBeReady", "externalSecretMustBeReady",
        "externalSecretRefreshTimeMustAdvanceAfterSync", "awscurrentReferenceMustRemainExact",
    ):
        require(qualification.get(name) is True, f"post-sync gate weakened: {name}")
    for name in ("targetSecretDataMayBeRead", "awsSecretValueMayBeRead", "forceSyncAnnotationMayBeWritten", "secretValueDigestMayBeEmitted"):
        require(qualification.get(name) is False, f"secret boundary widened: {name}")

    require(value.get("failureAndRecovery") == {
        "anyAmbiguousFailureStopsProgression": True,
        "privateEvidenceMustBePreserved": True,
        "automaticRetry": False,
        "automaticRollback": False,
        "directCrdDowngradeOrDeletion": False,
        "directSecretMutation": False,
        "preferredRecovery": "reviewed-git-revert-to-2.8.0-after-separate-approval",
        "rollbackMustNotDeleteCrds": True,
        "twoNineMustConvergeBeforeTwoTenPlanning": True,
    }, "failure/recovery drift")
    require(value.get("evidenceRequirements") == {
        "privateResourceIdentitiesOnly": True,
        "secretValuesExcluded": True,
        "kubernetesSecretDataExcluded": True,
        "publicEvidenceMayContainOnlyRedactedBooleansCountsVersionsAndDigests": True,
        "preflightResultRequiredBeforePinMutation": True,
        "postSyncResultRequiredBeforeNextHop": True,
    }, "evidence boundary drift")
    require(value.get("overallGate") == {
        "status": "blocked-awaiting-v0.12.4.1.5-live-preflight-contract",
        "releaseNotesReviewed": True,
        "artifactAndRenderProofBound": True,
        "repositoryVersionChanged": False,
        "livePreflightCompleted": False,
        "serverSideDryRunCompleted": False,
        "liveUpgradeAuthorized": False,
    }, "overall gate drift")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and len(boundary) == 12, "execution boundary drift")
    require(all(item is False for item in boundary.values()), "live authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1.5-external-secrets-2.9.0-live-preflight-contract", "next checkpoint drift")


def set_path(value: dict[str, Any], path: tuple[Any, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.4.1.4-external-secrets-2.9.0-hop-plan.json"
    document_path = root / "docs/V0.12.4.1.4_EXTERNAL_SECRETS_2.9.0_HOP_PLAN.md"
    checker_path = root / "scripts/check-v0.12.4.1.4-external-secrets-2.9.0-hop-plan.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutations = (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("releaseIdentity", "targetChartVersion"), "2.10.0"),
        (("releaseIdentity", "targetApplicationReleaseCommit"), "0" * 40),
        (("releaseIdentity", "targetChartSha256"), "0" * 64),
        (("releaseNoteReview", "announcedManualMigrationRequired"), True),
        (("releaseNoteReview", "repositoryRelevantChanges", 0, "repositoryDisposition"), "ignored"),
        (("releaseNoteReview", "staticCompatibilityIsNotLiveQualification"), False),
        (("firstHopScope", "environment"), "aws-test"),
        (("firstHopScope", "allowedFutureGitMutation", "to"), "2.11.0"),
        (("firstHopScope", "awsProdIncluded"), True),
        (("approvalStages", 0, "mayPersistKubernetesObjects"), True),
        (("approvalStages", 1, "requiresFreshProtectedMainRequest"), False),
        (("preflightRequirements",), EXPECTED_PREFLIGHT[:-1]),
        (("serverSideDryRunBoundary", "kubectlDiffForbidden"), False),
        (("serverSideDryRunBoundary", "nonDryRunApplyForbidden"), False),
        (("futureGitopsExecution", "mergeRequiresLiveApproval"), False),
        (("futureGitopsExecution", "directHelmUpgradeForbidden"), False),
        (("futureGitopsExecution", "automaticProgressionToTwoTenForbidden"), False),
        (("postSyncQualification", "awsSecretValueMayBeRead"), True),
        (("postSyncQualification", "forceSyncAnnotationMayBeWritten"), True),
        (("failureAndRecovery", "automaticRetry"), True),
        (("failureAndRecovery", "automaticRollback"), True),
        (("failureAndRecovery", "directCrdDowngradeOrDeletion"), True),
        (("evidenceRequirements", "secretValuesExcluded"), False),
        (("overallGate", "repositoryVersionChanged"), True),
        (("overallGate", "liveUpgradeAuthorized"), True),
        (("executionBoundary", "kubernetesServerDryRunAuthorized"), True),
        (("executionBoundary", "gitVersionMutationAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.1.6-live-upgrade"),
    )
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(set_path(contract, path, replacement))
        except (AttributeError, KeyError, TypeError, FirstHopPlanError):
            continue
        raise FirstHopPlanError(f"fail-open mutation {index}")

    predecessor = load(root / "delivery/contracts/v0.12.4.1.3-external-secrets-artifact-render-proof.json")
    require(predecessor.get("nextCheckpoint") == "v0.12.4.1.4-external-secrets-2.9.0-hop-plan", "predecessor handoff drift")
    target_artifact = predecessor.get("artifactVerification", [])[1]
    target_render = predecessor.get("renderedCharts", [])[1]
    require(target_artifact.get("chartVersion") == "2.9.0", "predecessor chart identity drift")
    require(target_artifact.get("assetSha256") == contract["releaseIdentity"]["targetChartSha256"], "predecessor artifact digest drift")
    require(target_render.get("renderedManifestSha256") == contract["releaseIdentity"]["targetRenderedManifestSha256"], "predecessor render digest drift")

    operator = (root / "clusters/aws/base/platform/external-secrets.yaml").read_text()
    require("targetRevision: 2.8.0" in operator, "External Secrets pin changed")
    require("targetRevision: 2.9.0" not in operator, "first-hop pin applied early")
    require("automated:" in operator and "selfHeal: true" in operator, "automated Argo sync boundary drift")
    external_secret = (root / "clusters/aws/base/security/external-secrets/startup-apps/demo-api-postgresql.yaml").read_text()
    for marker in ("version: AWSCURRENT", "conversionStrategy: Default", "decodingStrategy: None", "metadataPolicy: None"):
        require(marker in external_secret, f"explicit strategy boundary drift: {marker}")
    require("templateFrom:" not in external_secret, "templateFrom introduced")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "changing `spec.source.targetRevision` is itself a live operation",
        "Static render compatibility cannot close that risk",
        "`kubectl diff` is deliberately excluded",
        "Neither AWS secret values nor Kubernetes Secret data may be read",
        "There is no automatic retry or rollback",
        "v0.12.4.1.5-external-secrets-2.9.0-live-preflight-contract",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    require("v0.12.4.1.4-external-secrets-2.9.0-hop-plan" in (root / "README.md").read_text(), "README checkpoint missing")
    require("v0.12.4.1.4 - External Secrets 2.9.0 first-hop plan" in (root / "docs/ROADMAP.md").read_text(), "roadmap increment missing")
    require("## v0.12.4.1.4" in (root / "CHANGELOG.md").read_text(), "changelog entry missing")

    tracked_paths = [contract_path, document_path, checker_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "first-hop source tracking drift")
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
        except FirstHopPlanError:
            continue
        raise FirstHopPlanError(f"non-executable worktree mode accepted: {oct(rejected_mode)}")

    print(
        f"v0.12.4.1.4 External Secrets 2.9.0 first-hop plan and {len(mutations)} "
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

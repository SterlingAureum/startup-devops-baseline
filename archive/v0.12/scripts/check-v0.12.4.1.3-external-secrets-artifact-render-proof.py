#!/usr/bin/env python3
"""Validate the offline External Secrets artifact and render proof."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
from typing import Any


class ArtifactRenderProofError(ValueError):
    """Raised when the reviewed artifact or render boundary changes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactRenderProofError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing file: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
    return value


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_checker_worktree_mode(mode: int) -> None:
    require(stat.S_ISREG(mode), "checker worktree file type drift")
    require(bool(mode & stat.S_IXUSR), "checker owner-executable bit missing")


EXPECTED_ARTIFACTS = [
    ("2.8.0", "v2.8.0", "6f1eed573faac17c3272c576cfd419a5b40db25d", "2026-07-18T16:52:08Z", 205224, "251e4615013c6d2f9ade5cedf1cd8615613f286bfc381e44fb005f197e611ecd"),
    ("2.9.0", "v2.9.0", "cc5bfbc2234ace9cb0caff4ea89c435cf517b27b", "2026-08-08T12:43:21Z", 206598, "da2d5c126a103b4c1b16a9dc1c168c4332a3687144e88ac070e594f81a0b6578"),
    ("2.10.0", "v2.10.0", "8488600898e856d74a7e0f53ed5e3cc79d89f4e8", "2026-08-28T13:09:40Z", 209670, "b96e948fff3674638b5d3f9e43886f3796e04739c4b4127929aed2ddac7d1418"),
    ("2.11.0", "v2.11.0", "d735072ef89d4c2e896c9dc78313f127ac0c10aa", "2026-09-21T12:12:54Z", 210446, "8199b42fe80b871c6a86233a80bb14f599fd6e1e6462c1216d836577f845e161"),
]

EXPECTED_RENDERS = [
    ("2.8.0", "b7e26db417f1915c9af759a5f41f0b24b021c6becf61b569a3061c2d858b0288", 958511, "9c6627e0ee175dc4c41f848a178f572a5f12a1ef4131270865f9834f415057b7"),
    ("2.9.0", "880e6805213cf77cd89cf0e60e03624bc01c74d23a2c61693a1be2a5ce2ca8bb", 959272, "87fa2eb5bc7a8c1b3d0907bfc768c1e161f2bbf381f1148bf8df8b2601c2d7a2"),
    ("2.10.0", "8ec6234a7b81e649b8257b9673c0d29b9be13f77dd7d2597471af5656f611a88", 970147, "f1a46ed5093c1920f160c8f293ee7d04c28fef5990629d42ba8156d9c12399f4"),
    ("2.11.0", "6c1b9d88ee7ca5c49b0adbfa934f134f6975b2a1a9c75da32b8a6704adec0095", 976244, "71ff4aa203709f67f994d66d723a0e27fb991eca6c66d9b3c4aaeda66ef4b868"),
]

STABLE_OBJECT_DIGEST = "0d333eae64c79759c4a75726f043b2ff9b828f7367fecdf1c881ef3e5cce4bd0"
STABLE_RBAC_DIGEST = "7a57ea6b25c3f8bb9b4a49042082df12eec84eb3f74a663445e27656b8937852"
STABLE_SERVICE_ACCOUNT_DIGEST = "ae7a7ede3cff53b4b6553b2ebbf5cab1395451351020bb51f48aad52dd7cd4e4"
STABLE_WEBHOOK_DIGEST = "6dfc6b6f346f7d1369e68ac1ba96a347ac702541340ad5f34fdd0fb3d8b935e3"


def validate_contract(value: dict[str, Any]) -> None:
    require(value.get("schemaVersion") == "v0.12.4.1.3-external-secrets-artifact-render-proof-v1", "schema drift")
    require(value.get("version") == "v0.12.4.1.3", "version drift")
    require(value.get("status") == "external-secrets-artifact-and-render-proof-recorded-offline", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("protectedMainBaselineCommit") == "1fbf77b4922d847056ce44b86c6bbf24d445bebc", "baseline drift")
    require(value.get("evidenceProducedAtDate") == "2026-09-29", "evidence date drift")

    sources = value.get("officialSources")
    require(isinstance(sources, dict) and len(sources) == 3, "official source inventory drift")
    require(all(isinstance(url, str) and url.startswith("https://") for url in sources.values()), "non-HTTPS official source")

    require(value.get("toolchain") == {
        "helmVersion": "v3.18.6",
        "helmLinuxAmd64ArchiveSha256": "3f43c0aa57243852dd542493a0f54f1396c0bc8ec7296bbb2c01e802010819ce",
        "kubernetesRenderVersion": "1.36.0",
        "releaseName": "external-secrets",
        "releaseNamespace": "external-secrets",
        "renderCommandShape": "helm template external-secrets <verified-chart.tgz> --namespace external-secrets --kube-version 1.36.0 --values <exact-repository-values.yaml>",
        "lintCommandShape": "helm lint <verified-chart.tgz> --namespace external-secrets --kube-version 1.36.0 --values <exact-repository-values.yaml>",
    }, "toolchain drift")

    artifacts = value.get("artifactVerification")
    require(isinstance(artifacts, list) and len(artifacts) == 4, "artifact inventory drift")
    for artifact, expected in zip(artifacts, EXPECTED_ARTIFACTS):
        version, app_version, commit, published_at, size, digest = expected
        require(artifact == {
            "chartVersion": version,
            "applicationVersion": app_version,
            "releaseTag": f"helm-chart-{version}",
            "releaseCommit": commit,
            "publishedAtUtc": published_at,
            "assetName": f"external-secrets-{version}.tgz",
            "assetSizeBytes": size,
            "assetSha256": digest,
            "assetUrl": f"https://github.com/external-secrets/external-secrets/releases/download/helm-chart-{version}/external-secrets-{version}.tgz",
            "githubReleaseAssetImmutable": False,
            "chartName": "external-secrets",
            "chartKubeVersion": ">= 1.19.0-0",
        }, f"artifact drift: {version}")

    require(value.get("artifactTrustBoundary") == {
        "releaseApiDigestMatchedDownloadedBytesForEveryVersion": True,
        "chartMetadataMatchedReleaseTagForEveryVersion": True,
        "applicationVersionMatchedChartMetadataForEveryVersion": True,
        "futureDownloadMustMatchRecordedSha256": True,
        "releaseUrlAloneIsNotAcceptedAsIntegrityProof": True,
        "chartArchivesCommittedToRepository": False,
    }, "artifact trust boundary drift")

    require(value.get("exactRepositoryValues") == {
        "applicationPath": "clusters/aws/base/platform/external-secrets.yaml",
        "currentTargetRevision": "2.8.0",
        "sourceValuesBlockSha256": "4a742de86896c97b0ca755cad40b320253ce3aec7ad695e2785bfc9ef43a3e9d",
        "canonicalJsonSha256": "2a76fc99d44b40bcd610296b6dbfe06fdb6582d5870d14092aa53a1c6da62bc5",
        "configuredLeafCount": 49,
        "valuesSchemaPresentForEveryChart": True,
        "helmLintPassedForEveryChart": True,
        "renderStderrEmptyForEveryChart": True,
        "unknownRootValueKeys": [],
        "defaultEmptyMapExtensionRoots": [
            "resources", "affinity", "webhook.resources", "webhook.affinity",
            "certController.resources", "certController.affinity",
        ],
    }, "repository values proof drift")

    renders = value.get("renderedCharts")
    require(isinstance(renders, list) and len(renders) == 4, "render inventory drift")
    for render, expected in zip(renders, EXPECTED_RENDERS):
        version, manifest_digest, size, crd_digest = expected
        require(render == {
            "chartVersion": version,
            "renderedManifestSha256": manifest_digest,
            "renderedManifestSizeBytes": size,
            "repeatRenderByteIdentical": True,
            "objectInventorySha256": STABLE_OBJECT_DIGEST,
            "crdSpecInventorySha256": crd_digest,
            "rbacSemanticSha256": STABLE_RBAC_DIGEST,
            "serviceAccountSemanticSha256": STABLE_SERVICE_ACCOUNT_DIGEST,
            "webhookSemanticSha256": STABLE_WEBHOOK_DIGEST,
        }, f"render proof drift: {version}")

    require(value.get("stableRenderedTopology") == {
        "documentCount": 37,
        "kindCounts": {
            "ClusterRole": 1, "ClusterRoleBinding": 1, "CustomResourceDefinition": 20,
            "Deployment": 3, "Role": 4, "RoleBinding": 2, "Secret": 1,
            "Service": 1, "ServiceAccount": 2, "ValidatingWebhookConfiguration": 2,
        },
        "allCrdsNamespaced": True,
        "forbiddenClusterOrPushCrdNames": [],
        "deploymentNames": ["external-secrets", "external-secrets-cert-controller", "external-secrets-webhook"],
        "controllerServiceAccountCreatedByChart": False,
        "auxiliaryServiceAccountNames": ["external-secrets-cert-controller", "external-secrets-webhook"],
        "certControllerClusterRoleAndBindingCount": 2,
        "rbacSemanticInventoryStableAcrossAllVersions": True,
        "webhookSemanticInventoryStableAcrossAllVersions": True,
        "serviceAccountSemanticInventoryStableAcrossAllVersions": True,
    }, "rendered topology drift")

    hops = value.get("hopDiffs")
    require(isinstance(hops, list) and len(hops) == 3, "hop diff inventory drift")
    expected_hops = [
        ("2.8.0", "2.9.0", ["externalsecrets.external-secrets.io", "secretstores.external-secrets.io"]),
        ("2.9.0", "2.10.0", [
            "acraccesstokens.generators.external-secrets.io", "cloudsmithaccesstokens.generators.external-secrets.io",
            "ecrauthorizationtokens.generators.external-secrets.io", "gcraccesstokens.generators.external-secrets.io",
            "quayaccesstokens.generators.external-secrets.io", "secretstores.external-secrets.io",
            "stssessiontokens.generators.external-secrets.io", "vaultdynamicsecrets.generators.external-secrets.io",
        ]),
        ("2.10.0", "2.11.0", ["secretstores.external-secrets.io"]),
    ]
    for hop, expected in zip(hops, expected_hops):
        source, target, changed_crds = expected
        require(hop.get("fromVersion") == source and hop.get("toVersion") == target, "hop order drift")
        require(hop.get("addedObjectIdentities") == [] and hop.get("removedObjectIdentities") == [], "object topology expanded")
        require(hop.get("changedCrdNames") == changed_crds, f"CRD diff drift: {source}")
        require(isinstance(hop.get("repositoryRelevantReview"), str) and hop["repositoryRelevantReview"], "CRD review missing")
        for gate in ("deploymentChangesLimitedToVersionLabelsAndThreeImageTags",):
            require(hop.get(gate) is True, f"workload diff drift: {source}")
        for gate in ("rbacRulesChanged", "webhookSemanticsChanged", "serviceAccountSemanticsChanged"):
            require(hop.get(gate) is False, f"semantic expansion: {source}:{gate}")

    require(value.get("repositoryResourceCompatibility") == {
        "customResourceCount": 2,
        "customResourceSourceSetSha256": "d37b761d4f518c5f8364c860ac6fe37cc999a31d8646f33d7a53b68ec90ecfe2",
        "apiVersion": "external-secrets.io/v1",
        "kinds": ["ExternalSecret", "SecretStore"],
        "v1ServedAndStorageInEveryChart": True,
        "exactManifestFieldsPresentInEveryRenderedCrdSchema": True,
        "explicitExternalSecretDefaultsAvoidTheTwoEightToTwoNineDefaultRemoval": True,
        "awsSecretsManagerProviderSchemaRetainedAcrossEveryHop": True,
        "clusterScopedResourceExpansion": False,
        "pushSecretExpansion": False,
        "staticAwsCredentialsIntroduced": False,
        "secretValuesReadOrRecorded": False,
    }, "repository resource compatibility drift")

    require(value.get("overallGate") == {
        "status": "artifact-proof-complete-awaiting-first-hop-plan",
        "artifactDigestsCaptured": True,
        "deterministicRenderProofCompleted": True,
        "crdRbacWorkloadDiffCompleted": True,
        "repositoryVersionChanged": False,
        "liveQualificationCompleted": False,
        "liveUpgradeAuthorized": False,
    }, "overall gate drift")
    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict) and len(boundary) == 13, "execution boundary drift")
    require(all(item is False for item in boundary.values()), "execution authority enabled")
    require(value.get("nextCheckpoint") == "v0.12.4.1.4-external-secrets-2.9.0-hop-plan", "next checkpoint drift")


def set_path(value: dict[str, Any], path: tuple[Any, ...], replacement: Any) -> dict[str, Any]:
    candidate = deepcopy(value)
    cursor: Any = candidate
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return candidate


def values_block(text: str) -> bytes:
    lines = text.splitlines()
    start = lines.index("      valuesObject:") + 1
    end = next(index for index in range(start, len(lines)) if lines[index].startswith("  destination:"))
    return ("\n".join(line[8:] for line in lines[start:end]) + "\n").encode()


def validate_repository(root: Path) -> None:
    contract_path = root / "delivery/contracts/v0.12.4.1.3-external-secrets-artifact-render-proof.json"
    document_path = root / "docs/V0.12.4.1.3_EXTERNAL_SECRETS_ARTIFACT_RENDER_PROOF.md"
    checker_path = root / "scripts/check-v0.12.4.1.3-external-secrets-artifact-render-proof.py"
    contract = load(contract_path)
    validate_contract(contract)

    mutations = (
        (("protectedMainBaselineCommit",), "0" * 40),
        (("toolchain", "helmVersion"), "v3.19.0"),
        (("toolchain", "kubernetesRenderVersion"), "1.37.0"),
        (("artifactVerification", 1, "assetSha256"), "0" * 64),
        (("artifactVerification", 2, "releaseCommit"), "0" * 40),
        (("artifactVerification", 3, "githubReleaseAssetImmutable"), True),
        (("artifactTrustBoundary", "futureDownloadMustMatchRecordedSha256"), False),
        (("artifactTrustBoundary", "chartArchivesCommittedToRepository"), True),
        (("exactRepositoryValues", "currentTargetRevision"), "2.11.0"),
        (("exactRepositoryValues", "sourceValuesBlockSha256"), "0" * 64),
        (("exactRepositoryValues", "helmLintPassedForEveryChart"), False),
        (("renderedCharts", 0, "renderedManifestSha256"), "0" * 64),
        (("renderedCharts", 3, "repeatRenderByteIdentical"), False),
        (("stableRenderedTopology", "documentCount"), 38),
        (("stableRenderedTopology", "allCrdsNamespaced"), False),
        (("stableRenderedTopology", "forbiddenClusterOrPushCrdNames"), ["clustersecretstores.external-secrets.io"]),
        (("stableRenderedTopology", "rbacSemanticInventoryStableAcrossAllVersions"), False),
        (("hopDiffs", 0, "addedObjectIdentities"), ["ClusterRole//unexpected"]),
        (("hopDiffs", 1, "rbacRulesChanged"), True),
        (("repositoryResourceCompatibility", "v1ServedAndStorageInEveryChart"), False),
        (("repositoryResourceCompatibility", "clusterScopedResourceExpansion"), True),
        (("repositoryResourceCompatibility", "secretValuesReadOrRecorded"), True),
        (("overallGate", "repositoryVersionChanged"), True),
        (("overallGate", "liveUpgradeAuthorized"), True),
        (("executionBoundary", "kubernetesReadAuthorized"), True),
        (("executionBoundary", "versionDeclarationMutationAuthorized"), True),
        (("nextCheckpoint",), "v0.12.4.1.4-live-upgrade"),
    )
    for index, (path, replacement) in enumerate(mutations, 1):
        try:
            validate_contract(set_path(contract, path, replacement))
        except (AttributeError, KeyError, TypeError, ArtifactRenderProofError):
            continue
        raise ArtifactRenderProofError(f"fail-open mutation {index}")

    predecessor = load(root / "delivery/contracts/v0.12.4.1.2-external-secrets-supportedness-repair-plan.json")
    require(predecessor.get("nextCheckpoint") == "v0.12.4.1.3-external-secrets-artifact-and-render-proof", "predecessor handoff drift")
    require(predecessor.get("overallGate", {}).get("repositoryVersionChanged") is False, "predecessor version boundary drift")

    operator_path = root / "clusters/aws/base/platform/external-secrets.yaml"
    operator = operator_path.read_text()
    require("targetRevision: 2.8.0" in operator, "External Secrets pin changed")
    require("targetRevision: 2.9.0" not in operator and "targetRevision: 2.10.0" not in operator and "targetRevision: 2.11.0" not in operator, "future pin applied early")
    require(sha256(values_block(operator)) == contract["exactRepositoryValues"]["sourceValuesBlockSha256"], "repository values source drift")

    resource_dir = root / "clusters/aws/base/security/external-secrets/startup-apps"
    resources = []
    for path in sorted(resource_dir.glob("*.yaml")):
        if "apiVersion: external-secrets.io/v1" in path.read_text():
            resources.append(path.name.encode() + b"\0" + path.read_bytes())
    require(len(resources) == 2, "repository custom-resource inventory drift")
    require(sha256(b"".join(resources)) == contract["repositoryResourceCompatibility"]["customResourceSourceSetSha256"], "repository custom-resource source drift")

    archived = subprocess.run(
        ["git", "-C", str(root), "ls-files", "*.tgz", "*.tar.gz"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(not archived, "chart or tool archive committed")

    document = " ".join(document_path.read_text().split())
    for phrase in (
        "URL is not sufficient future evidence",
        "produced byte-identical output on a second render",
        "same 37 object identities",
        "cluster-scoped RBAC does not expand",
        "`v1` remains both served and storage",
        "v0.12.4.1.4-external-secrets-2.9.0-hop-plan",
    ):
        require(phrase in document, f"document boundary missing: {phrase}")
    require("v0.12.4.1.3-external-secrets-artifact-and-render-proof" in (root / "README.md").read_text(), "README checkpoint missing")
    require("v0.12.4.1.3 - External Secrets artifact and render proof" in (root / "docs/ROADMAP.md").read_text(), "roadmap increment missing")
    require("## v0.12.4.1.3" in (root / "CHANGELOG.md").read_text(), "changelog entry missing")

    tracked_paths = [contract_path, document_path, checker_path]
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    require(len(tracked) == 3, "proof source tracking drift")
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
        except ArtifactRenderProofError:
            continue
        raise ArtifactRenderProofError(f"non-executable worktree mode accepted: {oct(rejected_mode)}")

    print(
        f"v0.12.4.1.3 External Secrets artifact/render proof and {len(mutations)} "
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

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

import yaml


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.2"
assert contract["version"] == "v0.11.9.3.2"
assert contract["predecessor"] == "v0.11.9.3.1"
assert contract["status"] == "offline-readiness-implemented-main-integration-not-executed"
assert contract["implementationBaselineCommit"] == "cf2c7cd37c114e875b731fb151a05aad9b9cddd6"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.3-reviewed-main-integration"

policy = contract["activeRevisionPolicy"]
assert policy == {
    "localRoot": "HEAD",
    "localSameRepositoryChildren": "HEAD",
    "awsDevRoot": "main",
    "awsDevSameRepositoryChildren": "main",
    "awsTestRoot": "main",
    "awsTestSameRepositoryChildren": "main",
    "awsProdRoot": "main",
    "awsProdSameRepositoryChildren": "main",
    "featureRevisionAllowedInActiveAwsOverlay": False,
    "externalChartVersionsPreserved": True,
}

dev_overlay_path = root / "clusters/aws/overlays/dev/kustomization.yaml"
dev_overlay_text = dev_overlay_path.read_text()
dev_overlay = yaml.safe_load(dev_overlay_text)
assert "feature/v0.11-observability-sre-baseline" not in dev_overlay_text
assert "/spec/source/targetRevision" not in dev_overlay_text
assert len(dev_overlay["patches"]) == 1
assert dev_overlay["patches"][0]["target"]["name"] == "monitoring-aws-dev"
assert contract["restoration"]["restoredApplicationCount"] == 9
assert contract["restoration"]["liveReconciliationPerformed"] is False

for environment in ("dev", "test", "prod"):
    overlay_dir = root / f"clusters/aws/overlays/{environment}"
    for path in sorted(overlay_dir.rglob("*.yaml")):
        text = path.read_text()
        if re.search(r"(?:targetRevision|value):\s*(?:refs/heads/)?feature/", text):
            raise SystemExit(f"Active AWS overlay retains a feature revision: {path.relative_to(root)}")
    root_application = yaml.safe_load((overlay_dir / "root-app.yaml").read_text())
    assert root_application["spec"]["source"]["targetRevision"] == "main"

repository = "https://github.com/SterlingAureum/startup-devops-baseline.git"
same_repository_apps = []
external_versions = {}
for path in sorted((root / "clusters/aws/base/platform").rglob("*.yaml")):
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, dict) or document.get("kind") != "Application":
        continue
    source = document["spec"]["source"]
    if source.get("repoURL") == repository:
        assert source["targetRevision"] == "main", path
        same_repository_apps.append(document["metadata"]["name"])
    elif "chart" in source:
        external_versions[source["chart"]] = str(source["targetRevision"])

assert sorted(same_repository_apps) == sorted([
    "application-admission-policies-aws-dev",
    "data-platform-network-policy-aws-dev",
    "demo-api-aws-dev",
    "external-secrets-startup-apps",
    "namespace-guardrails-aws-dev",
    "observability-views-aws-dev",
    "postgresql-baseline",
    "runtime-qualification-rbac-aws-dev",
    "startup-apps-network-policy-aws-dev",
])
assert external_versions == {
    "argo-rollouts": "2.41.1",
    "aws-load-balancer-controller": "1.14.0",
    "plugin-barman-cloud": "0.7.0",
    "cert-manager": "v1.21.0",
    "cloudnative-pg": "0.29.0",
    "external-secrets": "2.8.0",
    "karpenter": "1.14.0",
    "karpenter-crd": "1.14.0",
    "kube-prometheus-stack": "88.5.0",
}

local_root = yaml.safe_load((root / "clusters/local/root-app.yaml").read_text())
local_values = yaml.safe_load((root / "clusters/local/platform/values.yaml").read_text())
assert local_root["spec"]["source"]["targetRevision"] == "HEAD"
assert local_values["git"]["targetRevision"] == "HEAD"

preview = contract["historicalPreview"]
assert preview == {
    "path": "clusters/aws/overlays/test-feature-qualification",
    "revision": "feature/v0.11-observability-sre-baseline",
    "purpose": "v0.11.8.2 offline qualification preview evidence",
    "active": False,
    "bootstrapAllowed": False,
    "automaticSyncAllowed": False,
    "exactExceptionRetained": True,
}
preview_root = yaml.safe_load((root / preview["path"] / "root-app.yaml").read_text())
preview_overlay = (root / preview["path"] / "kustomization.yaml").read_text()
assert preview_root["spec"]["source"]["targetRevision"] == preview["revision"]
assert preview_root["spec"]["source"]["path"] == preview["path"]
assert "Preview only" in preview_overlay
assert preview["revision"] in preview_overlay

for relative, expected_sha256 in contract["releaseFiles"].items():
    data = (root / relative).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    assert actual == expected_sha256, f"{relative}: release identity changed"
    assert contract["candidate"]["digest"].encode() not in data

assert contract["candidate"] == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
    "writtenToAwsReleaseFile": False,
}

boundary = (root / "scripts/check-aws-gitops-revision-boundary.sh").read_text()
for environment in ("DEV", "TEST", "PROD"):
    marker = f'EXPECTED_{environment}_GIT_TARGET_REVISION="${{EXPECTED_{environment}_GIT_TARGET_REVISION:-main}}"'
    assert marker in boundary, marker
assert "EXPECTED_DEV_GIT_TARGET_REVISION:-feature/" not in boundary

promotion_workflow = (root / ".github/workflows/demo-api-promote-existing-image.yaml").read_text()
runtime_workflow = (root / ".github/workflows/demo-api-runtime-qualification.yaml").read_text()
assert '"${GITHUB_REF}" != "refs/heads/main"' in promotion_workflow
assert '"${GITHUB_REF}" != "refs/heads/main"' in runtime_workflow
assert "gh pr merge" not in promotion_workflow

gates = contract["integrationGates"]
assert gates["completeQualityGatesRequired"] is True
assert gates["featurePullRequestReviewRequired"] is True
assert gates["codeOwnerReviewRequired"] is True
assert gates["protectedMainMergeRequired"] is True
assert gates["exactMergedMainCommitCapturedAfterMerge"] is True
for key in (
    "existingImageWorkflowDispatchBeforeMergeAllowed",
    "remoteRuntimeBeforeMergeAllowed",
    "awsEnvironmentCreationBeforeMergeAllowed",
):
    assert gates[key] is False

trusted = contract["trustedBoundaries"]
assert trusted["existingImagePromotionAllowedRef"] == "refs/heads/main"
assert trusted["runtimeQualificationAllowedRef"] == "refs/heads/main"
assert trusted["pullRequestCodeAllowedRemoteCredentials"] is False
assert trusted["productionRuntimeWorkflowEnabled"] is False
assert trusted["automaticPromotionPrMerge"] is False
assert trusted["automaticEnvironmentCreation"] is False
assert all(value is False for value in contract["producerExecution"].values())

for relative, marker in (
    ("README.md", "v0.11.9.3.2-protected-main-integration-readiness"),
    ("CHANGELOG.md", "## v0.11.9.3.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.2"),
    ("docs/V0.11.9.3.2_PROTECTED_MAIN_INTEGRATION_READINESS.md", "Historical preview boundary"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.2-protected-main-integration-readiness.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.2 active main revisions, release immutability, historical preview and trusted boundaries passed.")
PY

"${ROOT_DIR}/scripts/validate-active-gitops-revisions.sh"
"${ROOT_DIR}/scripts/validate-v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification.sh"

if command -v kustomize >/dev/null 2>&1 || command -v kubectl >/dev/null 2>&1; then
  "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh"
else
  echo "SKIP: real Kustomize rendering; CI/local full toolchain must run the revision-boundary checker."
fi

bash -n \
  "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.2-protected-main-integration-readiness.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck \
    "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh" \
    "${ROOT_DIR}/scripts/validate-v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification.sh" \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh" \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.2-protected-main-integration-readiness.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.2 protected-main integration readiness validation passed; no live operation was executed."

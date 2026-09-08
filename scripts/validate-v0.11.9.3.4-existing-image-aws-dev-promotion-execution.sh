#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.4-existing-image-aws-dev-promotion-execution.json"
READINESS_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"
SUCCESSOR_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.3-reviewed-main-integration.json"
SUCCESSOR_CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.2-release-successor.py"
DERIVE_RELEASE_ID="${ROOT_DIR}/scripts/derive-demo-api-release-id.py"
AWS_DEV_RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"

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
import sys

import yaml


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.4"
assert contract["version"] == "v0.11.9.3.4"
assert contract["predecessor"] == "v0.11.9.3.3.2"
assert contract["status"] == "existing-image-aws-dev-promotion-merged-runtime-not-qualified"
assert contract["implementationBaselineCommit"] == "071e32914a304f6e3ca006f0f60f54b21b5d810d"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.5-aws-dev-live-rehearsal-preflight"

handoff = contract["existingImageHandoff"]
assert handoff == {
    "workflow": ".github/workflows/demo-api-promote-existing-image.yaml",
    "workflowRunId": "34180004676",
    "workflowHeadCommit": "03e39f3416a8f5e368d0cda497487376ec575d52",
    "workflowConclusion": "success",
    "imageRebuilt": False,
    "promotionPullRequestNumber": 71,
    "promotionPullRequestUrl": "https://github.com/SterlingAureum/startup-devops-baseline/pull/71",
    "promotionBranch": "release/demo-api-sha-cf0a6bc",
    "initialPromotionHeadCommit": "e97072019374d0137388a8cfb35332a3fd8d81c2",
    "finalPromotionHeadCommit": "2353977e3efa1f202a0bfe3cd1c2b9f6a4b505d2",
    "finalPromotionBaseCommit": "7a71662f8032219372f1e078298cd08338e8f995",
    "changedPaths": ["apps/demo-api/helm/values/releases/aws-dev.yaml"],
    "pullRequestChecksSuccessful": True,
    "merged": True,
    "mergedAt": "2026-09-08T07:13:30Z",
    "mergeCommit": "071e32914a304f6e3ca006f0f60f54b21b5d810d",
    "promotionHeadContainedInMain": True,
}

candidate = contract["selectedCandidate"]
assert candidate == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceRepository": "SterlingAureum/startup-devops-baseline",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "sourceWorkflowRunId": "34070524953",
    "applicationVersion": "sha-cf0a6bc",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
    "awsDevReleaseFileSha256": "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46",
}

release_paths = {
    name: root / f"apps/demo-api/helm/values/releases/{name}.yaml"
    for name in ("aws-dev", "aws-test", "aws-prod")
}
release_hashes = {
    name: hashlib.sha256(path.read_bytes()).hexdigest()
    for name, path in release_paths.items()
}
boundary = contract["environmentBoundary"]
assert release_hashes["aws-dev"] == candidate["awsDevReleaseFileSha256"]
assert release_hashes["aws-test"] == boundary["awsTestReleaseFileSha256"]
assert release_hashes["aws-prod"] == boundary["awsProdReleaseFileSha256"]

expected_release = {
    "image": {
        "repository": candidate["repository"],
        "tag": candidate["tag"],
        "digest": candidate["digest"],
    },
    "release": {"applicationVersion": candidate["applicationVersion"]},
    "delivery": {
        "sourceRepository": candidate["sourceRepository"],
        "sourceCommit": candidate["sourceCommit"],
        "workflowRunId": candidate["sourceWorkflowRunId"],
    },
}
assert yaml.safe_load(release_paths["aws-dev"].read_text()) == expected_release

for name in ("aws-test", "aws-prod"):
    release_text = release_paths[name].read_text()
    assert candidate["digest"] not in release_text
    assert candidate["sourceCommit"] not in release_text

assert boundary == {
    "awsDevDesiredStateUpdated": True,
    "awsTestReleaseFileSha256": "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22",
    "awsProdReleaseFileSha256": "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22",
    "candidatePresentInAwsTest": False,
    "candidatePresentInAwsProd": False,
    "maximumActiveEksEnvironments": 1,
    "awsEnvironmentCreated": False,
    "argoCdReconciliationObserved": False,
    "runtimeQualificationExecuted": False,
    "sourceRuntimeEvidenceRecorded": False,
    "awsTestPromotionAllowed": False,
}

assert contract["postMergeMain"] == {
    "commit": "071e32914a304f6e3ca006f0f60f54b21b5d810d",
    "validateRunId": "34198278046",
    "validateConclusion": "success",
    "releaseOrchestratorRunId": "34198278111",
    "releaseOrchestratorConclusion": "success",
    "imagePublishRunObserved": False,
    "releaseOnlyMergeExcludedFromImagePublishPaths": True,
}
assert contract["producerExecution"] == {
    "existingImageWorkflowDispatched": True,
    "promotionPullRequestCreated": True,
    "promotionPullRequestMerged": True,
    "selectedCandidateWrittenToAwsDev": True,
    "imageRebuilt": False,
    "awsAccessed": False,
    "clusterAccessed": False,
    "runtimeQualificationExecuted": False,
}

image_workflow = (root / ".github/workflows/demo-api-image-publish.yaml").read_text()
image_push_trigger = image_workflow.split("  push:\n", 1)[1].split(
    "  workflow_dispatch:\n", 1
)[0]
assert "paths:" in image_push_trigger
assert "apps/demo-api/helm/values/releases" not in image_push_trigger
orchestrator_workflow = (root / ".github/workflows/demo-api-release-orchestrator.yaml").read_text()
assert "apps/demo-api/helm/values/releases/aws-*.yaml" in orchestrator_workflow

for relative, marker in (
    ("README.md", "v0.11.9.3.4-existing-image-aws-dev-promotion-execution"),
    ("CHANGELOG.md", "## v0.11.9.3.4"),
    ("docs/ROADMAP.md", "v0.11.9.3.4"),
    ("docs/CI_IMAGE_WORKFLOW.md", "v0.11.9.3.4 execution record"),
    ("docs/V0.11.9.3.4_EXISTING_IMAGE_AWS_DEV_PROMOTION_EXECUTION.md", "Runtime boundary"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.4-existing-image-aws-dev-promotion-execution.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.4-existing-image-aws-dev-promotion-execution.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.4 Git handoff evidence, immutable aws-dev identity and no-runtime boundary passed.")
PY

successor_state="$(
  "${SUCCESSOR_CHECK}" \
    --release-file "${AWS_DEV_RELEASE_FILE}" \
    --readiness-contract "${READINESS_CONTRACT}" \
    --successor-contract "${SUCCESSOR_CONTRACT}"
)"
if [[ "${successor_state}" != "reviewed-selected-candidate" ]]; then
  echo "Expected reviewed-selected-candidate, got ${successor_state}" >&2
  exit 1
fi

derived_release_id="$(
  "${DERIVE_RELEASE_ID}" \
    --release-file "${AWS_DEV_RELEASE_FILE}" \
    --format id
)"
if [[ "${derived_release_id}" != "demo-api-cf0a6bcbc466-cdffd3d71763" ]]; then
  echo "Unexpected aws-dev release ID: ${derived_release_id}" >&2
  exit 1
fi

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.4-existing-image-aws-dev-promotion-execution.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.4-existing-image-aws-dev-promotion-execution.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.4 existing-image aws-dev promotion execution validation passed; no live operation was executed."

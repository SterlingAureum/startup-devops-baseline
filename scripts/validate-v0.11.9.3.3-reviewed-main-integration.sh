#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.3-reviewed-main-integration.json"
READINESS_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"
RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
SUCCESSOR_CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.2-release-successor.py"
AWS_TEST_SUCCESSOR_CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.6.6.1-aws-test-release-successor.py"

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

assert contract["schemaVersion"] == "v0.11.9.3.3"
assert contract["version"] == "v0.11.9.3.3"
assert contract["predecessor"] == "v0.11.9.3.2"
assert contract["status"] == "reviewed-main-integrated-selected-existing-image-promotion-not-dispatched"
assert contract["implementationBaselineCommit"] == "6013688a384c4e39a5b2b79d1b95bb29d00725de"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.4-existing-image-aws-dev-promotion-execution"

integration = contract["mainIntegration"]
assert integration["pullRequestNumber"] == 68
assert integration["featureHeadCommit"] == "7192f28f947e9f1942cfc67d093dc00afa7a0755"
assert integration["preMergeMainCommit"] == "4cb8592fb02224551fc78f1cf6a5cf82ea869089"
assert integration["mergedMainCommit"] == contract["implementationBaselineCommit"]
assert integration["mergedAt"] == "2026-09-07T12:58:53Z"
assert integration["featureContainedInMain"] is True
assert integration["pullRequestMergeableBeforeMerge"] == "MERGEABLE"
assert integration["pullRequestMergeStateBeforeMerge"] == "CLEAN"
assert integration["pullRequestChecks"] == {
    "terraform validate/validate": "SUCCESS",
    "validate/demo-api release currentness": "SUCCESS",
    "validate/quality-gates / quality-gates": "SUCCESS",
}
assert integration["mainPushRuns"] == {
    "demo-api release orchestrator": "34124828650",
    "terraform validate": "34124828437",
    "validate": "34124828759",
    "demo-api image publish": "34124828745",
}
assert integration["allObservedMainPushRunsSuccessful"] is True

selected = contract["selectedCandidate"]
assert selected == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceRepository": "SterlingAureum/startup-devops-baseline",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
    "localQualifiedRevision": 70,
    "localAnalysisRuns": [
        "demo-api-7557fdfb9b-70-2",
        "demo-api-7557fdfb9b-70-5",
    ],
    "selectedForAwsDev": True,
    "writtenToAwsDevReleaseFile": False,
}
assert selected["tag"] == f"sha-{selected['sourceCommit'][:7]}"
assert selected["releaseId"] == (
    f"demo-api-{selected['sourceCommit'][:12]}-"
    f"{selected['digest'].removeprefix('sha256:')[:12]}"
)

incidental = contract["incidentalMainBuild"]
assert incidental["tag"] == "sha-6013688"
assert incidental["digest"] == "sha256:445f8e432cd0848a615f99a123a8305262255bd4a6082675a58744742660b02d"
assert incidental["sourceCommit"] == integration["mergedMainCommit"]
assert incidental["workflowRunId"] == integration["mainPushRuns"]["demo-api image publish"]
assert incidental["releaseId"] == "demo-api-6013688a384c-445f8e432cd0"
assert incidental["promotionPullRequestNumber"] == 69
assert incidental["promotionBranch"] == "release/demo-api-sha-6013688"
assert incidental["promotionHeadCommit"] == "0fb0ccf94715b498f0ec2615386dbcf60a6e4094"
assert incidental["observedPromotionState"] == "open-quality-gates-rejected"
assert incidental["selectedForAwsDev"] is False
assert incidental["runtimeQualified"] is False
assert incidental["requiredDisposition"] == "close-without-merge"
assert incidental["digest"] != selected["digest"]

policy = contract["releaseFilePolicy"]
assert policy == {
    "awsDevPrePromotionSha256": "e13937cd11df5c4625fe0de50808b9d74e14503e3b6021900a8f8ae8f0e87d80",
    "awsTestSha256": "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22",
    "awsProdSha256": "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22",
    "allowedAwsDevSuccessor": "selectedCandidate",
    "incidentalMainBuildAllowed": False,
    "otherAwsDevIdentityAllowed": False,
    "awsTestOrProdChangeAllowed": False,
}
aws_prod = root / "apps/demo-api/helm/values/releases/aws-prod.yaml"
assert hashlib.sha256(aws_prod.read_bytes()).hexdigest() == policy["awsProdSha256"]
assert selected["digest"] not in aws_prod.read_text()

for environment in ("dev", "test", "prod"):
    root_application = yaml.safe_load((root / f"clusters/aws/overlays/{environment}/root-app.yaml").read_text())
    assert root_application["spec"]["source"]["targetRevision"] == "main"

promotion = contract["promotionBoundary"]
assert promotion["closeIncidentalPromotionPullRequestFirst"] is True
assert promotion["existingImageWorkflow"] == ".github/workflows/demo-api-promote-existing-image.yaml"
assert promotion["allowedDispatchRef"] == "refs/heads/main"
assert promotion["sourceRunId"] == selected["workflowRunId"]
assert promotion["expectedSourceCommit"] == selected["sourceCommit"]
assert promotion["automaticMergeAllowed"] is False
assert promotion["concurrentPromotionPullRequestsAllowed"] is False
assert promotion["workflowDispatched"] is False

execution = contract["producerExecution"]
assert execution["mainMerged"] is True
assert execution["mainPushImageBuilt"] is True
assert execution["incidentalPromotionPullRequestCreated"] is True
assert execution["incidentalPromotionPullRequestMerged"] is False
assert execution["selectedExistingImageWorkflowDispatched"] is False
assert execution["selectedCandidateWrittenToAwsDev"] is False
assert execution["awsAccessed"] is False
assert execution["clusterAccessed"] is False
assert execution["runtimeQualificationExecuted"] is False

historical_validator = (root / "scripts/validate-v0.11.9.3.2-protected-main-integration-readiness.sh").read_text()
assert "check-v0.11.9.3.2-release-successor.py" in historical_validator
assert "v0.11.9.3.3-reviewed-main-integration.json" in historical_validator

for relative, marker in (
    ("README.md", "v0.11.9.3.3-reviewed-main-integration"),
    ("CHANGELOG.md", "## v0.11.9.3.3"),
    ("docs/ROADMAP.md", "v0.11.9.3.3"),
    ("docs/V0.11.9.3.3_REVIEWED_MAIN_INTEGRATION.md", "Single selected successor"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.3-reviewed-main-integration.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.3-reviewed-main-integration.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.3 main integration, candidate selection and no-runtime boundaries passed.")
PY

"${AWS_TEST_SUCCESSOR_CHECK}" \
  --release-file "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml" \
  >/dev/null

current_state="$(
  "${SUCCESSOR_CHECK}" \
    --release-file "${RELEASE_FILE}" \
    --readiness-contract "${READINESS_CONTRACT}" \
    --successor-contract "${CONTRACT}"
)"
if [[ "${current_state}" != "historical-baseline" && \
      "${current_state}" != "reviewed-selected-candidate" ]]; then
  echo "Unexpected current aws-dev release state: ${current_state}" >&2
  exit 1
fi

FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "${FIXTURE_DIR}"' EXIT
ACCEPTED_VALUES="${FIXTURE_DIR}/accepted.yaml"
REJECTED_VALUES="${FIXTURE_DIR}/rejected.yaml"
cp "${RELEASE_FILE}" "${ACCEPTED_VALUES}"
cp "${RELEASE_FILE}" "${REJECTED_VALUES}"

VALUES_FILE="${ACCEPTED_VALUES}" \
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
IMAGE_TAG="sha-cf0a6bc" \
IMAGE_DIGEST="sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623" \
APP_VERSION="sha-cf0a6bc" \
  "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null
VALUES_FILE="${ACCEPTED_VALUES}" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="cf0a6bcbc466b61f2018a0a92c961d7c03f128e8" \
WORKFLOW_RUN_ID="34070524953" \
  "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null

if [[ "$(
  "${SUCCESSOR_CHECK}" \
    --release-file "${ACCEPTED_VALUES}" \
    --readiness-contract "${READINESS_CONTRACT}" \
    --successor-contract "${CONTRACT}"
)" != "reviewed-selected-candidate" ]]; then
  echo "Reviewed selected candidate fixture was not accepted." >&2
  exit 1
fi

VALUES_FILE="${REJECTED_VALUES}" \
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
IMAGE_TAG="sha-6013688" \
IMAGE_DIGEST="sha256:445f8e432cd0848a615f99a123a8305262255bd4a6082675a58744742660b02d" \
APP_VERSION="sha-6013688" \
  "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null
VALUES_FILE="${REJECTED_VALUES}" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="6013688a384c4e39a5b2b79d1b95bb29d00725de" \
WORKFLOW_RUN_ID="34124828745" \
  "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null

if "${SUCCESSOR_CHECK}" \
  --release-file "${REJECTED_VALUES}" \
  --readiness-contract "${READINESS_CONTRACT}" \
  --successor-contract "${CONTRACT}" >/dev/null 2>&1; then
  echo "Incidental unqualified main image was accepted as an aws-dev successor." >&2
  exit 1
fi

bash -n \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.2-protected-main-integration-readiness.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.3-reviewed-main-integration.sh"
python3 -m py_compile "${SUCCESSOR_CHECK}"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.2-protected-main-integration-readiness.sh" \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.3-reviewed-main-integration.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.3 reviewed main integration validation passed; no live operation was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.3.1-immutable-local-aws-successor-repair.json"
HISTORICAL_VALIDATOR="${ROOT_DIR}/scripts/validate-v0.11.9.2.2.3.3.2-immutable-local-baseline-image.sh"
READINESS_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"
SUCCESSOR_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.3-reviewed-main-integration.json"
SUCCESSOR_CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.2-release-successor.py"
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


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.3.1"
assert contract["version"] == "v0.11.9.3.3.1"
assert contract["predecessor"] == "v0.11.9.3.3"
assert contract["status"] == "historical-local-identity-validator-repaired-promotion-pr-held"
assert contract["implementationBaselineCommit"] == "03e39f3416a8f5e368d0cda497487376ec575d52"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.4-existing-image-aws-dev-promotion-execution"

failure = contract["observedFailure"]
assert failure == {
    "existingImageWorkflowRunId": "34180004676",
    "existingImageWorkflowConclusion": "success",
    "existingImageWorkflowHeadCommit": "03e39f3416a8f5e368d0cda497487376ec575d52",
    "promotionPullRequestNumber": 71,
    "promotionPullRequestUrl": "https://github.com/SterlingAureum/startup-devops-baseline/pull/71",
    "promotionBranch": "release/demo-api-sha-cf0a6bc",
    "promotionHeadCommit": "e97072019374d0137388a8cfb35332a3fd8d81c2",
    "promotionBaseCommit": "03e39f3416a8f5e368d0cda497487376ec575d52",
    "validationWorkflowRunId": "34180043793",
    "releaseCurrentnessConclusion": "success",
    "qualityGatesConclusion": "failure",
    "failingValidator": "scripts/validate-v0.11.9.2.2.3.3.2-immutable-local-baseline-image.sh",
    "failure": "The historical local-only checkpoint rejected its accepted image digest and source commit in every AWS release file, including the later reviewed aws-dev successor.",
    "promotionPullRequestMerged": False,
}

repair = contract["repair"]
assert repair["localDefaultValuesRemainExact"] is True
assert repair["awsDevValidator"] == "scripts/check-v0.11.9.3.2-release-successor.py"
assert repair["awsDevAllowedStates"] == [
    "historical-baseline",
    "reviewed-selected-candidate",
]
assert repair["selectedCandidateTag"] == "sha-cf0a6bc"
assert repair["selectedCandidateDigest"] == "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623"
assert repair["selectedCandidateSourceCommit"] == "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8"
assert repair["selectedCandidateWorkflowRunId"] == "34070524953"
assert repair["incidentalMainTagRejected"] == "sha-6013688"
assert repair["incidentalMainDigestRejected"] == "sha256:445f8e432cd0848a615f99a123a8305262255bd4a6082675a58744742660b02d"
assert repair["awsTestCandidateForbidden"] is True
assert repair["awsProdCandidateForbidden"] is True
assert repair["partialOrUnknownIdentityForbidden"] is True

local_values = (root / "apps/demo-api/helm/values.yaml").read_text()
assert repair["selectedCandidateDigest"] in local_values
assert repair["selectedCandidateSourceCommit"] in local_values

for environment in ("aws-test", "aws-prod"):
    release = (root / f"apps/demo-api/helm/values/releases/{environment}.yaml").read_text()
    assert repair["selectedCandidateDigest"] not in release
    assert repair["selectedCandidateSourceCommit"] not in release

readiness = json.loads((root / "delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json").read_text())
current_aws_dev = (root / "apps/demo-api/helm/values/releases/aws-dev.yaml").read_bytes()
assert hashlib.sha256(current_aws_dev).hexdigest() == readiness["releaseFiles"]["apps/demo-api/helm/values/releases/aws-dev.yaml"]

historical = (root / failure["failingValidator"]).read_text()
for marker in (
    'AWS_DEV_RELEASE_FILE="${AWS_DEV_RELEASE_FILE:-apps/demo-api/helm/values/releases/aws-dev.yaml}"',
    "check-v0.11.9.3.2-release-successor.py",
    "reviewed-selected-candidate",
):
    assert marker in historical, marker

assert all(value is False for value in contract["scope"].values())
assert contract["promotionHold"] == {
    "pullRequestNumber": 71,
    "keepOpen": True,
    "mergeBeforeRepairMainAllowed": False,
    "rerunBeforeRepairMainAllowed": False,
    "updateBranchBeforeRepairMainAllowed": False,
}

for relative, marker in (
    ("README.md", "v0.11.9.3.3.1-immutable-local-aws-successor-repair"),
    ("CHANGELOG.md", "## v0.11.9.3.3.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.3.1"),
    ("docs/V0.11.9.3.3.1_IMMUTABLE_LOCAL_AWS_SUCCESSOR_REPAIR.md", "Promotion hold"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.3.1-immutable-local-aws-successor-repair.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.3.1 historical validator boundary and no-runtime scope passed.")
PY

FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "${FIXTURE_DIR}"' EXIT
ACCEPTED_VALUES="${FIXTURE_DIR}/accepted.yaml"
REJECTED_VALUES="${FIXTURE_DIR}/rejected.yaml"
cp "${AWS_DEV_RELEASE_FILE}" "${ACCEPTED_VALUES}"
cp "${AWS_DEV_RELEASE_FILE}" "${REJECTED_VALUES}"

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

AWS_DEV_RELEASE_FILE="${AWS_DEV_RELEASE_FILE}" \
  "${HISTORICAL_VALIDATOR}" >/dev/null

AWS_DEV_RELEASE_FILE="${ACCEPTED_VALUES}" \
  "${HISTORICAL_VALIDATOR}" >/dev/null

if AWS_DEV_RELEASE_FILE="${REJECTED_VALUES}" \
  "${HISTORICAL_VALIDATOR}" >/dev/null 2>&1; then
  echo "Historical validator accepted the incidental unqualified main image." >&2
  exit 1
fi

if "${SUCCESSOR_CHECK}" \
  --release-file "${REJECTED_VALUES}" \
  --readiness-contract "${READINESS_CONTRACT}" \
  --successor-contract "${SUCCESSOR_CONTRACT}" >/dev/null 2>&1; then
  echo "Shared successor allowlist accepted the incidental main image." >&2
  exit 1
fi

bash -n \
  "${HISTORICAL_VALIDATOR}" \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck \
    "${HISTORICAL_VALIDATOR}" \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.3.1 immutable local AWS successor repair validation passed; no live operation was executed."

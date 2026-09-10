#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.3.2-remote-successor-chain-repair.json"
DESIGN_VALIDATOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh"
PRIOR_REPAIR_VALIDATOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh"
READINESS_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json"
SUCCESSOR_CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.3-reviewed-main-integration.json"
SUCCESSOR_CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.2-release-successor.py"
AWS_DEV_RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
AWS_TEST_RELEASE_FILE="${AWS_TEST_RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml}"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.3.2"
assert contract["version"] == "v0.11.9.3.3.2"
assert contract["predecessor"] == "v0.11.9.3.3.1"
assert contract["status"] == "remaining-remote-successor-chain-guards-repaired-promotion-pr-held"
assert contract["implementationBaselineCommit"] == "6f259e229a8f653e1a567fe809ed58926d31bbb4"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.4-existing-image-aws-dev-promotion-execution"

failure = contract["observedFailure"]
assert failure == {
    "promotionPullRequestNumber": 71,
    "promotionBranch": "release/demo-api-sha-cf0a6bc",
    "observedAfterMainCommit": "6f259e229a8f653e1a567fe809ed58926d31bbb4",
    "failingValidator": "scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh",
    "embeddedPythonLine": 87,
    "failedAssertion": "candidate digest absent from every AWS release file",
    "promotionPullRequestMerged": False,
}

audit = contract["chainAudit"]
assert audit["repairedValidators"] == [
    "scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh",
    "scripts/validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh",
]
assert audit["sharedAwsDevAllowlist"] == "scripts/check-v0.11.9.3.2-release-successor.py"
assert audit["awsDevAllowedStates"] == [
    "historical-baseline",
    "reviewed-selected-candidate",
]
assert audit["awsTestAndAwsProdRemainPrePromotion"] is True
assert audit["incidentalMainImageRemainsRejected"] is True
assert audit["staticRegressionScanAdded"] is True

assert contract["selectedCandidate"] == {
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
}
assert contract["rejectedCandidate"] == {
    "tag": "sha-6013688",
    "digest": "sha256:445f8e432cd0848a615f99a123a8305262255bd4a6082675a58744742660b02d",
    "sourceCommit": "6013688a384c4e39a5b2b79d1b95bb29d00725de",
    "workflowRunId": "34124828745",
}
assert all(value is False for value in contract["scope"].values())
assert contract["promotionHold"] == {
    "pullRequestNumber": 71,
    "keepOpen": True,
    "mergeBeforeRepairMainAllowed": False,
    "rerunHistoricalFailureAllowed": False,
    "nextUpdateOnlyAfterRepairMain": True,
}

design_text = (root / failure["failingValidator"]).read_text()
prior_repair_text = (root / "scripts/validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh").read_text()
for text in (design_text, prior_repair_text):
    assert "check-v0.11.9.3.2-release-successor.py" in text
    assert "reviewed-selected-candidate" in text
    assert 'AWS_DEV_RELEASE_FILE="${AWS_DEV_RELEASE_FILE:-' in text

assert 'apps/demo-api/helm/values/releases/aws-prod.yaml' in design_text
assert 'for environment in ("aws-dev", "aws-test", "aws-prod"):' not in design_text
assert "hashlib.sha256(current_aws_dev)" not in prior_repair_text

for path in sorted((root / "scripts").glob("validate-v0.11*.sh")):
    if path.name == "validate-v0.11.9.3.3.2-remote-successor-chain-repair.sh":
        continue
    text = path.read_text()
    if (
        'for environment in ("aws-dev", "aws-test", "aws-prod"):' in text
        and 'candidate["digest"] not in release' in text
    ):
        raise SystemExit(f"Permanent all-AWS candidate absence assertion remains: {path.name}")
    if "hashlib.sha256(current_aws_dev)" in text:
        raise SystemExit(f"Permanent current aws-dev fingerprint assertion remains: {path.name}")

release = (root / "apps/demo-api/helm/values/releases/aws-prod.yaml").read_text()
assert contract["selectedCandidate"]["digest"] not in release
assert contract["selectedCandidate"]["sourceCommit"] not in release

for relative, marker in (
    ("README.md", "v0.11.9.3.3.2-remote-successor-chain-repair"),
    ("CHANGELOG.md", "## v0.11.9.3.3.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.3.2"),
    ("docs/V0.11.9.3.3.2_REMOTE_SUCCESSOR_CHAIN_REPAIR.md", "Unified successor semantics"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.3.2-remote-successor-chain-repair.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.3.2-remote-successor-chain-repair.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.3.2 remaining successor-chain assertions and no-runtime scope passed.")
PY

"${ROOT_DIR}/scripts/check-v0.11.9.3.6.6.1-aws-test-release-successor.py" \
  --release-file "${AWS_TEST_RELEASE_FILE}" >/dev/null

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
  "${DESIGN_VALIDATOR}" >/dev/null
AWS_DEV_RELEASE_FILE="${ACCEPTED_VALUES}" \
  "${DESIGN_VALIDATOR}" >/dev/null
if AWS_DEV_RELEASE_FILE="${REJECTED_VALUES}" \
  "${DESIGN_VALIDATOR}" >/dev/null 2>&1; then
  echo "Remote design validator accepted the incidental unqualified image." >&2
  exit 1
fi

AWS_DEV_RELEASE_FILE="${AWS_DEV_RELEASE_FILE}" \
  "${PRIOR_REPAIR_VALIDATOR}" >/dev/null
AWS_DEV_RELEASE_FILE="${ACCEPTED_VALUES}" \
  "${PRIOR_REPAIR_VALIDATOR}" >/dev/null
if AWS_DEV_RELEASE_FILE="${REJECTED_VALUES}" \
  "${PRIOR_REPAIR_VALIDATOR}" >/dev/null 2>&1; then
  echo "Prior repair validator accepted the incidental unqualified image." >&2
  exit 1
fi

for values_file in "${AWS_DEV_RELEASE_FILE}" "${ACCEPTED_VALUES}"; do
  state="$(
    "${SUCCESSOR_CHECK}" \
      --release-file "${values_file}" \
      --readiness-contract "${READINESS_CONTRACT}" \
      --successor-contract "${SUCCESSOR_CONTRACT}"
  )"
  if [[ "${state}" != "historical-baseline" && \
        "${state}" != "reviewed-selected-candidate" ]]; then
    echo "Unexpected allowed fixture state: ${state}" >&2
    exit 1
  fi
done

bash -n \
  "${DESIGN_VALIDATOR}" \
  "${PRIOR_REPAIR_VALIDATOR}" \
  "${ROOT_DIR}/scripts/validate-v0.11.9.3.3.2-remote-successor-chain-repair.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck \
    "${DESIGN_VALIDATOR}" \
    "${PRIOR_REPAIR_VALIDATOR}" \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.3.2-remote-successor-chain-repair.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.3.2 remote successor chain repair validation passed; no live operation was executed."

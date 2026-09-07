#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.1-existing-image-aws-dev-promotion.json"
WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-promote-existing-image.yaml"
VERIFY_SCRIPT="${ROOT_DIR}/scripts/verify-existing-demo-api-image-metadata.sh"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command_name in bash git jq python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" "${CONTRACT}" "${WORKFLOW}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
workflow = Path(sys.argv[3]).read_text()

assert contract["schemaVersion"] == "v0.11.9.3.1"
assert contract["version"] == "v0.11.9.3.1"
assert contract["predecessor"] == "v0.11.9.3.0"
assert contract["status"] == "implemented-offline-live-dispatch-blocked-until-protected-main"
assert contract["implementationBaselineCommit"] == "e8a980ffed354b143e9b25df959d22920abf7ce0"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.2-protected-main-integration-readiness"

assert contract["candidate"] == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceRepository": "SterlingAureum/startup-devops-baseline",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "metadataArtifact": "demo-api-image-metadata-cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "applicationVersion": "sha-cf0a6bc",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
}

workflow_contract = contract["workflow"]
assert workflow_contract["path"] == ".github/workflows/demo-api-promote-existing-image.yaml"
assert workflow_contract["trigger"] == "workflow_dispatch"
assert workflow_contract["allowedRef"] == "refs/heads/main"
assert workflow_contract["inputs"] == ["source_run_id", "expected_source_commit"]
assert workflow_contract["baseBranch"] == "main"
assert workflow_contract["targetEnvironment"] == "aws-dev"
assert workflow_contract["targetReleaseFile"] == "apps/demo-api/helm/values/releases/aws-dev.yaml"
assert workflow_contract["automaticMerge"] is False
assert workflow_contract["automaticDeployment"] is False

assert contract["sourceGates"]["manualDigestInputAllowed"] is False
for key, value in contract["sourceGates"].items():
    if key != "manualDigestInputAllowed" and key != "metadataSchema":
        assert value is True, key
assert contract["sourceGates"]["metadataSchema"] == "v0.7.1"

supply = contract["supplyChainGates"]
assert supply["digestAddressedManifestRequired"] is True
assert supply["slsaProvenanceRequired"] is True
assert supply["spdxSbomAttestationRequired"] is True
assert supply["attestationSignerWorkflowRequired"] == ".github/workflows/demo-api-image-publish.yaml"
assert supply["missingArtifactBehavior"] == "fail-closed-no-rebuild"
assert supply["missingAttestationBehavior"] == "fail-closed-no-rebuild"

mutation = contract["mutationBoundary"]
assert mutation["releaseFileOnly"] is True
assert mutation["environmentValuesChanged"] is False
assert mutation["existingBranchMayBeOverwritten"] is False
assert mutation["automaticPrMerge"] is False

assert contract["permissions"] == {
    "actions": "read",
    "contents": "write",
    "packages": "read",
    "pullRequests": "write",
    "idToken": "none",
    "attestations": "none",
    "awsCredentials": "none",
    "clusterCredentials": "none",
}
assert all(value is False for value in contract["producerExecution"].values())

trigger = workflow.split("permissions:", 1)[0]
assert "\n  workflow_dispatch:\n" in trigger
if re.search(r"(?m)^  (push|pull_request|schedule|workflow_call):", trigger):
    raise SystemExit("Existing-image promotion workflow must remain manual-only")

required_fragments = (
    '"${GITHUB_REF}" != "refs/heads/main"',
    "refs/heads/main",
    "actions: read",
    "contents: write",
    "packages: read",
    "pull-requests: write",
    "run-id: ${{ inputs.source_run_id }}",
    "github-token: ${{ secrets.GITHUB_TOKEN }}",
    "./scripts/verify-existing-demo-api-image-metadata.sh",
    'docker buildx imagetools inspect',
    "gh attestation verify",
    "--bundle-from-oci",
    "--signer-workflow",
    "--source-digest",
    "--predicate-type https://spdx.dev/Document/v2.3",
    "./scripts/promote-demo-api-image.sh",
    "apps/demo-api/helm/values/releases/aws-dev.yaml",
    "main changed before promotion branch publication",
    "main changed before PR creation",
    "will not be overwritten",
    "gh pr create",
)
for fragment in required_fragments:
    if fragment not in workflow:
        raise SystemExit(f"Existing-image promotion workflow is missing: {fragment}")

ordered_steps = (
    "Capture main and source run identity",
    "Download original image metadata artifact",
    "Verify existing image metadata and ancestry",
    "Verify digest and both attestations",
    "Prepare or reuse exact promotion branch",
    "Create or reuse promotion pull request",
)
positions = [workflow.index(f"      - name: {name}\n") for name in ordered_steps]
assert positions == sorted(positions)

for forbidden in (
    "docker/build-push-action",
    "actions/attest@",
    "configure-aws-credentials",
    "aws eks",
    "kubectl",
    "argocd",
    "gh pr merge",
    "id-token: write",
    "attestations: write",
):
    if forbidden in workflow:
        raise SystemExit(f"Existing-image promotion contains forbidden capability: {forbidden}")

for relative, marker in (
    ("README.md", "v0.11.9.3.1-existing-image-aws-dev-promotion"),
    ("CHANGELOG.md", "## v0.11.9.3.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.1"),
    ("docs/CI_IMAGE_WORKFLOW.md", "Historical existing-image handoff"),
    ("docs/V0.11.9.3.1_EXISTING_IMAGE_AWS_DEV_PROMOTION.md", "No manual digest input"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.1-existing-image-aws-dev-promotion.sh"),
    (".github/CODEOWNERS", "/.github/workflows/demo-api-promote-existing-image.yaml"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.1 workflow, permissions, ordering, fail-closed and no-runtime boundaries passed.")
PY

FIXTURE_REPO="${WORK_DIR}/repo"
mkdir -p "${FIXTURE_REPO}"
git -C "${FIXTURE_REPO}" init --quiet
git -C "${FIXTURE_REPO}" config user.name "Promotion Fixture"
git -C "${FIXTURE_REPO}" config user.email "fixture@example.invalid"
printf '%s\n' seed > "${FIXTURE_REPO}/fixture.txt"
git -C "${FIXTURE_REPO}" add fixture.txt
git -C "${FIXTURE_REPO}" commit --quiet -m seed
root_sha="$(git -C "${FIXTURE_REPO}" rev-parse HEAD)"
printf '%s\n' source >> "${FIXTURE_REPO}/fixture.txt"
git -C "${FIXTURE_REPO}" commit --quiet -am source
source_sha="$(git -C "${FIXTURE_REPO}" rev-parse HEAD)"
printf '%s\n' main >> "${FIXTURE_REPO}/fixture.txt"
git -C "${FIXTURE_REPO}" commit --quiet -am main
base_sha="$(git -C "${FIXTURE_REPO}" rev-parse HEAD)"
git -C "${FIXTURE_REPO}" switch --quiet --create side "${root_sha}"
printf '%s\n' side >> "${FIXTURE_REPO}/fixture.txt"
git -C "${FIXTURE_REPO}" commit --quiet -am side
side_sha="$(git -C "${FIXTURE_REPO}" rev-parse HEAD)"
git -C "${FIXTURE_REPO}" switch --quiet master

digest="sha256:$(printf 'a%.0s' {1..64})"
tag="sha-${source_sha:0:7}"
run_id="34070524953"
repository="SterlingAureum/startup-devops-baseline"
image_repository="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api"

jq --null-input \
  --argjson id "${run_id}" \
  --arg source_commit "${source_sha}" \
  --arg repository "${repository}" '{
    id: $id,
    status: "completed",
    conclusion: "success",
    head_sha: $source_commit,
    path: ".github/workflows/demo-api-image-publish.yaml@feature/v0.11-observability-sre-baseline",
    repository: {full_name: $repository}
  }' > "${WORK_DIR}/run.json"

jq --null-input \
  --arg image_repository "${image_repository}" \
  --arg tag "${tag}" \
  --arg digest "${digest}" \
  --arg repository "${repository}" \
  --arg source_commit "${source_sha}" \
  --arg run_id "${run_id}" '{
    schemaVersion: "v0.7.1",
    image: {
      repository: $image_repository,
      tag: $tag,
      digest: $digest,
      reference: ($image_repository + "@" + $digest)
    },
    source: {repository: $repository, commit: $source_commit},
    build: {workflowRunId: $run_id}
  }' > "${WORK_DIR}/metadata.json"

(
  cd "${FIXTURE_REPO}"
  GITHUB_OUTPUT="${WORK_DIR}/outputs" \
  METADATA_FILE="${WORK_DIR}/metadata.json" \
  RUN_FILE="${WORK_DIR}/run.json" \
  EXPECTED_WORKFLOW_RUN_ID="${run_id}" \
  EXPECTED_SOURCE_REPOSITORY="${repository}" \
  EXPECTED_SOURCE_COMMIT="${source_sha}" \
  EXPECTED_IMAGE_REPOSITORY="${image_repository}" \
  BASE_REVISION="${base_sha}" \
    "${VERIFY_SCRIPT}" >/dev/null
)

for expected_output in \
  "image-tag=${tag}" \
  "image-digest=${digest}" \
  "source-commit=${source_sha}" \
  "workflow-run-id=${run_id}" \
  "metadata-artifact-name=demo-api-image-metadata-${source_sha}" \
  "release-id=demo-api-${source_sha:0:12}-aaaaaaaaaaaa"; do
  grep -Fx "${expected_output}" "${WORK_DIR}/outputs" >/dev/null || {
    echo "Existing-image verifier output is missing: ${expected_output}" >&2
    exit 1
  }
done

cp "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  "${WORK_DIR}/promoted-aws-dev.yaml"
METADATA_FILE="${WORK_DIR}/metadata.json" \
VALUES_FILE="${WORK_DIR}/promoted-aws-dev.yaml" \
EXPECTED_IMAGE_REPOSITORY="${image_repository}" \
EXPECTED_SOURCE_REPOSITORY="${repository}" \
EXPECTED_SOURCE_COMMIT="${source_sha}" \
  "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null

python3 - \
  "${WORK_DIR}/promoted-aws-dev.yaml" \
  "${image_repository}" \
  "${tag}" \
  "${digest}" \
  "${repository}" \
  "${source_sha}" \
  "${run_id}" <<'PY'
from pathlib import Path
import sys


release = Path(sys.argv[1]).read_text()
expected = (
    f"  repository: {sys.argv[2]}",
    f'  tag: "{sys.argv[3]}"',
    f'  digest: "{sys.argv[4]}"',
    f'  applicationVersion: "{sys.argv[3]}"',
    f'  sourceRepository: "{sys.argv[5]}"',
    f'  sourceCommit: "{sys.argv[6]}"',
    f'  workflowRunId: "{sys.argv[7]}"',
)
for line in expected:
    if release.count(line) != 1:
        raise SystemExit(f"Promoted release identity is missing or duplicated: {line}")
PY

jq '.conclusion = "failure"' "${WORK_DIR}/run.json" > "${WORK_DIR}/failed-run.json"
if (
  cd "${FIXTURE_REPO}"
  METADATA_FILE="${WORK_DIR}/metadata.json" \
  RUN_FILE="${WORK_DIR}/failed-run.json" \
  EXPECTED_WORKFLOW_RUN_ID="${run_id}" \
  EXPECTED_SOURCE_REPOSITORY="${repository}" \
  EXPECTED_SOURCE_COMMIT="${source_sha}" \
  EXPECTED_IMAGE_REPOSITORY="${image_repository}" \
  BASE_REVISION="${base_sha}" \
    "${VERIFY_SCRIPT}" >/dev/null 2>&1
); then
  echo "Existing-image verifier accepted a failed source workflow run." >&2
  exit 1
fi

jq '.path = ".github/workflows/not-the-image-publisher.yaml@main"' \
  "${WORK_DIR}/run.json" > "${WORK_DIR}/wrong-workflow-run.json"
if (
  cd "${FIXTURE_REPO}"
  METADATA_FILE="${WORK_DIR}/metadata.json" \
  RUN_FILE="${WORK_DIR}/wrong-workflow-run.json" \
  EXPECTED_WORKFLOW_RUN_ID="${run_id}" \
  EXPECTED_SOURCE_REPOSITORY="${repository}" \
  EXPECTED_SOURCE_COMMIT="${source_sha}" \
  EXPECTED_IMAGE_REPOSITORY="${image_repository}" \
  BASE_REVISION="${base_sha}" \
    "${VERIFY_SCRIPT}" >/dev/null 2>&1
); then
  echo "Existing-image verifier accepted a run from another workflow." >&2
  exit 1
fi

jq '.build.workflowRunId = "1"' "${WORK_DIR}/metadata.json" > "${WORK_DIR}/wrong-run-metadata.json"
if (
  cd "${FIXTURE_REPO}"
  METADATA_FILE="${WORK_DIR}/wrong-run-metadata.json" \
  RUN_FILE="${WORK_DIR}/run.json" \
  EXPECTED_WORKFLOW_RUN_ID="${run_id}" \
  EXPECTED_SOURCE_REPOSITORY="${repository}" \
  EXPECTED_SOURCE_COMMIT="${source_sha}" \
  EXPECTED_IMAGE_REPOSITORY="${image_repository}" \
  BASE_REVISION="${base_sha}" \
    "${VERIFY_SCRIPT}" >/dev/null 2>&1
); then
  echo "Existing-image verifier accepted metadata from another run." >&2
  exit 1
fi

if (
  cd "${FIXTURE_REPO}"
  METADATA_FILE="${WORK_DIR}/metadata.json" \
  RUN_FILE="${WORK_DIR}/run.json" \
  EXPECTED_WORKFLOW_RUN_ID="${run_id}" \
  EXPECTED_SOURCE_REPOSITORY="${repository}" \
  EXPECTED_SOURCE_COMMIT="${source_sha}" \
  EXPECTED_IMAGE_REPOSITORY="${image_repository}" \
  BASE_REVISION="${side_sha}" \
    "${VERIFY_SCRIPT}" >/dev/null 2>&1
); then
  echo "Existing-image verifier accepted a source outside the selected main history." >&2
  exit 1
fi

bash -n "${VERIFY_SCRIPT}" "${ROOT_DIR}/scripts/validate-v0.11.9.3.1-existing-image-aws-dev-promotion.sh"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${VERIFY_SCRIPT}" "${ROOT_DIR}/scripts/validate-v0.11.9.3.1-existing-image-aws-dev-promotion.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.1 existing-image aws-dev promotion validation passed; no live operation was executed."

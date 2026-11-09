#!/usr/bin/env bash
set -Eeuo pipefail

METADATA_FILE="${METADATA_FILE:-demo-api-image-metadata.json}"
RUN_FILE="${RUN_FILE:-demo-api-image-workflow-run.json}"
EXPECTED_WORKFLOW_RUN_ID="${EXPECTED_WORKFLOW_RUN_ID:-}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-}"
EXPECTED_SOURCE_COMMIT="${EXPECTED_SOURCE_COMMIT:-}"
EXPECTED_IMAGE_REPOSITORY="${EXPECTED_IMAGE_REPOSITORY:-}"
EXPECTED_WORKFLOW_PATH="${EXPECTED_WORKFLOW_PATH:-.github/workflows/demo-api-image-publish.yaml}"
BASE_REVISION="${BASE_REVISION:-}"

for command_name in git jq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

if [[ ! "${EXPECTED_WORKFLOW_RUN_ID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Expected workflow run ID must be a positive decimal integer." >&2
  exit 1
fi
if [[ ! "${EXPECTED_SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Expected source commit must be a full lowercase Git SHA." >&2
  exit 1
fi
if [[ ! "${BASE_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Base revision must be a full lowercase Git SHA." >&2
  exit 1
fi
if [[ ! "${EXPECTED_IMAGE_REPOSITORY}" =~ ^ghcr\.io/[a-z0-9._/-]+$ ]]; then
  echo "Expected image repository must be a lowercase GHCR path." >&2
  exit 1
fi
if [[ -z "${EXPECTED_SOURCE_REPOSITORY}" ]]; then
  echo "Expected source repository is required." >&2
  exit 1
fi
if [[ ! -f "${METADATA_FILE}" ]]; then
  echo "Image metadata file not found: ${METADATA_FILE}" >&2
  exit 1
fi
if [[ ! -f "${RUN_FILE}" ]]; then
  echo "Workflow run response not found: ${RUN_FILE}" >&2
  exit 1
fi

jq --exit-status \
  --arg run_id "${EXPECTED_WORKFLOW_RUN_ID}" \
  --arg source_repository "${EXPECTED_SOURCE_REPOSITORY}" \
  --arg source_commit "${EXPECTED_SOURCE_COMMIT}" \
  --arg workflow_path "${EXPECTED_WORKFLOW_PATH}" '
    (.id | tostring) == $run_id and
    .status == "completed" and
    .conclusion == "success" and
    .head_sha == $source_commit and
    (.path == $workflow_path or
      (.path | startswith($workflow_path + "@"))) and
    .repository.full_name == $source_repository
  ' "${RUN_FILE}" >/dev/null || {
  echo "Workflow run does not match the successful image publisher identity." >&2
  exit 1
}

jq --exit-status \
  --arg run_id "${EXPECTED_WORKFLOW_RUN_ID}" \
  --arg source_repository "${EXPECTED_SOURCE_REPOSITORY}" \
  --arg source_commit "${EXPECTED_SOURCE_COMMIT}" \
  --arg image_repository "${EXPECTED_IMAGE_REPOSITORY}" '
    .schemaVersion == "v0.7.1" and
    .image.repository == $image_repository and
    (.image.tag | test("^sha-[0-9a-f]{7}$")) and
    (.image.digest | test("^sha256:[0-9a-f]{64}$")) and
    .image.reference == (.image.repository + "@" + .image.digest) and
    .source.repository == $source_repository and
    .source.commit == $source_commit and
    (.build.workflowRunId | tostring) == $run_id
  ' "${METADATA_FILE}" >/dev/null || {
  echo "Image metadata does not match the requested workflow run identity." >&2
  exit 1
}

image_repository="$(jq --raw-output '.image.repository' "${METADATA_FILE}")"
image_tag="$(jq --raw-output '.image.tag' "${METADATA_FILE}")"
image_digest="$(jq --raw-output '.image.digest' "${METADATA_FILE}")"
source_commit="$(jq --raw-output '.source.commit' "${METADATA_FILE}")"

if [[ "${image_tag}" != "sha-${source_commit:0:7}" ]]; then
  echo "Image tag does not derive from the metadata source commit." >&2
  exit 1
fi

if ! git cat-file -e "${source_commit}^{commit}" 2>/dev/null; then
  echo "Image source commit is not present in the checked-out repository." >&2
  exit 1
fi
if ! git cat-file -e "${BASE_REVISION}^{commit}" 2>/dev/null; then
  echo "Base revision is not present in the checked-out repository." >&2
  exit 1
fi
if ! git merge-base --is-ancestor "${source_commit}" "${BASE_REVISION}"; then
  echo "Image source commit is not an ancestor of the selected main revision." >&2
  exit 1
fi

digest_hex="${image_digest#sha256:}"
release_id="demo-api-${source_commit:0:12}-${digest_hex:0:12}"
artifact_name="demo-api-image-metadata-${source_commit}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "image-repository=${image_repository}"
    echo "image-tag=${image_tag}"
    echo "image-digest=${image_digest}"
    echo "image-reference=${image_repository}@${image_digest}"
    echo "source-commit=${source_commit}"
    echo "workflow-run-id=${EXPECTED_WORKFLOW_RUN_ID}"
    echo "metadata-artifact-name=${artifact_name}"
    echo "release-id=${release_id}"
  } >> "${GITHUB_OUTPUT}"
fi

echo "Verified existing demo-api image metadata:"
echo "  run=${EXPECTED_WORKFLOW_RUN_ID}"
echo "  source=${EXPECTED_SOURCE_REPOSITORY}@${source_commit}"
echo "  image=${image_repository}@${image_digest}"
echo "  release=${release_id}"

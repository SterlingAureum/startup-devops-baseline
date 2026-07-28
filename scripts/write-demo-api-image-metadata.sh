#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE_DIGEST="${IMAGE_DIGEST:-}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-${GITHUB_REPOSITORY:-}}"
SOURCE_COMMIT="${SOURCE_COMMIT:-${GITHUB_SHA:-}}"
WORKFLOW_RUN_ID="${WORKFLOW_RUN_ID:-${GITHUB_RUN_ID:-}}"
OUTPUT_FILE="${OUTPUT_FILE:-demo-api-image-metadata.json}"

command -v jq >/dev/null 2>&1 || {
  echo "Required command not found: jq" >&2
  exit 1
}

if [[ -z "${IMAGE_TAG}" || \
      -z "${IMAGE_DIGEST}" || \
      -z "${SOURCE_REPOSITORY}" || \
      -z "${SOURCE_COMMIT}" || \
      -z "${WORKFLOW_RUN_ID}" ]]; then
  echo "Image tag, digest, source repository, commit, and workflow run ID are required." >&2
  exit 1
fi

if [[ ! "${IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "IMAGE_DIGEST must be a lowercase sha256 digest." >&2
  exit 1
fi

if [[ ! "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "SOURCE_COMMIT must be a full lowercase Git commit SHA." >&2
  exit 1
fi

jq \
  --null-input \
  --arg repository "${IMAGE_REPOSITORY}" \
  --arg tag "${IMAGE_TAG}" \
  --arg digest "${IMAGE_DIGEST}" \
  --arg source_repository "${SOURCE_REPOSITORY}" \
  --arg source_commit "${SOURCE_COMMIT}" \
  --arg workflow_run_id "${WORKFLOW_RUN_ID}" \
  '{
    schemaVersion: "v0.7.1",
    image: {
      repository: $repository,
      tag: $tag,
      digest: $digest,
      reference: ($repository + "@" + $digest)
    },
    source: {
      repository: $source_repository,
      commit: $source_commit
    },
    build: {
      workflowRunId: $workflow_run_id
    }
  }' >"${OUTPUT_FILE}"

echo "Image identity metadata written:"
echo "  file=${OUTPUT_FILE}"
echo "  tag=${IMAGE_TAG}"
echo "  digest=${IMAGE_DIGEST}"

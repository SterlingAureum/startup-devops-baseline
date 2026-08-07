#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
METADATA_FILE="${METADATA_FILE:-demo-api-image-metadata.json}"
VALUES_FILE="${VALUES_FILE:-apps/demo-api/helm/values/releases/aws-dev.yaml}"
EXPECTED_IMAGE_REPOSITORY="${EXPECTED_IMAGE_REPOSITORY:-}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-}"
EXPECTED_SOURCE_COMMIT="${EXPECTED_SOURCE_COMMIT:-}"

command -v jq >/dev/null 2>&1 || {
  echo "Required command not found: jq" >&2
  exit 1
}

if [[ ! -f "${METADATA_FILE}" ]]; then
  echo "Image metadata file not found: ${METADATA_FILE}" >&2
  exit 1
fi

if [[ ! -f "${VALUES_FILE}" ]]; then
  echo "Promotion values file not found: ${VALUES_FILE}" >&2
  exit 1
fi

jq --exit-status '
  .schemaVersion == "v0.7.1" and
  (.image.repository | type == "string" and length > 0) and
  (.image.tag | test("^sha-[0-9a-f]{7}$")) and
  (.image.digest | test("^sha256:[0-9a-f]{64}$")) and
  (.image.reference == (.image.repository + "@" + .image.digest)) and
  (.source.repository | type == "string" and length > 0) and
  (.source.commit | test("^[0-9a-f]{40}$")) and
  (.build.workflowRunId | type == "string" and length > 0)
' "${METADATA_FILE}" >/dev/null || {
  echo "Image metadata does not satisfy the v0.7.1 identity contract." >&2
  exit 1
}

IMAGE_REPOSITORY="$(jq --raw-output '.image.repository' "${METADATA_FILE}")"
IMAGE_TAG="$(jq --raw-output '.image.tag' "${METADATA_FILE}")"
IMAGE_DIGEST="$(jq --raw-output '.image.digest' "${METADATA_FILE}")"
SOURCE_REPOSITORY="$(jq --raw-output '.source.repository' "${METADATA_FILE}")"
SOURCE_COMMIT="$(jq --raw-output '.source.commit' "${METADATA_FILE}")"
WORKFLOW_RUN_ID="$(jq --raw-output '.build.workflowRunId' "${METADATA_FILE}")"

if [[ "${IMAGE_TAG}" != "sha-${SOURCE_COMMIT:0:7}" ]]; then
  echo "Image tag does not match the metadata source commit." >&2
  exit 1
fi

if [[ -n "${EXPECTED_IMAGE_REPOSITORY}" && \
      "${IMAGE_REPOSITORY}" != "${EXPECTED_IMAGE_REPOSITORY}" ]]; then
  echo "Metadata image repository does not match the published repository." >&2
  exit 1
fi

if [[ -n "${EXPECTED_SOURCE_REPOSITORY}" && \
      "${SOURCE_REPOSITORY}" != "${EXPECTED_SOURCE_REPOSITORY}" ]]; then
  echo "Metadata source repository does not match the workflow repository." >&2
  exit 1
fi

if [[ -n "${EXPECTED_SOURCE_COMMIT}" && \
      "${SOURCE_COMMIT}" != "${EXPECTED_SOURCE_COMMIT}" ]]; then
  echo "Metadata source commit does not match the workflow revision." >&2
  exit 1
fi

VALUES_FILE="${VALUES_FILE}" \
IMAGE_REPOSITORY="${IMAGE_REPOSITORY}" \
IMAGE_TAG="${IMAGE_TAG}" \
IMAGE_DIGEST="${IMAGE_DIGEST}" \
APP_VERSION="${IMAGE_TAG}" \
  "${ROOT_DIR}/scripts/set-demo-api-image.sh"

VALUES_FILE="${VALUES_FILE}" \
SOURCE_REPOSITORY="${SOURCE_REPOSITORY}" \
SOURCE_COMMIT="${SOURCE_COMMIT}" \
WORKFLOW_RUN_ID="${WORKFLOW_RUN_ID}" \
  "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "image-repository=${IMAGE_REPOSITORY}"
    echo "image-tag=${IMAGE_TAG}"
    echo "image-digest=${IMAGE_DIGEST}"
    echo "source-repository=${SOURCE_REPOSITORY}"
    echo "source-commit=${SOURCE_COMMIT}"
    echo "workflow-run-id=${WORKFLOW_RUN_ID}"
    echo "values-file=${VALUES_FILE}"
  } >> "${GITHUB_OUTPUT}"
fi

echo "Prepared aws-dev release identity from verified image metadata:"
echo "  source=${SOURCE_REPOSITORY}@${SOURCE_COMMIT}"
echo "  image=${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"
echo "  values=${VALUES_FILE}"

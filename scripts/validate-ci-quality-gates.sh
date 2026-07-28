#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash docker helm jq python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Checking shell script syntax"
while IFS= read -r script; do
  bash -n "${script}"
done < <(find "${ROOT_DIR}/scripts" -maxdepth 1 -type f -name '*.sh' | sort)

echo "==> Linting and rendering the local Helm release"
helm lint "${ROOT_DIR}/apps/demo-api/helm"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  >"${WORK_DIR}/demo-api-local.yaml"

echo "==> Linting and rendering the aws-dev Helm release"
helm lint "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values-aws-dev.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values-aws-dev.yaml" \
  >"${WORK_DIR}/demo-api-aws-dev.yaml"

TEST_IMAGE_DIGEST="sha256:$(printf 'a%.0s' {1..64})"
TEST_IMAGE_REFERENCE="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api@${TEST_IMAGE_DIGEST}"

echo "==> Validating digest-pinned Helm rendering"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --set "image.digest=${TEST_IMAGE_DIGEST}" \
  >"${WORK_DIR}/demo-api-local-digest.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values-aws-dev.yaml" \
  --set "image.digest=${TEST_IMAGE_DIGEST}" \
  >"${WORK_DIR}/demo-api-aws-dev-digest.yaml"

for manifest in \
  "${WORK_DIR}/demo-api-local-digest.yaml" \
  "${WORK_DIR}/demo-api-aws-dev-digest.yaml"; do
  grep -F "image: \"${TEST_IMAGE_REFERENCE}\"" "${manifest}" >/dev/null || {
    echo "Digest-pinned image reference is missing from ${manifest}." >&2
    exit 1
  }
done

if helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --set "image.digest=sha256:invalid" \
  >"${WORK_DIR}/demo-api-invalid-digest.yaml" 2>/dev/null; then
  echo "Helm accepted an invalid image digest." >&2
  exit 1
fi

echo "==> Validating image identity metadata"
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
IMAGE_TAG="sha-0123456" \
IMAGE_DIGEST="${TEST_IMAGE_DIGEST}" \
SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
SOURCE_COMMIT="0123456789abcdef0123456789abcdef01234567" \
WORKFLOW_RUN_ID="local-validation" \
OUTPUT_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
  "${ROOT_DIR}/scripts/write-demo-api-image-metadata.sh"

jq --exit-status \
  --arg digest "${TEST_IMAGE_DIGEST}" \
  --arg reference "${TEST_IMAGE_REFERENCE}" \
  '
    .schemaVersion == "v0.7.1" and
    .image.digest == $digest and
    .image.reference == $reference and
    .source.commit == "0123456789abcdef0123456789abcdef01234567"
  ' "${WORK_DIR}/demo-api-image-metadata.json" >/dev/null

echo "==> Validating the digest promotion values update"
cp \
  "${ROOT_DIR}/apps/demo-api/helm/values-aws-dev.yaml" \
  "${WORK_DIR}/values-aws-dev.yaml"
VALUES_FILE="${WORK_DIR}/values-aws-dev.yaml" \
IMAGE_TAG="sha-0123456" \
IMAGE_DIGEST="${TEST_IMAGE_DIGEST}" \
APP_VERSION="sha-0123456" \
  "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null

grep -F 'tag: "sha-0123456"' "${WORK_DIR}/values-aws-dev.yaml" >/dev/null
grep -F "digest: \"${TEST_IMAGE_DIGEST}\"" \
  "${WORK_DIR}/values-aws-dev.yaml" >/dev/null
grep -F 'APP_VERSION: "sha-0123456"' \
  "${WORK_DIR}/values-aws-dev.yaml" >/dev/null

echo "==> Running demo-api unit tests in the test image stage"
docker build \
  --target test \
  --tag demo-api-ci-test:unit \
  "${ROOT_DIR}/apps/demo-api"

echo "==> Building the final demo-api runtime image"
docker build \
  --tag demo-api-ci-test:runtime \
  "${ROOT_DIR}/apps/demo-api"

echo "CI quality gates passed."

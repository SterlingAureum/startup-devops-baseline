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

echo "==> Validating GitHub Actions runtime and promotion trigger contracts"
PUBLISH_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-image-publish.yaml"
for action in \
  "actions/checkout@v7" \
  "actions/upload-artifact@v6" \
  "actions/download-artifact@v7" \
  "azure/setup-helm@v5" \
  "docker/setup-buildx-action@v4" \
  "docker/login-action@v4" \
  "docker/metadata-action@v6" \
  "docker/build-push-action@v7"; do
  grep -F "uses: ${action}" "${PUBLISH_WORKFLOW}" >/dev/null || {
    echo "Expected Node.js 24 Action is missing: ${action}" >&2
    exit 1
  }
done

if grep -RE \
  'uses: (actions/checkout@v4|azure/setup-helm@v4|actions/upload-artifact@v4|docker/build-push-action@v6|docker/login-action@v3|docker/metadata-action@v5|docker/setup-buildx-action@v3)' \
  "${ROOT_DIR}/.github/workflows" >/dev/null; then
  echo "A reported Node.js 20 Action version is still active." >&2
  exit 1
fi

python3 - "${PUBLISH_WORKFLOW}" <<'PY'
from pathlib import Path
import sys

lines = Path(sys.argv[1]).read_text().splitlines()
paths_start = lines.index("    paths:")
trigger_paths = []
for line in lines[paths_start + 1:]:
    if line.startswith("      - "):
        trigger_paths.append(line.strip().removeprefix("- ").strip("'\""))
        continue
    if line and not line.startswith("      "):
        break

if "apps/demo-api/helm/values-aws-dev.yaml" in trigger_paths:
    raise SystemExit(
        "aws-dev promotion values must not trigger another image publish"
    )
if "apps/demo-api/src/**" not in trigger_paths:
    raise SystemExit("demo-api source changes must trigger image publishing")
PY

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

echo "==> Validating metadata-driven aws-dev promotion"
cp \
  "${ROOT_DIR}/apps/demo-api/helm/values-aws-dev.yaml" \
  "${WORK_DIR}/values-aws-dev.yaml"
EXPECTED_IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
EXPECTED_SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
EXPECTED_SOURCE_COMMIT="0123456789abcdef0123456789abcdef01234567" \
METADATA_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
VALUES_FILE="${WORK_DIR}/values-aws-dev.yaml" \
  "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null

grep -F 'tag: "sha-0123456"' "${WORK_DIR}/values-aws-dev.yaml" >/dev/null
grep -F "digest: \"${TEST_IMAGE_DIGEST}\"" \
  "${WORK_DIR}/values-aws-dev.yaml" >/dev/null
grep -F 'APP_VERSION: "sha-0123456"' \
  "${WORK_DIR}/values-aws-dev.yaml" >/dev/null

helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${WORK_DIR}/values-aws-dev.yaml" \
  >"${WORK_DIR}/demo-api-promoted-aws-dev.yaml"
grep -F "image: \"${TEST_IMAGE_REFERENCE}\"" \
  "${WORK_DIR}/demo-api-promoted-aws-dev.yaml" >/dev/null

if EXPECTED_SOURCE_COMMIT="ffffffffffffffffffffffffffffffffffffffff" \
  METADATA_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
  VALUES_FILE="${WORK_DIR}/values-aws-dev.yaml" \
    "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null 2>&1; then
  echo "Promotion accepted metadata for an unexpected source commit." >&2
  exit 1
fi

if EXPECTED_IMAGE_REPOSITORY="ghcr.io/example/other/demo-api" \
  METADATA_FILE="${WORK_DIR}/demo-api-image-metadata.json" \
  VALUES_FILE="${WORK_DIR}/values-aws-dev.yaml" \
    "${ROOT_DIR}/scripts/promote-demo-api-image.sh" >/dev/null 2>&1; then
  echo "Promotion accepted metadata for an unexpected image repository." >&2
  exit 1
fi

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

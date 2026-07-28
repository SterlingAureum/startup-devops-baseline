#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash docker helm; do
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

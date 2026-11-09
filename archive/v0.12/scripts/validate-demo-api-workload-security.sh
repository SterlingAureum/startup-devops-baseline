#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
IMAGE_NAME="${IMAGE_NAME:-demo-api-security-validation:local}"
CONTAINER_ID=""

cleanup() {
  if [[ -n "${CONTAINER_ID}" ]]; then
    docker rm --force "${CONTAINER_ID}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in docker helm; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

assert_manifest_contains() {
  local manifest="$1"
  local expected="$2"

  grep -F "${expected}" "${manifest}" >/dev/null || {
    echo "Expected security setting is missing from ${manifest}: ${expected}" >&2
    exit 1
  }
}

echo "==> Rendering hardened local and aws-dev workloads"
helm lint "${ROOT_DIR}/apps/demo-api/helm"
helm lint "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/aws-dev.yaml" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"

helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  >"${WORK_DIR}/demo-api-local.yaml"
helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/aws-dev.yaml" \
  --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml" \
  >"${WORK_DIR}/demo-api-aws-dev.yaml"

for manifest in \
  "${WORK_DIR}/demo-api-local.yaml" \
  "${WORK_DIR}/demo-api-aws-dev.yaml"; do
  for expected in \
    "automountServiceAccountToken: false" \
    "runAsNonRoot: true" \
    "runAsUser: 10001" \
    "runAsGroup: 10001" \
    "type: RuntimeDefault" \
    "allowPrivilegeEscalation: false" \
    "readOnlyRootFilesystem: true" \
    "mountPath: /tmp" \
    "medium: \"Memory\"" \
    "sizeLimit: 64Mi"; do
    assert_manifest_contains "${manifest}" "${expected}"
  done

  capability_drop_count="$(
    grep -c -F -- "- ALL" "${manifest}" || true
  )"
  if (( capability_drop_count < 1 )); then
    echo "The workload does not drop all Linux capabilities: ${manifest}" >&2
    exit 1
  fi
done

echo "==> Running demo-api unit tests in the image test stage"
docker build \
  --target test \
  --tag "${IMAGE_NAME}-test" \
  "${ROOT_DIR}/apps/demo-api"

echo "==> Building the hardened demo-api runtime image"
docker build \
  --tag "${IMAGE_NAME}" \
  "${ROOT_DIR}/apps/demo-api"

configured_user="$(docker image inspect \
  --format '{{.Config.User}}' "${IMAGE_NAME}")"
if [[ "${configured_user}" != "10001:10001" ]]; then
  echo "Unexpected runtime image user: ${configured_user:-root}" >&2
  exit 1
fi

echo "==> Verifying non-root execution and filesystem restrictions"
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  "${IMAGE_NAME}" \
  sh -ec '
    test "$(id -u)" = "10001"
    test "$(id -g)" = "10001"
    if touch /app/root-filesystem-write-test 2>/dev/null; then
      echo "The read-only root filesystem accepted a write." >&2
      exit 1
    fi
    touch /tmp/writable-tmp-test
  '

echo "==> Starting the hardened runtime image"
CONTAINER_ID="$(
  docker run --detach \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    "${IMAGE_NAME}"
)"

ready=false
for _ in {1..30}; do
  if docker exec "${CONTAINER_ID}" \
    python -c \
      'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1).status == 200' \
      >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done

if [[ "${ready}" != "true" ]]; then
  echo "The hardened demo-api container did not become healthy." >&2
  docker logs "${CONTAINER_ID}" >&2 || true
  exit 1
fi

echo "demo-api workload security validation passed."

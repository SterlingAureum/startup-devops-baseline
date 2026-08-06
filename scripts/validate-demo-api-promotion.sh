#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in awk bash cmp cp grep python3 sha256sum; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

RELEASES_DIR="${ROOT_DIR}/apps/demo-api/helm/values/releases"
PROMOTION_SCRIPT="${ROOT_DIR}/scripts/promote-demo-api-release.sh"
PROMOTION_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-promote-environment.yaml"
PUBLISH_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-image-publish.yaml"

for environment in aws-dev aws-test aws-prod; do
  cp "${RELEASES_DIR}/${environment}.yaml" "${WORK_DIR}/${environment}.yaml"
  cp "${RELEASES_DIR}/${environment}.yaml" "${WORK_DIR}/${environment}.original.yaml"
done

expected_repository="$(awk '/^  repository:/{gsub(/"/, "", $2); print $2}' "${WORK_DIR}/aws-dev.yaml")"
expected_tag="$(awk '/^  tag:/{gsub(/"/, "", $2); print $2}' "${WORK_DIR}/aws-dev.yaml")"
expected_digest="$(awk '/^  digest:/{gsub(/"/, "", $2); print $2}' "${WORK_DIR}/aws-dev.yaml")"
expected_source_commit="$(awk '/^  sourceCommit:/{gsub(/"/, "", $2); print $2}' "${WORK_DIR}/aws-dev.yaml")"
source_sha256="$(sha256sum "${WORK_DIR}/aws-dev.yaml" | awk '{print $1}')"
SOURCE_ENVIRONMENT=aws-dev \
TARGET_ENVIRONMENT=aws-test \
SOURCE_RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
TARGET_RELEASE_FILE="${WORK_DIR}/aws-test.yaml" \
EXPECTED_SOURCE_RELEASE_SHA256="${source_sha256}" \
GITHUB_OUTPUT="${WORK_DIR}/promotion-output" \
  "${PROMOTION_SCRIPT}" >/dev/null

cmp "${WORK_DIR}/aws-dev.yaml" "${WORK_DIR}/aws-dev.original.yaml"
cmp "${WORK_DIR}/aws-test.yaml" "${WORK_DIR}/aws-dev.yaml"
cmp "${WORK_DIR}/aws-prod.yaml" "${WORK_DIR}/aws-prod.original.yaml"
for output in \
  "image-tag=${expected_tag}" \
  "image-digest=${expected_digest}" \
  "source-commit=${expected_source_commit}" \
  "image-reference=${expected_repository}@${expected_digest}"; do
  grep -Fx "${output}" "${WORK_DIR}/promotion-output" >/dev/null || {
    echo "Promotion output is missing: ${output}" >&2
    exit 1
  }
done

source_sha256="$(sha256sum "${WORK_DIR}/aws-test.yaml" | awk '{print $1}')"
SOURCE_ENVIRONMENT=aws-test \
TARGET_ENVIRONMENT=aws-prod \
SOURCE_RELEASE_FILE="${WORK_DIR}/aws-test.yaml" \
TARGET_RELEASE_FILE="${WORK_DIR}/aws-prod.yaml" \
EXPECTED_SOURCE_RELEASE_SHA256="${source_sha256}" \
  "${PROMOTION_SCRIPT}" >/dev/null

cmp "${WORK_DIR}/aws-test.yaml" "${WORK_DIR}/aws-dev.yaml"
cmp "${WORK_DIR}/aws-prod.yaml" "${WORK_DIR}/aws-test.yaml"

for edge in \
  build:aws-test \
  build:aws-prod \
  aws-dev:aws-prod \
  aws-prod:aws-test \
  aws-test:aws-dev \
  aws-dev:aws-dev; do
  source_environment="${edge%%:*}"
  target_environment="${edge##*:}"
  source_file="${WORK_DIR}/aws-dev.yaml"
  if [[ "${source_environment}" == "aws-test" || \
        "${source_environment}" == "aws-prod" ]]; then
    source_file="${WORK_DIR}/${source_environment}.yaml"
  fi
  if SOURCE_ENVIRONMENT="${source_environment}" \
    TARGET_ENVIRONMENT="${target_environment}" \
    SOURCE_RELEASE_FILE="${source_file}" \
    TARGET_RELEASE_FILE="${WORK_DIR}/${target_environment}.yaml" \
      "${PROMOTION_SCRIPT}" >/dev/null 2>&1; then
    echo "Promotion script accepted rejected edge: ${source_environment} -> ${target_environment}" >&2
    exit 1
  fi
done

if SOURCE_ENVIRONMENT=build \
  TARGET_ENVIRONMENT=aws-dev \
  SOURCE_RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
  TARGET_RELEASE_FILE="${WORK_DIR}/aws-test.yaml" \
    "${PROMOTION_SCRIPT}" >/dev/null 2>&1; then
  echo "Environment promotion script incorrectly owns build -> aws-dev." >&2
  exit 1
fi

cp "${WORK_DIR}/aws-dev.original.yaml" "${WORK_DIR}/invalid-digest.yaml"
python3 - "${WORK_DIR}/invalid-digest.yaml" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
path.write_text(re.sub(
    r'(?m)^(  digest:) "sha256:[0-9a-f]{64}"$',
    r'\1 "sha256:invalid"',
    path.read_text(),
))
PY

if SOURCE_ENVIRONMENT=aws-dev \
  TARGET_ENVIRONMENT=aws-test \
  SOURCE_RELEASE_FILE="${WORK_DIR}/invalid-digest.yaml" \
  TARGET_RELEASE_FILE="${WORK_DIR}/aws-test.yaml" \
    "${PROMOTION_SCRIPT}" >/dev/null 2>&1; then
  echo "Promotion script accepted an invalid source image digest." >&2
  exit 1
fi

if SOURCE_ENVIRONMENT=aws-dev \
  TARGET_ENVIRONMENT=aws-test \
  SOURCE_RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
  TARGET_RELEASE_FILE="${WORK_DIR}/aws-test.yaml" \
  EXPECTED_SOURCE_RELEASE_SHA256="$(printf '0%.0s' {1..64})" \
    "${PROMOTION_SCRIPT}" >/dev/null 2>&1; then
  echo "Promotion script accepted a stale source release snapshot." >&2
  exit 1
fi

python3 - \
  "${PROMOTION_WORKFLOW}" \
  "${PUBLISH_WORKFLOW}" <<'PY'
from pathlib import Path
import re
import sys

promotion = Path(sys.argv[1]).read_text()
publish = Path(sys.argv[2]).read_text()

if "\n  workflow_dispatch:\n" not in promotion:
    raise SystemExit("Ordered promotion workflow must support manual dispatch")
if re.search(r"(?m)^  (push|pull_request|schedule):", promotion):
    raise SystemExit("Ordered promotion workflow must be manual-only")
if "source_environment:" not in promotion or "target_environment:" not in promotion:
    raise SystemExit("Ordered promotion workflow must require source and target inputs")
for environment in ("build", "aws-dev", "aws-test", "aws-prod"):
    if f"          - {environment}" not in promotion:
        raise SystemExit(f"Ordered promotion input options omit {environment}")

required_fragments = (
    "group: demo-api-environment-promotion-${{ inputs.target_environment }}",
    "cancel-in-progress: false",
    "BASE_BRANCH: main",
    "ref: main",
    "packages: read",
    "pull-requests: write",
    "./scripts/promote-demo-api-release.sh",
    'git show "origin/${BASE_BRANCH}:${source_release_path}"',
    'docker buildx imagetools inspect "${IMAGE_REFERENCE}"',
    "main changed while promotion was being prepared",
    "main changed before PR creation",
    "Promotion branch must differ from main only in ${TARGET_RELEASE_PATH}",
    "gh pr create",
)
for fragment in required_fragments:
    if fragment not in promotion:
        raise SystemExit(f"Ordered promotion workflow is missing contract: {fragment}")

if re.search(
    r"(?im)\b(kubectl|aws\s+eks|update-kubeconfig|configure-aws-credentials|argocd)\b",
    promotion,
):
    raise SystemExit("Ordered promotion workflow must not access Argo CD, Kubernetes, or EKS")
if re.search(r"(?im)\bgh\s+pr\s+merge\b", promotion):
    raise SystemExit("Ordered promotion workflow must never merge its own PR")
if "values/environments/${TARGET_ENVIRONMENT}.yaml" not in promotion:
    raise SystemExit("Target environment values must be rendered but never promoted")
if "values/releases/${TARGET_ENVIRONMENT}.yaml" not in promotion:
    raise SystemExit("Target release file must be the only promotion output")

if "branches:\n      - main" not in publish:
    raise SystemExit("Image publish workflow must retain main as the build source")
if "name: Create aws-dev promotion PR" not in publish:
    raise SystemExit("Image publish workflow must retain build -> aws-dev")
if "apps/demo-api/helm/values/releases/aws-dev.yaml" not in publish:
    raise SystemExit("build -> aws-dev must target only the aws-dev release file")
if "apps/demo-api/helm/values/releases/aws-test.yaml" in publish or \
        "apps/demo-api/helm/values/releases/aws-prod.yaml" in publish:
    raise SystemExit("Image build workflow must not skip directly to test or prod")

print("demo-api ordered promotion workflow contract passed.")
PY

echo "demo-api promotion behavior passed."

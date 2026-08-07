#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOSITORY_DIR="${REPOSITORY_DIR:-${SCRIPT_ROOT}}"
ROLLBACK_TO_REVISION="${ROLLBACK_TO_REVISION:-}"
ROLLBACK_BASE_REVISION="${ROLLBACK_BASE_REVISION:-HEAD}"
VALUES_PATH="${VALUES_PATH:-apps/demo-api/helm/values/releases/aws-dev.yaml}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-SterlingAureum/startup-devops-baseline}"

for command in git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ -z "${ROLLBACK_TO_REVISION}" ]]; then
  echo "ROLLBACK_TO_REVISION is required." >&2
  exit 1
fi

if [[ "${VALUES_PATH}" == /* || \
      "${VALUES_PATH}" == ".." || \
      "${VALUES_PATH}" == ../* || \
      "${VALUES_PATH}" == */../* || \
      "${VALUES_PATH}" == */.. ]]; then
  echo "VALUES_PATH must be a repository-relative path without '..'." >&2
  exit 1
fi

git -C "${REPOSITORY_DIR}" rev-parse --is-inside-work-tree \
  >/dev/null 2>&1 || {
  echo "REPOSITORY_DIR is not a Git work tree: ${REPOSITORY_DIR}" >&2
  exit 1
}

TARGET_REVISION="$(
  git -C "${REPOSITORY_DIR}" rev-parse \
    --verify "${ROLLBACK_TO_REVISION}^{commit}"
)" || {
  echo "Could not resolve rollback target ${ROLLBACK_TO_REVISION}." >&2
  exit 1
}

BASE_REVISION="$(
  git -C "${REPOSITORY_DIR}" rev-parse \
    --verify "${ROLLBACK_BASE_REVISION}^{commit}"
)" || {
  echo "Could not resolve rollback base ${ROLLBACK_BASE_REVISION}." >&2
  exit 1
}

if ! git -C "${REPOSITORY_DIR}" merge-base --is-ancestor \
  "${TARGET_REVISION}" "${BASE_REVISION}"; then
  echo "Rollback target must be contained in the selected base history." >&2
  exit 1
fi

git -C "${REPOSITORY_DIR}" cat-file -e \
  "${TARGET_REVISION}:${VALUES_PATH}" 2>/dev/null || {
  echo "${VALUES_PATH} is missing from rollback target ${TARGET_REVISION}." >&2
  exit 1
}

TARGET_PARENT="$(
  git -C "${REPOSITORY_DIR}" rev-parse "${TARGET_REVISION}^1"
)" || {
  echo "Rollback target must have a parent commit." >&2
  exit 1
}

mapfile -t TARGET_FILES < <(
  git -C "${REPOSITORY_DIR}" diff \
    --name-only \
    "${TARGET_PARENT}" \
    "${TARGET_REVISION}"
)
if (( ${#TARGET_FILES[@]} != 1 )) || \
   [[ "${TARGET_FILES[0]}" != "${VALUES_PATH}" ]]; then
  echo "Rollback target must change only ${VALUES_PATH}." >&2
  printf 'Rollback target file: %s\n' "${TARGET_FILES[@]}" >&2
  exit 1
fi

mapfile -t TARGET_VALUES < <(
  git -C "${REPOSITORY_DIR}" show "${TARGET_REVISION}:${VALUES_PATH}" |
    python3 -c '
import json
import sys

section = None
values = {}
for raw in sys.stdin:
    line = raw.rstrip("\n")
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if not line.startswith(" ") and stripped.endswith(":"):
        section = stripped[:-1]
        continue
    if section is None or not line.startswith("  ") or ":" not in stripped:
        continue
    key, value = stripped.split(":", 1)
    value = value.strip()
    if value.startswith("\"") and value.endswith("\""):
        value = json.loads(value)
    elif value.startswith(chr(39)) and value.endswith(chr(39)):
        value = value[1:-1].replace(chr(39) * 2, chr(39))
    values[(section, key)] = value

for field in (
    ("image", "repository"),
    ("image", "tag"),
    ("image", "digest"),
    ("release", "applicationVersion"),
    ("delivery", "sourceRepository"),
    ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
):
    print(values.get(field, ""))
'
)

if (( ${#TARGET_VALUES[@]} != 7 )); then
  echo "Could not parse the rollback delivery identity." >&2
  exit 1
fi

IMAGE_REPOSITORY="${TARGET_VALUES[0]}"
IMAGE_TAG="${TARGET_VALUES[1]}"
IMAGE_DIGEST="${TARGET_VALUES[2]}"
APP_VERSION="${TARGET_VALUES[3]}"
SOURCE_REPOSITORY="${TARGET_VALUES[4]}"
SOURCE_COMMIT="${TARGET_VALUES[5]}"
WORKFLOW_RUN_ID="${TARGET_VALUES[6]}"

if [[ -z "${IMAGE_REPOSITORY}" || \
      ! "${IMAGE_TAG}" =~ ^sha-[0-9a-f]{7}$ || \
      ! "${IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ || \
      "${APP_VERSION}" != "${IMAGE_TAG}" || \
      "${SOURCE_REPOSITORY}" != "${EXPECTED_SOURCE_REPOSITORY}" || \
      ! "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ || \
      "${IMAGE_TAG}" != "sha-${SOURCE_COMMIT:0:7}" || \
      -z "${WORKFLOW_RUN_ID}" ]]; then
  echo "Rollback target does not satisfy the delivery identity contract." >&2
  exit 1
fi

git -C "${REPOSITORY_DIR}" cat-file -e \
  "${SOURCE_COMMIT}^{commit}" 2>/dev/null || {
  echo "Rollback source commit ${SOURCE_COMMIT} is not available." >&2
  exit 1
}

VALUES_FILE="${REPOSITORY_DIR}/${VALUES_PATH}"
mkdir -p "$(dirname "${VALUES_FILE}")"
git -C "${REPOSITORY_DIR}" show \
  "${TARGET_REVISION}:${VALUES_PATH}" > "${VALUES_FILE}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "target-revision=${TARGET_REVISION}"
    echo "image-repository=${IMAGE_REPOSITORY}"
    echo "image-tag=${IMAGE_TAG}"
    echo "image-digest=${IMAGE_DIGEST}"
    echo "source-repository=${SOURCE_REPOSITORY}"
    echo "source-commit=${SOURCE_COMMIT}"
    echo "workflow-run-id=${WORKFLOW_RUN_ID}"
    echo "values-file=${VALUES_PATH}"
  } >> "${GITHUB_OUTPUT}"
fi

echo "Prepared demo-api GitOps rollback:"
echo "  desired_state_commit=${TARGET_REVISION}"
echo "  source=${SOURCE_REPOSITORY}@${SOURCE_COMMIT}"
echo "  image=${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"
echo "  values=${VALUES_PATH}"

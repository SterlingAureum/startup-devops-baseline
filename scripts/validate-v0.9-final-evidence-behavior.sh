#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d "${ROOT_DIR}/.v096-evidence.XXXXXX")"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

DIGEST="sha256:$(printf 'a%.0s' {1..64})"
SOURCE_COMMIT="$(printf 'b%.0s' {1..40})"
REPOSITORY_REVISION="$(printf 'c%.0s' {1..40})"
IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api"

write_fixture() {
  local path="$1"
  local schema="$2"
  local environment="$3"
  local recorded_at="$4"
  mkdir -p "$(dirname "${path}")"
  jq -n \
    --arg schema "${schema}" \
    --arg environment "${environment}" \
    --arg repository "${IMAGE_REPOSITORY}" \
    --arg digest "${DIGEST}" \
    --arg source "${SOURCE_COMMIT}" \
    --arg recorded_at "${recorded_at}" '
      {
        schemaVersion: $schema,
        environment: $environment,
        status: "passed",
        release: {
          imageRepository: $repository,
          imageDigest: $digest,
          sourceCommit: $source,
          applicationVersion: ("sha-" + ($source[0:7]))
        },
        qualification: (if $schema == "v0.9.4" then {recordedAt: $recorded_at} else null end),
        runtime: (if $schema == "v0.9.5" then {recordedAt: $recorded_at} else null end)
      }
    ' >"${path}"
}

write_fixture "${WORK_DIR}/dev-runtime.json" "v0.9.5" "aws-dev" "2026-08-07T00:30:00Z"
write_fixture "${WORK_DIR}/test-release.json" "v0.9.4" "aws-test" "2026-08-07T00:40:00Z"
write_fixture "${WORK_DIR}/test-runtime.json" "v0.9.5" "aws-test" "2026-08-07T00:50:00Z"

FINAL_FILE="${WORK_DIR}/final.json"
EVIDENCE_ID="20260807010000" \
EVIDENCE_ACTOR="SterlingAureum" \
REPOSITORY_REVISION="${REPOSITORY_REVISION}" \
RECORDED_AT="2026-08-07T01:30:00Z" \
DEV_RUNTIME_EVIDENCE_FILE="${WORK_DIR}/dev-runtime.json" \
TEST_RELEASE_EVIDENCE_FILE="${WORK_DIR}/test-release.json" \
TEST_RUNTIME_EVIDENCE_FILE="${WORK_DIR}/test-runtime.json" \
FAILOVER_COMPLETED_AT="2026-08-07T01:00:00Z" \
TEST_DESTROY_COMPLETED_AT="2026-08-07T01:10:00Z" \
COST_AUDIT_COMPLETED_AT="2026-08-07T01:20:00Z" \
OUTPUT_FILE="${FINAL_FILE}" \
  "${ROOT_DIR}/scripts/write-v0.9-final-evidence.sh" >/dev/null

EVIDENCE_FILE="${FINAL_FILE}" \
  "${ROOT_DIR}/scripts/validate-v0.9-final-evidence.sh" >/dev/null

jq '.status = "failed"' "${WORK_DIR}/test-runtime.json" \
  >"${WORK_DIR}/test-runtime-tampered.json"
mv "${WORK_DIR}/test-runtime-tampered.json" "${WORK_DIR}/test-runtime.json"

if EVIDENCE_FILE="${FINAL_FILE}" \
     "${ROOT_DIR}/scripts/validate-v0.9-final-evidence.sh" >/dev/null 2>&1; then
  echo "Final evidence validator accepted a tampered referenced record." >&2
  exit 1
fi

echo "v0.9 final evidence behavior passed."

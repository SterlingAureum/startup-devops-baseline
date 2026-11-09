#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_TRIVY_VERSION="${EXPECTED_TRIVY_VERSION:-0.74.0}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"

for command in awk jq trivy; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

actual_trivy_version="$(trivy --version | awk '/^Version:/ {print $2; exit}')"
if [[ "${actual_trivy_version}" != "${EXPECTED_TRIVY_VERSION}" ]]; then
  echo "Expected Trivy ${EXPECTED_TRIVY_VERSION}, found ${actual_trivy_version:-unknown}." >&2
  exit 1
fi

if [[ -z "${IMAGE_REFERENCE:-}" ]]; then
  evidence_file="${FINAL_EVIDENCE_FILE:-}"
  if [[ -z "${evidence_file}" ]]; then
    evidence_file="$({
      find "${ROOT_DIR}/evidence/v0.10/final" \
        -maxdepth 1 -type f -name '*.json' -print 2>/dev/null || true
    } | sort | tail -n 1)"
  fi
  [[ -n "${evidence_file}" && -f "${evidence_file}" ]] || {
    echo "No final evidence file found; set IMAGE_REFERENCE explicitly." >&2
    exit 1
  }
  image_digest="$(jq --exit-status --raw-output '.release.imageDigest' "${evidence_file}")"
  [[ "${image_digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "Final evidence contains an invalid image digest." >&2
    exit 1
  }
  IMAGE_REFERENCE="${IMAGE_REPOSITORY}@${image_digest}"
fi

printf 'Scanning immutable demo-api image: %s\n' "${IMAGE_REFERENCE}"
trivy image \
  --scanners vuln \
  --pkg-types os,library \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1 \
  "${IMAGE_REFERENCE}"

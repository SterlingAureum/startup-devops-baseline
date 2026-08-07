#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash cmp cp git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

WRITER="${ROOT_DIR}/scripts/write-demo-api-release-evidence.sh"
VALIDATOR="${ROOT_DIR}/scripts/validate-demo-api-release-evidence.sh"
PROMOTION_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-promote-environment.yaml"
EVIDENCE_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-record-release-evidence.yaml"
ROLLBACK_WORKFLOW="${ROOT_DIR}/.github/workflows/demo-api-rollback.yaml"
CODEOWNERS="${ROOT_DIR}/.github/CODEOWNERS"
RELEASES_DIR="${ROOT_DIR}/apps/demo-api/helm/values/releases"

echo "==> Validating release evidence behavior"
for environment in aws-dev aws-test; do
  release_file="${WORK_DIR}/${environment}.yaml"
  evidence_file="${WORK_DIR}/${environment}-424242.json"
  cp "${RELEASES_DIR}/${environment}.yaml" "${release_file}"

  ENVIRONMENT="${environment}" \
  RELEASE_FILE="${release_file}" \
  OUTPUT_FILE="${evidence_file}" \
  VALIDATED_REPOSITORY_REVISION="$(printf 'a%.0s' {1..40})" \
  EVIDENCE_RUN_ID="424242" \
  EVIDENCE_RUN_ATTEMPT="2" \
  EVIDENCE_ACTOR="SterlingAureum" \
    "${WRITER}" >/dev/null

  EXPECTED_ENVIRONMENT="${environment}" \
  EXPECTED_EVIDENCE_RUN_ID="424242" \
  EVIDENCE_FILE="${evidence_file}" \
  RELEASE_FILE="${release_file}" \
    "${VALIDATOR}" >/dev/null
done

if EXPECTED_ENVIRONMENT="aws-test" \
  EXPECTED_EVIDENCE_RUN_ID="424242" \
  EVIDENCE_FILE="${WORK_DIR}/aws-dev-424242.json" \
  RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
    "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Evidence validator accepted the wrong source environment." >&2
  exit 1
fi

if EXPECTED_ENVIRONMENT="aws-dev" \
  EXPECTED_EVIDENCE_RUN_ID="999999" \
  EVIDENCE_FILE="${WORK_DIR}/aws-dev-424242.json" \
  RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
    "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Evidence validator accepted the wrong workflow run ID." >&2
  exit 1
fi

printf '\n# stale source release\n' >> "${WORK_DIR}/aws-dev.yaml"
if EXPECTED_ENVIRONMENT="aws-dev" \
  EXPECTED_EVIDENCE_RUN_ID="424242" \
  EVIDENCE_FILE="${WORK_DIR}/aws-dev-424242.json" \
  RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
    "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Evidence validator accepted a changed source release." >&2
  exit 1
fi

cp "${RELEASES_DIR}/aws-dev.yaml" "${WORK_DIR}/aws-dev.yaml"
python3 - "${WORK_DIR}/aws-dev-424242.json" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
document = json.loads(path.read_text())
document["status"] = "failed"
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
PY
if EXPECTED_ENVIRONMENT="aws-dev" \
  EXPECTED_EVIDENCE_RUN_ID="424242" \
  EVIDENCE_FILE="${WORK_DIR}/aws-dev-424242.json" \
  RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
    "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Evidence validator accepted a non-passing record." >&2
  exit 1
fi

ENVIRONMENT="aws-dev" \
RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
OUTPUT_FILE="${WORK_DIR}/identity-tampered.json" \
VALIDATED_REPOSITORY_REVISION="$(printf 'c%.0s' {1..40})" \
EVIDENCE_RUN_ID="616161" \
EVIDENCE_RUN_ATTEMPT="1" \
EVIDENCE_ACTOR="SterlingAureum" \
  "${WRITER}" >/dev/null
python3 - "${WORK_DIR}/identity-tampered.json" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
document = json.loads(path.read_text())
document["release"]["imageDigest"] = "sha256:" + "9" * 64
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
PY
if EXPECTED_ENVIRONMENT="aws-dev" \
  EXPECTED_EVIDENCE_RUN_ID="616161" \
  EVIDENCE_FILE="${WORK_DIR}/identity-tampered.json" \
  RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
    "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Evidence validator accepted identity fields that differ from the source release." >&2
  exit 1
fi

ENVIRONMENT="aws-dev" \
RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
OUTPUT_FILE="${WORK_DIR}/expired.json" \
VALIDATED_REPOSITORY_REVISION="$(printf 'b%.0s' {1..40})" \
EVIDENCE_RUN_ID="515151" \
EVIDENCE_RUN_ATTEMPT="1" \
EVIDENCE_ACTOR="SterlingAureum" \
RECORDED_AT="2000-01-01T00:00:00Z" \
  "${WRITER}" >/dev/null
if EXPECTED_ENVIRONMENT="aws-dev" \
  EXPECTED_EVIDENCE_RUN_ID="515151" \
  EVIDENCE_FILE="${WORK_DIR}/expired.json" \
  RELEASE_FILE="${WORK_DIR}/aws-dev.yaml" \
  EVIDENCE_MAX_AGE_SECONDS="604800" \
    "${VALIDATOR}" >/dev/null 2>&1; then
  echo "Evidence validator accepted an expired record." >&2
  exit 1
fi

echo "==> Validating environment-scoped rollback behavior"
ROLLBACK_REPOSITORY="${WORK_DIR}/rollback-repository"
mkdir -p "${ROLLBACK_REPOSITORY}/apps/demo-api/helm/values/releases"
for environment in aws-dev aws-test aws-prod; do
  cp \
    "${RELEASES_DIR}/${environment}.yaml" \
    "${ROLLBACK_REPOSITORY}/apps/demo-api/helm/values/releases/${environment}.yaml"
done
git -C "${ROLLBACK_REPOSITORY}" init --quiet --initial-branch=main
git -C "${ROLLBACK_REPOSITORY}" config user.name "governance-gates"
git -C "${ROLLBACK_REPOSITORY}" config user.email "governance-gates@example.invalid"
git -C "${ROLLBACK_REPOSITORY}" add .
git -C "${ROLLBACK_REPOSITORY}" commit --quiet -m "test: rollback baseline"

for environment in aws-dev aws-test aws-prod; do
  values_path="apps/demo-api/helm/values/releases/${environment}.yaml"
  values_file="${ROLLBACK_REPOSITORY}/${values_path}"
  source_commit_a="$(git -C "${ROLLBACK_REPOSITORY}" rev-parse HEAD)"
  digest_a="sha256:$(printf '3%.0s' {1..64})"

  VALUES_FILE="${values_file}" \
  IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
  IMAGE_TAG="sha-${source_commit_a:0:7}" \
  IMAGE_DIGEST="${digest_a}" \
  APP_VERSION="sha-${source_commit_a:0:7}" \
    "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null
  VALUES_FILE="${values_file}" \
  SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
  SOURCE_COMMIT="${source_commit_a}" \
  WORKFLOW_RUN_ID="rollback-${environment}-a" \
    "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null
  git -C "${ROLLBACK_REPOSITORY}" add "${values_path}"
  git -C "${ROLLBACK_REPOSITORY}" commit --quiet -m "release: ${environment} fixture A"
  rollback_target="$(git -C "${ROLLBACK_REPOSITORY}" rev-parse HEAD)"

  source_commit_b="${rollback_target}"
  digest_b="sha256:$(printf '4%.0s' {1..64})"
  VALUES_FILE="${values_file}" \
  IMAGE_REPOSITORY="ghcr.io/sterlingaureum/startup-devops-baseline/demo-api" \
  IMAGE_TAG="sha-${source_commit_b:0:7}" \
  IMAGE_DIGEST="${digest_b}" \
  APP_VERSION="sha-${source_commit_b:0:7}" \
    "${ROOT_DIR}/scripts/set-demo-api-image.sh" >/dev/null
  VALUES_FILE="${values_file}" \
  SOURCE_REPOSITORY="SterlingAureum/startup-devops-baseline" \
  SOURCE_COMMIT="${source_commit_b}" \
  WORKFLOW_RUN_ID="rollback-${environment}-b" \
    "${ROOT_DIR}/scripts/set-demo-api-delivery-metadata.sh" >/dev/null
  git -C "${ROLLBACK_REPOSITORY}" add "${values_path}"
  git -C "${ROLLBACK_REPOSITORY}" commit --quiet -m "release: ${environment} fixture B"

  REPOSITORY_DIR="${ROLLBACK_REPOSITORY}" \
  ROLLBACK_TO_REVISION="${rollback_target}" \
  VALUES_PATH="${values_path}" \
    "${ROOT_DIR}/scripts/prepare-demo-api-rollback.sh" >/dev/null

  git -C "${ROLLBACK_REPOSITORY}" show "${rollback_target}:${values_path}" |
    cmp --silent - "${values_file}" || {
      echo "Rollback did not restore ${environment} exactly." >&2
      exit 1
    }
  mapfile -t changed_files < <(git -C "${ROLLBACK_REPOSITORY}" diff --name-only)
  if [[ "${#changed_files[@]}" != "1" || "${changed_files[0]}" != "${values_path}" ]]; then
    echo "Rollback escaped the ${environment} release boundary." >&2
    exit 1
  fi
  git -C "${ROLLBACK_REPOSITORY}" restore --source HEAD -- "${values_path}"
done

echo "==> Validating workflow and approval contracts"
python3 - \
  "${PROMOTION_WORKFLOW}" \
  "${EVIDENCE_WORKFLOW}" \
  "${ROLLBACK_WORKFLOW}" \
  "${CODEOWNERS}" <<'PY'
from pathlib import Path
import re
import sys

promotion, evidence, rollback, codeowners = [Path(path).read_text() for path in sys.argv[1:]]

for name, workflow in (
    ("promotion", promotion),
    ("evidence", evidence),
    ("rollback", rollback),
):
    if "\n  workflow_dispatch:\n" not in workflow:
        raise SystemExit(f"{name} workflow must support manual dispatch")
    if re.search(r"(?m)^  (push|pull_request|schedule|workflow_run):", workflow):
        raise SystemExit(f"{name} workflow must remain manual-only")
    if re.search(
        r"(?im)\b(kubectl|aws\s+eks|update-kubeconfig|configure-aws-credentials|argocd)\b",
        workflow,
    ):
        raise SystemExit(f"{name} workflow must not access Argo CD, Kubernetes, or EKS")
    if re.search(r"(?im)\bgh\s+pr\s+merge\b", workflow):
        raise SystemExit(f"{name} workflow must never merge its own PR")

for fragment in (
    "evidence_run_id:",
    "runtime_evidence_id:",
    "name: ${{ inputs.target_environment }}",
    "deployment: false",
    "./scripts/validate-demo-api-release-evidence.sh",
    "evidence/demo-api/${SOURCE_ENVIRONMENT}/${EVIDENCE_RUN_ID}.json",
    "evidence/demo-api/runtime/${SOURCE_ENVIRONMENT}/${RUNTIME_EVIDENCE_ID}.json",
    "Reviewed release evidence is missing from main",
    "Reviewed AWS runtime evidence is missing from main",
    "./scripts/validate-demo-api-runtime-evidence.sh",
):
    if fragment not in promotion:
        raise SystemExit(f"Promotion governance is missing: {fragment}")

for fragment in (
    "name: ${{ inputs.environment }}",
    "deployment: false",
    "./scripts/write-demo-api-release-evidence.sh",
    "./scripts/validate-demo-api-release-evidence.sh",
    'docker buildx imagetools inspect "${image_reference}"',
    "Evidence branch may add only ${EVIDENCE_FILE}",
    "separate v0.9.5 AWS runtime evidence",
):
    if fragment not in evidence:
        raise SystemExit(f"Evidence workflow is missing: {fragment}")

for fragment in (
    "target_environment:",
    "name: ${{ inputs.target_environment }}",
    "deployment: false",
    "group: demo-api-environment-rollback-${{ inputs.target_environment }}",
    "values/releases/${TARGET_ENVIRONMENT}.yaml",
    'docker buildx imagetools inspect "${IMAGE_REFERENCE}"',
    "main changed while rollback was being prepared",
    "Rollback branch must differ from main only in ${VALUES_PATH}",
):
    if fragment not in rollback:
        raise SystemExit(f"Rollback governance is missing: {fragment}")
for environment in ("aws-dev", "aws-test", "aws-prod"):
    if f"          - {environment}" not in rollback:
        raise SystemExit(f"Rollback workflow omits {environment}")

for path in (
    "/apps/demo-api/helm/values/releases/ @SterlingAureum",
    "/evidence/demo-api/ @SterlingAureum",
    "/.github/CODEOWNERS @SterlingAureum",
    "/.github/workflows/demo-api-*.yaml @SterlingAureum",
    "/scripts/record-demo-api-runtime-evidence-aws.sh @SterlingAureum",
    "/scripts/write-demo-api-runtime-evidence.sh @SterlingAureum",
    "/scripts/validate-demo-api-runtime-evidence.sh @SterlingAureum",
):
    if path not in codeowners:
        raise SystemExit(f"CODEOWNERS is missing protected path: {path}")

print("demo-api promotion governance contracts passed.")
PY

echo "demo-api promotion governance behavior passed."

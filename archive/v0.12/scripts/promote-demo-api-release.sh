#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ENVIRONMENT="${SOURCE_ENVIRONMENT:-}"
TARGET_ENVIRONMENT="${TARGET_ENVIRONMENT:-}"
EXPECTED_SOURCE_RELEASE_SHA256="${EXPECTED_SOURCE_RELEASE_SHA256:-}"
EXPECTED_IMAGE_REPOSITORY="${EXPECTED_IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-SterlingAureum/startup-devops-baseline}"

for command in python3 realpath; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

case "${SOURCE_ENVIRONMENT}->${TARGET_ENVIRONMENT}" in
  aws-dev-\>aws-test|aws-test-\>aws-prod)
    ;;
  build-\>aws-dev)
    echo "build -> aws-dev is owned by demo-api-image-publish.yaml, not the environment promotion script." >&2
    exit 1
    ;;
  *)
    echo "Rejected demo-api promotion edge: ${SOURCE_ENVIRONMENT:-<empty>} -> ${TARGET_ENVIRONMENT:-<empty>}" >&2
    exit 1
    ;;
esac

SOURCE_RELEASE_FILE="${SOURCE_RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/${SOURCE_ENVIRONMENT}.yaml}"
TARGET_RELEASE_FILE="${TARGET_RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/${TARGET_ENVIRONMENT}.yaml}"

if [[ ! -f "${SOURCE_RELEASE_FILE}" ]]; then
  echo "Source release file not found: ${SOURCE_RELEASE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${TARGET_RELEASE_FILE}" ]]; then
  echo "Target release file not found: ${TARGET_RELEASE_FILE}" >&2
  exit 1
fi

if [[ "$(realpath "${SOURCE_RELEASE_FILE}")" == "$(realpath "${TARGET_RELEASE_FILE}")" ]]; then
  echo "Source and target release files must be different." >&2
  exit 1
fi

python3 - \
  "${SOURCE_RELEASE_FILE}" \
  "${TARGET_RELEASE_FILE}" \
  "${EXPECTED_SOURCE_RELEASE_SHA256}" \
  "${EXPECTED_IMAGE_REPOSITORY}" \
  "${EXPECTED_SOURCE_REPOSITORY}" \
  "${GITHUB_OUTPUT:-}" <<'PY'
from pathlib import Path
import hashlib
import json
import re
import sys

source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
expected_source_sha256 = sys.argv[3]
expected_image_repository = sys.argv[4]
expected_source_repository = sys.argv[5]
github_output = sys.argv[6]

expected_fields = {
    ("image", "repository"),
    ("image", "tag"),
    ("image", "digest"),
    ("release", "applicationVersion"),
    ("delivery", "sourceRepository"),
    ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
}


def decode_scalar(raw):
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def read_release(path):
    values = {}
    sections = set()
    section = None
    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            if section in sections:
                raise ValueError(f"{path}:{line_number}: duplicate section {section}")
            sections.add(section)
            continue
        if indent == 2 and section and ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            field = (section, key)
            if field in values:
                raise ValueError(f"{path}:{line_number}: duplicate field {section}.{key}")
            values[field] = decode_scalar(raw_value)
            continue
        raise ValueError(f"{path}:{line_number}: unsupported release values structure")

    if sections != {"image", "release", "delivery"}:
        raise ValueError(f"{path}: only image, release, and delivery sections are allowed")
    if set(values) != expected_fields:
        missing = sorted(expected_fields - set(values))
        extra = sorted(set(values) - expected_fields)
        raise ValueError(f"{path}: release schema mismatch; missing={missing}, extra={extra}")
    return values


def validate_identity(path, values):
    repository = values[("image", "repository")]
    tag = values[("image", "tag")]
    digest = values[("image", "digest")]
    application_version = values[("release", "applicationVersion")]
    source_repository = values[("delivery", "sourceRepository")]
    source_commit = values[("delivery", "sourceCommit")]
    workflow_run_id = values[("delivery", "workflowRunId")]

    if repository != expected_image_repository:
        raise ValueError(f"{path}: unexpected image repository")
    if source_repository != expected_source_repository:
        raise ValueError(f"{path}: unexpected source repository")
    if not re.fullmatch(r"sha-[0-9a-f]{7}", tag):
        raise ValueError(f"{path}: invalid image tag")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"{path}: invalid image digest")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError(f"{path}: invalid source commit")
    if tag != f"sha-{source_commit[:7]}" or application_version != tag:
        raise ValueError(f"{path}: readable identities are inconsistent")
    if not workflow_run_id:
        raise ValueError(f"{path}: workflowRunId is empty")


source_bytes = source_path.read_bytes()
source_sha256 = hashlib.sha256(source_bytes).hexdigest()
if expected_source_sha256:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
        raise SystemExit("EXPECTED_SOURCE_RELEASE_SHA256 must be a lowercase SHA-256 value.")
    if source_sha256 != expected_source_sha256:
        raise SystemExit("Source release is stale: its content no longer matches the captured main state.")

try:
    source = read_release(source_path)
    target = read_release(target_path)
    validate_identity(source_path, source)
    validate_identity(target_path, target)
except ValueError as error:
    raise SystemExit(str(error)) from error

ordered_fields = (
    ("image", "repository"),
    ("image", "tag"),
    ("image", "digest"),
    ("release", "applicationVersion"),
    ("delivery", "sourceRepository"),
    ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
)
lines = []
active_section = None
for section, key in ordered_fields:
    if section != active_section:
        if lines:
            lines.append("")
        lines.append(f"{section}:")
        active_section = section
    value = source[(section, key)]
    rendered = value if (section, key) == ("image", "repository") else json.dumps(value)
    lines.append(f"  {key}: {rendered}")

target_path.write_text("\n".join(lines) + "\n")

try:
    promoted = read_release(target_path)
    validate_identity(target_path, promoted)
except ValueError as error:
    raise SystemExit(str(error)) from error

if promoted != source:
    raise SystemExit("Target release identity differs from the source after promotion.")
if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha256:
    raise SystemExit("Source release file changed during promotion.")

outputs = {
    "image-repository": source[("image", "repository")],
    "image-tag": source[("image", "tag")],
    "image-digest": source[("image", "digest")],
    "image-reference": (
        f'{source[("image", "repository")]}@{source[("image", "digest")]}'
    ),
    "source-repository": source[("delivery", "sourceRepository")],
    "source-commit": source[("delivery", "sourceCommit")],
    "workflow-run-id": source[("delivery", "workflowRunId")],
    "source-release-sha256": source_sha256,
}
if github_output:
    with Path(github_output).open("a") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")

print("Prepared ordered demo-api environment promotion:")
print(f"  source={source_path}")
print(f"  target={target_path}")
print(f"  image={outputs['image-reference']}")
print(f"  source_commit={outputs['source-commit']}")
PY

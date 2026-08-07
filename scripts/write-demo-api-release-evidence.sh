#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${ENVIRONMENT:-}"
RELEASE_FILE="${RELEASE_FILE:-}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
VALIDATED_REPOSITORY_REVISION="${VALIDATED_REPOSITORY_REVISION:-}"
EVIDENCE_RUN_ID="${EVIDENCE_RUN_ID:-}"
EVIDENCE_RUN_ATTEMPT="${EVIDENCE_RUN_ATTEMPT:-1}"
EVIDENCE_ACTOR="${EVIDENCE_ACTOR:-}"
RECORDED_AT="${RECORDED_AT:-}"
EXPECTED_IMAGE_REPOSITORY="${EXPECTED_IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-SterlingAureum/startup-devops-baseline}"

for command in python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

case "${ENVIRONMENT}" in
  aws-dev|aws-test)
    ;;
  *)
    echo "Release qualification evidence is allowed only for aws-dev or aws-test." >&2
    exit 1
    ;;
esac

RELEASE_FILE="${RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/${ENVIRONMENT}.yaml}"
OUTPUT_FILE="${OUTPUT_FILE:-${ROOT_DIR}/evidence/demo-api/${ENVIRONMENT}/${EVIDENCE_RUN_ID}.json}"

if [[ ! -f "${RELEASE_FILE}" ]]; then
  echo "Release file not found: ${RELEASE_FILE}" >&2
  exit 1
fi

python3 - \
  "${RELEASE_FILE}" \
  "${OUTPUT_FILE}" \
  "${ENVIRONMENT}" \
  "${VALIDATED_REPOSITORY_REVISION}" \
  "${EVIDENCE_RUN_ID}" \
  "${EVIDENCE_RUN_ATTEMPT}" \
  "${EVIDENCE_ACTOR}" \
  "${RECORDED_AT}" \
  "${EXPECTED_IMAGE_REPOSITORY}" \
  "${EXPECTED_SOURCE_REPOSITORY}" \
  "${GITHUB_OUTPUT:-}" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys

(
    release_path,
    output_path,
    environment,
    repository_revision,
    run_id,
    run_attempt,
    actor,
    recorded_at,
    expected_image_repository,
    expected_source_repository,
    github_output,
) = sys.argv[1:]

release_path = Path(release_path)
output_path = Path(output_path)


def decode_scalar(raw):
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def read_release(path):
    values = {}
    section = None
    for line_number, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            continue
        if indent == 2 and section and ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            field = (section, key)
            if field in values:
                raise ValueError(f"{path}:{line_number}: duplicate field {section}.{key}")
            values[field] = decode_scalar(raw_value)
            continue
        raise ValueError(f"{path}:{line_number}: unsupported release values structure")
    return values


required_fields = {
    ("image", "repository"),
    ("image", "tag"),
    ("image", "digest"),
    ("release", "applicationVersion"),
    ("delivery", "sourceRepository"),
    ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
}

try:
    values = read_release(release_path)
except ValueError as error:
    raise SystemExit(str(error)) from error

if set(values) != required_fields:
    raise SystemExit("Release values do not satisfy the isolated release schema.")
if not re.fullmatch(r"[0-9a-f]{40}", repository_revision):
    raise SystemExit("VALIDATED_REPOSITORY_REVISION must be a full lowercase commit SHA.")
if not re.fullmatch(r"[0-9]+", run_id):
    raise SystemExit("EVIDENCE_RUN_ID must contain only decimal digits.")
if not re.fullmatch(r"[1-9][0-9]*", run_attempt):
    raise SystemExit("EVIDENCE_RUN_ATTEMPT must be a positive integer.")
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", actor):
    raise SystemExit("EVIDENCE_ACTOR is not a valid GitHub login.")

repository = values[("image", "repository")]
tag = values[("image", "tag")]
digest = values[("image", "digest")]
application_version = values[("release", "applicationVersion")]
source_repository = values[("delivery", "sourceRepository")]
source_commit = values[("delivery", "sourceCommit")]
build_run_id = values[("delivery", "workflowRunId")]

if repository != expected_image_repository:
    raise SystemExit("Release evidence rejected an unexpected image repository.")
if source_repository != expected_source_repository:
    raise SystemExit("Release evidence rejected an unexpected source repository.")
if not re.fullmatch(r"sha-[0-9a-f]{7}", tag):
    raise SystemExit("Release evidence rejected an invalid image tag.")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
    raise SystemExit("Release evidence rejected an invalid image digest.")
if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
    raise SystemExit("Release evidence rejected an invalid source commit.")
if tag != f"sha-{source_commit[:7]}" or application_version != tag:
    raise SystemExit("Release evidence rejected inconsistent readable identities.")
if not build_run_id:
    raise SystemExit("Release evidence requires the original build workflow identity.")

if recorded_at:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", recorded_at):
        raise SystemExit("RECORDED_AT must use UTC YYYY-MM-DDTHH:MM:SSZ format.")
    datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
else:
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

release_sha256 = hashlib.sha256(release_path.read_bytes()).hexdigest()
document = {
    "schemaVersion": "v0.9.4",
    "application": "demo-api",
    "environment": environment,
    "status": "passed",
    "release": {
        "path": f"apps/demo-api/helm/values/releases/{environment}.yaml",
        "sha256": release_sha256,
        "imageRepository": repository,
        "imageTag": tag,
        "imageDigest": digest,
        "applicationVersion": application_version,
        "sourceRepository": source_repository,
        "sourceCommit": source_commit,
        "buildWorkflowRunId": build_run_id,
    },
    "qualification": {
        "mode": "static-release-qualification",
        "checks": [
            "release-schema",
            "helm-lint",
            "helm-render",
            "immutable-artifact-exists",
        ],
        "repositoryRevision": repository_revision,
        "workflowRunId": run_id,
        "workflowRunAttempt": int(run_attempt),
        "actor": actor,
        "recordedAt": recorded_at,
    },
}

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
evidence_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()

if github_output:
    with Path(github_output).open("a") as output:
        output.write(f"evidence-file={output_path}\n")
        output.write(f"evidence-sha256={evidence_sha256}\n")
        output.write(f"source-release-sha256={release_sha256}\n")
        output.write(f"image-reference={repository}@{digest}\n")
        output.write(f"image-tag={tag}\n")
        output.write(f"image-digest={digest}\n")

print("Recorded demo-api release qualification evidence:")
print(f"  environment={environment}")
print(f"  release_sha256={release_sha256}")
print(f"  image={repository}@{digest}")
print(f"  evidence={output_path}")
PY

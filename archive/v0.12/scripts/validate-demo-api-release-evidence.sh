#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_ENVIRONMENT="${EXPECTED_ENVIRONMENT:-}"
EXPECTED_EVIDENCE_RUN_ID="${EXPECTED_EVIDENCE_RUN_ID:-}"
EVIDENCE_FILE="${EVIDENCE_FILE:-}"
RELEASE_FILE="${RELEASE_FILE:-}"
EVIDENCE_MAX_AGE_SECONDS="${EVIDENCE_MAX_AGE_SECONDS:-604800}"
EXPECTED_IMAGE_REPOSITORY="${EXPECTED_IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-SterlingAureum/startup-devops-baseline}"

case "${EXPECTED_ENVIRONMENT}" in
  aws-dev|aws-test)
    ;;
  *)
    echo "EXPECTED_ENVIRONMENT must be aws-dev or aws-test." >&2
    exit 1
    ;;
esac

if [[ ! "${EXPECTED_EVIDENCE_RUN_ID}" =~ ^[0-9]+$ ]]; then
  echo "EXPECTED_EVIDENCE_RUN_ID must contain only decimal digits." >&2
  exit 1
fi
if [[ ! "${EVIDENCE_MAX_AGE_SECONDS}" =~ ^[0-9]+$ ]]; then
  echo "EVIDENCE_MAX_AGE_SECONDS must be a non-negative integer." >&2
  exit 1
fi

EVIDENCE_FILE="${EVIDENCE_FILE:-${ROOT_DIR}/evidence/demo-api/${EXPECTED_ENVIRONMENT}/${EXPECTED_EVIDENCE_RUN_ID}.json}"
RELEASE_FILE="${RELEASE_FILE:-${ROOT_DIR}/apps/demo-api/helm/values/releases/${EXPECTED_ENVIRONMENT}.yaml}"

for file in "${EVIDENCE_FILE}" "${RELEASE_FILE}"; do
  if [[ ! -f "${file}" ]]; then
    echo "Required evidence input not found: ${file}" >&2
    exit 1
  fi
done

python3 - \
  "${EVIDENCE_FILE}" \
  "${RELEASE_FILE}" \
  "${EXPECTED_ENVIRONMENT}" \
  "${EXPECTED_EVIDENCE_RUN_ID}" \
  "${EVIDENCE_MAX_AGE_SECONDS}" \
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
    evidence_path,
    release_path,
    expected_environment,
    expected_run_id,
    max_age_seconds,
    expected_image_repository,
    expected_source_repository,
    github_output,
) = sys.argv[1:]

evidence_path = Path(evidence_path)
release_path = Path(release_path)
max_age_seconds = int(max_age_seconds)


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

try:
    evidence = json.loads(evidence_path.read_text())
except (json.JSONDecodeError, OSError) as error:
    raise SystemExit(f"Could not parse release evidence: {error}") from error

if set(evidence) != {
    "schemaVersion", "application", "environment", "status", "release", "qualification"
}:
    raise SystemExit("Release evidence top-level schema is not exact.")
if evidence["schemaVersion"] != "v0.9.4":
    raise SystemExit("Unsupported release evidence schema.")
if evidence["application"] != "demo-api" or evidence["status"] != "passed":
    raise SystemExit("Release evidence is not a passing demo-api qualification.")
if evidence["environment"] != expected_environment:
    raise SystemExit("Release evidence environment does not match the promotion source.")

release = evidence["release"]
qualification = evidence["qualification"]
if set(release) != {
    "path", "sha256", "imageRepository", "imageTag", "imageDigest",
    "applicationVersion", "sourceRepository", "sourceCommit", "buildWorkflowRunId"
}:
    raise SystemExit("Release evidence identity schema is not exact.")
if set(qualification) != {
    "mode", "checks", "repositoryRevision", "workflowRunId",
    "workflowRunAttempt", "actor", "recordedAt"
}:
    raise SystemExit("Release evidence qualification schema is not exact.")

expected_release_path = f"apps/demo-api/helm/values/releases/{expected_environment}.yaml"
if release["path"] != expected_release_path:
    raise SystemExit("Release evidence path does not match its environment.")
if release["sha256"] != hashlib.sha256(release_path.read_bytes()).hexdigest():
    raise SystemExit("Release evidence is stale for the current source release.")

try:
    current_release = read_release(release_path)
except ValueError as error:
    raise SystemExit(str(error)) from error
expected_release_fields = {
    ("image", "repository"),
    ("image", "tag"),
    ("image", "digest"),
    ("release", "applicationVersion"),
    ("delivery", "sourceRepository"),
    ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
}
if set(current_release) != expected_release_fields:
    raise SystemExit("Current source release does not satisfy the isolated release schema.")
evidence_identity = {
    ("image", "repository"): release["imageRepository"],
    ("image", "tag"): release["imageTag"],
    ("image", "digest"): release["imageDigest"],
    ("release", "applicationVersion"): release["applicationVersion"],
    ("delivery", "sourceRepository"): release["sourceRepository"],
    ("delivery", "sourceCommit"): release["sourceCommit"],
    ("delivery", "workflowRunId"): str(release["buildWorkflowRunId"]),
}
current_release[("delivery", "workflowRunId")] = str(
    current_release[("delivery", "workflowRunId")]
)
if evidence_identity != current_release:
    raise SystemExit("Release evidence identity differs from the current source release.")
if release["imageRepository"] != expected_image_repository:
    raise SystemExit("Release evidence contains an unexpected image repository.")
if release["sourceRepository"] != expected_source_repository:
    raise SystemExit("Release evidence contains an unexpected source repository.")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", release["imageDigest"]):
    raise SystemExit("Release evidence contains an invalid image digest.")
if not re.fullmatch(r"[0-9a-f]{40}", release["sourceCommit"]):
    raise SystemExit("Release evidence contains an invalid source commit.")
expected_tag = f"sha-{release['sourceCommit'][:7]}"
if release["imageTag"] != expected_tag or release["applicationVersion"] != expected_tag:
    raise SystemExit("Release evidence readable identities are inconsistent.")
if not str(release["buildWorkflowRunId"]):
    raise SystemExit("Release evidence omits the build workflow identity.")

required_checks = {
    "release-schema", "helm-lint", "helm-render", "immutable-artifact-exists"
}
if qualification["mode"] != "static-release-qualification":
    raise SystemExit("Release evidence qualification mode is unsupported.")
if set(qualification["checks"]) != required_checks:
    raise SystemExit("Release evidence does not contain the complete qualification set.")
if str(qualification["workflowRunId"]) != expected_run_id:
    raise SystemExit("Release evidence workflow run does not match the requested evidence.")
if not isinstance(qualification["workflowRunAttempt"], int) or qualification["workflowRunAttempt"] < 1:
    raise SystemExit("Release evidence workflow attempt is invalid.")
if not re.fullmatch(r"[0-9a-f]{40}", qualification["repositoryRevision"]):
    raise SystemExit("Release evidence repository revision is invalid.")
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", qualification["actor"]):
    raise SystemExit("Release evidence actor is invalid.")

try:
    recorded_at = datetime.strptime(
        qualification["recordedAt"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
except (TypeError, ValueError) as error:
    raise SystemExit("Release evidence timestamp is invalid.") from error

age_seconds = (datetime.now(timezone.utc) - recorded_at).total_seconds()
if age_seconds < -300:
    raise SystemExit("Release evidence timestamp is unexpectedly in the future.")
if max_age_seconds and age_seconds > max_age_seconds:
    raise SystemExit("Release evidence has expired; qualify the current source release again.")

evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
if github_output:
    with Path(github_output).open("a") as output:
        output.write(f"evidence-sha256={evidence_sha256}\n")
        output.write(f"evidence-recorded-at={qualification['recordedAt']}\n")
        output.write(f"evidence-actor={qualification['actor']}\n")
        output.write(f"evidence-repository-revision={qualification['repositoryRevision']}\n")

print("demo-api release qualification evidence passed:")
print(f"  environment={expected_environment}")
print(f"  evidence_run_id={expected_run_id}")
print(f"  evidence_sha256={evidence_sha256}")
print(f"  release_sha256={release['sha256']}")
PY

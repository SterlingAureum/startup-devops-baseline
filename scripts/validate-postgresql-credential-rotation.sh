#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - \
  "${ROOT_DIR}/scripts/stage-demo-api-postgresql-credential.sh" \
  "${ROOT_DIR}/scripts/discard-demo-api-postgresql-credential.sh" \
  "${ROOT_DIR}/scripts/validate-postgresql-credential-rotation-aws.sh" \
  "${ROOT_DIR}/docs/archive/V0.8.5_POSTGRESQL_CREDENTIAL_ROTATION.md" \
  "${ROOT_DIR}/docs/ROADMAP.md" \
  "${ROOT_DIR}/CHANGELOG.md" <<'PY'
from pathlib import Path
import sys

stage_path, discard_path, runtime_path, doc_path, roadmap_path, changelog_path = (
    Path(value) for value in sys.argv[1:]
)
for path in (
    stage_path,
    discard_path,
    runtime_path,
    doc_path,
    roadmap_path,
    changelog_path,
):
    if not path.is_file():
        raise SystemExit(f"Required v0.8.5 Checkpoint 1 file is missing: {path}")

stage = stage_path.read_text()
discard = discard_path.read_text()
runtime = runtime_path.read_text()
doc = doc_path.read_text()
roadmap = roadmap_path.read_text()
changelog = changelog_path.read_text()

def require(text: str, marker: str, context: str) -> None:
    if marker not in text:
        raise SystemExit(f"Missing {context}: {marker}")

for marker in (
    'CONFIRM_POSTGRESQL_CREDENTIAL_STAGE:-}" != "stage-awspending"',
    '--version-stage AWSCURRENT',
    '--version-stages AWSPENDING',
    'secrets.token_urlsafe(48)',
    'file:///dev/stdin',
    'ExternalSecret is not Ready or is not pinned to AWSCURRENT.',
    'AWSCURRENT, PostgreSQL, ExternalSecret, Kubernetes Secret, and demo-api were not changed.',
):
    require(stage, marker, "safe candidate-staging contract")

for forbidden in (
    "ALTER ROLE",
    "rollout restart",
    "kubectl delete pod",
    "force-sync=",
    "--move-to-version-id",
):
    if forbidden in stage:
        raise SystemExit(f"Checkpoint 1 staging must not perform cutover action: {forbidden}")

for marker in (
    'CONFIRM_POSTGRESQL_CREDENTIAL_DISCARD:-}" != "discard-awspending"',
    '--version-stage AWSPENDING',
    '--remove-from-version-id "${PENDING_VERSION_ID}"',
    'AWSCURRENT was not moved.',
):
    require(discard, marker, "guarded candidate-discard contract")

for forbidden in ("delete-secret", "--move-to-version-id"):
    if forbidden in discard:
        raise SystemExit(f"Discard script contains destructive stage operation: {forbidden}")

for marker in (
    'Expected distinct, singular AWSCURRENT and AWSPENDING versions.',
    'len(pending_password) < 48',
    '.spec.data[0].remoteRef.version == "AWSCURRENT"',
    'PostgreSQL credential rotation Checkpoint 1 AWS validation passed.',
):
    require(runtime, marker, "AWS candidate-isolation validation")

for marker in (
    "Checkpoint 1: Candidate Credential Staging",
    "AWSPENDING",
    "does not alter the PostgreSQL role",
    "Checkpoint 2",
    "Never enable shell xtrace",
):
    require(doc, marker, "v0.8.5 Checkpoint 1 operating model")

require(
    roadmap,
    "validation - in progress; candidate staging delivered",
    "v0.8.5 roadmap status",
)
require(changelog, "## v0.8.5 (Unreleased)", "unreleased v0.8.5 changelog")
PY

echo "PostgreSQL credential rotation Checkpoint 1 contract validation passed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${EVIDENCE_FILE:?Set EVIDENCE_FILE to a v0.9.6 final evidence JSON file.}"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

python3 - "${ROOT_DIR}" "${EVIDENCE_FILE}" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys

root = Path(sys.argv[1]).resolve()
evidence_path = Path(sys.argv[2])
if not evidence_path.is_absolute():
    evidence_path = root / evidence_path
document = json.loads(evidence_path.read_text())

if document.get("schemaVersion") != "v0.9.6" or document.get("status") != "passed":
    raise SystemExit("Final evidence schema or status is invalid.")
if not re.fullmatch(r"\d{14}", str(document.get("evidenceId", ""))):
    raise SystemExit("Final evidence ID is invalid.")
if not re.fullmatch(r"[0-9a-f]{40}", str(document.get("repositoryRevision", ""))):
    raise SystemExit("Final evidence repository revision is invalid.")

artifact = document.get("artifact", {})
if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("imageDigest", ""))):
    raise SystemExit("Final evidence artifact digest is invalid.")
if not re.fullmatch(r"[0-9a-f]{40}", str(artifact.get("sourceCommit", ""))):
    raise SystemExit("Final evidence source commit is invalid.")

expected_refs = {
    "awsDevRuntime": ("v0.9.5", "aws-dev"),
    "awsTestRelease": ("v0.9.4", "aws-test"),
    "awsTestRuntime": ("v0.9.5", "aws-test"),
}
identities = []
for key, (schema, environment) in expected_refs.items():
    reference = document.get("evidence", {}).get(key, {})
    relative = Path(str(reference.get("path", "")))
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit(f"{key} path is not repository-relative")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise SystemExit(f"{key} escaped the repository") from error
    if not path.is_file():
        raise SystemExit(f"{key} target does not exist")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != reference.get("sha256"):
        raise SystemExit(f"{key} hash does not match")
    target = json.loads(path.read_text())
    if target.get("schemaVersion") != schema or target.get("environment") != environment or target.get("status") != "passed":
        raise SystemExit(f"{key} target identity is invalid")
    release = target.get("release", {})
    identities.append((
        release.get("imageRepository"), release.get("imageDigest"),
        release.get("sourceCommit"), release.get("applicationVersion"),
    ))

expected_artifact = {
    "imageRepository": identities[0][0],
    "imageDigest": identities[0][1],
    "sourceCommit": identities[0][2],
    "applicationVersion": identities[0][3],
}
if len(set(identities)) != 1 or artifact != expected_artifact:
    raise SystemExit("Final evidence artifact identity does not match referenced evidence.")

lifecycle = document.get("lifecycle", {})
if lifecycle.get("awsTestMode") != "ephemeral-clean-room" or lifecycle.get("awsProdValidation") != "static-only":
    raise SystemExit("Final evidence lifecycle boundary is invalid.")
required_checks = {
    "clean-main-source", "aws-dev-runtime-qualified",
    "ordered-dev-to-test-promotion", "aws-test-rollout-and-analysis-qualified",
    "postgresql-primary-failover-recovered", "aws-test-terraform-destroyed",
    "aws-test-cost-residual-audit-passed", "aws-prod-static-declarations-rendered",
}
if set(lifecycle.get("checks", [])) != required_checks:
    raise SystemExit("Final evidence lifecycle checks are incomplete.")

def parse_time(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(value)):
        raise SystemExit("Final evidence contains an invalid timestamp.")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

ordered = [
    parse_time(lifecycle.get("postgresqlFailoverCompletedAt")),
    parse_time(lifecycle.get("terraformDestroyCompletedAt")),
    parse_time(lifecycle.get("costCleanupAuditCompletedAt")),
    parse_time(document.get("recordedAt")),
]
if ordered != sorted(ordered):
    raise SystemExit("Final evidence timestamps are not ordered.")

test_release_time = parse_time(json.loads((root / Path(document["evidence"]["awsTestRelease"]["path"])).read_text()).get("qualification", {}).get("recordedAt"))
test_runtime_time = parse_time(json.loads((root / Path(document["evidence"]["awsTestRuntime"]["path"])).read_text()).get("runtime", {}).get("recordedAt"))
if test_release_time > test_runtime_time or test_runtime_time > ordered[0]:
    raise SystemExit("Referenced test release, runtime, and failover timestamps are not ordered.")

sensitive_pattern = re.compile(r"password|credential|secretvalue|token|privatekey", re.I)
def walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if sensitive_pattern.search(str(key)):
                raise SystemExit("Final evidence contains a prohibited sensitive field name.")
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)
walk(document)

print("v0.9 final evidence validation passed.")
PY

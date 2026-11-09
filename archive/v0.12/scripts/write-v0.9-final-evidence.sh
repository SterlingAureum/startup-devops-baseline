#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EVIDENCE_ID="${EVIDENCE_ID:-$(date -u +%Y%m%d%H%M%S)}"
OUTPUT_FILE="${OUTPUT_FILE:-${ROOT_DIR}/evidence/v0.9/final/${EVIDENCE_ID}.json}"

: "${EVIDENCE_ACTOR:?Set EVIDENCE_ACTOR to the GitHub login recording final evidence.}"
: "${DEV_RUNTIME_EVIDENCE_FILE:?Set DEV_RUNTIME_EVIDENCE_FILE.}"
: "${TEST_RELEASE_EVIDENCE_FILE:?Set TEST_RELEASE_EVIDENCE_FILE.}"
: "${TEST_RUNTIME_EVIDENCE_FILE:?Set TEST_RUNTIME_EVIDENCE_FILE.}"
: "${FAILOVER_COMPLETED_AT:?Set FAILOVER_COMPLETED_AT in UTC YYYY-MM-DDTHH:MM:SSZ.}"
: "${TEST_DESTROY_COMPLETED_AT:?Set TEST_DESTROY_COMPLETED_AT in UTC YYYY-MM-DDTHH:MM:SSZ.}"
: "${COST_AUDIT_COMPLETED_AT:?Set COST_AUDIT_COMPLETED_AT in UTC YYYY-MM-DDTHH:MM:SSZ.}"

for command in git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

REPOSITORY_REVISION="${REPOSITORY_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"
RECORDED_AT="${RECORDED_AT:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

python3 - \
  "${ROOT_DIR}" \
  "${OUTPUT_FILE}" \
  "${EVIDENCE_ID}" \
  "${EVIDENCE_ACTOR}" \
  "${REPOSITORY_REVISION}" \
  "${RECORDED_AT}" \
  "${DEV_RUNTIME_EVIDENCE_FILE}" \
  "${TEST_RELEASE_EVIDENCE_FILE}" \
  "${TEST_RUNTIME_EVIDENCE_FILE}" \
  "${FAILOVER_COMPLETED_AT}" \
  "${TEST_DESTROY_COMPLETED_AT}" \
  "${COST_AUDIT_COMPLETED_AT}" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import sys

(
    root_raw, output_raw, evidence_id, actor, revision, recorded_at,
    dev_runtime_raw, test_release_raw, test_runtime_raw,
    failover_at, destroy_at, audit_at,
) = sys.argv[1:]
root = Path(root_raw).resolve()
output = Path(output_raw).resolve()


def parse_time(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise SystemExit(f"Invalid UTC timestamp: {value}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_inside_repo(raw: str, label: str):
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise SystemExit(f"{label} must be inside the repository") from error
    if not path.is_file():
        raise SystemExit(f"{label} does not exist: {relative}")
    data = json.loads(path.read_text())
    return path, relative.as_posix(), data


if not re.fullmatch(r"\d{14}", evidence_id):
    raise SystemExit("EVIDENCE_ID must use UTC YYYYMMDDHHMMSS digits.")
if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", actor):
    raise SystemExit("EVIDENCE_ACTOR is not a valid GitHub login.")
if not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise SystemExit("REPOSITORY_REVISION must be a full lowercase commit SHA.")

times = [parse_time(value) for value in (failover_at, destroy_at, audit_at, recorded_at)]
if times != sorted(times):
    raise SystemExit("Failover, destroy, cleanup audit, and final recording timestamps must be ordered.")

dev_path, dev_relative, dev = load_inside_repo(dev_runtime_raw, "dev runtime evidence")
release_path, release_relative, test_release = load_inside_repo(test_release_raw, "test release evidence")
test_path, test_relative, test_runtime = load_inside_repo(test_runtime_raw, "test runtime evidence")

expected = (
    (dev, "v0.9.5", "aws-dev", "dev runtime evidence"),
    (test_release, "v0.9.4", "aws-test", "test release evidence"),
    (test_runtime, "v0.9.5", "aws-test", "test runtime evidence"),
)
for document, schema, environment, label in expected:
    if document.get("schemaVersion") != schema or document.get("environment") != environment or document.get("status") != "passed":
        raise SystemExit(f"{label} has an unexpected schema, environment, or status")

test_release_at = parse_time(test_release.get("qualification", {}).get("recordedAt", ""))
test_runtime_at = parse_time(test_runtime.get("runtime", {}).get("recordedAt", ""))
if test_release_at > test_runtime_at or test_runtime_at > times[0]:
    raise SystemExit("Test release, runtime, and failover timestamps must be ordered.")

identities = []
for document in (dev, test_release, test_runtime):
    release = document.get("release", {})
    identities.append((
        release.get("imageRepository"),
        release.get("imageDigest"),
        release.get("sourceCommit"),
        release.get("applicationVersion"),
    ))
if len(set(identities)) != 1:
    raise SystemExit("Final evidence rejected an artifact identity change across dev and test.")

def reference(path: Path, relative: str):
    return {
        "path": relative,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }

document = {
    "schemaVersion": "v0.9.6",
    "status": "passed",
    "evidenceId": evidence_id,
    "actor": actor,
    "recordedAt": recorded_at,
    "repositoryRevision": revision,
    "artifact": {
        "imageRepository": identities[0][0],
        "imageDigest": identities[0][1],
        "sourceCommit": identities[0][2],
        "applicationVersion": identities[0][3],
    },
    "evidence": {
        "awsDevRuntime": reference(dev_path, dev_relative),
        "awsTestRelease": reference(release_path, release_relative),
        "awsTestRuntime": reference(test_path, test_relative),
    },
    "lifecycle": {
        "awsTestMode": "ephemeral-clean-room",
        "postgresqlFailoverCompletedAt": failover_at,
        "terraformDestroyCompletedAt": destroy_at,
        "costCleanupAuditCompletedAt": audit_at,
        "awsProdValidation": "static-only",
        "checks": [
            "clean-main-source",
            "aws-dev-runtime-qualified",
            "ordered-dev-to-test-promotion",
            "aws-test-rollout-and-analysis-qualified",
            "postgresql-primary-failover-recovered",
            "aws-test-terraform-destroyed",
            "aws-test-cost-residual-audit-passed",
            "aws-prod-static-declarations-rendered",
        ],
    },
}

output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
print(f"Recorded v0.9 final evidence: {output}")
PY

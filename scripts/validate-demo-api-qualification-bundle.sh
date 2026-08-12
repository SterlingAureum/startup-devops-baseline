#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

CONTROL_PLANE_SHA="cccccccccccccccccccccccccccccccccccccccc"
RUN_ID="400"
RUN_ATTEMPT="2"
RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
STATIC_RESULT="${WORK_DIR}/static.json"
RUNTIME_RESULT="${WORK_DIR}/runtime.json"
SCOPE_RESULT="${WORK_DIR}/scope.json"
TEST_SCOPE_RESULT="${WORK_DIR}/scope-test.json"
BUNDLE_FILE="${WORK_DIR}/bundle.json"

ENVIRONMENT=aws-dev \
RELEASE_FILE="${RELEASE_FILE}" \
OUTPUT_FILE="${STATIC_RESULT}" \
VALIDATED_REPOSITORY_REVISION="${CONTROL_PLANE_SHA}" \
EVIDENCE_RUN_ID="${RUN_ID}" \
EVIDENCE_RUN_ATTEMPT="${RUN_ATTEMPT}" \
EVIDENCE_ACTOR=SterlingAureum \
RECORDED_AT=2026-08-12T00:00:00Z \
  "${ROOT_DIR}/scripts/write-demo-api-release-evidence.sh" >/dev/null

python3 - "${STATIC_RESULT}" "${RUNTIME_RESULT}" "${CONTROL_PLANE_SHA}" "${RUN_ID}" "${RUN_ATTEMPT}" <<'PY'
from pathlib import Path
import json
import sys

static_path, output_path, revision, run_id, run_attempt = sys.argv[1:]
static = json.loads(Path(static_path).read_text())
release = static["release"]
release_id = f"demo-api-{release['sourceCommit'][:12]}-{release['imageDigest'].removeprefix('sha256:')[:12]}"
runtime = {
    "schemaVersion": "v0.10.3",
    "application": "demo-api",
    "environment": "aws-dev",
    "releaseId": release_id,
    "status": "qualified",
    "reason": "all_checks_passed",
    "recordedAt": "2026-08-12T00:30:00Z",
    "expiresAt": "2026-08-13T00:30:00Z",
    "controlPlane": {
        "repository": "SterlingAureum/startup-devops-baseline",
        "ref": "refs/heads/main",
        "revision": revision,
        "releaseFile": "apps/demo-api/helm/values/releases/aws-dev.yaml",
        "releaseFileSha256": release["sha256"],
    },
    "expected": {
        "sourceCommit": release["sourceCommit"],
        "imageDigest": release["imageDigest"],
        "imageReference": f"{release['imageRepository']}@{release['imageDigest']}",
    },
    "executor": {
        "kind": "ephemeral-self-hosted",
        "githubEnvironment": "aws-dev-runtime",
        "runnerName": "fixture-runner",
        "workflowRunId": run_id,
        "workflowRunAttempt": run_attempt,
        "awsCallerArn": "arn:aws:sts::123456789012:assumed-role/fixture/runtime",
        "clusterName": "startup-devops-baseline-dev",
    },
    "runtime": {
        "argoApplication": "demo-api-aws-dev",
        "argoRevision": revision,
        "workloadKind": "Deployment",
        "workloadName": "demo-api",
        "rolloutPhase": "not-applicable",
        "analysisRunName": "",
        "analysisRunPhase": "not-applicable",
        "httpsHostname": "demo.dev.aureumstack.com",
        "readyPodCount": 2,
        "observedImageIds": [f"{release['imageRepository']}@{release['imageDigest']}"],
        "checks": [
            "argocd-synced-healthy",
            "release-annotations-match",
            "all-pods-ready",
            "immutable-pod-image-id-match",
            "https-health",
            "https-ready-database",
            "https-version-identity",
            "read-only-rbac-boundary",
        ],
    },
}
Path(output_path).write_text(json.dumps(runtime, indent=2, sort_keys=True) + "\n")
PY

"${ROOT_DIR}/scripts/calculate-demo-api-qualification-scope.py" \
  --environment aws-dev \
  --output "${SCOPE_RESULT}" >/dev/null
"${ROOT_DIR}/scripts/calculate-demo-api-qualification-scope.py" \
  --environment aws-test \
  --output "${TEST_SCOPE_RESULT}" >/dev/null
"${ROOT_DIR}/scripts/write-demo-api-qualification-bundle.py" \
  --environment aws-dev \
  --static-result "${STATIC_RESULT}" \
  --runtime-result "${RUNTIME_RESULT}" \
  --scope-result "${SCOPE_RESULT}" \
  --control-plane-sha "${CONTROL_PLANE_SHA}" \
  --workflow-run-id "${RUN_ID}" \
  --workflow-run-attempt "${RUN_ATTEMPT}" \
  --actor SterlingAureum \
  --recorded-at 2026-08-12T01:00:00Z \
  --output "${BUNDLE_FILE}" >/dev/null
"${ROOT_DIR}/scripts/validate-demo-api-qualification-bundle.py" \
  --bundle "${BUNDLE_FILE}" \
  --now 2026-08-12T02:00:00Z >/dev/null

python3 - "${ROOT_DIR}" "${WORK_DIR}" "${BUNDLE_FILE}" "${SCOPE_RESULT}" "${TEST_SCOPE_RESULT}" <<'PY'
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(sys.argv[1])
work = Path(sys.argv[2])
bundle = json.loads(Path(sys.argv[3]).read_text())
scope = json.loads(Path(sys.argv[4]).read_text())
test_scope = json.loads(Path(sys.argv[5]).read_text())
sys.path.insert(0, str(root / "scripts"))
from demo_api_qualification_bundle import canonical_bytes, validate

now = datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)


def rejected(name, mutate, rehash=False):
    candidate = copy.deepcopy(bundle)
    mutate(candidate)
    if rehash:
        candidate["staticQualification"]["sha256"] = hashlib.sha256(
            canonical_bytes(candidate["staticQualification"]["result"])
        ).hexdigest()
        candidate["runtimeQualification"]["sha256"] = hashlib.sha256(
            canonical_bytes(candidate["runtimeQualification"]["result"])
        ).hexdigest()
    try:
        validate(candidate, root=root, now=now)
    except (KeyError, TypeError, ValueError):
        return
    raise SystemExit(f"Unsafe Qualification Bundle mutation was accepted: {name}")


mutations = [
    ("production environment", lambda d: d.__setitem__("environment", "aws-prod"), False),
    ("different runtime run", lambda d: d["runtimeQualification"]["result"]["executor"].__setitem__("workflowRunId", "999"), True),
    ("different static attempt", lambda d: d["staticQualification"]["result"]["qualification"].__setitem__("workflowRunAttempt", 9), True),
    ("scope hash", lambda d: d["qualificationScope"].__setitem__("scopeSha256", "0" * 64), False),
    ("release hash", lambda d: d["release"].__setitem__("sha256", "0" * 64), False),
    ("secret field", lambda d: d["orchestration"].__setitem__("token", "forbidden"), False),
    ("automatic extension", lambda d: d.__setitem__("expiresAt", "2026-08-20T00:00:00Z"), False),
]
for name, mutate, rehash in mutations:
    rejected(name, mutate, rehash)

fixture_root = work / "scope-fixture"
for item in scope["files"]:
    source = root / item["path"]
    target = fixture_root / item["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
contract_source = root / scope["contract"]
contract_target = fixture_root / scope["contract"]
contract_target.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(contract_source, contract_target)
for item in test_scope["files"]:
    source = root / item["path"]
    target = fixture_root / item["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
test_contract_source = root / test_scope["contract"]
test_contract_target = fixture_root / test_scope["contract"]
test_contract_target.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(test_contract_source, test_contract_target)
validate(bundle, root=fixture_root, now=now)
for environment in ("aws-test", "aws-prod"):
    relative = Path(f"apps/demo-api/helm/values/releases/{environment}.yaml")
    target = fixture_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / relative, target)
bundle_relative = Path(
    f"evidence/demo-api/qualification/aws-dev/{bundle['releaseId']}/400-2.json"
)
bundle_target = fixture_root / bundle_relative
bundle_target.parent.mkdir(parents=True, exist_ok=True)
bundle_target.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
open_prs = work / "open-prs.json"
open_prs.write_text("[]\n")


def collect(name):
    output = work / f"snapshot-{name}.json"
    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/collect-demo-api-orchestration-snapshot.py"),
            "--root", str(fixture_root),
            "--operation", "status",
            "--policy", "reviewed",
            "--event-name", "fixture",
            "--ref", "refs/heads/main",
            "--captured-main-revision", "c" * 40,
            "--observed-main-revision", "c" * 40,
            "--repository", "SterlingAureum/startup-devops-baseline",
            "--open-prs-json", str(open_prs),
            "--now", "2026-08-12T02:00:00Z",
            "--output", str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return json.loads(output.read_text())


snapshot = collect("fresh")
if snapshot["qualificationBundles"]["aws-dev"]["state"] != "fresh":
    raise SystemExit("Collector did not recognize the fresh reviewed Qualification Bundle")
scoped_file = fixture_root / scope["files"][0]["path"]
scoped_file.write_bytes(scoped_file.read_bytes() + b"\n# mutation\n")
try:
    validate(bundle, root=fixture_root, now=now)
except ValueError:
    pass
else:
    raise SystemExit("A changed deployment input did not invalidate the Qualification Bundle")
snapshot = collect("scope-mutated")
if snapshot["qualificationBundles"]["aws-dev"]["state"] != "missing":
    raise SystemExit("Collector accepted a Qualification Bundle after its deployment scope changed")

print("Qualification Bundle positive, negative, and scope invalidation tests passed.")
PY

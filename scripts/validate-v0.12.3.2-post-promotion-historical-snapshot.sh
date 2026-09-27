#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-full}"
if [[ "${mode}" != "full" && "${mode}" != "--structure-only" ]]; then
  echo "Usage: $0 [--structure-only]" >&2
  exit 2
fi

SNAPSHOT_COMMIT="f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7"

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.3.2-post-promotion-historical-snapshot.json"
document_path = root / "docs/V0.12.3.2_POST_PROMOTION_HISTORICAL_SNAPSHOT.md"
executables = [
    root / "scripts/check-v0.12.3.2-historical-snapshot.py",
    root / "scripts/test-v0.12.3.2-historical-snapshot.py",
    root / "scripts/validate-v0.12.3.2-post-promotion-historical-snapshot.sh",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.3.2-post-promotion-historical-snapshot-v1", "schema drift")
    require(value.get("version") == "v0.12.3.2", "version drift")
    require(value.get("status") == "delivered-static-historical-attestation-awaiting-github-validation", "status drift")
    require(value.get("implementationBaselineCommit") == "d51aa1c11a148f5c3ecbb2eb60a20d566b5ca15a", "baseline drift")
    incident = value.get("incidentClosure")
    require(incident == {
        "promotionPullRequest": 169,
        "promotedReleasePath": "apps/demo-api/helm/values/releases/aws-dev.yaml",
        "promotedReleaseSha256": "c650fec1aa027a411b786c30f8f7b81e26ff1c5597ba679d0086b1e801d4d143",
        "promotedSourceCommit": "f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7",
    }, "incident closure drift")
    snapshot = value.get("historicalSnapshot")
    require(snapshot == {
        "commit": incident["promotedSourceCommit"],
        "purpose": "last-green-pre-promotion-v0.11-static-attestation",
        "entrypointManifest": "delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt",
        "entrypointCount": 112,
        "snapshotReleaseSha256": "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46",
        "mustBeAncestorOfCurrentHead": True,
        "manifestMustMatchCurrent": True,
        "allEntrypointsMustBeGitExecutable": True,
        "snapshotReleaseDigestMustMatch": True,
        "detachedWorktreeCreated": False,
        "runtimeReplayRequired": False,
    }, "historical attestation drift")
    boundary = value.get("executionBoundary")
    require(boundary.get("currentRepositoryRunsCurrentV012StructureValidators") is True, "current structure validation disabled")
    for key in (
        "historicalV011ValidatorsExecuted",
        "snapshotRuntimeReplayExecuted",
        "historicalContractsOrDigestsRewritten",
        "currentReleaseStateOverwritten",
        "snapshotPushedOrCommitted",
        "workflowFetchDepthChanged",
        "requiredCheckNameChanged",
    ):
        require(boundary.get(key) is False, f"unsafe execution boundary enabled: {key}")
    safety = value.get("safety")
    for key in ("unknownChangesStillRunFull", "releaseOnlyRoutingPreserved"):
        require(safety.get(key) is True, f"routing safety disabled: {key}")
    for key in (
        "snapshotCommitOverrideAllowed",
        "arbitrarySnapshotRootAllowed",
        "awsOperationAuthorized",
        "terraformOperationAuthorized",
        "kubernetesOperationAuthorized",
        "stateRecoveryResumed",
    ):
        require(safety.get(key) is False, f"unsafe authority enabled: {key}")
    require(value.get("deferred") == {
        "exactMergeTreeAttestedCoreGateReuse": "v1.0",
        "historicalValidatorArchival": "v1.0",
        "repositoryPhysicalRestructure": "v1.0",
    }, "deferred boundary drift")


contract = json.loads(contract_path.read_text())
validate(contract)
mutations = []


def mutate(path, replacement):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    mutations.append(item)


mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["incidentClosure", "promotionPullRequest"], 168)
mutate(["incidentClosure", "promotedReleaseSha256"], "0" * 64)
mutate(["historicalSnapshot", "commit"], "0" * 40)
mutate(["historicalSnapshot", "entrypointCount"], 111)
mutate(["historicalSnapshot", "mustBeAncestorOfCurrentHead"], False)
mutate(["historicalSnapshot", "manifestMustMatchCurrent"], False)
mutate(["historicalSnapshot", "allEntrypointsMustBeGitExecutable"], False)
mutate(["historicalSnapshot", "snapshotReleaseDigestMustMatch"], False)
mutate(["historicalSnapshot", "detachedWorktreeCreated"], True)
mutate(["historicalSnapshot", "runtimeReplayRequired"], True)
mutate(["executionBoundary", "currentRepositoryRunsCurrentV012StructureValidators"], False)
mutate(["executionBoundary", "historicalV011ValidatorsExecuted"], True)
mutate(["executionBoundary", "snapshotRuntimeReplayExecuted"], True)
mutate(["executionBoundary", "historicalContractsOrDigestsRewritten"], True)
mutate(["executionBoundary", "currentReleaseStateOverwritten"], True)
mutate(["executionBoundary", "requiredCheckNameChanged"], True)
mutate(["safety", "unknownChangesStillRunFull"], False)
mutate(["safety", "terraformOperationAuthorized"], True)
mutate(["deferred", "historicalValidatorArchival"], "v0.12.3.2")
for index, candidate in enumerate(mutations, 1):
    try:
        validate(candidate)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open mutation {index}")

require(document_path.is_file(), "snapshot document missing")
document = document_path.read_text()
for phrase in (
    "static historical attestation",
    "does not create a detached worktree",
    "does not execute a v0.11 validator",
    "does not alter a v0.11 contract or digest",
    "paused Terraform state exercise remains paused",
):
    require(phrase in document, f"static attestation boundary missing: {phrase}")

tracked_paths = executables + [contract_path, document_path]
tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in tracked_paths]],
    capture_output=True,
    text=True,
    check=True,
).stdout.splitlines()
require(len(tracked) == len(tracked_paths), "source tracking drift")
modes = {}
for line in tracked:
    metadata, path = line.split("\t", 1)
    modes[path] = metadata.split()[0]
for path in executables:
    relative = str(path.relative_to(root))
    require(modes.get(relative) == "100755", f"executable mode drift: {relative}")
for path in (contract_path, document_path):
    relative = str(path.relative_to(root))
    require(modes.get(relative) == "100644", f"document mode drift: {relative}")

print(f"v0.12.3.2 static historical attestation contract and {len(mutations)} fail-closed mutations passed offline.")
PY

bash -n \
  "${ROOT_DIR}/scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh" \
  "${ROOT_DIR}/scripts/validate-v0.12.3.2-post-promotion-historical-snapshot.sh"
python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.3.2-historical-snapshot.py" \
  "${ROOT_DIR}/scripts/test-v0.12.3.2-historical-snapshot.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.3.2-historical-snapshot.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.3.2-historical-snapshot.py" \
  --root "${ROOT_DIR}"

if [[ "${mode}" == "--structure-only" ]]; then
  bash "${ROOT_DIR}/scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh" --structure-only
  echo "v0.12.3.2 structure-only static historical attestation passed; history was not replayed."
  exit 0
fi

for command in git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.3.2-historical-snapshot.py" \
  --root "${ROOT_DIR}" \
  --verify-static-attestation \
  --snapshot-commit "${SNAPSHOT_COMMIT}"
bash "${ROOT_DIR}/scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh" --structure-only

echo "v0.12.3.2 static historical attestation passed; runtime replay was not executed."

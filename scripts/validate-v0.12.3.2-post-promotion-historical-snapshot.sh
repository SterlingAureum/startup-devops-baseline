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
    require(value.get("implementationBaselineCommit") == "d51aa1c11a148f5c3ecbb2eb60a20d566b5ca15a", "baseline drift")
    incident = value.get("incidentClosure")
    require(incident == {
        "promotionPullRequest": 169,
        "promotedReleasePath": "apps/demo-api/helm/values/releases/aws-dev.yaml",
        "promotedReleaseSha256": "c650fec1aa027a411b786c30f8f7b81e26ff1c5597ba679d0086b1e801d4d143",
        "promotedSourceCommit": "f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7",
    }, "incident closure drift")
    snapshot = value.get("historicalSnapshot")
    require(snapshot.get("commit") == incident["promotedSourceCommit"], "snapshot commit drift")
    require(snapshot.get("entrypointManifest") == "delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt", "manifest drift")
    require(snapshot.get("entrypointCount") == 112, "entrypoint count drift")
    require(snapshot.get("snapshotReleaseSha256") == "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46", "snapshot release drift")
    for key in ("mustBeAncestorOfCurrentHead", "detachedCleanWorktreeRequired", "manifestMustMatchCurrent", "allEntrypointsMustBeExecutable"):
        require(snapshot.get(key) is True, f"snapshot boundary disabled: {key}")
    boundary = value.get("executionBoundary")
    for key in ("currentRepositoryRunsCurrentV012Validators", "snapshotRunsOnlyManifestedV011Entrypoints"):
        require(boundary.get(key) is True, f"execution boundary disabled: {key}")
    for key in ("historicalContractsOrDigestsRewritten", "currentReleaseStateOverwritten", "snapshotPushedOrCommitted", "workflowFetchDepthChanged", "requiredCheckNameChanged"):
        require(boundary.get(key) is False, f"unsafe execution boundary enabled: {key}")
    safety = value.get("safety")
    for key in ("unknownChangesStillRunFull", "releaseOnlyRoutingPreserved"):
        require(safety.get(key) is True, f"routing safety disabled: {key}")
    for key in ("snapshotCommitOverrideAllowed", "arbitrarySnapshotRootAllowed", "awsOperationAuthorized", "terraformOperationAuthorized", "kubernetesOperationAuthorized", "stateRecoveryResumed"):
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
mutate(["historicalSnapshot", "detachedCleanWorktreeRequired"], False)
mutate(["historicalSnapshot", "manifestMustMatchCurrent"], False)
mutate(["historicalSnapshot", "allEntrypointsMustBeExecutable"], False)
mutate(["executionBoundary", "currentRepositoryRunsCurrentV012Validators"], False)
mutate(["executionBoundary", "snapshotRunsOnlyManifestedV011Entrypoints"], False)
mutate(["executionBoundary", "historicalContractsOrDigestsRewritten"], True)
mutate(["executionBoundary", "currentReleaseStateOverwritten"], True)
mutate(["executionBoundary", "requiredCheckNameChanged"], True)
mutate(["safety", "unknownChangesStillRunFull"], False)
mutate(["safety", "snapshotCommitOverrideAllowed"], True)
mutate(["safety", "arbitrarySnapshotRootAllowed"], True)
mutate(["safety", "terraformOperationAuthorized"], True)
mutate(["safety", "stateRecoveryResumed"], True)
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
    "temporary detached worktree",
    "exact reviewed snapshot commit",
    "does not alter a v0.11 contract or digest",
    "paused Terraform state exercise remains paused",
):
    require(phrase in document, f"snapshot boundary missing: {phrase}")

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

print(f"v0.12.3.2 historical snapshot contract and {len(mutations)} fail-closed mutations passed offline.")
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
  echo "v0.12.3.2 structure-only historical snapshot validation passed; history was not replayed."
  exit 0
fi

for command in git python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

git -C "${ROOT_DIR}" cat-file -e "${SNAPSHOT_COMMIT}^{commit}"
git -C "${ROOT_DIR}" merge-base --is-ancestor "${SNAPSHOT_COMMIT}" HEAD

snapshot_parent="$(mktemp -d)"
snapshot_root="${snapshot_parent}/repository"
cleanup() {
  git -C "${ROOT_DIR}" worktree remove --force "${snapshot_root}" >/dev/null 2>&1 || true
  rmdir "${snapshot_parent}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

git -C "${ROOT_DIR}" worktree add --detach "${snapshot_root}" "${SNAPSHOT_COMMIT}"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.3.2-historical-snapshot.py" \
  --root "${ROOT_DIR}" \
  --verify-snapshot-root "${snapshot_root}" \
  --snapshot-commit "${SNAPSHOT_COMMIT}"

(
  export V011_HISTORICAL_SNAPSHOT_ROOT="${snapshot_root}"
  export V011_HISTORICAL_SNAPSHOT_COMMIT="${SNAPSHOT_COMMIT}"
  bash "${ROOT_DIR}/scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh"
)

echo "v0.12.3.2 full validation passed with v0.11 isolated at the reviewed historical snapshot."

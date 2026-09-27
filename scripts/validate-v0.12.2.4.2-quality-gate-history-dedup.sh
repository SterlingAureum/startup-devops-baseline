#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR
mode="${1:-full}"
if [[ "${mode}" != "full" && "${mode}" != "--structure-only" ]]; then
  echo "Usage: $0 [--structure-only]" >&2
  exit 2
fi

python3 - <<'PY'
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.4.2-quality-gate-history-dedup.json"
manifest_path = root / "delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt"
helper_path = root / "scripts/check-tracked-terraform-format.sh"
checker_path = root / "scripts/check-v0.12.2.4.2-quality-gate-orchestration.py"
test_path = root / "scripts/test-v0.12.2.4.2-quality-gate-orchestration.py"
validator_path = root / "scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.4.2-quality-gate-history-dedup-v1", "schema drift")
    require(value.get("version") == "v0.12.2.4.2", "version drift")
    require(value.get("implementationBaselineCommit") == "13bea2e73a229c0b0795f9d25178e766ebde56ed", "baseline drift")
    observed = value.get("observedBaseline")
    require(observed.get("localQualityGateElapsedSeconds") == "818.612", "elapsed evidence drift")
    require(observed.get("localQualityGateCompleted") is False, "completion evidence drift")
    require(observed.get("stopPathTracked") is False, "private path classification drift")
    require(observed.get("validationLogSha256") == "51eaadf3403bbdaf7b58b7bac25708c5665cea40bebaabf65c27cbafffbd9ad6", "log digest drift")
    graph = value.get("callGraph")
    expected = {
        "preChangeRootDirectValidatorCount": 198,
        "preChangeV011RootDirectValidatorCount": 168,
        "preChangeEffectiveValidatorExecutionCount": 951,
        "preChangeEffectiveV011ExecutionCount": 866,
        "postChangeRootDirectValidatorCount": 29,
        "postChangeV011RootDirectValidatorCount": 0,
        "delegatedV011EntrypointCount": 112,
        "uniqueReachableV011ValidatorCount": 168,
        "postChangeEffectiveValidatorExecutionCount": 245,
        "postChangeEffectiveV011ExecutionCount": 176,
        "postChangeEffectiveHistoricalV012ExecutionCount": 25,
        "postChangeV012OrchestrationExecutionCount": 2,
    }
    require(all(graph.get(key) == expected_value for key, expected_value in expected.items()), "call graph count drift")
    require(graph.get("entrypointManifestSha256") == hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "manifest digest drift")
    successor = value.get("successor")
    require(successor.get("rootDirectV012Validators") == ["validate-v0.12.3.1-ci-change-impact-routing.sh"], "successor root drift")
    require(successor.get("delegatedV012Validators") == ["validate-v0.12.2.4.2-quality-gate-history-dedup.sh"], "successor delegation drift")
    require(successor.get("effectiveValidatorExecutionCount") == 246, "successor effective count drift")
    require(successor.get("effectiveV012OrchestrationExecutionCount") == 3, "successor orchestration count drift")
    terraform = value.get("terraformFormatBoundary")
    require(terraform.get("trackedFilesOnly") is True, "tracked format boundary drift")
    require(terraform.get("ignoredPrivateTfvarsInspected") is False, "private tfvars boundary drift")
    invariants = value.get("invariants")
    for key in ("allExistingV011ValidatorsRemainReachable", "allExistingV012ValidatorsRemainReachable", "legacyRootRegistrationTextPreserved", "compatibilityValidatorFormatScopeChanged", "unknownChangeFailsToFullSuite"):
        require(invariants.get(key) is True, f"invariant drift: {key}")
    for key in ("historicalV011ValidatorFilesModified", "requiredCheckNamesChanged", "workflowTriggersChanged", "pathRoutingIntroduced"):
        require(invariants.get(key) is False, f"boundary drift: {key}")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "producer drift")


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
mutate(["observedBaseline", "localQualityGateCompleted"], True)
mutate(["observedBaseline", "stopPathTracked"], True)
mutate(["callGraph", "delegatedV011EntrypointCount"], 111)
mutate(["callGraph", "uniqueReachableV011ValidatorCount"], 167)
mutate(["callGraph", "postChangeEffectiveV011ExecutionCount"], 177)
mutate(["callGraph", "entrypointManifestSha256"], "0" * 64)
mutate(["successor", "effectiveValidatorExecutionCount"], 245)
mutate(["terraformFormatBoundary", "trackedFilesOnly"], False)
mutate(["terraformFormatBoundary", "ignoredPrivateTfvarsInspected"], True)
mutate(["invariants", "allExistingV011ValidatorsRemainReachable"], False)
mutate(["invariants", "requiredCheckNamesChanged"], True)
mutate(["invariants", "workflowTriggersChanged"], True)
mutate(["packageProducer", "runsTerraform"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open mutation {index}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--",
     str(helper_path.relative_to(root)), str(checker_path.relative_to(root)),
     str(test_path.relative_to(root)), str(validator_path.relative_to(root)),
     str(manifest_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 5, "source tracking drift")
modes = {}
for line in tracked:
    metadata, path = line.split("\t", 1)
    modes[path] = metadata.split()[0]
for executable_path in (helper_path, checker_path, test_path, validator_path):
    relative_path = str(executable_path.relative_to(root))
    require(modes.get(relative_path) == "100755", f"executable mode drift: {relative_path}")
manifest_relative_path = str(manifest_path.relative_to(root))
require(modes.get(manifest_relative_path) == "100644", "manifest mode drift")
print(f"v0.12.2.4.2 orchestration contract and {len(mutations)} fail-closed mutations passed offline.")
PY

bash -n "${ROOT_DIR}/scripts/check-tracked-terraform-format.sh" "${ROOT_DIR}/scripts/validate-v0.12.2.4.1-validator-orchestration-dedup.sh" "${ROOT_DIR}/scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh"
python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.2.4.1-validator-orchestration.py" \
  "${ROOT_DIR}/scripts/check-v0.12.2.4.2-quality-gate-orchestration.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.4.2-quality-gate-orchestration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.4.2-quality-gate-orchestration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/check-v0.12.2.4.2-quality-gate-orchestration.py" --root "${ROOT_DIR}"

if [[ "${mode}" == "--structure-only" ]]; then
  echo "v0.12.2.4.2 structure-only validation passed; historical validators were not executed."
  exit 0
fi

compatibility_started_at=${SECONDS}
bash "${ROOT_DIR}/scripts/validate-v0.12.1.0.1-ci-compatibility-repair.sh"
echo "v0.12 compatibility_elapsed_seconds=$((SECONDS - compatibility_started_at))"

v011_started_at=${SECONDS}
v011_count=0
v011_validation_root="${V011_HISTORICAL_SNAPSHOT_ROOT:-${ROOT_DIR}}"
if [[ "${v011_validation_root}" != "${ROOT_DIR}" ]]; then
  [[ "${v011_validation_root}" = /* ]] || {
    echo "Historical v0.11 snapshot root must be absolute." >&2
    exit 1
  }
  [[ ! -L "${v011_validation_root}" && -d "${v011_validation_root}" ]] || {
    echo "Historical v0.11 snapshot root must be a real directory." >&2
    exit 1
  }
  [[ "${V011_HISTORICAL_SNAPSHOT_COMMIT:-}" == "f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7" ]] || {
    echo "Historical v0.11 snapshot commit is not the reviewed commit." >&2
    exit 1
  }
  [[ "$(git -C "${v011_validation_root}" rev-parse HEAD)" == "${V011_HISTORICAL_SNAPSHOT_COMMIT}" ]] || {
    echo "Historical v0.11 snapshot HEAD drifted." >&2
    exit 1
  }
  [[ -z "$(git -C "${v011_validation_root}" status --porcelain)" ]] || {
    echo "Historical v0.11 snapshot worktree is dirty." >&2
    exit 1
  }
  cmp \
    "${ROOT_DIR}/delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt" \
    "${v011_validation_root}/delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt"
elif [[ -n "${V011_HISTORICAL_SNAPSHOT_COMMIT:-}" ]]; then
  echo "Historical v0.11 snapshot commit was supplied without an isolated root." >&2
  exit 1
fi
while IFS= read -r validator; do
  [[ -n "${validator}" ]] || continue
  echo "==> Validating deduplicated v0.11 entrypoint ${validator}"
  bash "${v011_validation_root}/scripts/${validator}"
  v011_count=$((v011_count + 1))
done <"${ROOT_DIR}/delivery/contracts/v0.12.2.4.2-v0.11-entrypoints.txt"
echo "v0.11 delegated_entrypoint_count=${v011_count}; elapsed_seconds=$((SECONDS - v011_started_at))"

v012_started_at=${SECONDS}
bash "${ROOT_DIR}/scripts/validate-v0.12.2.4.1-validator-orchestration-dedup.sh"
echo "v0.12 delegated_orchestration_elapsed_seconds=$((SECONDS - v012_started_at))"
echo "v0.12.2.4.2 full historical orchestration passed; no AWS or live Terraform operation was executed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR

python3 - <<'PY'
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.4.1-validator-orchestration-dedup.json"
checker_path = root / "scripts/check-v0.12.2.4.1-validator-orchestration.py"
test_path = root / "scripts/test-v0.12.2.4.1-validator-orchestration.py"
validator_path = root / "scripts/validate-v0.12.2.4.1-validator-orchestration-dedup.sh"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.4.1-validator-orchestration-dedup-v1", "schema drift")
    require(value.get("version") == "v0.12.2.4.1", "version drift")
    require(value.get("status") == "delivered-offline", "status drift")
    require(value.get("implementationBaselineCommit") == "1153c48c70a4f2873014800280cfbd25eed2e3ef", "baseline drift")
    scope = value.get("scope")
    require(scope.get("preChangeDirectV012ValidatorCount") == 23, "pre-change count drift")
    require(scope.get("postChangeDirectV012ValidatorCount") == 2, "post-change count drift")
    require(scope.get("uniqueChainedValidatorCount") == 22, "chain count drift")
    require(scope.get("rootDirectInvocationReduction") == 21, "reduction drift")
    require(scope.get("preChangeEffectiveHistoricalValidatorExecutions") == 254, "pre-change effective count drift")
    require(scope.get("postChangeEffectiveHistoricalValidatorExecutions") == 23, "post-change effective count drift")
    require(scope.get("duplicateHistoricalValidatorExecutionReduction") == 231, "effective reduction drift")
    require(scope.get("rootDirectV012Validators") == [
        "validate-v0.12.1.0.1-ci-compatibility-repair.sh",
        "validate-v0.12.2.4.1-validator-orchestration-dedup.sh",
    ], "root entrypoint drift")
    require(scope.get("chainedValidatorEntryPoint") == "validate-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.sh", "chain entrypoint drift")
    invariants = value.get("invariants")
    for key in (
        "standaloneCompatibilityValidatorPreserved",
        "allExistingV012ValidatorsRemainReachable",
        "successorPredecessorOrderPreserved",
        "unknownChangeFailsToFullSuite",
    ):
        require(invariants.get(key) is True, f"invariant drift: {key}")
    for key in (
        "historicalValidatorFilesModified",
        "requiredCheckNamesChanged",
        "workflowTriggersChanged",
        "pathRoutingIntroduced",
    ):
        require(invariants.get(key) is False, f"boundary drift: {key}")
    deferred = value.get("deferred")
    require(set(deferred.values()) == {"v0.12.3.1"}, "deferred routing drift")
    require(value.get("packageProducer") == {
        "runsAws": False,
        "runsTerraform": False,
        "readsPrivateEvidence": False,
        "grantsLiveAuthority": False,
    }, "package producer drift")


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
mutate(["scope", "postChangeDirectV012ValidatorCount"], 23)
mutate(["scope", "uniqueChainedValidatorCount"], 21)
mutate(["scope", "rootDirectInvocationReduction"], 0)
mutate(["scope", "duplicateHistoricalValidatorExecutionReduction"], 230)
mutate(["invariants", "allExistingV012ValidatorsRemainReachable"], False)
mutate(["invariants", "historicalValidatorFilesModified"], True)
mutate(["invariants", "requiredCheckNamesChanged"], True)
mutate(["invariants", "workflowTriggersChanged"], True)
mutate(["invariants", "pathRoutingIntroduced"], True)
mutate(["packageProducer", "runsTerraform"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open mutation {index}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--",
     str(checker_path.relative_to(root)), str(test_path.relative_to(root)),
     str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 3, "validator source tracking drift")
require(all(line.startswith("100755 ") for line in tracked), "executable mode drift")
print(f"v0.12.2.4.1 orchestration contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.2.4.1-validator-orchestration.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.4.1-validator-orchestration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.4.1-validator-orchestration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/check-v0.12.2.4.1-validator-orchestration.py" --root "${ROOT_DIR}"

chain_started_at=${SECONDS}
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.sh"
chain_elapsed_seconds=$((SECONDS - chain_started_at))

echo "v0.12.2.4.1 validator orchestration passed offline; unique_chained_validator_count=22; chained_elapsed_seconds=${chain_elapsed_seconds}; no AWS or Terraform command was executed."

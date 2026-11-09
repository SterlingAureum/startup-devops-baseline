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
import json
import os
from pathlib import Path
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.3.1-ci-change-impact-routing.json"
executables = [
    root / "scripts/classify-ci-change-impact.py",
    root / "scripts/test-ci-change-impact.py",
    root / "scripts/check-v0.12.3.1-ci-change-impact-routing.py",
    root / "scripts/validate-ci-documentation-change.sh",
    root / "scripts/validate-demo-api-image-quality-gates.sh",
    root / "scripts/validate-v0.12.3.1-ci-change-impact-routing.sh",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.3.1-ci-change-impact-routing-v1", "schema drift")
    require(value.get("version") == "v0.12.3.1", "version drift")
    require(value.get("implementationBaselineCommit") == "9f78dbfa894079fce272d219f44e498d21a5243f", "baseline drift")
    observed = value.get("observedFullGate")
    require(observed == {
        "completed": True,
        "totalElapsedSeconds": 302,
        "compatibilityElapsedSeconds": 4,
        "v011ElapsedSeconds": 267,
        "v012ElapsedSeconds": 3,
        "validationLogSha256": "35d33c633c0a34480a58cac4dc8dd8c6fcb169a4184ba701c7b804ed5db54e1b",
    }, "observed gate drift")
    routing = value.get("routing")
    require(routing.get("defaultMode") == "full", "default mode drift")
    require(routing.get("manualDispatchMode") == "full", "manual mode drift")
    require(routing.get("unknownOrAmbiguousChangeMode") == "full", "unknown mode drift")
    require(routing.get("documentationMode") == "documentation", "documentation mode drift")
    require(routing.get("renameDetectionDisablesCoreToDocsBypass") is True, "rename boundary drift")
    require(routing.get("validatorBoundDocumentationMode") == "full", "validator-bound documentation drift")
    for key in ("scriptsAreDocumentationOnly", "contractsAreDocumentationOnly", "workflowChangesAreDocumentationOnly"):
        require(routing.get(key) is False, f"unsafe documentation scope: {key}")
    workflow = value.get("workflowBoundary")
    for key in ("secretScanRunsInEveryMode", "imagePublishUsesTargetedGate", "imagePublicationDependsOnTargetedGate", "corePullRequestAndMainPushBothRemainFull"):
        require(workflow.get(key) is True, f"workflow invariant drift: {key}")
    for key in ("validateWorkflowTriggersChanged", "requiredQualityGateJobIdChanged", "documentationModeRunsHelm", "documentationModeRunsTrivy"):
        require(workflow.get(key) is False, f"workflow boundary drift: {key}")
    safety = value.get("safety")
    for key in ("classifierFailureFallsBackToFull", "validatorReferenceReadFailureFallsBackToFull", "emptyDiffFallsBackToFull", "zeroOrMissingBaseFallsBackToFull", "directPushFallsBackToFullUnlessDocumentationOnly"):
        require(safety.get(key) is True, f"fail-closed drift: {key}")
    require(safety.get("terraformStateOperationAuthorized") is False, "state authority drift")
    require(safety.get("awsOperationAuthorized") is False, "AWS authority drift")
    require(value.get("deferred") == {
        "exactMergeTreeAttestedCoreGateReuse": "v0.12.3.2-or-v1.0",
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
mutate(["observedFullGate", "completed"], False)
mutate(["observedFullGate", "v011ElapsedSeconds"], 266)
mutate(["routing", "defaultMode"], "documentation")
mutate(["routing", "unknownOrAmbiguousChangeMode"], "documentation")
mutate(["routing", "scriptsAreDocumentationOnly"], True)
mutate(["routing", "contractsAreDocumentationOnly"], True)
mutate(["routing", "workflowChangesAreDocumentationOnly"], True)
mutate(["routing", "renameDetectionDisablesCoreToDocsBypass"], False)
mutate(["routing", "validatorBoundDocumentationMode"], "documentation")
mutate(["workflowBoundary", "secretScanRunsInEveryMode"], False)
mutate(["workflowBoundary", "imagePublishUsesTargetedGate"], False)
mutate(["workflowBoundary", "corePullRequestAndMainPushBothRemainFull"], False)
mutate(["safety", "classifierFailureFallsBackToFull"], False)
mutate(["safety", "validatorReferenceReadFailureFallsBackToFull"], False)
mutate(["safety", "terraformStateOperationAuthorized"], True)
mutate(["safety", "awsOperationAuthorized"], True)
mutate(["deferred", "historicalValidatorArchival"], "v0.12.3.1")
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open mutation {index}")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", *[str(path.relative_to(root)) for path in executables], str(contract_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == len(executables) + 1, "source tracking drift")
modes = {}
for line in tracked:
    metadata, path = line.split("\t", 1)
    modes[path] = metadata.split()[0]
for path in executables:
    relative = str(path.relative_to(root))
    require(modes.get(relative) == "100755", f"executable mode drift: {relative}")
require(modes.get(str(contract_path.relative_to(root))) == "100644", "contract mode drift")
print(f"v0.12.3.1 routing contract and {len(mutations)} fail-closed mutations passed offline.")
PY

bash -n "${ROOT_DIR}/scripts/validate-ci-documentation-change.sh" "${ROOT_DIR}/scripts/validate-demo-api-image-quality-gates.sh" "${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh"
python3 -m py_compile "${ROOT_DIR}/scripts/classify-ci-change-impact.py" "${ROOT_DIR}/scripts/test-ci-change-impact.py" "${ROOT_DIR}/scripts/check-v0.12.3.1-ci-change-impact-routing.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-ci-change-impact.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/check-v0.12.3.1-ci-change-impact-routing.py" --root "${ROOT_DIR}"

if [[ "${mode}" == "--structure-only" ]]; then
  bash "${ROOT_DIR}/scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh" --structure-only
  echo "v0.12.3.1 structure-only routing validation passed; full history was not executed."
  exit 0
fi

bash "${ROOT_DIR}/scripts/validate-v0.12.2.4.2-quality-gate-history-dedup.sh"
echo "v0.12.3.1 full routing and predecessor validation passed; no AWS or live Terraform operation was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-full}"
if [[ "${mode}" != "full" && "${mode}" != "--structure-only" ]]; then
  echo "Usage: $0 [--structure-only]" >&2
  exit 2
fi

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.3.1.1-release-change-routing-repair.json"
document_path = root / "docs/V0.12.3.1.1_RELEASE_CHANGE_ROUTING_REPAIR.md"
executables = [
    root / "scripts/classify-ci-change-impact.py",
    root / "scripts/test-ci-change-impact.py",
    root / "scripts/check-v0.12.3.1.1-release-change-routing-repair.py",
    root / "scripts/validate-demo-api-release-quality-gates.sh",
    root / "scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.3.1.1-release-change-routing-repair-v1", "schema drift")
    require(value.get("version") == "v0.12.3.1.1", "version drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "f0736dcb8b1e5a36f2faf0594f9ef222ed9268b7", "baseline drift")
    incident = value.get("incident")
    require(incident.get("pullRequest") == 169, "incident PR drift")
    require(incident.get("changedPath") == "apps/demo-api/helm/values/releases/aws-dev.yaml", "incident path drift")
    require(incident.get("failure") == "repository-tree-drift", "incident failure drift")
    require(incident.get("cause") == "exact-release-change-misrouted-to-full-history", "incident cause drift")
    routing = value.get("routing")
    require(routing.get("automaticReleaseMode") == "release", "release mode drift")
    require(routing.get("allowedReleasePaths") == [
        "apps/demo-api/helm/values/releases/aws-dev.yaml",
        "apps/demo-api/helm/values/releases/aws-test.yaml",
        "apps/demo-api/helm/values/releases/aws-prod.yaml",
    ], "release path inventory drift")
    for key in ("exactlyOneChangedPathRequired", "pullRequestSupported", "mainPushSupported"):
        require(routing.get(key) is True, f"routing boundary disabled: {key}")
    require(routing.get("mixedChangeMode") == "full", "mixed changes fail open")
    require(routing.get("unknownOrAmbiguousChangeMode") == "full", "unknown changes fail open")
    require(routing.get("explicitReleaseModeExposedToCallers") is False, "explicit release bypass exposed")
    gate = value.get("releaseGate")
    require(gate.get("historicalRepositoryValidatorsReplayed") is False, "release gate replays history")
    for key in (
        "releaseSchemaValidated", "imageIdentityConsistencyValidated",
        "promotionGovernanceValidated", "allEnvironmentHelmRendersValidated",
        "predecessorStructureValidatorSuccessorAware",
        "predecessorValidatorTopologySuccessorAware",
        "secretScanPreserved", "trivyConfigScanPreserved",
    ):
        require(gate.get(key) is True, f"release gate boundary disabled: {key}")
    safety = value.get("safety")
    require(not any(safety.values()), "unsafe authority enabled")
    require(value.get("deferred") == {
        "postPromotionHistoricalSnapshotIsolation": "v0.12.3.2",
        "historicalValidatorArchival": "v1.0",
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
mutate(["incident", "pullRequest"], 168)
mutate(["incident", "changedPath"], "apps/demo-api/helm/values.yaml")
mutate(["routing", "allowedReleasePaths"], contract["routing"]["allowedReleasePaths"][:2])
mutate(["routing", "exactlyOneChangedPathRequired"], False)
mutate(["routing", "mixedChangeMode"], "release")
mutate(["routing", "unknownOrAmbiguousChangeMode"], "release")
mutate(["routing", "explicitReleaseModeExposedToCallers"], True)
mutate(["releaseGate", "historicalRepositoryValidatorsReplayed"], True)
mutate(["releaseGate", "releaseSchemaValidated"], False)
mutate(["releaseGate", "promotionGovernanceValidated"], False)
mutate(["releaseGate", "predecessorStructureValidatorSuccessorAware"], False)
mutate(["releaseGate", "predecessorValidatorTopologySuccessorAware"], False)
mutate(["releaseGate", "secretScanPreserved"], False)
mutate(["releaseGate", "trivyConfigScanPreserved"], False)
mutate(["safety", "v011ContractRewritten"], True)
mutate(["safety", "terraformStateOperationAuthorized"], True)
mutate(["deferred", "historicalValidatorArchival"], "v0.12.3.1.1")
for index, candidate in enumerate(mutations, 1):
    try:
        validate(candidate)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open mutation {index}")

require(document_path.is_file(), "repair document missing")
document = document_path.read_text()
for phrase in (
    "The promotion commit and release-file update were valid",
    "exactly one",
    "Any additional, renamed, adjacent, unknown, or ambiguous path remains `full`",
    "does not rewrite a v0.11 contract or digest",
):
    require(phrase in document, f"repair boundary missing: {phrase}")

tracked_paths = executables + [contract_path, document_path]
tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", *[
        str(path.relative_to(root)) for path in tracked_paths
    ]],
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

print(f"v0.12.3.1.1 release routing contract and {len(mutations)} fail-closed mutations passed offline.")
PY

bash -n \
  "${ROOT_DIR}/scripts/validate-demo-api-release-quality-gates.sh" \
  "${ROOT_DIR}/scripts/validate-v0.12.3.1.1-release-change-routing-repair.sh"
python3 -m py_compile \
  "${ROOT_DIR}/scripts/classify-ci-change-impact.py" \
  "${ROOT_DIR}/scripts/test-ci-change-impact.py" \
  "${ROOT_DIR}/scripts/check-v0.12.3.1.1-release-change-routing-repair.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-ci-change-impact.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.3.1.1-release-change-routing-repair.py" \
  --root "${ROOT_DIR}"
bash "${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh" --structure-only

if [[ "${mode}" == "--structure-only" ]]; then
  echo "v0.12.3.1.1 structure-only release routing repair passed; historical validators were not executed."
  exit 0
fi

bash "${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh"
echo "v0.12.3.1.1 full release routing repair and predecessor validation passed; no AWS or live Terraform operation was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

bash -n "${BASH_SOURCE[0]}"

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PYTHON'
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.1.0.1-ci-compatibility-repair.json"
foundation_path = root / "delivery/contracts/v0.12.1-remote-state-foundation.json"
historical_path = root / "delivery/contracts/v0.11.9.3.6.7.6-aws-test-guarded-teardown.json"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Missing file: {path.relative_to(root)}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"Expected object: {path.relative_to(root)}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


expected_pins = {
    "infra/terraform/aws/environments/dev/versions.tf": (
        "bab349b5a20400dfaf72355220fb22749b7f09795d14d455d7a200be82480dd3"
    ),
    "infra/terraform/aws/environments/test/versions.tf": (
        "bab349b5a20400dfaf72355220fb22749b7f09795d14d455d7a200be82480dd3"
    ),
    "infra/terraform/aws/environments/prod/versions.tf": (
        "bab349b5a20400dfaf72355220fb22749b7f09795d14d455d7a200be82480dd3"
    ),
    "infra/terraform/aws/runtime-identities/versions.tf": (
        "fd09df4f62d7accaa5515916f8abee4fbd1dc4b30d5dcb8d1578fe2ada26061a"
    ),
}


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.1.0.1-ci-compatibility-repair-v1", "schema drift")
    require(value.get("version") == "v0.12.1.0.1", "version drift")
    require(value.get("status") == "delivered-offline-ci-compatibility-repair", "unsafe status")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.1", "predecessor version drift")
    require(predecessor.get("contract") == str(foundation_path.relative_to(root)), "predecessor path drift")

    failures = value.get("observedFailures")
    require(isinstance(failures, dict), "missing failure classification")
    require(failures.get("missingTfvarsWasCause") is False, "tfvars misclassified as cause")
    require(failures["qualityGate"].get("error") == "teardown-source-drift", "quality failure drift")
    require(
        failures["qualityGate"].get("cause") == "premature-existing-local-root-terraform-floor-change",
        "quality failure cause drift",
    )
    require(failures["terraformValidate"].get("error") == "terraform-fmt-check-exit-3", "fmt failure drift")
    require(
        failures["terraformValidate"].get("path") == "infra/terraform/aws/state-bootstrap/main.tf",
        "fmt path drift",
    )

    floors = value.get("terraformFloorBoundary")
    require(isinstance(floors, dict), "missing Terraform floor boundary")
    require(floors.get("ciVersion") == "1.16.3", "CI Terraform pin drift")
    require(floors.get("stateBootstrapMinimumVersion") == "1.11.0", "bootstrap floor drift")
    require(floors.get("remoteBackendMinimumVersion") == "1.11.0", "remote floor drift")
    require(floors.get("existingLocalRootMinimumVersionDuringV0121") == "1.8.0", "local floor drift")
    require(floors.get("existingRootsStillUseLocalBackend") is True, "existing root migrated early")
    require(
        floors.get("existingRootFloorRaiseOwner")
        == "v0.12.2-pre-migration-successor-compatible-checkpoint",
        "future floor owner drift",
    )
    require(floors.get("floorRaiseCombinedWithStateMigration") is False, "floor raise combined with migration")

    require(value.get("restoredHistoricalPins") == expected_pins, "historical pin inventory drift")

    formatting = value.get("formatRepair")
    require(isinstance(formatting, dict), "missing format repair")
    require(formatting.get("path") == "infra/terraform/aws/state-bootstrap/main.tf", "format path drift")
    require(
        formatting.get("sha256") == "28569c01d928ed664522fb0ca279db0736e88ee392305b2898c2a2f249430be7",
        "format digest drift",
    )
    require(formatting.get("semanticChange") is False, "format repair claims semantic change")
    require(formatting.get("terraformFmtCheckRequiredInCi") is True, "CI fmt gate disabled")

    historical = value.get("historicalBoundary")
    require(isinstance(historical, dict), "missing historical boundary")
    require(not any(historical.values()), "historical contract or authority rewritten")

    execution = value.get("executionBoundary")
    require(isinstance(execution, dict), "missing execution boundary")
    require(execution.get("offlineRepairOnly") is True, "repair is not offline-only")
    for key, enabled in execution.items():
        if key != "offlineRepairOnly":
            require(enabled is False, f"live effect enabled: {key}")

    successor = value.get("successor")
    require(isinstance(successor, dict), "missing successor")
    require(successor.get("version") == "v0.12.1.1", "successor drift")
    require("regenerated" in successor.get("scope", ""), "regeneration boundary missing")

    if check_files:
        foundation = load(foundation_path)
        require(foundation.get("version") == "v0.12.1", "invalid predecessor")
        for path in value["documents"].values():
            require((root / path).is_file(), f"missing document: {path}")
        for path, expected in expected_pins.items():
            require(digest(root / path) == expected, f"historical source pin not restored: {path}")
        require(
            digest(root / formatting["path"]) == formatting["sha256"],
            "formatted state-bootstrap source drift",
        )


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("tfvars blamed", lambda item: item["observedFailures"].__setitem__("missingTfvarsWasCause", True)),
    ("old bootstrap floor", lambda item: item["terraformFloorBoundary"].__setitem__("stateBootstrapMinimumVersion", "1.8.0")),
    ("old remote floor", lambda item: item["terraformFloorBoundary"].__setitem__("remoteBackendMinimumVersion", "1.8.0")),
    ("premature local floor", lambda item: item["terraformFloorBoundary"].__setitem__("existingLocalRootMinimumVersionDuringV0121", "1.11.0")),
    ("early migration", lambda item: item["terraformFloorBoundary"].__setitem__("existingRootsStillUseLocalBackend", False)),
    ("combined migration", lambda item: item["terraformFloorBoundary"].__setitem__("floorRaiseCombinedWithStateMigration", True)),
    ("pin changed", lambda item: item["restoredHistoricalPins"].__setitem__(next(iter(expected_pins)), "0" * 64)),
    ("semantic format change", lambda item: item["formatRepair"].__setitem__("semanticChange", True)),
    ("historical rewrite", lambda item: item["historicalBoundary"].__setitem__("v011ContractRewritten", True)),
    ("executor reauthorized", lambda item: item["historicalBoundary"].__setitem__("v011ExecutorReauthorized", True)),
    ("apply enabled", lambda item: item["executionBoundary"].__setitem__("terraformApplyExecuted", True)),
    ("migration enabled", lambda item: item["executionBoundary"].__setitem__("stateMigrated", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

historical_contract = load(historical_path)
historical_pins = {
    item["path"]: item["sha256"]
    for item in historical_contract["reviewedFiles"]
    if item["path"] in expected_pins
}
require(historical_pins == expected_pins, "v0.11 historical pins were rewritten")

foundation = load(foundation_path)
terraform = foundation["terraform"]
require(terraform.get("bootstrapMinimumVersion") == "1.11.0", "foundation bootstrap floor mismatch")
require(terraform.get("existingRootMinimumVersionDuringV0121") == "1.8.0", "foundation local floor mismatch")
require(terraform.get("remoteBackendMinimumVersion") == "1.11.0", "foundation remote floor mismatch")

main_tf = (root / contract["formatRepair"]["path"]).read_text()
canonical_identifier = (
    'identifiers = ["arn:${data.aws_partition.current.partition}:iam::'
    '${data.aws_caller_identity.current.account_id}:root"]'
)
require(canonical_identifier in main_tf, "canonical KMS principal collection missing")
require('identifiers = [\n        "arn:${data.aws_partition.current.partition}' not in main_tf, "noncanonical principal collection retained")

docs = (root / contract["documents"]["repair"]).read_text()
for phrase in (
    "was unrelated to the absent private tfvars",
    "preserves the immutable v0.11 contract",
    "must not be applied",
    "No AWS, Terraform init, plan",
):
    require(phrase in docs, f"repair document missing boundary: {phrase}")

print("v0.12.1.0.1 exact historical pins, scoped Terraform floors and 12 negative mutations passed offline.")
PYTHON

"${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.6-guarded-aws-test-teardown.sh"
"${ROOT_DIR}/scripts/validate-v0.12.1-remote-state-foundation.sh"

if command -v terraform >/dev/null 2>&1; then
  terraform fmt -check -recursive "${ROOT_DIR}/infra/terraform/aws"
else
  echo "SKIP: terraform unavailable; terraform-validate CI must run the exact fmt check."
fi

echo "v0.12.1.0.1 CI compatibility repair passed; no live operation was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.4.1.1-gitleaks-evidence-field-repair.json"
REPAIRED_EVIDENCE="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.4.1-aws-test-gitops-bootstrap-execution-evidence.json"
REPAIRED_VALIDATOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.4.1-aws-test-gitops-bootstrap-execution-evidence.sh"
PREDECESSOR="${REPAIRED_VALIDATOR}"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" \
  "${CONTRACT}" \
  "${REPAIRED_EVIDENCE}" \
  "${REPAIRED_VALIDATOR}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract_path = Path(sys.argv[2])
evidence_path = Path(sys.argv[3])
validator_path = Path(sys.argv[4])
contract = json.loads(contract_path.read_text())
evidence = json.loads(evidence_path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.7.4.1.1"
assert contract["predecessor"] == "v0.11.9.3.6.7.4.1"
assert contract["status"] == "gitleaks-evidence-field-false-positive-repaired"
assert contract["implementationBaselineCommit"] == "121d8328d36ace3c18e2b85a3bc47006432cd8ab"
assert contract["nextCheckpoint"] == (
    "merge-repair-then-design-guarded-aws-test-root-application-deploy"
)

finding = contract["scannerFinding"]
assert finding == {
    "scanner": "gitleaks",
    "ruleId": "generic-api-key",
    "findingCount": 1,
    "commit": "121d8328d36ace3c18e2b85a3bc47006432cd8ab",
    "path": "delivery/contracts/v0.11.9.3.6.7.4.1-aws-test-gitops-bootstrap-execution-evidence.json",
    "reportedLine": 155,
    "reportedValueRedacted": True,
    "classification": "false-positive-sha256-fingerprint",
    "credentialMaterialCommitted": False,
}

repair = contract["repair"]
assert repair["replacementProperty"] == "metadataObservationSha256"
assert repair["digestAlgorithm"] == "SHA-256"
assert repair["digestUnchanged"] is True
assert repair["evidenceMeaningUnchanged"] is True
assert repair["allowlistChanged"] is False
assert repair["broadSuppressionAdded"] is False
assert repair["predecessorValidatorStrengthened"] is True

inputs = contract["repositoryInputs"]
assert inputs["failedEvidenceContract"] == {
    "path": finding["path"],
    "preRepairSha256": "eff97c7fbf3a7149d38b42e89cdfd2617d79cc6bf8f8aba1a31e08b933a7732f",
    "repairedSha256": "bc323b3a50dcf4bcec79e26130470dbfb73c98756052b921425a04fa6f105052",
}
assert inputs["strengthenedEvidenceValidator"] == {
    "path": "scripts/validate-v0.11.9.3.6.7.4.1-aws-test-gitops-bootstrap-execution-evidence.sh",
    "sha256": "55fe56674d388f430fa7f6816e7b37cb6d457c5195f0f8dfc3c4415ce42da045",
}
assert inputs["unchangedScannerAllowlist"] == {
    "path": ".gitleaksignore",
    "sha256": "a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca",
}
assert inputs["repairValidator"]["path"] == (
    "scripts/validate-v0.11.9.3.6.7.4.1.1-gitleaks-evidence-field-repair.sh"
)
assert digest(evidence_path) == inputs["failedEvidenceContract"]["repairedSha256"]
assert digest(validator_path) == inputs["strengthenedEvidenceValidator"]["sha256"]
assert digest(root / ".gitleaksignore") == inputs["unchangedScannerAllowlist"]["sha256"]

stable = evidence["privateArtifactInventory"]["stableReadOnlyOutputs"]
assert stable[repair["replacementProperty"]] == repair["digest"]
assert repair["digest"] == "b56815ad21d9c784844929c040d9ec27a83ad016bdfff7405798801b5ae3a1ac"
assert len(stable) == 9
assert stable["matchedBeforeAndAfter"] is True

assert not any(contract["operationBoundary"].values())
assert not any(contract["packageProducer"].values())
PY

"${PREDECESSOR}"

echo "v0.11.9.3.6.7.4.1.1 Gitleaks evidence-field repair passed; no live operation was executed."

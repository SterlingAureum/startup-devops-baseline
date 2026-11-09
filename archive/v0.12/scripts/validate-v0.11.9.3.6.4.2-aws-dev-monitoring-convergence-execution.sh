#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.6.4.2"
assert contract["version"] == "v0.11.9.3.6.4.2"
assert contract["predecessor"] == "v0.11.9.3.6.4.1"
assert contract["status"] == "aws-dev-monitoring-convergence-execution-recorded"
assert contract["implementationBaselineCommit"] == "6421e140b3ac9a89e806896ef627b258ac201e3b"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.5-aws-dev-runtime-qualification"

approval = contract["approval"]
assert approval["scope"] == "aws-dev monitoring convergence repair"
assert approval["timeWindowScoped"] is True
assert all(approval[key] is False for key in (
    "rootRedeployApproved",
    "runtimeQualificationApproved",
    "trafficApproved",
    "promotionApproved",
    "teardownApproved",
))

before = contract["preExecutionState"]
assert before == {
    "controlPlaneCommit": "6421e140b3ac9a89e806896ef627b258ac201e3b",
    "clusterStatus": "ACTIVE",
    "clusterVersion": "1.36",
    "kubernetesReadyz": "ok",
    "rootApplicationStatus": "Synced/Healthy",
    "demoApplicationStatus": "Synced/Healthy",
    "demoWorkloadKind": "Deployment",
    "demoDeploymentReady": True,
    "databaseReady": True,
    "monitoringApplicationStatus": "Synced/Degraded",
    "grafanaSecretStatus": "absent",
    "grafanaDeploymentReady": False,
    "convergenceState": "missing-secret-repair-required",
    "executionAuthorizedByPreflight": False,
}

execution = contract["execution"]
assert execution["entrypoint"] == "scripts/execute-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.py"
assert execution["phase"] == "execute"
assert execution["executorExit"] == 0
assert re.fullmatch(r"[0-9a-f]{64}", execution["privateLogSha256"])
assert execution["privateLogSha256"] == "11905ff7f03cc121eda72bcf5ece4db9a303c9496c88ea9fbed331564e9a6e4d"
assert execution["privateLogCommitted"] is False
assert execution["privateLogModeConfigured"] == "0600"
assert execution["privateLogModeIndependentlyRestated"] is False
assert execution["credentialValuesPrinted"] is False
assert execution["credentialValuesCommitted"] is False

after = contract["postExecutionState"]
assert after["controlPlaneCommit"] == "6421e140b3ac9a89e806896ef627b258ac201e3b"
assert after["candidateReleaseId"] == "demo-api-cf0a6bcbc466-cdffd3d71763"
assert after["grafanaSecretAction"] == "created"
assert after["grafanaSecretPresent"] is True
assert after["grafanaSecretValuesExposed"] is False
assert after["grafanaDeployment"] == {
    "generation": 1,
    "observedGeneration": 1,
    "replicas": 1,
    "readyReplicas": 1,
    "updatedReplicas": 1,
    "availableReplicas": 1,
}
assert after["monitoringApplication"] == {
    "sync": "Synced",
    "health": "Healthy",
    "chart": "kube-prometheus-stack",
    "targetRevision": "88.5.0",
}
assert all(after[key] is False for key in (
    "rootApplicationRedeployed",
    "runtimeQualified",
    "trafficGenerated",
    "progressiveDeliveryPromoted",
    "automaticTeardownExecuted",
))

boundary = contract["evidenceBoundary"]
assert boundary["rawExecutorLogStoredOutsideRepository"] is True
assert boundary["completionTimestampClaimed"] is False
assert all(boundary[key] is False for key in (
    "awsAccountCommitted",
    "eksArnCommitted",
    "clusterEndpointCommitted",
    "secretManifestCommitted",
    "secretDataCommitted",
))
assert all(value is False for value in contract["packageProducer"].values())

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "private_log=/tmp" not in serialized
assert "admin-password" not in serialized

for relative, marker in (
    ("README.md", "v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution"),
    ("CHANGELOG.md", "## v0.11.9.3.6.4.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.4.2"),
    ("docs/V0.11.9.3.6.4.2_AWS_DEV_MONITORING_CONVERGENCE_EXECUTION.md", execution["privateLogSha256"]),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.4.2 approved scope, log identity, Grafana readiness and monitoring convergence evidence passed.")
PY

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.2-aws-dev-monitoring-convergence-execution.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.4.2 monitoring convergence execution evidence passed; no live operation was executed."

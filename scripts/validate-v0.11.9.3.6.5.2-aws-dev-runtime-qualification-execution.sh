#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair.sh"

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

assert contract["schemaVersion"] == "v0.11.9.3.6.5.2"
assert contract["version"] == "v0.11.9.3.6.5.2"
assert contract["predecessor"] == "v0.11.9.3.6.5.1.1"
assert contract["status"] == "aws-dev-runtime-qualification-execution-recorded"
commit = "489c8036b21ee465160a1de0973a24b95b73dbfb"
release_id = "demo-api-cf0a6bcbc466-cdffd3d71763"
empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
assert contract["implementationBaselineCommit"] == commit
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "review-separate-aws-dev-to-aws-test-release-promotion"

preflight = contract["preflight"]
assert preflight == {
    "status": "aws-dev-runtime-qualification-inputs-verified",
    "executorExit": 0,
    "controlPlaneCommit": commit,
    "clusterStatus": "ACTIVE",
    "clusterVersion": "1.36",
    "kubernetesReadyz": "ok",
    "rootApplicationStatus": "Synced/Healthy",
    "demoApplicationStatus": "Synced/Healthy",
    "monitoringApplicationStatus": "Synced/Healthy",
    "demoDeploymentReady": True,
    "databaseReady": True,
    "grafanaDeploymentReady": True,
    "prometheusDemoTargetUp": True,
    "candidateReleaseId": release_id,
    "qualificationEndUtc": "2026-09-10T14:48:29Z",
    "remainingWindowSeconds": 12911,
    "executionAuthorized": False,
    "trafficGenerated": False,
    "runtimeQualified": False,
    "privateResultSha256": "6f03faaa8d2d5e398cf41f1431a5ba430eebd2c8dc7e137baa078aec63269353",
    "privateStderrSha256": empty_sha,
    "privateStderrEmpty": True,
}

approval = contract["approval"]
assert approval["scope"] == "aws-dev runtime qualification"
assert approval["timeWindowEndUtc"] == "2026-09-10T14:48:29Z"
assert approval["runtimeQualificationApproved"] is True
assert approval["normalTrafficApproved"] is True
assert approval["maximumRequestCount"] == 54
assert approval["allowedPaths"] == ["/health", "/ready", "/version"]
assert approval["prometheusSloAndAlertValidationApproved"] is True
assert approval["finalRuntimeHealthCheckApproved"] is True
for key in (
    "faultInjectionApproved",
    "rootOrMonitoringMutationApproved",
    "rolloutOrAnalysisRunApproved",
    "progressivePromotionApproved",
    "teardownApproved",
):
    assert approval[key] is False

execution = contract["execution"]
assert execution == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.5-aws-dev-runtime-qualification.py",
    "phase": "execute",
    "executorExit": 0,
    "status": "aws-dev-runtime-qualification-complete",
    "controlPlaneCommit": commit,
    "candidateReleaseId": release_id,
    "boundedRequestCount": 54,
    "trafficGenerated": True,
    "runtimeQualified": True,
    "requestSeriesReady": True,
    "availabilitySloPassed": True,
    "latencySloPassed": True,
    "criticalAlertsFiring": False,
    "finalRuntimeHealthy": True,
    "progressiveDeliveryPromoted": False,
    "automaticTeardownExecuted": False,
    "qualificationEndUtc": "2026-09-10T14:48:29Z",
    "privateResultSha256": "2d56815b00bbcd050966b761828a093ee9fee7ab0aa63b15c77ebfa967c07d61",
    "privateStderrSha256": empty_sha,
    "privateStderrEmpty": True,
}

evidence = contract["privateEvidence"]
assert evidence["directoryModeRestated"] == "0700"
assert evidence["resultFileModeRestated"] == "0600"
assert evidence["stderrFileModeRestated"] == "0600"
assert evidence["rawFilesStoredOutsideRepository"] is True
assert evidence["completionTimestampClaimed"] is False
for key in (
    "rawFilesCommitted",
    "awsAccountCommitted",
    "eksArnCommitted",
    "clusterEndpointCommitted",
    "privatePathCommitted",
):
    assert evidence[key] is False

boundary = contract["operationBoundary"]
assert boundary["runtimeQualificationExecuted"] is True
assert boundary["boundedNormalTrafficGenerated"] is True
for key in (
    "faultInjected",
    "rootOrMonitoringChanged",
    "rolloutOrAnalysisRunExecuted",
    "progressiveDeliveryPromoted",
    "awsTestPromotionExecuted",
    "teardownExecuted",
):
    assert boundary[key] is False
assert all(value is False for value in contract["packageProducer"].values())

for digest in (
    preflight["privateResultSha256"],
    preflight["privateStderrSha256"],
    execution["privateResultSha256"],
    execution["privateStderrSha256"],
):
    assert re.fullmatch(r"[0-9a-f]{64}", digest)

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
for forbidden in ("arn:aws:", "/tmp/", "eks.amazonaws.com", "admin-password"):
    assert forbidden not in serialized

for relative, marker in (
    ("README.md", "v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution"),
    ("CHANGELOG.md", "## v0.11.9.3.6.5.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.5.2"),
    ("docs/V0.11.9.3.6.5.2_AWS_DEV_RUNTIME_QUALIFICATION_EXECUTION.md", execution["privateResultSha256"]),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.5.2 exact-main, bounded traffic, SLO and private evidence contracts passed.")
PY

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.2-aws-dev-runtime-qualification-execution.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.5.2 runtime qualification execution evidence passed; no live operation or traffic was executed."

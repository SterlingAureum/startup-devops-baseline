#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.json"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract_path = Path(sys.argv[2])
contract = json.loads(contract_path.read_text())

assert contract["schemaVersion"] == "v0.11.9.3.5.1"
assert contract["version"] == "v0.11.9.3.5.1"
assert contract["predecessor"] == "v0.11.9.3.5"
assert contract["status"] == "aws-dev-live-rehearsal-read-only-preflight-executed-ready"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6-aws-dev-live-rehearsal-create-plan"

control = contract["controlPlane"]
assert control == {
    "branch": "main",
    "commit": "cd5aac1f2ab4363fe05ac3507d2abe0a15f54422",
    "pullRequestNumber": 75,
    "pullRequestHeadCommit": "b0711ea76dbecbc1b9883a3b7fee8dc89dab696c",
    "pullRequestBaseCommit": "1ede302a833074c567da89b15875c0ad3a8f2c69",
    "mergedMainCommit": "cd5aac1f2ab4363fe05ac3507d2abe0a15f54422",
    "mergedAt": "2026-09-08T10:45:31Z",
    "successfulMainValidateRunId": "34217223349",
    "successfulMainValidateConclusion": "success",
    "supersededMainValidateRunId": "34217132194",
    "supersededMainValidateConclusion": "cancelled",
    "supersededBySameCommitConcurrency": True,
}

candidate = contract["selectedCandidate"]
assert candidate == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
    "awsDevReleaseFileSha256": "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46",
}
release = root / "apps/demo-api/helm/values/releases/aws-dev.yaml"
assert hashlib.sha256(release.read_bytes()).hexdigest() == candidate["awsDevReleaseFileSha256"]

private = contract["privateEvidence"]
assert private == {
    "rawPlanCommitted": False,
    "rawPreflightResultCommitted": False,
    "awsAccountIdCommitted": False,
    "planSha256": "56eef1a83217d9d5b2287ac295dcc0fa915313b3d23f3f494d20ab56b151a66b",
    "preflightResultSha256": "ad91ef09cd481b9d32efbfb2fbe91ca8e552827bda369f063bf9e02fc499e068",
    "planParentMode": "0700",
    "evidenceDirectoryMode": "0700",
    "planFileMode": "0600",
    "preflightResultFileMode": "0600",
}
for key in ("planSha256", "preflightResultSha256"):
    assert re.fullmatch(r"[0-9a-f]{64}", private[key])
assert private["planSha256"] != private["preflightResultSha256"]

result = contract["preflightResult"]
assert result["status"] == "ready-for-separate-aws-dev-create-approval"
assert result["controlPlaneCommit"] == control["commit"]
assert result["region"] == "us-east-1"
assert result["activeRehearsalClusters"] == []
assert result["blockedReason"] is None
assert result["checksPerformed"] == [
    "private-plan-permissions",
    "clean-exact-main",
    "candidate-source-ancestry",
    "aws-dev-release-identity",
    "aws-caller-identity",
    "eks-rehearsal-cluster-inventory",
    "local-terraform-state-summary",
]
assert result["terraformStateSummary"] == {
    "exists": True,
    "resourceBlocks": 0,
    "resourceInstances": 0,
    "containsDevEksCluster": False,
}
assert result["mutationsPerformed"] == []
assert result["executionAuthorized"] is False
assert result["nextAction"] == "review-separate-create-approval"

operation = contract["operationBoundary"]
assert operation["completedAwsReads"] == [
    "sts get-caller-identity",
    "eks list-clusters",
]
for key in (
    "terraformCommandExecuted",
    "terraformApplyExecuted",
    "kubernetesCommandExecuted",
    "argocdCommandExecuted",
    "environmentCreated",
    "trafficGenerated",
    "remoteFaultReplayed",
    "teardownExecuted",
    "awsTestPromotionExecuted",
):
    assert operation[key] is False, key

doc = root / "docs/V0.11.9.3.5.1_AWS_DEV_LIVE_REHEARSAL_PREFLIGHT_EXECUTION.md"
for path in (contract_path, doc):
    text = path.read_text()
    assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text), path
    assert "aws_account_id" not in text, path

for relative, marker in (
    ("README.md", "v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution"),
    ("CHANGELOG.md", "## v0.11.9.3.5.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.5.1"),
    ("docs/V0.11.9.3.5.1_AWS_DEV_LIVE_REHEARSAL_PREFLIGHT_EXECUTION.md", "Redacted evidence record"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.5.1 redacted fingerprints, ready inventory and no-mutation execution boundaries passed.")
PY

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.5.1 read-only preflight execution evidence passed; no live operation was executed."

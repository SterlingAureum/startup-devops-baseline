#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.json"
TEMPLATE="${ROOT_DIR}/delivery/examples/v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.json"
CHECKER="${ROOT_DIR}/scripts/check-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.py"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${CHECKER}" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
checker_path = Path(sys.argv[3])

assert contract["schemaVersion"] == "v0.11.9.3.6"
assert contract["version"] == "v0.11.9.3.6"
assert contract["predecessor"] == "v0.11.9.3.5.1"
assert contract["status"] == "aws-dev-live-rehearsal-create-plan-implemented-live-create-blocked"
assert contract["implementationBaselineCommit"] == "05270a186fcf8aa5b82ff4d1e44ea467f4a1498d"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor"

preflight = contract["preflightEvidence"]
assert preflight == {
    "contract": "delivery/contracts/v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution.json",
    "controlPlaneCommit": "cd5aac1f2ab4363fe05ac3507d2abe0a15f54422",
    "planSha256": "56eef1a83217d9d5b2287ac295dcc0fa915313b3d23f3f494d20ab56b151a66b",
    "resultSha256": "ad91ef09cd481b9d32efbfb2fbe91ca8e552827bda369f063bf9e02fc499e068",
    "status": "ready-for-separate-aws-dev-create-approval",
    "activeRehearsalClusters": [],
    "terraformResourceBlocks": 0,
    "terraformResourceInstances": 0,
    "freshPreflightRequiredAfterImplementationMerge": True,
}

private = contract["privatePlan"]
assert private == {
    "template": "delivery/examples/v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.json",
    "checker": "scripts/check-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.py",
    "mode": "offline-create-plan-only",
    "fileMode": "0600",
    "outsideRepository": True,
    "postImplementationMainCommitRequired": True,
    "rawCredentialsAllowed": False,
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

assert contract["target"] == {
    "environment": "aws-dev",
    "region": "us-east-1",
    "clusterName": "startup-devops-baseline-dev",
    "terraformDirectory": "infra/terraform/aws/environments/dev",
    "terraformStatePath": "infra/terraform/aws/environments/dev/terraform.tfstate",
    "createEntrypoint": "scripts/apply-aws-dev.sh",
    "gitopsBootstrapEntrypoint": "scripts/bootstrap-eks-argocd.sh",
    "rootDeployEntrypoint": "scripts/deploy-aws-dev-root-app.sh",
    "destroyEntrypoint": "scripts/destroy-aws-dev.sh",
    "residualCostAuditEntrypoint": "scripts/validate-aws-cost-cleanup.sh",
}
assert contract["creationControls"] == {
    "environmentConfirmationVariable": "CONFIRM_AWS_DEV_APPLY",
    "environmentConfirmationValue": "create-ephemeral-aws-dev",
    "expectedAccountVariable": "EXPECTED_AWS_ACCOUNT_ID",
    "interactiveTerraformPlanConfirmation": "apply-aws-dev",
    "terraformPlanReplacementAllowed": False,
    "terraformPlanDestroyAllowed": False,
    "nonemptyStateAllowed": False,
    "movingMainAllowed": False,
}
assert contract["costControl"] == {
    "currency": "USD",
    "maximumActiveRehearsalEksEnvironments": 1,
    "maximumSessionHours": 8,
    "maximumReviewedSessionBudgetUsd": 50,
    "reviewedEstimateRequired": True,
    "reviewedSessionBudgetRequired": True,
    "automaticBudgetEnforcement": False,
    "automaticTeardown": False,
    "teardownRequiresSeparateApproval": True,
    "deadlineStopsQualificationAndRequiresReview": True,
    "residualCostAuditRequired": True,
}

assert contract["sequence"] == [
    "fresh-read-only-preflight",
    "separate-live-create-approval",
    "guarded-terraform-plan",
    "interactive-plan-confirmation",
    "terraform-apply",
    "eks-api-readiness",
    "argocd-bootstrap",
    "root-application-deploy",
    "aws-dev-runtime-observability-qualification",
    "preserve-private-evidence",
    "separate-teardown-review",
    "destroy-and-residual-cost-audit",
]

operation = contract["operationBoundary"]
assert operation["planValidationOnly"] is True
for key in (
    "awsCommandAllowed",
    "terraformCommandAllowed",
    "kubernetesCommandAllowed",
    "argocdCommandAllowed",
    "environmentCreationAllowed",
    "trafficGenerationAllowed",
    "remoteFaultReplayAllowed",
    "automaticTeardownAllowed",
    "awsTestPromotionAllowed",
):
    assert operation[key] is False, key
assert all(value is False for value in contract["producerExecution"].values())

# The plan checker must remain pure parsing/validation. The subprocess import
# belongs only to the test harness used to exercise its CLI.
tree = ast.parse(checker_path.read_text())
imports = {
    alias.name
    for node in ast.walk(tree)
    if isinstance(node, (ast.Import, ast.ImportFrom))
    for alias in node.names
}
assert not imports.intersection({"boto3", "botocore", "subprocess", "os"})
for node in ast.walk(tree):
    assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))

for relative, marker in (
    ("README.md", "v0.11.9.3.6-aws-dev-live-rehearsal-create-plan"),
    ("CHANGELOG.md", "## v0.11.9.3.6"),
    ("docs/ROADMAP.md", "v0.11.9.3.6"),
    ("docs/V0.11.9.3.6_AWS_DEV_LIVE_REHEARSAL_CREATE_PLAN.md", "Failure-stop rules"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6 private create-plan, cost/time and no-execution boundaries passed.")
PY

if PYTHONDONTWRITEBYTECODE=1 python3 "${CHECKER}" \
  --plan "${TEMPLATE}" >/dev/null 2>&1; then
  echo "Repository create-plan template unexpectedly passed with placeholders." >&2
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6 aws-dev create-plan validation passed; no live operation was executed."

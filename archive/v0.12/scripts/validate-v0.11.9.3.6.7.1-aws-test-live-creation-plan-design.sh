#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.json"
TEMPLATE="${ROOT_DIR}/delivery/examples/v0.11.9.3.6.7.1-aws-test-live-creation-plan.json"
CHECKER="${ROOT_DIR}/scripts/check-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7-aws-test-live-creation-preflight.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${CHECKER}" "${TEMPLATE}" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
checker_path = Path(sys.argv[3])
template = json.loads(Path(sys.argv[4]).read_text())

version = "v0.11.9.3.6.7.1"
baseline = "05f481b5ce06705e130e5674175028f6645a63e1"
preflight_sha = "e1cf8f0fed49292b45ea3f79f5f43b51ce879f01e3d6f64753b429cab41b60f2"
empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
profile_sha = "03c7447a6cba2c01f4ac0da85c9cd6c68f84b3cfeb807e2f3d58bab81ffdc497"
backend_sha = "374c263bc0de2200590d27c33707bfc426bc24fe0d6a3db4dd587a89cd4d9192"
wrapper_sha = "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114"
release_id = "demo-api-cf0a6bcbc466-cdffd3d71763"

assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.7"
assert contract["status"] == (
    "guarded-aws-test-private-creation-plan-design-implemented-live-plan-blocked"
)
assert contract["implementationBaselineCommit"] == baseline
assert contract["terraformPlanAuthorized"] is False
assert contract["terraformApplyAuthorized"] is False
assert contract["environmentCreationAuthorized"] is False

reviewed = contract["reviewedPreflight"]
assert reviewed == {
    "controlPlaneCommit": baseline,
    "resultSha256": preflight_sha,
    "stderrSha256": empty_sha,
    "status": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
    "accountVerified": True,
    "accountIdEmitted": False,
    "activeRehearsalEnvironmentCount": 0,
    "terraformBackendKind": "local",
    "terraformStateExists": True,
    "terraformStateResourceBlockCount": 0,
    "terraformStateResourceInstanceCount": 0,
    "devTestReleaseEqual": True,
    "awsProdReleaseHeld": True,
    "releaseId": release_id,
    "terraformCommandExecuted": False,
    "terraformPlanExecuted": False,
    "terraformApplyExecuted": False,
    "environmentCreationAuthorized": False,
    "mutationExecuted": False,
    "awsTestCreated": False,
    "freshPostMergePreflightRequired": True,
}

private_plan = contract["privatePlan"]
assert private_plan == {
    "template": "delivery/examples/v0.11.9.3.6.7.1-aws-test-live-creation-plan.json",
    "checker": "scripts/check-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py",
    "mode": "offline-private-aws-test-create-plan-design",
    "outsideRepository": True,
    "directoryMode": "0700",
    "fileMode": "0600",
    "postImplementationProtectedMainCommitRequired": True,
    "freshPreflightResultSha256Required": True,
    "privateAccountRequired": True,
    "privateManagementIpv4Required": True,
    "privateTerraformTfvarsSha256Required": True,
    "rawCredentialsAllowed": False,
}

assert contract["selectedRelease"] == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "releaseId": release_id,
}

infra = contract["infrastructure"]
assert infra == {
    "targetEnvironment": "aws-test",
    "region": "us-east-1",
    "clusterName": "startup-devops-baseline-test",
    "terraformDirectory": "infra/terraform/aws/environments/test",
    "terraformBackendKind": "local",
    "terraformStatePath": "infra/terraform/aws/environments/test/terraform.tfstate",
    "backendDeclarationSha256": backend_sha,
    "qualificationProfilePath": "delivery/profiles/aws-test-observability-qualification.tfvars",
    "qualificationProfileSha256": profile_sha,
    "localTerraformTfvarsPrivateFingerprintRequired": True,
    "ownerTagReviewRequired": True,
    "qualificationCapacityReviewRequired": True,
}
for relative, expected in (
    ("infra/terraform/aws/environments/test/backend.tf", backend_sha),
    ("delivery/profiles/aws-test-observability-qualification.tfvars", profile_sha),
    ("scripts/apply-aws-test.sh", wrapper_sha),
):
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected

entrypoint = contract["entrypointBoundary"]
assert entrypoint["legacyPlanAndApplyWrapper"] == "scripts/apply-aws-test.sh"
assert entrypoint["legacyPlanAndApplyWrapperSha256"] == wrapper_sha
assert entrypoint["legacyWrapperInvocationAllowed"] is False
assert entrypoint["historicalFeaturePlannerInvocationAllowed"] is False
assert entrypoint["futureGuardedPlanExecutorCheckpoint"] == "v0.11.9.3.6.7.2"

policy = contract["terraformPlanPolicy"]
assert policy["mode"] == "create"
assert policy["allowedActionVectors"] == [["create"], ["read"], ["no-op"]]
for key in (
    "atLeastOneCreateRequired",
    "emptyStateRequired",
    "absentTestClusterRequired",
    "savedBinaryPlanRequired",
    "privateJsonAndTextRenderingRequired",
    "machineGateRequired",
    "humanCostAndResourceReviewRequired",
):
    assert policy[key] is True, key
for key in (
    "updateAllowed",
    "deleteAllowed",
    "replacementAllowed",
    "unknownActionAllowed",
    "applyDuringPlanPhaseAllowed",
):
    assert policy[key] is False, key
assert policy["reviewTtlSeconds"] == 3600

cost = contract["costControl"]
assert cost == {
    "currency": "USD",
    "maximumActiveRehearsalEksEnvironments": 1,
    "maximumSessionHours": 8,
    "maximumReviewedSessionBudgetUsd": 50,
    "reviewedCurrentPricingEstimateRequired": True,
    "automaticBudgetEnforcement": False,
    "automaticTeardown": False,
    "teardownRequiresSeparateApproval": True,
    "residualCostAuditRequired": True,
}

operation = contract["operationBoundary"]
assert operation["offlinePlanDesignValidationOnly"] is True
assert all(value is False for key, value in operation.items() if key != "offlinePlanDesignValidationOnly")
assert all(value is False for value in contract["packageProducer"].values())

assert template["schema_version"] == version
assert template["implementation_baseline_commit"] == baseline
assert template["reviewed_preflight"]["result_sha256"] == preflight_sha
assert template["reviewed_preflight"]["stderr_sha256"] == empty_sha
assert template["candidate"]["release_id"] == release_id
assert template["plan_controls"]["terraform_apply_allowed"] is False
assert template["plan_controls"]["allowed_action_vectors"] == [["create"], ["read"], ["no-op"]]

# The checker is pure offline parsing/validation and must not gain command or
# environment access. Its CLI reads only the explicitly supplied plan file.
tree = ast.parse(checker_path.read_text())
imports = {
    alias.name
    for node in ast.walk(tree)
    if isinstance(node, (ast.Import, ast.ImportFrom))
    for alias in node.names
}
assert not imports.intersection({"boto3", "botocore", "subprocess", "os", "socket"})
for node in ast.walk(tree):
    assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert "amazonaws.com" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.7.1 guarded aws-test private creation-plan design"),
    ("CHANGELOG.md", "## v0.11.9.3.6.7.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.7.1"),
    ("docs/V0.11.9.3.6.7.1_GUARDED_AWS_TEST_PRIVATE_CREATION_PLAN_DESIGN.md", "terraform_plan_authorized=false"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.7.1 reviewed-preflight, private-plan and no-live-plan boundaries passed.")
PY

if PYTHONDONTWRITEBYTECODE=1 python3 "${CHECKER}" \
  --plan "${TEMPLATE}" >/dev/null 2>&1; then
  echo "Repository aws-test creation-plan template unexpectedly passed placeholders." >&2
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile "${CHECKER}" "${TESTS}"
python3 -m json.tool "${CONTRACT}" >/dev/null
python3 -m json.tool "${TEMPLATE}" >/dev/null

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.sh"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.7.1 aws-test private creation-plan design passed; no live operation was executed."

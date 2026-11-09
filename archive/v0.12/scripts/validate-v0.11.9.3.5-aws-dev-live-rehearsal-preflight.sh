#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.5-aws-dev-live-rehearsal-preflight.json"
PLAN_TEMPLATE="${ROOT_DIR}/delivery/examples/v0.11.9.3.5-aws-dev-live-rehearsal-plan.json"
PLAN_CHECKER="${ROOT_DIR}/scripts/check-v0.11.9.3.5-aws-dev-live-rehearsal-plan.py"
PREFLIGHT="${ROOT_DIR}/scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.py"
AWS_TEST_SUCCESSOR_CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.6.6.1-aws-test-release-successor.py"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${PREFLIGHT}" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys

import yaml


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
preflight_path = Path(sys.argv[3])

assert contract["schemaVersion"] == "v0.11.9.3.5"
assert contract["version"] == "v0.11.9.3.5"
assert contract["predecessor"] == "v0.11.9.3.4"
assert contract["status"] == "aws-dev-live-rehearsal-read-only-preflight-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "1ede302a833074c567da89b15875c0ad3a8f2c69"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.5.1-aws-dev-live-rehearsal-preflight-execution"

assert contract["implementationBaselineEvidence"] == {
    "pullRequestNumber": 74,
    "pullRequestUrl": "https://github.com/SterlingAureum/startup-devops-baseline/pull/74",
    "pullRequestHeadCommit": "6dca1cd04ea19aa0cb9cb12e5d023f83ff50fc01",
    "pullRequestBaseCommit": "071e32914a304f6e3ca006f0f60f54b21b5d810d",
    "mergedMainCommit": "1ede302a833074c567da89b15875c0ad3a8f2c69",
    "mergedAt": "2026-09-08T09:11:53Z",
    "mainValidateRunId": "34208660392",
    "mainValidateConclusion": "success",
    "awsDevReleaseFileSha256": "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46",
}

private_plan = contract["privatePlan"]
assert private_plan["template"] == "delivery/examples/v0.11.9.3.5-aws-dev-live-rehearsal-plan.json"
assert private_plan["checker"] == "scripts/check-v0.11.9.3.5-aws-dev-live-rehearsal-plan.py"
assert private_plan["mode"] == "read-only-preflight"
assert private_plan["fileMode"] == "0600"
assert private_plan["evidenceDirectoryOutsideRepository"] is True
assert private_plan["evidenceDirectoryPrivate"] is True
assert private_plan["postImplementationMainCommitRequired"] is True
assert private_plan["rawCredentialsAllowed"] is False

preflight = contract["preflight"]
assert preflight["entrypoint"] == "scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py"
assert preflight["confirmationEnvironmentVariable"] == "CONFIRM_AWS_DEV_PREFLIGHT"
assert preflight["confirmationValue"] == "observe-reviewed-aws-dev-rehearsal"
assert preflight["requiredGitBranch"] == "main"
assert preflight["cleanWorktreeRequired"] is True
assert preflight["headMustEqualOriginMainAndPlan"] is True
assert preflight["implementationBaselineMustBeAncestor"] is True
assert preflight["imageSourceCommitMustBeAncestor"] is True
assert preflight["awsDevReleaseIdentityMustMatch"] is True
assert preflight["readOnlyAwsCommands"] == [
    "sts get-caller-identity",
    "eks list-clusters",
]
assert preflight["terraformStateInspection"] == "direct-redacted-summary-no-terraform-command"
assert preflight["terraformStateAttributesEmitted"] is False
assert preflight["mutationsPerformed"] == []

inventory = contract["inventoryPolicy"]
assert inventory["maximumActiveRehearsalEksEnvironments"] == 1
assert inventory["readyState"] == "no-rehearsal-cluster-and-empty-or-absent-dev-state"
assert inventory["existingDevState"] == "blocked-requires-separate-resume-review"
assert inventory["partialState"] == "blocked-preserve-state-and-investigate"
assert inventory["testOrProdActive"] == "blocked-preserve-and-complete-current-environment"
assert inventory["unmanagedDev"] == "blocked-no-create"
assert inventory["deleteTerraformStateAllowed"] is False

candidate = contract["selectedCandidate"]
assert candidate == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
}

release_path = root / "apps/demo-api/helm/values/releases/aws-dev.yaml"
assert hashlib.sha256(release_path.read_bytes()).hexdigest() == contract[
    "implementationBaselineEvidence"
]["awsDevReleaseFileSha256"]
assert yaml.safe_load(release_path.read_text()) == {
    "image": {
        "repository": candidate["repository"],
        "tag": candidate["tag"],
        "digest": candidate["digest"],
    },
    "release": {"applicationVersion": candidate["tag"]},
    "delivery": {
        "sourceRepository": "SterlingAureum/startup-devops-baseline",
        "sourceCommit": candidate["sourceCommit"],
        "workflowRunId": candidate["workflowRunId"],
    },
}

aws_prod = root / "apps/demo-api/helm/values/releases/aws-prod.yaml"
assert hashlib.sha256(aws_prod.read_bytes()).hexdigest() == (
    "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22"
)
assert candidate["digest"] not in aws_prod.read_text()

operation = contract["operationBoundary"]
assert operation["awsReadsOnly"] is True
for key in (
    "terraformCommandAllowed",
    "terraformApplyAllowed",
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

# Inspect every statically declared AWS command passed to command_runner. A new
# AWS operation must be reviewed here before it can enter the preflight.
tree = ast.parse(preflight_path.read_text())
aws_calls: set[tuple[str, str]] = set()
for node in ast.walk(tree):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        continue
    if node.func.id != "command_runner" or not node.args:
        continue
    argument = node.args[0]
    if not isinstance(argument, ast.List) or len(argument.elts) < 3:
        continue
    prefix: list[str] = []
    for item in argument.elts[:3]:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            prefix.append(item.value)
    if len(prefix) == 3 and prefix[0] == "aws":
        aws_calls.add((prefix[1], prefix[2]))
assert aws_calls == {("sts", "get-caller-identity"), ("eks", "list-clusters")}

source = preflight_path.read_text()
for forbidden in (
    "create-cluster",
    "delete-cluster",
    "update-cluster",
    "update-kubeconfig",
    "terraform", "kubectl", "argocd",
    "apply-aws-dev.sh",
):
    if forbidden == "terraform":
        # State path and summary names are expected; no executable is allowed.
        assert '["terraform"' not in source and "shutil.which(\"terraform\")" not in source
    else:
        assert forbidden not in source

for relative, marker in (
    ("README.md", "v0.11.9.3.5-aws-dev-live-rehearsal-preflight"),
    ("CHANGELOG.md", "## v0.11.9.3.5"),
    ("docs/ROADMAP.md", "v0.11.9.3.5"),
    ("docs/V0.11.9.3.5_AWS_DEV_LIVE_REHEARSAL_PREFLIGHT.md", "Result states"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.5-aws-dev-live-rehearsal-preflight.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.5 private-plan, read-only AWS inventory and no-execution boundaries passed.")
PY

"${AWS_TEST_SUCCESSOR_CHECK}" \
  --release-file "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml" \
  >/dev/null

if PYTHONDONTWRITEBYTECODE=1 python3 "${PLAN_CHECKER}" \
  --plan "${PLAN_TEMPLATE}" >/dev/null 2>&1; then
  echo "Repository plan template unexpectedly passed without private inputs." >&2
  exit 1
fi

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.5 aws-dev live-rehearsal preflight validation passed; no live operation was executed."

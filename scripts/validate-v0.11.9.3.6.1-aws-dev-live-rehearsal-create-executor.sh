#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.1-aws-dev-live-rehearsal-create.py"
EXECUTOR_TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.py"
PLAN_CHECKER="${ROOT_DIR}/scripts/check-aws-dev-create-terraform-plan.py"
PLAN_TESTS="${ROOT_DIR}/scripts/test-aws-dev-create-terraform-plan.py"
APPLY_SCRIPT="${ROOT_DIR}/scripts/apply-eks-api-access-cidr.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" "${PLAN_CHECKER}" "${APPLY_SCRIPT}" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
executor_path = Path(sys.argv[3])
plan_checker_path = Path(sys.argv[4])
apply_path = Path(sys.argv[5])

assert contract["schemaVersion"] == "v0.11.9.3.6.1"
assert contract["version"] == "v0.11.9.3.6.1"
assert contract["predecessor"] == "v0.11.9.3.6"
assert contract["status"] == "guarded-aws-dev-create-executor-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "4ecf8515c636066a4e8e9cc640ee96473fbfd21d"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.2-aws-dev-infrastructure-create-execution"

executor = contract["executor"]
assert executor == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.1-aws-dev-live-rehearsal-create.py",
    "phases": ["verify", "execute"],
    "createPlanChecker": "scripts/check-v0.11.9.3.6-aws-dev-live-rehearsal-create-plan.py",
    "preflightEntrypoint": "scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py",
    "infrastructureCreateEntrypoint": "scripts/apply-aws-dev.sh",
    "requiredBranch": "main",
    "cleanWorktreeRequired": True,
    "headMustEqualOriginMainAndPlan": True,
    "privateInputFileMode": "0600",
    "privateParentDirectoryModeMaximum": "0700",
    "freshPreflightRerunImmediatelyBeforeCreate": True,
    "freshPreflightMustBeByteIdentical": True,
}
assert contract["confirmations"] == {
    "preflight": {
        "variable": "CONFIRM_AWS_DEV_PREFLIGHT",
        "value": "observe-reviewed-aws-dev-rehearsal",
    },
    "rehearsalCreate": {
        "variable": "CONFIRM_AWS_DEV_REHEARSAL_CREATE",
        "value": "execute-reviewed-aws-dev-rehearsal-create",
    },
    "infrastructureApply": {
        "variable": "CONFIRM_AWS_DEV_APPLY",
        "value": "create-ephemeral-aws-dev",
    },
    "interactiveTerraformPlan": "apply-aws-dev",
}

gate = contract["terraformPlanGate"]
assert gate == {
    "checker": "scripts/check-aws-dev-create-terraform-plan.py",
    "source": "terraform show -json saved-plan",
    "allowedActionVectors": [["create"], ["read"], ["no-op"]],
    "atLeastOneCreateRequired": True,
    "updateAllowed": False,
    "deleteAllowed": False,
    "replacementAllowed": False,
    "emptyPlanAllowed": False,
    "malformedPlanAllowed": False,
    "rawPlanPersistedByChecker": False,
}
assert contract["successBoundary"] == {
    "status": "aws-dev-infrastructure-created-api-ready",
    "eksApiReadyRequired": True,
    "gitopsBootstrapped": False,
    "rootApplicationDeployed": False,
    "runtimeQualified": False,
    "trafficGenerated": False,
    "automaticTeardownExecuted": False,
    "nextAction": "review-separate-gitops-bootstrap",
}
assert contract["failureBoundary"] == {
    "preserveTerraformState": True,
    "preservePrivateEvidence": True,
    "uncertaintyIsAbsence": False,
    "automaticRetry": False,
    "automaticDestroy": False,
    "remoteFaultReplay": False,
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
assert all(value is False for value in contract["producerExecution"].values())

executor_source = executor_path.read_text()
assert executor_source.count("subprocess.run(") == 3
assert 'PREFLIGHT = ROOT / "scripts/preflight-v0.11.9.3.5-aws-dev-live-rehearsal.py"' in executor_source
assert 'APPLY = ROOT / "scripts/apply-aws-dev.sh"' in executor_source
for forbidden in (
    "bootstrap-eks-argocd.sh",
    "deploy-aws-dev-root-app.sh",
    "destroy-aws-dev.sh",
    "apply-aws-test.sh",
    "kubectl",
    "argocd",
):
    assert forbidden not in executor_source

tree = ast.parse(plan_checker_path.read_text())
imports = {
    alias.name
    for node in ast.walk(tree)
    if isinstance(node, (ast.Import, ast.ImportFrom))
    for alias in node.names
}
assert not imports.intersection({"boto3", "botocore", "subprocess", "os"})
checker_source = plan_checker_path.read_text()
assert 'ALLOWED_ACTIONS = {("create",), ("read",), ("no-op",)}' in checker_source

apply_source = apply_path.read_text()
for marker in (
    'terraform -chdir="${TF_DIR}" show -json "${PLAN_FILE}"',
    'python3 "${CREATE_PLAN_CHECKER}" --plan-json "${PLAN_JSON}"',
    "Review the plan above. Type apply-aws-dev to apply",
):
    assert marker in apply_source
assert apply_source.index("--plan-json") < apply_source.index("Review the plan above")
assert apply_source.index("Review the plan above") < apply_source.index('terraform -chdir="${TF_DIR}" apply')

for relative, marker in (
    ("README.md", "v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor"),
    ("CHANGELOG.md", "## v0.11.9.3.6.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.1"),
    ("docs/V0.11.9.3.6.1_AWS_DEV_LIVE_REHEARSAL_CREATE_EXECUTOR.md", "Machine Terraform plan gate"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.1 exact-main, immediate-preflight, create-only plan and phase boundaries passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${PLAN_TESTS}"
PYTHONDONTWRITEBYTECODE=1 python3 "${EXECUTOR_TESTS}"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.1.3-aws-deployment-entrypoint-repair.sh"

for script in "${APPLY_SCRIPT}" "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.sh"; do
  bash -n "${script}"
done

if command -v shellcheck >/dev/null 2>&1; then
  (
    cd "${ROOT_DIR}"
    shellcheck -x \
      "${APPLY_SCRIPT}" \
      "${ROOT_DIR}/scripts/validate-v0.11.8.1.3-aws-deployment-entrypoint-repair.sh" \
      "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.sh"
  )
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.1 guarded create-executor validation passed; no live operation was executed."

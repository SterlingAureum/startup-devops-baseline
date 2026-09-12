#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.json"
PLAN_GATE="${ROOT_DIR}/scripts/check-aws-test-create-terraform-plan.py"
PLAN_GATE_TESTS="${ROOT_DIR}/scripts/test-aws-test-create-terraform-plan.py"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py"
EXECUTOR_TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${PLAN_GATE}" "${EXECUTOR}" <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
plan_gate_path = Path(sys.argv[3])
executor_path = Path(sys.argv[4])
plan_gate = plan_gate_path.read_text()
executor = executor_path.read_text()

version = "v0.11.9.3.6.7.2"
baseline = "a94b69c75210a98210a3b9da7d4d32b0e8cbf93d"
preflight_sha = "5f12981fc2720ff4ac9a03b11d5d3444f03bbb0408d0e87190643549e81e18c3"
empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.7.1"
assert contract["status"] == (
    "guarded-aws-test-terraform-plan-executor-implemented-not-executed"
)
assert contract["implementationBaselineCommit"] == baseline
assert contract["terraformPlanAuthorized"] is False
assert contract["terraformPlanExecuted"] is False
assert contract["terraformApplyAuthorized"] is False
assert contract["terraformApplyExecuted"] is False
assert contract["environmentCreationAuthorized"] is False

design = contract["designInput"]
assert design == {
    "reviewedPreflightControlPlaneCommit": baseline,
    "reviewedPreflightResultSha256": preflight_sha,
    "reviewedPreflightStderrSha256": empty_sha,
    "reviewedPreflightStatus": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
    "reviewedPreflightExecutedTerraform": False,
    "reviewedPreflightCreatedAwsTest": False,
    "freshPreflightRequiredAfterExecutorMerge": True,
}

inputs = contract["reviewedRepositoryInputs"]
expected_inputs = {
    "planDesignContract": (
        "delivery/contracts/v0.11.9.3.6.7.1-aws-test-live-creation-plan-design.json",
        "02eb0395f0e54a2698f728d06750b4206b698ae14b2bcfdc6290c89acfe7cdb8",
    ),
    "privatePlanTemplate": (
        "delivery/examples/v0.11.9.3.6.7.1-aws-test-live-creation-plan.json",
        "07e4cf748f93878b05164aba9a032aa9baaa27477d3fdb218ecc19bbb1ef53d1",
    ),
    "privatePlanChecker": (
        "scripts/check-v0.11.9.3.6.7.1-aws-test-live-creation-plan.py",
        "eadc9322d00027916b1d2c8f14cc87bd51ef3585aed40e2302a8827e5389311d",
    ),
    "livePreflightEntrypoint": (
        "scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py",
        "b41a1c58865ffd44ae35165a7a17e941dd19d4b05dd0b1d6f2f09938afeec487",
    ),
    "terraformPlanGate": (
        "scripts/check-aws-test-create-terraform-plan.py",
        "d61a840c164a8e6a22b0ffde5f85c5b5a13de036b24530b3c98cc35002ff23c8",
    ),
    "planExecutor": (
        "scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py",
        "6bee71419d5398c0623a7ac9434c3803107dba77bdb9908f204db56fbe1792b5",
    ),
}
assert set(inputs) == set(expected_inputs)
for key, (relative, expected_sha) in expected_inputs.items():
    assert inputs[key] == {"path": relative, "sha256": expected_sha}
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected_sha

executor_contract = contract["executor"]
assert executor_contract["phases"] == ["verify", "execute"]
assert executor_contract["requiredBranch"] == "main"
assert executor_contract["verifyRunsCommands"] is False
assert executor_contract["verifyAuthorizesPlan"] is False
assert executor_contract["executeRequiresSeparateApproval"] is True
assert executor_contract["immediatePreflightMustBeByteIdentical"] is True
assert executor_contract["minimumRemainingSessionWindowSeconds"] == 900
assert executor_contract["automaticRetryAllowed"] is False

commands = contract["commandBoundary"]
assert commands["verifyAllowedCommands"] == []
assert commands["executeReadOnlyAwsCommands"] == [
    "sts get-caller-identity",
    "eks list-clusters",
    "secretsmanager describe-secret before plan",
    "secretsmanager describe-secret after plan",
]
assert commands["executeTerraformCommands"] == [
    "terraform init -input=false -lockfile=readonly",
    "terraform plan -input=false -lock=true -out=private",
    "terraform show -json private-plan",
    "terraform show -no-color private-plan",
]
for key in (
    "terraformApplyAllowed",
    "terraformDestroyAllowed",
    "kubectlAllowed",
    "argocdAllowed",
    "gitMutationAllowed",
    "awsMutationAllowed",
):
    assert commands[key] is False, key

secret = contract["secretMetadataBoundary"]
assert secret["lookup"] == "secretsmanager DescribeSecret metadata only"
assert secret["requiredStateBeforeAndAfterPlan"] == "ResourceNotFoundException"
assert secret["credentialValueReadAllowed"] is False
assert secret["accessDeniedMeansAbsent"] is False
assert secret["automaticDeleteRestoreOrImportAllowed"] is False

gate = contract["terraformPlanGate"]
assert gate["allowedActionVectors"] == [["create"], ["read"], ["no-op"]]
for key in (
    "atLeastOneCreateRequired",
    "exactlyOneAwsTestEksClusterCreateRequired",
    "runtimeAccessEntryMustMatchExactOptionalRole",
):
    assert gate[key] is True, key
for key in (
    "foreignAccountArnAllowed",
    "nonTestEnvironmentTagAllowed",
    "updateAllowed",
    "deleteAllowed",
    "replacementAllowed",
    "unknownActionAllowed",
    "emptyPlanAllowed",
):
    assert gate[key] is False, key

private = contract["privateOutput"]
assert private["directoryMode"] == "0700"
assert private["fileMode"] == "0600"
assert private["planReviewTtlSeconds"] == 3600
for key in (
    "publicOutputContainsPrivatePath",
    "publicOutputContainsAccountId",
    "publicOutputContainsManagementIpv4",
    "publicOutputContainsResourceIdentity",
):
    assert private[key] is False, key

success = contract["successBoundary"]
assert success == {
    "status": "aws-test-create-only-terraform-plan-produced",
    "terraformPlanExecuted": True,
    "terraformApplyExecuted": False,
    "environmentCreationAuthorized": False,
    "environmentCreated": False,
    "gitopsBootstrapped": False,
    "trafficGenerated": False,
    "automaticRetryPerformed": False,
    "nextAction": "review-private-plan-before-separate-apply-executor-design",
}
assert all(value is False for value in contract["packageProducer"].values())

for marker in (
    "CONFIRM_AWS_TEST_TERRAFORM_PLAN_EXECUTION",
    "execute-reviewed-aws-test-create-plan",
    "Immediate preflight bytes changed",
    "-lockfile=readonly",
    "TF_DATA_DIR",
    "TF_IN_AUTOMATION",
    "ResourceNotFoundException",
    "secret-before-plan",
    "secret-after-plan",
    "terraform-plan.json",
    "terraform-plan.txt",
    "plan-record.json",
    "terraform_apply_executed\": False",
    "environment_creation_authorized\": False",
    "automatic_retry_performed\": False",
):
    assert marker in executor, marker
for marker in (
    "ALLOWED_ACTIONS",
    "eks_node_min_size",
    "eks_public_access_cidrs",
    "aws_eks_cluster",
    "aws_eks_access_entry",
    "different AWS account",
    "non-test Environment tag",
):
    assert marker in plan_gate, marker

# The plan gate parses private JSON only and must not execute commands.
tree = ast.parse(plan_gate)
imports = {
    alias.name
    for node in ast.walk(tree)
    if isinstance(node, (ast.Import, ast.ImportFrom))
    for alias in node.names
}
assert not imports.intersection({"boto3", "botocore", "subprocess", "os", "socket"})

# No executor subprocess command list may contain terraform apply/destroy,
# kubectl or argocd. Documentation/status strings do not count as invocations.
tree = ast.parse(executor)
for node in ast.walk(tree):
    if isinstance(node, (ast.List, ast.Tuple)):
        literals = [
            item.value
            for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        assert not ({"apply", "destroy", "kubectl", "argocd"} & set(literals)), literals

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert "amazonaws.com" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.7.2 guarded aws-test Terraform plan executor"),
    ("CHANGELOG.md", "## v0.11.9.3.6.7.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.7.2"),
    ("docs/V0.11.9.3.6.7.2_GUARDED_AWS_TEST_TERRAFORM_PLAN_EXECUTOR.md", "terraform_plan_authorized=false"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.7.2 exact-main, byte-preflight, create-plan and no-apply contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${PLAN_GATE_TESTS}"
PYTHONDONTWRITEBYTECODE=1 python3 "${EXECUTOR_TESTS}"
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${PLAN_GATE}" "${PLAN_GATE_TESTS}" "${EXECUTOR}" "${EXECUTOR_TESTS}"
python3 -m json.tool "${CONTRACT}" >/dev/null

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.sh"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.7.2 aws-test Terraform plan executor passed; no live operation was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.4-aws-dev-root-application-deploy.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.4-aws-dev-root-application-deploy-executor.py"
DEPLOY="${ROOT_DIR}/scripts/deploy-aws-dev-root-app.sh"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" "${DEPLOY}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
executor_path = Path(sys.argv[3])
deploy_path = Path(sys.argv[4])

assert contract["schemaVersion"] == "v0.11.9.3.6.4"
assert contract["version"] == "v0.11.9.3.6.4"
assert contract["predecessor"] == "v0.11.9.3.6.3.1"
assert contract["status"] == "guarded-aws-dev-root-application-deploy-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "20224914590bc2ab8d1154d28e18f0d4e23cd383"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.5-aws-dev-runtime-qualification"

executor = contract["executor"]
assert executor == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.4-aws-dev-root-application-deploy.py",
    "phases": ["verify", "execute"],
    "rootDeployEntrypoint": "scripts/deploy-aws-dev-root-app.sh",
    "directAwsDevEntrypointBlocked": True,
    "requiredBranch": "main",
    "cleanWorktreeRequired": True,
    "headOriginAndRemoteMainMustMatchReviewedCommit": True,
    "rootTargetRevision": "main",
    "postDeployResolvedRevisionMustMatchReviewedCommit": True,
    "awsAccountInput": "EXPECTED_AWS_ACCOUNT_ID",
    "awsAccountCommitted": False,
}
assert contract["immutableInputs"] == {
    "rootSource": "clusters/aws/overlays/dev/root-app.yaml",
    "rootSourceSha256": "6f0fc680b04b7df3194549e626764a758856ebfb7cf38e806f573c4b0297e11f",
    "awsDevRelease": "apps/demo-api/helm/values/releases/aws-dev.yaml",
    "awsDevReleaseSha256": "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46",
    "candidateReleaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
}
assert contract["livePrerequisites"] == {
    "region": "us-east-1",
    "clusterName": "startup-devops-baseline-dev",
    "clusterStatus": "ACTIVE",
    "kubernetesServerMustMatchEksEndpoint": True,
    "kubernetesReadyz": "ok",
    "terraformStateAddressCount": 103,
    "argocdVersion": "v3.5.2",
    "argocdWorkloadCount": 7,
    "argocdWorkloadsFullyReady": True,
    "albApplicationStatus": "Synced/Healthy",
    "albChartVersion": "1.14.0",
    "albVpcMustMatchTerraform": True,
    "rootApplicationMustBeAbsent": True,
    "secretsManagerContainerValidatedWithoutSecretRead": True,
    "publicRoute53ZoneMustMatchTerraform": True,
}
assert contract["confirmations"] == {
    "readOnlyVerification": {
        "variable": "CONFIRM_AWS_DEV_ROOT_PREFLIGHT",
        "value": "observe-reviewed-aws-dev-root-deploy",
    },
    "rootTreeDeploy": {
        "variable": "CONFIRM_AWS_DEV_ROOT_DEPLOY",
        "value": "deploy-reviewed-aws-dev-root-application",
    },
    "internalEntrypoint": {
        "variable": "CONFIRM_AWS_DEV_ROOT_ENTRYPOINT",
        "value": "execute-validated-aws-dev-root-deploy",
        "operatorFacing": False,
    },
}
assert len(contract["approvedWriteScope"]) == 8
assert contract["successBoundary"] == {
    "status": "aws-dev-root-application-deploy-complete",
    "rootApplicationSynced": True,
    "rootApplicationHealthy": True,
    "rootResolvedRevisionReviewed": True,
    "databaseAndSecretBootstrapComplete": True,
    "demoApplicationAcceptedHealth": True,
    "stableDnsReconciled": True,
    "runtimeQualified": False,
    "progressiveDeliveryPromoted": False,
    "trafficGenerated": False,
    "automaticTeardownExecuted": False,
    "nextAction": "review-aws-dev-runtime-qualification",
}
assert all(value is False for value in contract["packageProducer"].values())

source = executor_path.read_text()
tree = ast.parse(source)
assert source.count("subprocess.run(") == 3
for marker in (
    'DEPLOY_ROOT = ROOT / "scripts/deploy-aws-dev-root-app.sh"',
    'ROOT_SOURCE_SHA256 = "6f0fc680b04b7df3194549e626764a758856ebfb7cf38e806f573c4b0297e11f"',
    'AWS_DEV_RELEASE_SHA256 = "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"',
    'OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-root-deploy"',
    'EXECUTION_CONFIRMATION = "deploy-reviewed-aws-dev-root-application"',
    '["ls-remote", "origin", "refs/heads/main"]',
    'TARGET_REVISION="main"',
    '"root_resolved_revision": expected_commit',
    '"runtime_qualified": False',
    '"progressive_delivery_promoted": False',
):
    assert marker in source, marker
assert "destroy-aws-dev.sh" not in source
assert "rollouts promote" not in source
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval" for node in ast.walk(tree))

deploy = deploy_path.read_text()
for marker in (
    'CONFIRM_AWS_DEV_ROOT_ENTRYPOINT:-',
    'execute-validated-aws-dev-root-deploy',
    'Direct aws-dev Root deployment is blocked.',
    'execute-v0.11.9.3.6.4-aws-dev-root-application-deploy.py',
):
    assert marker in deploy, marker
assert deploy.index("CONFIRM_AWS_DEV_ROOT_ENTRYPOINT") < deploy.index("for command in aws kubectl terraform jq")

for relative, marker in (
    ("README.md", "v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy"),
    ("CHANGELOG.md", "## v0.11.9.3.6.4"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.4"),
    ("docs/V0.11.9.3.6.4_AWS_DEV_GUARDED_ROOT_APPLICATION_DEPLOY.md", "Write scope requiring separate approval"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.4 exact-remote-main, AWS/EKS/Terraform, Argo/ALB, secret/DNS and Root boundaries passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"

direct_output="$(
  ROOT_APPLICATION=startup-devops-aws-dev-root \
  CONFIRM_AWS_DEV_ROOT_ENTRYPOINT=invalid \
    bash "${DEPLOY}" 2>&1 || true
)"
grep -F "Direct aws-dev Root deployment is blocked." <<<"${direct_output}" >/dev/null
if grep -F "Required command not found" <<<"${direct_output}" >/dev/null; then
  echo "Direct entrypoint reached command discovery before its guard." >&2
  exit 1
fi

bash "${PREDECESSOR}"

for script in "${DEPLOY}" "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy.sh"; do
  bash -n "${script}"
done

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck \
    "${DEPLOY}" \
    "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.4 guarded Root deployment validation passed; no live operation was executed."

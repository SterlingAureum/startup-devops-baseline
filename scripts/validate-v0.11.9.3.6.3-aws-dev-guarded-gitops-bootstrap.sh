#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.3-aws-dev-gitops-bootstrap.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.3-aws-dev-gitops-bootstrap-executor.py"
BOOTSTRAP="${ROOT_DIR}/scripts/bootstrap-eks-argocd.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" "${BOOTSTRAP}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
executor_path = Path(sys.argv[3])
bootstrap_path = Path(sys.argv[4])

assert contract["schemaVersion"] == "v0.11.9.3.6.3"
assert contract["version"] == "v0.11.9.3.6.3"
assert contract["predecessor"] == "v0.11.9.3.6.2.1"
assert contract["status"] == "guarded-aws-dev-gitops-bootstrap-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "04e5c40294c2b23c02626fcdf8e4648a9b788cdf"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.4-aws-dev-root-application-deploy"

executor = contract["executor"]
assert executor == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.3-aws-dev-gitops-bootstrap.py",
    "phases": ["verify", "execute"],
    "bootstrapEntrypoint": "scripts/bootstrap-eks-argocd.sh",
    "requiredBranch": "main",
    "cleanWorktreeRequired": True,
    "headMustEqualOriginMainAndReviewedCommit": True,
    "awsAccountInput": "EXPECTED_AWS_ACCOUNT_ID",
    "awsAccountCommitted": False,
    "region": "us-east-1",
    "clusterName": "startup-devops-baseline-dev",
    "clusterStatusRequired": "ACTIVE",
    "kubernetesServerMustMatchEksEndpoint": True,
    "kubernetesReadyzRequired": "ok",
    "terraformStateAddressCountRequired": 103,
    "argocdNamespaceMustBeAbsent": True,
    "irsaRoleAccountsMustMatchCaller": True,
    "terraformVpcIdValidated": True,
}
assert contract["argocd"] == {
    "exactVersion": "v3.5.2",
    "mutableStableAliasAllowed": False,
    "mutableLatestAliasAllowed": False,
    "manifest": "https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.2/manifests/install.yaml",
}
assert contract["confirmations"] == {
    "readOnlyVerification": {
        "variable": "CONFIRM_AWS_DEV_GITOPS_PREFLIGHT",
        "value": "observe-reviewed-aws-dev-gitops-bootstrap",
    },
    "gitopsBootstrap": {
        "variable": "CONFIRM_AWS_DEV_GITOPS_BOOTSTRAP",
        "value": "bootstrap-reviewed-aws-dev-gitops",
    },
}
assert contract["successBoundary"] == {
    "status": "aws-dev-gitops-bootstrap-complete",
    "argocdInstalled": True,
    "awsLoadBalancerControllerApplicationApplied": True,
    "karpenterServiceAccountPrepared": True,
    "rootApplicationDeployed": False,
    "applicationRuntimeQualified": False,
    "trafficGenerated": False,
    "automaticTeardownExecuted": False,
    "nextAction": "review-separate-root-application-deploy",
}
assert all(value is False for value in contract["packageProducer"].values())

source = executor_path.read_text()
tree = ast.parse(source)
assert source.count("subprocess.run(") == 3
for marker in (
    'BOOTSTRAP = ROOT / "scripts/bootstrap-eks-argocd.sh"',
    'PINNED_ARGOCD_VERSION = "v3.5.2"',
    "EXPECTED_STATE_ADDRESS_COUNT = 103",
    'OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-gitops-bootstrap"',
    'EXECUTION_CONFIRMATION = "bootstrap-reviewed-aws-dev-gitops"',
    '["git", "-C", str(ROOT), *arguments]',
    '["kubectl", "get", "--raw=/readyz"]',
    '"kubectl context does not point to the reviewed aws-dev EKS cluster"',
    '"argocd_namespace_present": False',
    '"root_application_deployed": False',
    '"next_action": "review-separate-root-application-deploy"',
):
    assert marker in source, marker
assert "deploy-aws-dev-root-app.sh" not in source
assert "destroy-aws-dev.sh" not in source
assert "apply-aws-dev.sh" not in source
assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval" for node in ast.walk(tree))

bootstrap = bootstrap_path.read_text()
for marker in (
    'ARGOCD_VERSION="${ARGOCD_VERSION:-v3.5.2}"',
    'ARGOCD_VERSION must be an exact vMAJOR.MINOR.PATCH release.',
    'argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml',
):
    assert marker in bootstrap, marker
assert 'ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"' not in bootstrap

for relative, marker in (
    ("README.md", "v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap"),
    ("CHANGELOG.md", "## v0.11.9.3.6.3"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.3"),
    ("docs/V0.11.9.3.6.3_AWS_DEV_GUARDED_GITOPS_BOOTSTRAP.md", "Separately approved execution"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.3 exact-main, account, live-state, pinned-version and phase boundaries passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
bash "${ROOT_DIR}/scripts/validate-v0.11.4.1.0-controller-metrics-discovery.sh"

for script in "${BOOTSTRAP}" "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap.sh"; do
  bash -n "${script}"
done

if command -v shellcheck >/dev/null 2>&1; then
  (
    cd "${ROOT_DIR}"
    shellcheck \
      "${BOOTSTRAP}" \
      "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap.sh"
  )
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.3 guarded GitOps bootstrap validation passed; no live operation was executed."

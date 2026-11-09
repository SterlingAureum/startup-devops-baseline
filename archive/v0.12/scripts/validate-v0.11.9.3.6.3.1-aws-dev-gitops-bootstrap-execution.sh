#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.3-aws-dev-guarded-gitops-bootstrap.sh"

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
contract_path = Path(sys.argv[2])
contract = json.loads(contract_path.read_text())

assert contract["schemaVersion"] == "v0.11.9.3.6.3.1"
assert contract["version"] == "v0.11.9.3.6.3.1"
assert contract["predecessor"] == "v0.11.9.3.6.3"
assert contract["status"] == "aws-dev-gitops-bootstrap-executed-and-observed"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.4-aws-dev-root-application-deploy"

assert contract["controlPlane"] == {
    "branch": "main",
    "commit": "64fe6bb58bb5dd6c33a03f25f0df19bef177c825",
    "headEqualsOriginMain": True,
    "cleanWorktree": True,
}
assert contract["preExecutionVerification"] == {
    "status": "aws-dev-gitops-bootstrap-inputs-verified",
    "executionAuthorized": False,
    "awsCallerAccountMatched": True,
    "eksStatus": "ACTIVE",
    "eksVersion": "1.36",
    "kubernetesServerMatchedEksEndpoint": True,
    "kubernetesReadyz": "ok",
    "terraformStateAddressCount": 103,
    "argocdNamespacePresent": False,
    "terraformBootstrapOutputsValidated": True,
}
assert contract["approval"] == {
    "separateGitopsBootstrapApproved": True,
    "readOnlyConfirmationSatisfied": True,
    "writeConfirmationSatisfied": True,
    "approvedScope": "Argo CD and AWS Load Balancer Controller bootstrap only",
    "rootDeployApproved": False,
    "teardownApproved": False,
}
assert contract["executionResult"] == {
    "status": "aws-dev-gitops-bootstrap-complete",
    "argocdVersion": "v3.5.2",
    "gitopsBootstrapped": True,
    "rootApplicationDeployed": False,
    "runtimeQualified": False,
    "trafficGenerated": False,
    "automaticTeardownExecuted": False,
    "nextAction": "review-separate-root-application-deploy",
}

observation = contract["postBootstrapObservation"]
assert observation["observedAt"] == "2026-09-09T11:16:55Z"
argocd = observation["argocd"]
assert argocd["observedWorkloadCount"] == 7
assert argocd["readyWorkloadCount"] == 7
assert argocd["coreVersion"] == "v3.5.2"
assert len(argocd["coreVersionWorkloads"]) == 5
assert set(argocd["coreVersionWorkloads"]) == {
    "argocd-applicationset-controller",
    "argocd-notifications-controller",
    "argocd-repo-server",
    "argocd-server",
    "argocd-application-controller",
}
assert argocd["auxiliaryImages"] == {
    "argocd-dex-server": "ghcr.io/dexidp/dex:v2.45.1",
    "argocd-redis": "public.ecr.aws/docker/library/redis:8.2.3-alpine",
}

alb = observation["awsLoadBalancerController"]
assert alb == {
    "applicationName": "aws-load-balancer-controller",
    "syncStatus": "Synced",
    "healthStatus": "Healthy",
    "chart": "aws-load-balancer-controller",
    "chartVersion": "1.14.0",
    "destinationNamespace": "kube-system",
    "deploymentRolloutComplete": True,
}
assert observation["irsa"] == {
    "awsLoadBalancerControllerServiceAccountPresent": True,
    "karpenterServiceAccountPresent": True,
    "roleAccountMatches": True,
    "rawRoleArnsCommitted": False,
}
assert observation["rootApplication"] == {
    "name": "startup-devops-aws-dev-root",
    "present": False,
}

assert all(value is False for value in contract["privateEvidence"].values())
assert contract["operationBoundary"] == {
    "gitopsBootstrapExecuted": True,
    "argocdInstalled": True,
    "awsLoadBalancerControllerApplicationApplied": True,
    "rootApplicationDeployExecuted": False,
    "applicationRuntimeQualificationExecuted": False,
    "trafficGenerated": False,
    "remoteFaultReplayed": False,
    "awsTestPromotionExecuted": False,
    "teardownExecuted": False,
}
assert all(value is False for value in contract["packageProducer"].values())

raw = contract_path.read_text()
assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", raw)
for forbidden in ("arn:aws:", "vpc-", "https://eks."):
    assert forbidden not in raw

for relative, marker in (
    ("README.md", "v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution"),
    ("CHANGELOG.md", "## v0.11.9.3.6.3.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.3.1"),
    ("docs/V0.11.9.3.6.3.1_AWS_DEV_GITOPS_BOOTSTRAP_EXECUTION.md", "Root boundary retained"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution.json"),
):
    assert marker in (root / relative).read_text(), relative

executor = (root / "scripts/execute-v0.11.9.3.6.3-aws-dev-gitops-bootstrap.py").read_text()
assert '"root_application_deployed": False' in executor
assert '"next_action": "review-separate-root-application-deploy"' in executor
assert "deploy-aws-dev-root-app.sh" not in executor

print("v0.11.9.3.6.3.1 protected-main bootstrap, Ready components, ALB and no-Root evidence passed.")
PY

bash "${PREDECESSOR}"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.3.1-aws-dev-gitops-bootstrap-execution.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.3.1 GitOps bootstrap execution evidence passed; no live operation was executed."

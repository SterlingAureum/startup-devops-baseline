#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.2-aws-dev-infrastructure-create-execution.json"

command -v python3 >/dev/null 2>&1 || {
  echo "Required command not found: python3" >&2
  exit 1
}

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract_path = Path(sys.argv[2])
contract = json.loads(contract_path.read_text())

assert contract["schemaVersion"] == "v0.11.9.3.6.2"
assert contract["version"] == "v0.11.9.3.6.2"
assert contract["predecessor"] == "v0.11.9.3.6.1.1"
assert contract["status"] == "aws-dev-infrastructure-created-api-ready-recorded"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.3-aws-dev-gitops-bootstrap-execution"

control = contract["controlPlane"]
assert control == {
    "branch": "main",
    "commit": "b01e76c4155536dd85088bda462d28f49cfde07f",
    "headEqualsOriginMain": True,
    "cleanWorktree": True,
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
private_false = (
    "rawCreatePlanCommitted",
    "rawFreshPreflightPlanCommitted",
    "rawFreshPreflightResultCommitted",
    "rawVerifyResultCommitted",
    "rawExecutionLogCommitted",
    "rawTerraformPlanCommitted",
    "rawTerraformStateCommitted",
    "awsAccountIdCommitted",
    "publicAccessCidrsCommitted",
    "nodeNamesCommitted",
)
assert all(private[key] is False for key in private_false)
expected_hashes = {
    "createPlanSha256": "8bceece2ffbe93005730eb314fdce3b1405a305be3746c907ef243b4f5a79a30",
    "freshPreflightPlanSha256": "903fb208e863837035c0ada19d879fd42fb4560a1067fdc7bd36d6bc6ce1c112",
    "freshPreflightResultSha256": "f8920484c699c9a3cbfee0fee7c9a804aae306d06b1e4e057dcaed6169cc8a79",
    "verifyResultSha256": "d2899be3a178cd5dd37052b17f3f8424023cbd2f7ea7479238b11383c5387478",
    "executionLogSha256": "402222e091dd34eba4274d185a4cfcca8ce66db515d9483dc61b27441ca1b505",
}
for key, expected in expected_hashes.items():
    assert private[key] == expected
    assert re.fullmatch(r"[0-9a-f]{64}", private[key])
assert len(set(expected_hashes.values())) == len(expected_hashes)
assert private["privateParentModeMaximum"] == "0700"
assert private["privateFileModes"] == "0600"

assert contract["approval"] == {
    "separateLiveCreateApproved": True,
    "maximumSessionHours": 8,
    "reviewedSessionBudgetUsd": 12,
    "threeEnvironmentConfirmationsSatisfied": True,
    "interactiveTerraformConfirmationSatisfied": True,
}

result = contract["executionResult"]
assert result["status"] == "aws-dev-infrastructure-created-api-ready"
assert result["terraformPlanPolicy"] == "nonempty-create-read-no-op-only"
assert result["terraformStateAddressCount"] == 103
observed = datetime.fromisoformat(result["observedAt"].replace("Z", "+00:00"))
deadline = datetime.fromisoformat(result["teardownReviewDeadlineUtc"].replace("Z", "+00:00"))
assert observed < deadline
assert result["eks"] == {
    "name": "startup-devops-baseline-dev",
    "status": "ACTIVE",
    "version": "1.36",
    "endpointPublicAccess": True,
    "endpointPrivateAccess": True,
    "enabledControlPlaneLogTypes": [],
    "nodeCount": 4,
    "readyNodeCount": 4,
    "observedKubeletVersions": ["v1.36.3-eks-cb19647"],
    "finalReadyz": "ok",
}
assert result["transientObservation"] == {
    "initialPostCreateReadyzTlsHandshakeTimeout": True,
    "subsequentNodeInventorySucceeded": True,
    "readOnlyReadyzRetrySucceeded": True,
    "creationOutcomeChanged": False,
}
assert result["gitopsBootstrapped"] is False
assert result["argocdNamespaceObserved"] is False
assert result["rootApplicationDeployed"] is False
assert result["runtimeQualified"] is False
assert result["automaticTeardownExecuted"] is False
assert result["nextAction"] == "review-separate-gitops-bootstrap"

assert contract["operationBoundary"] == {
    "immediateByteIdenticalPreflightPassed": True,
    "terraformPlanExecuted": True,
    "terraformApplyExecuted": True,
    "awsInfrastructureCreated": True,
    "kubernetesApiChecked": True,
    "gitopsBootstrapExecuted": False,
    "rootApplicationDeployExecuted": False,
    "trafficGenerated": False,
    "runtimeQualificationExecuted": False,
    "remoteFaultReplayed": False,
    "awsTestPromotionExecuted": False,
    "teardownExecuted": False,
}
assert all(value is False for value in contract["packageProducer"].values())

executor_source = (
    root / "scripts/execute-v0.11.9.3.6.1-aws-dev-live-rehearsal-create.py"
).read_text()
for marker in (
    '"status": "aws-dev-infrastructure-created-api-ready"',
    '"gitops_bootstrapped": False',
    '"root_application_deployed": False',
    '"runtime_qualified": False',
    '"automatic_teardown_executed": False',
    '"next_action": "review-separate-gitops-bootstrap"',
):
    assert marker in executor_source

doc = root / "docs/V0.11.9.3.6.2_AWS_DEV_INFRASTRUCTURE_CREATE_EXECUTION.md"
for path in (contract_path, doc):
    text = path.read_text()
    assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text), path
    assert not re.search(
        r"(?<![0-9A-Za-z.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?:/[0-9]{1,2})?(?![0-9A-Za-z.])",
        text,
    ), path
    for forbidden in ('"aws_account_id"', '"publicAccessCidrs":', "ip-10-"):
        assert forbidden not in text, (path, forbidden)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.2-aws-dev-infrastructure-create-execution"),
    ("CHANGELOG.md", "## v0.11.9.3.6.2"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.2"),
    ("docs/V0.11.9.3.6.2_AWS_DEV_INFRASTRUCTURE_CREATE_EXECUTION.md", "Redacted private evidence"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.2-aws-dev-infrastructure-create-execution.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.2-aws-dev-infrastructure-create-execution.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.2 redacted create evidence, ACTIVE EKS API and no-GitOps boundaries passed.")
PY

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.2-aws-dev-infrastructure-create-execution.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.2-aws-dev-infrastructure-create-execution.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.2 infrastructure create execution evidence passed; no live operation was executed."

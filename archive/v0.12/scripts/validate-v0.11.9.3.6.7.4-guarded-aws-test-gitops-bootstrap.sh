#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.4-guarded-aws-test-gitops-bootstrap.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.7.4-aws-test-gitops-bootstrap.py"
TEST="${ROOT_DIR}/scripts/test-v0.11.9.3.6.7.4-aws-test-gitops-bootstrap.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.3.1.1-aws-test-apply-and-resume-execution-evidence.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" "${TEST}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
executor = Path(sys.argv[3])
test = Path(sys.argv[4])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.7.4"
assert contract["predecessor"] == "v0.11.9.3.6.7.3.1.1"
assert contract["status"] == "guarded-aws-test-gitops-bootstrap-implemented-offline"
assert contract["implementationBaselineCommit"] == "8ff28f9f047d866c494db04cf71333efcdfe1f34"
assert contract["nextCheckpoint"] == "merge-run-fresh-private-preflight-and-obtain-separate-bootstrap-approval"

inputs = contract["reviewedInputs"]
assert inputs["applyAndResumeEvidence"] == {
    "path": "delivery/contracts/v0.11.9.3.6.7.3.1.1-aws-test-apply-and-resume-execution-evidence.json",
    "sha256": "6ff2fef31b72a513289fcb1a20204545012ddd24fbdb37ccc5806789686ab56f",
}
assert digest(root / inputs["applyAndResumeEvidence"]["path"]) == inputs["applyAndResumeEvidence"]["sha256"]
assert inputs["terraformState"] == {
    "sha256": "a53f7bb1091990195680c9b3918a6110d4b3b8cb61441ce22aec2faf68fa725b",
    "bytes": 241960,
    "fileMode": "0600",
    "committed": False,
}
assert inputs["privateCreationPlan"]["sha256"] == "70a3899c8475552b2bf155e287477e7f81091e3cee9cfb01deb7932e3c449be8"
for key in ("privateCreationPlan", "terraformState"):
    assert inputs[key]["committed"] is False
for key in ("sharedBootstrap", "awsTestRootApplication"):
    assert digest(root / inputs[key]["path"]) == inputs[key]["sha256"]

preflight = contract["livePreflight"]
for key in (
    "requiresFreshPostMergeProtectedMain", "requiresCleanMain",
    "requiresExpectedPrivateAccount", "requiresOnlyAwsTestRehearsalCluster",
    "requiresEksActive", "requiresReviewedPublicCidr",
    "requiresKubeconfigEndpointMatch", "requiresKubernetesReadyz",
    "requiresSecretMetadataPresent", "requiresTerraformStateSha256",
    "requiresArgocdNamespaceAbsent", "requiresBootstrapServiceAccountsAbsent",
    "requiresRootApplicationAbsent",
):
    assert preflight[key] is True, key
assert preflight["readsSecretValue"] is False
assert preflight["requiresTerraformStateAddressCount"] == 103
assert preflight["minimumRemainingTeardownReviewSeconds"] == 900
assert preflight["teardownReviewDeadlineUtc"] == "2026-09-12T17:38:53Z"
assert preflight["authorizesExecution"] is False

execution = contract["execution"]
for key in (
    "requiresSeparateApproval", "requiresReviewedVerifyResultSha256",
    "rerunsImmediatePreflight", "installsArgocd",
    "appliesAwsLoadBalancerControllerApplication",
):
    assert execution[key] is True, key
assert execution["sharedBootstrapInvocationCount"] == 1
assert execution["argocdVersion"] == "v3.5.2"
assert execution["targetEnvironment"] == "aws-test"
for key in (
    "deploysRootApplication", "invokesLegacyAwsTestBootstrap", "runsTerraformPlan",
    "runsTerraformApply", "runsTerraformDestroy", "runsTraffic",
    "runsQualification", "runsPromotion", "runsTeardown", "automaticRetry",
):
    assert execution[key] is False, key

assert all(contract["postBootstrapChecks"].values())
privacy = contract["privacy"]
assert privacy["privateOutputDirectoryMode"] == "0700"
assert privacy["privateOutputFileMode"] == "0600"
for key in (
    "accountIdEmitted", "networkIdentityEmitted", "resourceIdentityEmitted",
    "secretValueRead", "rawLiveOutputCommitted",
):
    assert privacy[key] is False, key

assert digest(executor) == "59fa05e351552e560b40a18a27fdd3b84cd7ab780c06cb62a5b98a72b592a241"
assert digest(test) == "1378bc06f74571c2309c75b9f731561d369fb701d5556d3051543da3fc1bf61d"
source = executor.read_text()
assert "scripts/bootstrap-aws-test.sh" not in source
assert '[str(BOOTSTRAP)]' in source
assert '"plan"' not in source
assert '"apply"' not in source
assert '"destroy"' not in source
assert "get-secret-value" not in source
assert "deploy-aws-dev-root-app" not in source
assert "automatic_retry_performed\": False" in source
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TEST}"
"${PREDECESSOR}"

echo "v0.11.9.3.6.7.4 guarded aws-test GitOps bootstrap validation passed."

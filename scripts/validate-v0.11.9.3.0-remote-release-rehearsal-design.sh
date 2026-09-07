#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.0-remote-release-rehearsal-design.json"
TEMPLATE="${ROOT_DIR}/delivery/examples/v0.11.9.3.0-remote-release-rehearsal-plan.json"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

assert contract["schemaVersion"] == "v0.11.9.3.0"
assert contract["version"] == "v0.11.9.3.0"
assert contract["predecessor"] == "v0.11.9.2.2.3.3.3.1"
assert contract["status"] == "offline-design-implemented-live-execution-blocked"
assert contract["designBaselineCommit"] == "d2ab89b22e5e048ed4d9121170e04d7fe7156f2c"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.1-existing-image-aws-dev-promotion"

candidate = contract["candidate"]
assert candidate == {
    "repository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "tag": "sha-cf0a6bc",
    "digest": "sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623",
    "sourceCommit": "cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "workflowRunId": "34070524953",
    "metadataArtifact": "demo-api-image-metadata-cf0a6bcbc466b61f2018a0a92c961d7c03f128e8",
    "applicationVersion": "sha-cf0a6bc",
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
    "rebuildRequired": False,
    "sameDigestRequiredAcrossEnvironments": True,
}

revision = contract["revisionModel"]
assert revision["integrationTarget"] == "main"
assert revision["trustedRuntimeRef"] == "refs/heads/main"
assert revision["mainIntegrationRequiredBeforeRemoteCredentials"] is True
assert revision["pullRequestCodeAllowedRemoteCredentials"] is False
assert revision["featureWorkflowRuntimeAllowed"] is False
assert revision["activeAwsOverlaysRestoredToMainBeforeMerge"] is True
assert revision["exactMergedMainCommitRequiredAsControlPlaneIdentity"] is True

entry = contract["artifactEntry"]
assert entry["method"] == "existing-image-metadata-release-pr"
assert entry["releaseFileOnly"] is True
assert entry["automaticMerge"] is False
assert entry["implementationStatus"] == "required-before-live"
assert entry["implementationCheckpoint"] == "v0.11.9.3.1"

assert [item["name"] for item in contract["environments"]] == ["aws-dev", "aws-test", "aws-prod"]
assert [item["workloadKind"] for item in contract["environments"]] == ["Deployment", "Rollout", "Rollout"]
assert [item["manualCanaryCheckpoints"] for item in contract["environments"]] == [0, 1, 1]
assert contract["costControl"]["maximumActiveEksEnvironments"] == 1
assert contract["costControl"]["automaticTeardown"] is False
assert contract["costControl"]["teardownRequiresSeparateApproval"] is True
assert contract["costControl"]["residualCostAuditRequired"] is True

failure = contract["localFailureEvidence"]
assert failure["acceptedForV011FailureScenario"] is True
assert (failure["failedRevision"], failure["recoveredRevision"]) == (69, 70)
assert failure["remoteReplayRequired"] is False
assert failure["remoteReplayAllowed"] is False

assert all(value is False for value in contract["automaticActions"].values())
assert all(value is False for value in contract["producerExecution"].values())

runtime_executor = json.loads((root / "delivery/contracts/runtime-executor.json").read_text())
assert runtime_executor["controlPlane"]["allowedRef"] == "refs/heads/main"
assert runtime_executor["controlPlane"]["allowPullRequestCode"] is False
assert runtime_executor["production"]["enabled"] is False

runtime_workflow = (root / ".github/workflows/demo-api-runtime-qualification.yaml").read_text()
assert '"${GITHUB_REF}" != "refs/heads/main"' in runtime_workflow
assert "Trusted runtime qualification may only be invoked from refs/heads/main" in runtime_workflow

fault = (root / "apps/demo-api/src/rehearsal_fault.py").read_text()
assert "if environment != 'local':" in fault
assert "Rehearsal fault mode is local-only" in fault

prod = json.loads((root / "delivery/contracts/v0.11.8.3-prod-read-only-qualification.json").read_text())
assert prod["approval"]["required_before_cloud_access"] is True
assert prod["runtime_mutations"] is False
assert prod["automatic_deployment"] is False
assert prod["prod_qualified"] is False

for environment in ("aws-dev", "aws-test", "aws-prod"):
    release = (root / f"apps/demo-api/helm/values/releases/{environment}.yaml").read_text()
    assert candidate["digest"] not in release

dev_overlay = (root / "clusters/aws/overlays/dev/kustomization.yaml").read_text()
successor = json.loads((root / "delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json").read_text())
assert successor["predecessor"] == "v0.11.9.3.1"
assert successor["activeRevisionPolicy"]["awsDevSameRepositoryChildren"] == "main"
assert successor["activeRevisionPolicy"]["awsTestSameRepositoryChildren"] == "main"
assert successor["activeRevisionPolicy"]["awsProdSameRepositoryChildren"] == "main"
assert revision["featureBranch"] not in dev_overlay
assert "path: /spec/source/targetRevision" not in dev_overlay

for relative, marker in (
    ("README.md", "v0.11.9.3.0-remote-release-rehearsal-design"),
    ("CHANGELOG.md", "## v0.11.9.3.0"),
    ("docs/ROADMAP.md", "v0.11.9.3.0"),
    ("docs/V0.11.9.3.0_REMOTE_RELEASE_REHEARSAL_DESIGN.md", "existing-image metadata handoff"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.0-remote-release-rehearsal-design.sh"),
    (".github/CODEOWNERS", "/scripts/check-v0.11.9.3.0-remote-release-rehearsal-plan.py"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.0 candidate, main boundary, environment order, local-failure disposition, and cost contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.11.9.3.0-remote-release-rehearsal-plan.py"

if python3 "${ROOT_DIR}/scripts/check-v0.11.9.3.0-remote-release-rehearsal-plan.py" \
  --plan "${TEMPLATE}" >/dev/null 2>&1; then
  echo "Unresolved repository plan template was accepted" >&2
  exit 1
fi

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.11.9.3.0-remote-release-rehearsal-plan.py" \
  "${ROOT_DIR}/scripts/test-v0.11.9.3.0-remote-release-rehearsal-plan.py"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.0-remote-release-rehearsal-design.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.0 remote release rehearsal design validation passed; no live operation was executed."

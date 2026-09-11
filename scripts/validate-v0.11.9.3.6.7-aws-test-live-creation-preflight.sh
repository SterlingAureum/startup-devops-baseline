#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7-aws-test-live-creation-preflight.json"
PREFLIGHT="${ROOT_DIR}/scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.7-aws-test-live-creation-preflight.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${PREFLIGHT}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
preflight = Path(sys.argv[3]).read_text()

version = "v0.11.9.3.6.7"
baseline = "c95af1633718eed3429e34311ed55910dbb53a7e"
audit_sha = "d73e4b5107b4c99ae1feebd2a34197040e4d0f50b6c6ccbecdf951bbe1da25e9"
promotion_sha = "4977ddfb21738530681ce671ebaf9d71d4132e4e81c9ea1135e4b3527c27a96e"
promoted_sha = "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46"
prod_sha = "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22"
backend_sha = "374c263bc0de2200590d27c33707bfc426bc24fe0d6a3db4dd587a89cd4d9192"
wrapper_sha = "e418af18ac98ae3a1c5c7c8a2f684d76634e454e321b4ad2813f215860d6b114"

assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.6.6.1"
assert contract["status"] == "aws-test-live-creation-preflight-implemented-not-executed"
assert contract["implementationBaselineCommit"] == baseline
assert contract["executionAuthorized"] is False
assert contract["nextAction"] == (
    "merge-run-fresh-private-preflight-and-review-before-aws-test-plan-design"
)

fingerprints = contract["inputFingerprints"]
assert fingerprints == {
    "awsDevResidualCostAuditEvidence": {
        "path": "delivery/contracts/v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.json",
        "sha256": audit_sha,
        "requiredStatus": "aws-dev-residual-cost-audit-execution-recorded",
    },
    "awsTestPromotionEvidence": {
        "path": "delivery/contracts/v0.11.9.3.6.6.4-aws-test-promotion-execution-evidence.json",
        "sha256": promotion_sha,
        "requiredStatus": "reviewed-aws-dev-to-aws-test-release-only-promotion-merged",
    },
    "awsDevReleaseSha256": promoted_sha,
    "awsTestReleaseSha256": promoted_sha,
    "awsProdReleaseSha256": prod_sha,
    "testLocalBackendDeclarationSha256": backend_sha,
    "legacyApplyWrapperSha256": wrapper_sha,
}

for relative, digest in (
    (fingerprints["awsDevResidualCostAuditEvidence"]["path"], audit_sha),
    (fingerprints["awsTestPromotionEvidence"]["path"], promotion_sha),
    ("apps/demo-api/helm/values/releases/aws-dev.yaml", promoted_sha),
    ("apps/demo-api/helm/values/releases/aws-test.yaml", promoted_sha),
    ("apps/demo-api/helm/values/releases/aws-prod.yaml", prod_sha),
    ("infra/terraform/aws/environments/test/backend.tf", backend_sha),
    ("scripts/apply-aws-test.sh", wrapper_sha),
):
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest

assert contract["selectedRelease"] == {
    "releaseId": "demo-api-cf0a6bcbc466-cdffd3d71763",
    "devAndTestByteEqual": True,
    "prodHeldAtPriorRelease": True,
    "imageRebuildRequired": False,
}

expected_preflight = {
    "entrypoint": "scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py",
    "testEntrypoint": "scripts/test-v0.11.9.3.6.7-aws-test-live-creation-preflight.py",
    "confirmationEnvironmentVariable": "CONFIRM_AWS_TEST_CREATE_PREFLIGHT",
    "confirmationValue": "observe-reviewed-aws-test-create-preflight",
    "targetEnvironment": "aws-test",
    "requiredAwsRegion": "us-east-1",
    "expectedAwsAccountRequired": True,
    "requiredGitBranch": "main",
    "cleanWorktreeRequired": True,
    "headAndOriginMainMustEqualReviewedCommit": True,
    "implementationBaselineMustBeAncestor": True,
    "imageSourceCommitMustBeAncestor": True,
    "maximumActiveRehearsalEksEnvironments": 0,
    "readOnlyAwsCommands": [
        "sts get-caller-identity",
        "eks list-clusters",
    ],
    "terraformCommandAllowed": False,
}
assert contract["preflight"] == expected_preflight

assert contract["terraformStateBoundary"] == {
    "backendKind": "local",
    "backendDeclarationPath": "infra/terraform/aws/environments/test/backend.tf",
    "statePath": "infra/terraform/aws/environments/test/terraform.tfstate",
    "acceptedState": "absent-or-valid-version-four-with-zero-resource-blocks-and-instances",
    "symlinkAllowed": False,
    "resourceAttributesEmitted": False,
    "statePathEmitted": False,
    "stateDeletionAllowed": False,
}
assert contract["legacyApplyBoundary"] == {
    "entrypoint": "scripts/apply-aws-test.sh",
    "directInvocationAllowed": False,
    "reason": "legacy wrapper creates a plan and immediately applies it without a separately reviewed executor boundary",
    "futurePlanMustRemainSeparateFromApply": True,
}
assert contract["redaction"] == {
    "accountIdEmitted": False,
    "activeClusterNamesEmittedOnReady": False,
    "terraformResourceAttributesEmitted": False,
    "privateResultDirectoryMode": "0700",
    "privateResultFileMode": "0600",
}
assert all(value is False for value in contract["boundaries"].values())
assert all(value is False for value in contract["packageProducer"].values())

for marker in (
    "CONFIRM_AWS_TEST_CREATE_PREFLIGHT",
    'AWS_ENVIRONMENT") != "aws-test"',
    "EXPECTED_AWS_ACCOUNT_ID",
    "require_exact_git(expected_commit",
    "IMPLEMENTATION_BASELINE_COMMIT",
    "IMAGE_SOURCE_COMMIT",
    "AUDIT_EVIDENCE_SHA256",
    "PROMOTION_EVIDENCE_SHA256",
    "LEGACY_APPLY_WRAPPER_SHA256",
    "TEST_BACKEND_SHA256",
    '"sts", "get-caller-identity"',
    '"eks",',
    '"list-clusters",',
    "summarize_local_state",
    "terraform_state_path_emitted",
    "legacy_apply_wrapper_invoked",
    "terraform_plan_executed",
    "terraform_apply_executed",
    "environment_creation_authorized",
    "account_id_emitted",
):
    assert marker in preflight, marker

for forbidden in (
    'runner(["terraform"',
    '"terraform", "apply"',
    '"terraform", "destroy"',
    '"aws", "ec2", "create',
    '"aws", "eks", "create',
    '"kubectl"',
    '"argocd"',
):
    assert forbidden not in preflight, forbidden

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert "amazonaws.com" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.7 guarded aws-test live-creation preflight"),
    ("CHANGELOG.md", "## v0.11.9.3.6.7"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.7"),
    ("docs/V0.11.9.3.6.7_GUARDED_AWS_TEST_LIVE_CREATION_PREFLIGHT.md", "observe-reviewed-aws-test-create-preflight"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.7-aws-test-live-creation-preflight.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.7-aws-test-live-creation-preflight.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.7 exact-main aws-test preflight, local-state and no-create contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
python3 -m py_compile "${PREFLIGHT}" "${TESTS}"
python3 -m json.tool "${CONTRACT}" >/dev/null

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7-aws-test-live-creation-preflight.sh"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7-aws-test-live-creation-preflight.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.7 guarded aws-test live-creation preflight passed; no live operation was executed."

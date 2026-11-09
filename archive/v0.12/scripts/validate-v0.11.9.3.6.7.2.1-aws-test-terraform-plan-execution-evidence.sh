#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.json"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())

version = "v0.11.9.3.6.7.2.1"
commit = "845d918bbf272b485461cc6ac193789bd57e9ef8"
empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
preflight_sha = "7a3212227faca5809e5ab4d0313d5cf2ed94d50596bf9fdca41d7b4a1389b0b7"
private_plan_sha = "3d1dec2c651de87053189cfc3e755b24e95d109cdc2027a66b0f2d70420a1237"
verify_sha = "67610e394c2242e336ef0bb572ed4153125e4e519d8df6c29cf27abd521424b1"
execution_sha = "513c807b7e5077d9702249580077f791fd2f8d35da9e0bc23b83fa7e9fda846e"

assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.7.2"
assert contract["status"] == "aws-test-terraform-plan-execution-evidence-recorded"
assert contract["implementationBaselineCommit"] == commit
assert contract["applyAuthorized"] is False
assert contract["nextCheckpoint"] == (
    "implement-guarded-aws-test-apply-executor-with-fresh-post-merge-plan"
)

expected_inputs = {
    "planExecutorContract": (
        "delivery/contracts/v0.11.9.3.6.7.2-aws-test-terraform-plan-executor.json",
        "8591ed8ce73575973fec775a7841a47c4b1c0e9aab83415e8ee9d5dba6b3b3f6",
    ),
    "planExecutor": (
        "scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py",
        "6bee71419d5398c0623a7ac9434c3803107dba77bdb9908f204db56fbe1792b5",
    ),
    "terraformPlanGate": (
        "scripts/check-aws-test-create-terraform-plan.py",
        "d61a840c164a8e6a22b0ffde5f85c5b5a13de036b24530b3c98cc35002ff23c8",
    ),
}
inputs = contract["reviewedRepositoryInputs"]
assert set(inputs) == set(expected_inputs)
for key, (relative, expected_sha) in expected_inputs.items():
    assert inputs[key] == {"path": relative, "sha256": expected_sha}
    actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    assert actual == expected_sha, relative

preflight = contract["freshPreflight"]
assert preflight == {
    "status": "aws-test-live-creation-preflight-ready-for-separate-plan-review",
    "controlPlaneCommit": commit,
    "resultSha256": preflight_sha,
    "stderrSha256": empty_sha,
    "directoryModeRestated": "0700",
    "fileModeRestated": "0600",
    "activeRehearsalEnvironmentCount": 0,
    "terraformStateResourceBlockCount": 0,
    "terraformStateResourceInstanceCount": 0,
    "terraformCommandExecuted": False,
    "environmentCreationAuthorized": False,
    "mutationExecuted": False,
}

private_plan = contract["privateCreationPlan"]
assert private_plan["sha256"] == private_plan_sha
assert private_plan["fileModeRestated"] == "0600"
assert private_plan["checkerResultSha256"] == (
    "1513b16a538d3319dc17669a6cf6ff473b1f89eb53451565db495d56df1150fd"
)
assert private_plan["checkerStderrSha256"] == empty_sha
assert private_plan["checkerStatus"] == (
    "aws-test-private-creation-plan-design-validated-offline"
)
assert private_plan["reviewedSessionBudgetUsd"] == 12.0
assert private_plan["pricingReferenceCommitted"] is False
assert private_plan["plannedStartUtc"] == "2026-09-12T08:06:18Z"
assert private_plan["teardownReviewDeadlineUtc"] == "2026-09-12T16:06:18Z"
assert private_plan["maximumSessionHours"] == 8

verification = contract["executorVerification"]
assert verification == {
    "resultSha256": verify_sha,
    "stderrSha256": empty_sha,
    "status": "aws-test-terraform-plan-executor-inputs-verified",
    "remainingWindowSeconds": 28757,
    "commandsExecuted": [],
    "terraformPlanAuthorized": False,
    "terraformPlanExecuted": False,
    "terraformApplyExecuted": False,
    "environmentCreationAuthorized": False,
}

approval = contract["approval"]
assert approval["scope"] == "one aws-test Terraform plan-only operation"
assert approval["startUtc"] == "2026-09-12T08:06:18Z"
assert approval["endUtc"] == "2026-09-12T16:06:18Z"
start = datetime.fromisoformat(approval["startUtc"].replace("Z", "+00:00"))
end = datetime.fromisoformat(approval["endUtc"].replace("Z", "+00:00"))
assert int((end - start).total_seconds()) == 28800
assert approval["reviewedSessionBudgetUsd"] == 12.0
for key in (
    "readOnlyAwsIdentityEnvironmentAndSecretMetadataApproved",
    "terraformInitPlanAndShowApproved",
    "privateArtifactCaptureApproved",
):
    assert approval[key] is True, key
for key in (
    "terraformApplyApproved",
    "terraformDestroyApproved",
    "awsMutationApproved",
    "environmentCreationApproved",
    "gitopsBootstrapApproved",
    "trafficApproved",
    "qualificationApproved",
    "promotionApproved",
    "teardownApproved",
    "automaticRetryApproved",
):
    assert approval[key] is False, key

execution = contract["execution"]
assert execution["entrypoint"] == (
    "scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py"
)
assert execution["phase"] == "execute"
assert execution["executorExit"] == 0
assert execution["resultSha256"] == execution_sha
assert execution["stderrSha256"] == empty_sha
assert execution["resultFileModeRestated"] == "0600"
assert execution["status"] == "aws-test-create-only-terraform-plan-produced"
assert execution["controlPlaneCommit"] == commit
assert execution["candidateReleaseId"] == "demo-api-cf0a6bcbc466-cdffd3d71763"
assert execution["freshPreflightSha256"] == preflight_sha
assert execution["resourceChangeCount"] == 96
assert execution["actionCounts"] == {"create": 90, "read": 6, "no-op": 0}
assert execution["awsTestClusterCreateCount"] == 1
assert execution["runtimeAccessEntryCreateCount"] == 1
for key in ("secretMetadataAbsentBeforeAndAfter", "variableInputsMatched", "terraformPlanExecuted"):
    assert execution[key] is True, key
for key in (
    "terraformApplyExecuted",
    "environmentCreationAuthorized",
    "environmentCreated",
    "automaticRetryPerformed",
    "privateResourceIdentityEmitted",
):
    assert execution[key] is False, key

artifacts = contract["privateArtifacts"]
expected_artifacts = {
    "binaryPlan": ("f2165bf95e16988a86d314743053c641592151c1e2b3602ca90bf4519b2046e5", 47319),
    "terraformPlanJson": ("94205d256d2918177f66d914576a63c0759b4068d2b85e50a0734ad22dd2cc66", 300637),
    "terraformPlanText": ("152bf76a977a1636706987df4210c6db085f17bc7c1aa2f2c40d87d84ee1c561", 118707),
    "planGate": ("acf67d2fc1cbf81a06d92b3d774446d5c5224f9fd0069d0e377fa11dc03b6cce", 347),
    "planRecord": ("8f076dfe988cad9ab24b9d7ae565204cfc1072934b527b02b29a277f43d9f604", 1327),
}
for key, (sha, size) in expected_artifacts.items():
    assert artifacts[key] == {
        "sha256": sha,
        "bytes": size,
        "fileModeRestated": "0600",
    }
assert artifacts["directoryModeRestated"] == "0700"
assert artifacts["secretBeforePlanStdoutBytes"] == 0
assert artifacts["secretBeforePlanStderrBytes"] == 139
assert artifacts["secretAfterPlanStdoutBytes"] == 0
assert artifacts["secretAfterPlanStderrBytes"] == 139
assert artifacts["secretNotFoundStderrExpected"] is True
assert artifacts["rawArtifactContentCommitted"] is False
assert artifacts["terraformInitStdoutBytes"] == 861
assert artifacts["terraformPlanStdoutBytes"] == 147814
for key in (
    "terraformInitStderrBytes",
    "terraformPlanStderrBytes",
    "terraformShowJsonStderrBytes",
    "terraformShowTextStderrBytes",
):
    assert artifacts[key] == 0, key

review = contract["humanReview"]
assert review["observedAtUtc"] == "2026-09-12T08:26:19Z"
assert review["accepted"] is True
expected_create_types = {
    "aws_acm_certificate": 1,
    "aws_acm_certificate_validation": 1,
    "aws_cloudwatch_event_rule": 5,
    "aws_cloudwatch_event_target": 5,
    "aws_cloudwatch_log_group": 1,
    "aws_ec2_tag": 1,
    "aws_eip": 1,
    "aws_eks_access_entry": 2,
    "aws_eks_addon": 4,
    "aws_eks_cluster": 1,
    "aws_eks_node_group": 1,
    "aws_fis_experiment_template": 1,
    "aws_iam_openid_connect_provider": 1,
    "aws_iam_policy": 9,
    "aws_iam_role": 9,
    "aws_iam_role_policy": 1,
    "aws_iam_role_policy_attachment": 18,
    "aws_internet_gateway": 1,
    "aws_nat_gateway": 1,
    "aws_route": 3,
    "aws_route53_record": 1,
    "aws_route_table": 3,
    "aws_route_table_association": 4,
    "aws_s3_bucket": 1,
    "aws_s3_bucket_lifecycle_configuration": 1,
    "aws_s3_bucket_ownership_controls": 1,
    "aws_s3_bucket_policy": 1,
    "aws_s3_bucket_public_access_block": 1,
    "aws_s3_bucket_server_side_encryption_configuration": 1,
    "aws_s3_bucket_versioning": 1,
    "aws_secretsmanager_secret": 1,
    "aws_sqs_queue": 1,
    "aws_sqs_queue_policy": 1,
    "aws_subnet": 4,
    "aws_vpc": 1,
}
assert review["expectedPlanSummary"] == (
    "90 to add, 0 to change, 0 to destroy; 6 read-only data lookups"
)
assert review["createResourceTypeCounts"] == expected_create_types
assert sum(expected_create_types.values()) == 90
assert review["readResourceTypeCounts"] == {
    "aws_iam_policy_document": 5,
    "tls_certificate": 1,
}
assert review["eksAccessEntryInterpretation"] == {
    "karpenterEc2LinuxNodeEntry": 1,
    "githubActionsRuntimeEntry": 1,
    "unexpectedEntry": 0,
}
for key in (
    "unexpectedResourceTypeReported",
    "updateDeleteOrReplacementReported",
    "unexpectedEnvironmentReported",
    "unexpectedCostScopeReported",
):
    assert review[key] is False, key

lifecycle = contract["planLifecycle"]
assert lifecycle == {
    "reviewExpiresAtUtc": "2026-09-12T09:19:02Z",
    "reviewedPlanMayBeAppliedByThisCheckpoint": False,
    "expiredPlanMayBeApplied": False,
    "timestampEditingAllowed": False,
    "freshPreflightRequiredAfterEvidenceMerge": True,
    "freshPrivateCreationPlanRequiredAfterEvidenceMerge": True,
    "freshTerraformPlanRequiredAfterEvidenceMerge": True,
}

evidence = contract["privateEvidence"]
for key in (
    "rawPreflightStoredOutsideRepository",
    "rawPrivateCreationPlanStoredOutsideRepository",
    "rawExecutorVerificationStoredOutsideRepository",
    "rawTerraformPlanBundleStoredOutsideRepository",
):
    assert evidence[key] is True, key
for key in (
    "rawFilesCommitted",
    "privatePathCommitted",
    "awsAccountCommitted",
    "managementIpv4Committed",
    "arnCommitted",
    "resourceAddressOrIdentityCommitted",
    "pricingReferenceCommitted",
):
    assert evidence[key] is False, key

assert contract["operationBoundary"] == {
    "terraformPlanExecuted": True,
    "terraformApplyExecuted": False,
    "terraformDestroyExecuted": False,
    "awsMutationExecuted": False,
    "environmentCreated": False,
    "gitopsBootstrapped": False,
    "trafficGenerated": False,
    "qualificationExecuted": False,
    "promotionExecuted": False,
    "teardownExecuted": False,
    "automaticRetryPerformed": False,
}
assert all(value is False for value in contract["packageProducer"].values())

for digest in (
    preflight_sha,
    private_plan_sha,
    verify_sha,
    execution_sha,
    *(sha for sha, _ in expected_artifacts.values()),
):
    assert re.fullmatch(r"[0-9a-f]{64}", digest)

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert "amazonaws.com" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.7.2.1 aws-test Terraform plan execution evidence"),
    ("CHANGELOG.md", "## v0.11.9.3.6.7.2.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.7.2.1"),
    ("docs/V0.11.9.3.6.7.2.1_AWS_TEST_TERRAFORM_PLAN_EXECUTION_EVIDENCE.md", execution_sha),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.7.2.1 exact-main plan execution, human review, expiry and no-apply evidence passed.")
PY

bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.sh"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.7.2.1 aws-test Terraform plan execution evidence passed; no live operation was executed."

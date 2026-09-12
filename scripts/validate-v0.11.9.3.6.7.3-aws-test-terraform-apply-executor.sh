#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.3-guarded-aws-test-terraform-apply-executor.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.7.3-aws-test-terraform-apply.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.7.3-aws-test-terraform-apply-executor.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

"${PREDECESSOR}"
PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
sha = lambda relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()

assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.7.3"
assert contract["predecessor"] == "v0.11.9.3.6.7.2.1"
assert contract["status"] == "guarded-aws-test-terraform-apply-executor-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "52e99fcfb86e7159eea037926954e81d1bc5f26f"

historical = contract["reviewedHistoricalEvidence"]
assert historical == {
    "path": "delivery/contracts/v0.11.9.3.6.7.2.1-aws-test-terraform-plan-execution-evidence.json",
    "sha256": "beaaf8195253b085db17729793e9c8365a006d52a9b93e41fb12badf572d3692",
    "historicalControlPlaneCommit": "845d918bbf272b485461cc6ac193789bd57e9ef8",
    "historicalBinaryPlanSha256": "f2165bf95e16988a86d314743053c641592151c1e2b3602ca90bf4519b2046e5",
    "historicalPlanExpiredAtUtc": "2026-09-12T09:19:02Z",
    "historicalPlanReusable": False,
    "timestampEditingAllowed": False,
}
assert sha(historical["path"]) == historical["sha256"]

expected_inputs = {
    "planExecutor": (
        "scripts/execute-v0.11.9.3.6.7.2-aws-test-terraform-plan.py",
        "6bee71419d5398c0623a7ac9434c3803107dba77bdb9908f204db56fbe1792b5",
    ),
    "terraformPlanGate": (
        "scripts/check-aws-test-create-terraform-plan.py",
        "d61a840c164a8e6a22b0ffde5f85c5b5a13de036b24530b3c98cc35002ff23c8",
    ),
    "livePreflightEntrypoint": (
        "scripts/preflight-v0.11.9.3.6.7-aws-test-live-creation.py",
        "b41a1c58865ffd44ae35165a7a17e941dd19d4b05dd0b1d6f2f09938afeec487",
    ),
}
assert set(contract["reviewedRepositoryInputs"]) == set(expected_inputs)
for key, (path, expected) in expected_inputs.items():
    assert contract["reviewedRepositoryInputs"][key] == {"path": path, "sha256": expected}
    assert sha(path) == expected

assert sha("scripts/execute-v0.11.9.3.6.7.3-aws-test-terraform-apply.py") == (
    "669ba4614368db656929c1a2224e6c1e73f49f5de8686e2e618b9d92429760ba"
)
assert sha("scripts/test-v0.11.9.3.6.7.3-aws-test-terraform-apply-executor.py") == (
    "c5efcaa8da9680fd08dcf9470e1f171e8573bd6fad5b28ceff9fe1038a2c4541"
)

fresh = contract["freshEvidenceRequiredAfterMerge"]
assert all(fresh[key] is True for key in (
    "postImplementationProtectedMain", "byteIdenticalLivePreflight",
    "populatedPrivateCreationPlan", "savedBinaryPlan",
    "terraformShowJsonAndText", "machinePlanGate", "humanPlanReview",
    "separateApplyApproval",
))
assert fresh["planReviewTtlSeconds"] == 3600
assert fresh["minimumRemainingPlanReviewSeconds"] == 900

executor = contract["executor"]
assert executor["phases"] == ["verify", "execute"]
assert executor["verifyRunsOperationalCommands"] is False
assert executor["verifyAuthorizesApply"] is False
assert executor["executeRequiresSeparateApproval"] is True
assert executor["automaticRetryAllowed"] is False

commands = contract["commandBoundary"]
assert commands["verifyAllowedOperationalCommands"] == []
assert commands["terraformPlanAllowed"] is False
assert commands["terraformDestroyAllowed"] is False
assert commands["legacyApplyWrapperAllowed"] is False
assert commands["kubectlAllowed"] is False
assert commands["argocdAllowed"] is False
assert commands["executeTerraformCommands"] == [
    "terraform show -json exact-saved-plan",
    "terraform apply -input=false -auto-approve exact-saved-plan",
    "terraform state list",
]

success = contract["successBoundary"]
assert success["status"] == "aws-test-reviewed-saved-plan-applied"
assert success["terraformPlanExecuted"] is False
assert success["terraformApplyExecuted"] is True
assert success["environmentCreated"] is True
for key in (
    "gitopsBootstrapExecuted", "trafficGenerated",
    "qualificationExecuted", "automaticRetryPerformed",
):
    assert success[key] is False

for key, value in contract["packageProducer"].items():
    assert value is False, key
for key in (
    "terraformPlanAuthorized", "terraformPlanExecuted",
    "terraformApplyAuthorized", "terraformApplyExecuted",
    "environmentCreationAuthorized", "environmentCreated",
):
    assert contract[key] is False, key

public_files = [
    root / "delivery/contracts/v0.11.9.3.6.7.3-guarded-aws-test-terraform-apply-executor.json",
    root / "docs/V0.11.9.3.6.7.3_GUARDED_AWS_TEST_TERRAFORM_APPLY_EXECUTOR.md",
]
for path in public_files:
    text = path.read_text()
    assert "/tmp/" not in text, path
    assert "arn:aws:" not in text, path
    assert re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text) is None, path

source = (root / "scripts/execute-v0.11.9.3.6.7.3-aws-test-terraform-apply.py").read_text()
assert "apply-aws-test.sh" not in source
assert "\"destroy\"" not in source
assert "\"plan\", \"-input=false\"" not in source
assert source.count("[*prefix, \"apply\"") == 1
assert "automatic_retry_performed\": False" in source
PY

echo "v0.11.9.3.6.7.3 guarded aws-test Terraform apply executor validation passed."

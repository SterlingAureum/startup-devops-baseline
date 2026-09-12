#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.7.3.1-aws-test-state-classification-repair.json"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.7.3.1-aws-test-post-apply-resume.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.3-aws-test-terraform-apply-executor.sh"

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

import ast
import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract_path = Path(sys.argv[2])
contract = json.loads(contract_path.read_text())
digest = lambda relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()

assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.7.3.1"
assert contract["predecessor"] == "v0.11.9.3.6.7.3"
assert contract["status"] == (
    "aws-test-state-classification-repair-and-post-apply-resume-implemented-not-executed"
)
assert contract["implementationBaselineCommit"] == "1376129d42c6dbc19ffb57c97244d2b31ddd4ff7"

incident = contract["incident"]
assert incident["appliedControlPlaneCommit"] == contract["implementationBaselineCommit"]
assert incident["applyExecutorExit"] == 1
assert incident["terraformApplyCommandSucceeded"] is True
assert incident["terraformStateListCommandSucceeded"] is True
assert incident["failureStage"] == "post-apply-state-address-classification"
assert incident["failedResultSha256"] == hashlib.sha256(b"").hexdigest()
assert incident["failedStderrSha256"] == "410415ad92580ecd0650655776821821caf6653bbc57cb4dd70f63995760be4e"
assert incident["failedStderrBytes"] == 88
assert incident["automaticRetryPerformed"] is False
assert incident["secondApplyAllowed"] is False

reviewed = contract["reviewedInputs"]
assert reviewed == {
    "freshPreflightSha256": "444ecdd6fb17bba42f48dc72083501d3cc64753aa38b8eda907d03d258f37f79",
    "privateCreationPlanSha256": "70a3899c8475552b2bf155e287477e7f81091e3cee9cfb01deb7932e3c449be8",
    "planExecutionResultSha256": "4bedd473845ec6d3b43b9b8afeeeece7c3dc5f33bf10e88d0574bbc7d18e0ec6",
    "applyVerifyResultSha256": "ffdc54c2c152654b63ceac050a5e951de4a2fa0bf259ba821c52440ce691b1e5",
    "binaryPlanSha256": "7c8b5c17b17dcface9fbc97810ec1cedc1985bcb32f3157f4e476b8211d82d0e",
    "terraformPlanJsonSha256": "d93343ca8b7294537eeccff8797827c8af3a63ea6f0088a7dc101236dbf231f3",
    "terraformPlanTextSha256": "152bf76a977a1636706987df4210c6db085f17bc7c1aa2f2c40d87d84ee1c561",
    "planGateSha256": "acf67d2fc1cbf81a06d92b3d774446d5c5224f9fd0069d0e377fa11dc03b6cce",
    "planRecordSha256": "a196b0b7370d7c3772c3a4a60ebeff43fd39ddd59aa7921fa8afabdefab98852",
}

private = contract["privateApplyEvidence"]
assert private["terraformApplyStdoutSha256"] == "ca2e3d7e1884e40a0339ce7912dae61d28be9abb720b0e3262df5e93a446e046"
assert private["terraformApplyStderrSha256"] == hashlib.sha256(b"").hexdigest()
assert private["terraformStateListStdoutSha256"] == "9c0c0fbce81f313a12d088bb0d071cfa20f911c1abb69fb35841de8dea7cdd96"
assert private["terraformStateSha256"] == "a53f7bb1091990195680c9b3918a6110d4b3b8cb61441ce22aec2faf68fa725b"
assert private["terraformStateBytes"] == 241960
assert private["privateDirectoryMode"] == "0700"
assert private["privateFileMode"] == "0600"
assert private["rawContentCommitted"] is False
assert private["privatePathCommitted"] is False

classification = contract["stateClassification"]
assert classification == {
    "planResourceChangeCount": 96,
    "planCreateAddressCount": 90,
    "stateListAddressCount": 103,
    "stateResourceBlockCount": 80,
    "stateResourceInstanceCount": 103,
    "missingPlannedCreateCount": 0,
    "unexpectedManagedAddressCount": 0,
    "acceptedUnplannedDataAddressCount": 7,
    "unexpectedUnclassifiedAddressCount": 0,
    "acceptedUnplannedDataTypes": {
        "aws_caller_identity": 3,
        "aws_partition": 3,
        "aws_route53_zone": 1,
    },
    "arbitraryDataSourceAllowed": False,
    "additionalManagedResourceAllowed": False,
    "missingPlannedCreateAllowed": False,
}

resume = contract["resumeExecutor"]
assert resume["phases"] == ["verify", "execute"]
assert resume["verifyOperationalCommands"] == []
assert resume["verifyAuthorizesResume"] is False
assert resume["executeRequiresSeparateApproval"] is True
assert resume["confirmationVariable"] == "CONFIRM_AWS_TEST_POST_APPLY_RESUME"
assert resume["confirmationValue"] == "verify-reviewed-aws-test-post-apply-state"

boundary = contract["resumeCommandBoundary"]
assert boundary["allowedAwsReads"] == [
    "sts get-caller-identity", "eks list-clusters", "eks describe-cluster",
    "secretsmanager describe-secret metadata",
]
for key in (
    "terraformCommandAllowed", "terraformPlanAllowed", "terraformApplyAllowed",
    "terraformDestroyAllowed", "awsMutationAllowed", "kubernetesCommandAllowed",
    "argocdCommandAllowed", "gitMutationAllowed",
):
    assert boundary[key] is False, key

for key, value in contract["packageProducer"].items():
    assert value is False, key
for key in (
    "resumeAuthorized", "terraformPlanAuthorized", "terraformApplyAuthorized",
    "terraformDestroyAuthorized",
):
    assert contract[key] is False, key

executor = "scripts/execute-v0.11.9.3.6.7.3.1-aws-test-post-apply-resume.py"
tests = "scripts/test-v0.11.9.3.6.7.3.1-aws-test-post-apply-resume.py"
assert digest(executor) == "10e8cc7d615401518bd9a2bf9bebb640eb591a776aeb1f13f7d005fab13554e9"
assert digest(tests) == "33fec066f6babab8b9f7fc1ce50bcb195c4355c58ca462b88ff2b9f4fd008db9"
tree = ast.parse((root / executor).read_text())
command_heads = []
for node in ast.walk(tree):
    if isinstance(node, ast.List) and node.elts:
        first = node.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            command_heads.append(first.value)
assert "terraform" not in command_heads
assert "kubectl" not in command_heads
assert "argocd" not in command_heads
assert set(command_heads) <= {
    "git", "aws", "branch", "status", "rev-parse", "merge-base", "create"
}

for path in (
    contract_path,
    root / "docs/V0.11.9.3.6.7.3.1_AWS_TEST_STATE_CLASSIFICATION_REPAIR.md",
):
    text = path.read_text()
    assert "/tmp/" not in text, path
    assert "arn:aws:" not in text, path
    assert re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text) is None, path
PY

echo "v0.11.9.3.6.7.3.1 state-classification repair and no-reapply resume contracts passed."

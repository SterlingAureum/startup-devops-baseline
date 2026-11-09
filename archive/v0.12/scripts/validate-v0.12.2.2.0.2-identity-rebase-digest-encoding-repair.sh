#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR

python3 - <<'PY'
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.2.0.2-identity-rebase-digest-encoding-repair.json"
predecessor_path = root / "delivery/contracts/v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.json"
executor_path = root / "scripts/execute-v0.12.2.2.0.1-bootstrap-state-recovery.py"
test_path = root / "scripts/test-v0.12.2.2.0.1-bootstrap-state-recovery.py"
validator_path = root / "scripts/validate-v0.12.2.2.0.2-identity-rebase-digest-encoding-repair.sh"
doc_path = root / "docs/V0.12.2.2.0.2_IDENTITY_REBASE_DIGEST_ENCODING_REPAIR.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.2.0.2-identity-rebase-digest-encoding-repair-v1", "schema drift")
    require(value.get("version") == "v0.12.2.2.0.2", "version drift")
    require(value.get("status") == "delivered-offline-digest-encoding-repair", "status drift")
    require(value.get("implementationBaselineCommit") == "7b0b4e8de1f4626021d62dbf922d145dc7d3a811", "baseline drift")
    require(value.get("predecessor") == {
        "version": "v0.12.2.2.0.1",
        "contract": "delivery/contracts/v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.json",
        "requiredStatus": "delivered-awaiting-separate-read-only-identity-rebase-recovery-approval",
    }, "predecessor drift")
    failed = value.get("failedVerification")
    require(failed.get("privateRecoveryRequestSha256") == "a10b3c4a9376745e25366a0f67d6ca9840f4637296da6671498b9fcc7b315ada", "failed request drift")
    require(failed.get("failure") == "State resources digest changed", "failure drift")
    require(all(failed.get(key) is False for key in ("awsCommandsExecuted", "terraformCommandsExecuted", "recoveryOutputCreated", "stateDriftObserved", "requestReusable")), "failed-attempt boundary drift")
    cause = value.get("rootCause")
    require(cause == {
        "recordedDigestEncoding": "sorted compact JSON followed by exactly one LF byte",
        "executorDigestEncoding": "sorted compact JSON without trailing LF",
        "missingByteHex": "0a",
        "contentComparisonWasEqual": True,
    }, "root cause drift")
    repair = value.get("repair")
    require(repair.get("sortedKeys") is True and repair.get("compactSeparators") is True and repair.get("trailingLfByteCount") == 1, "encoding repair drift")
    require(all(repair.get(key) is False for key in ("changesBoundDigestValues", "changesPrivateEvidence", "changesRecoveryAuthority")), "repair scope drift")
    require(repair.get("addsFixedLfRegressionTest") is True, "regression test missing")
    digests = value.get("reviewedDigestBindings")
    require(digests == {
        "resourcesSha256": "9ae208cbf85c37a2b9820e41be80b852efcc3cbdade7d9caa7e425784be0556e",
        "outputsSha256": "695a5087bac5068c4a7ae30ac5d3edc5cb09e28bd8cfe591d11a0c2d0aca8b2b",
        "backupCheckResultsSha256": "5edcc426d374ea432c4c8509b9a7e3060908f8b2bdaf754255934e05792134a8",
        "remoteCheckResultsSha256": "9e28019a03a22863c8ed4d06f2c57a1cf26e7634b3f6a3735c9f680fc17277ec",
        "semanticProjectionSha256": "46a2fda8b522437194aab7a03b41170ff6a02f1affaa067ec76ce8a0ebada48d",
    }, "digest bindings drift")
    evidence = value.get("evidence")
    require(all(evidence.get(key) is True for key in ("backupAndRemoteResourcesEqual", "backupAndRemoteOutputsEqual", "backupAndRemoteSemanticProjectionEqual", "allFiveRecordedDigestsMatchLfEncoding")), "evidence drift")
    boundary = value.get("executionBoundary")
    require(all(boundary.get(key) is False for key in ("packageApplyRunsAws", "packageApplyRunsTerraform", "packageValidationRunsAws", "packageValidationRunsTerraform", "terraformInit", "stateMigration", "statePush", "terraformPlan", "terraformApply", "destroy", "automaticRetry")), "authority drift")
    next_attempt = value.get("nextAttempt")
    require(all(next_attempt.get(key) is True for key in ("requiresNewPrivateRequest", "requiresNewApprovalWindow", "requiresNewProtectedMainCommit", "verifyBeforeSeparateExecuteApproval")), "next-attempt boundary drift")


contract = json.loads(contract_path.read_text())
validate(contract)
predecessor = json.loads(predecessor_path.read_text())
require(predecessor.get("version") == "v0.12.2.2.0.1" and predecessor.get("status") == contract["predecessor"]["requiredStatus"], "predecessor contract changed")

mutations = []
def mutate(path, value):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    mutations.append(item)

mutate(["status"], "complete")
mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["failedVerification", "privateRecoveryRequestSha256"], "0" * 64)
mutate(["failedVerification", "awsCommandsExecuted"], True)
mutate(["failedVerification", "stateDriftObserved"], True)
mutate(["failedVerification", "requestReusable"], True)
mutate(["rootCause", "missingByteHex"], "")
mutate(["rootCause", "contentComparisonWasEqual"], False)
mutate(["repair", "trailingLfByteCount"], 0)
mutate(["repair", "changesBoundDigestValues"], True)
mutate(["repair", "addsFixedLfRegressionTest"], False)
mutate(["reviewedDigestBindings", "resourcesSha256"], "0" * 64)
mutate(["evidence", "allFiveRecordedDigestsMatchLfEncoding"], False)
mutate(["executionBoundary", "terraformInit"], True)
mutate(["executionBoundary", "automaticRetry"], True)
mutate(["nextAttempt", "requiresNewPrivateRequest"], False)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open repair mutation {index}")

spec = importlib.util.spec_from_file_location("identity_rebase_digest_repair", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
with_lf = hashlib.sha256(b'{"a":1}\n').hexdigest()
without_lf = hashlib.sha256(b'{"a":1}').hexdigest()
require(executor.compact_digest({"a": 1}) == with_lf, "executor omits required LF")
require(executor.compact_digest({"a": 1}) != without_lf, "executor still uses no-LF digest")

tracked = subprocess.run(
    ["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))],
    capture_output=True, text=True, check=True,
).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("exactly one LF byte", "executed no AWS or Terraform command", "must not be reused", "new approval window"):
    require(marker in documentation, f"documentation marker missing: {marker}")

print(f"v0.12.2.2.0.2 digest-encoding repair and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.2.0.1-bootstrap-state-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.2.0.1-bootstrap-state-recovery.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.2.0.1-bootstrap-state-recovery.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.2.0.1-bootstrap-state-identity-rebase-recovery.sh"

echo "v0.12.2.2.0.2 identity-rebase digest-encoding repair passed offline; no AWS or Terraform command was executed."

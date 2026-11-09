#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT_DIR

python3 - <<'PY'
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-repair.json"
predecessor_path = root / "delivery/contracts/v0.12.2.3.1.0.2-reviewed-refresh-only-state-reconciliation.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-repair.sh"
doc_path = root / "docs/V0.12.2.3.1.0.2.0.1_STATE_PULL_CHECK_RESULTS_NORMALIZATION_REPAIR.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-repair-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.2.0.1", "version drift")
    require(value.get("status") == "delivered-awaiting-fresh-request-and-separate-approval", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "ab126f6bf7bff021b8821c0e0951d739c635aa49", "baseline drift")
    incident = value.get("incident")
    require(incident.get("failedApplyRequestSha256") == "a58ea364097505b798771eae726c147e906cd365fa7d9c6c4525c30bec31274f", "incident request drift")
    require(incident.get("applyExecuted") is False, "prior apply boundary drift")
    require(incident.get("completedOperationalCommands") == ["aws-identity-read", "terraform-state-pull-before"], "incident command drift")
    require(incident.get("failedIdentityStdoutSha256") == "972b1b4b008369972374b6a8bdeded41cf2df5347e0b0cea93e5c8777518d6be", "identity evidence drift")
    require(incident.get("observedStateSha256") == "5ff0cb562fa7bf6d99cd2068c373646fca50f06cbaa08f3f5a3e3392bf2c55e1" and incident.get("observedStateSize") == 69929, "observed state drift")
    normalization = value.get("normalizationGate")
    require(normalization.get("onlyChangedTopLevelKey") == "check_results", "normalization scope drift")
    require(normalization.get("observedCheckResultsSha256") == "5edcc426d374ea432c4c8509b9a7e3060908f8b2bdaf754255934e05792134a8", "check_results drift")
    require(normalization.get("semanticProjectionSha256") == "1d21a9edbfe82d1d1496b312c8a31996c20f9f4bf8505604a277cbdede2f8d15", "semantic projection drift")
    require(normalization.get("formatVersion") == 4 and normalization.get("terraformVersion") == "1.14.5", "state format drift")
    require(all(normalization.get(key) is True for key in ("serialUnchanged", "lineageUnchanged", "resourcesUnchanged", "outputsUnchanged", "addressesUnchanged")), "semantic equality drift")
    require(normalization.get("managedAddressCount") == 13 and normalization.get("dataAddressCount") == 9, "address count drift")
    verify = value.get("verifyBoundary")
    require(all(verify.get(key) is False for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence", "applyAuthorizedByVerify")), "verify boundary drift")
    require(verify.get("reconstructsFailedRequestAndReviewedPlanChain") is True and verify.get("revalidatesExactNormalization") is True, "verify chain drift")
    execute = value.get("executeBoundary")
    require(all(execute.get(key) is True for key in ("awsIdentityAndS3Read", "terraformStatePullAndList", "exactSavedRefreshPlanApply", "acceptExactCheckResultsNormalization")), "execution authority drift")
    require(all(execute.get(key) is False for key in ("terraformInit", "terraformPlan", "unsavedApply", "statePush", "destroy", "iamPolicyAttachment", "directS3Mutation", "forceUnlock", "automaticRetry", "automaticRollback")), "forbidden authority drift")
    success = value.get("successGate")
    require(success.get("applyExitCode") == 0 and success.get("remoteResourceActions") == 0 and success.get("stateSerialIncrement") == 1, "success action drift")
    require(success.get("managedAddressCount") == 13 and success.get("dataAddressCount") == 9, "success address drift")
    require(success.get("stateObjectVersionDelta") == 1 and success.get("stateDeleteMarkerDelta") == 0 and success.get("lockObjectVersionDelta") == 1 and success.get("lockDeleteMarkerDelta") == 1, "object history drift")
    require(all(success.get(key) is True for key in ("stateLineageUnchanged", "plannedValuesExactlyPersisted", "lockObjectAbsent", "humanReviewRequiredAfterExecution")), "success gate drift")
    failure = value.get("failurePolicy")
    require(all(failure.get(key) is True for key in ("preservePrivateEvidence", "preserveAnyWrittenState", "manualRecoveryRequired")), "failure preservation drift")
    require(failure.get("automaticRetry") is False and failure.get("automaticRollback") is False, "failure retry drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in ("publishesAwsAccount", "publishesResourceIdentity", "publishesStateBytes", "publishesPlanContents", "publishesObjectVersionIds", "publishesPrivatePaths")), "privacy drift")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "redacted result drift")
    require(value.get("successor") == {"scope": "separately-reviewed-post-reconciliation-zero-change-proof", "ordinaryPlanAuthorizedByThisIncrement": False}, "successor drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "package producer drift")


contract = json.loads(contract_path.read_text())
validate(contract)
predecessor = json.loads(predecessor_path.read_text())
require(predecessor.get("version") == "v0.12.2.3.1.0.2", "predecessor changed")

mutations = []
def mutate(path, replacement):
    item = deepcopy(contract)
    cursor = item
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    mutations.append(item)

mutate(["status"], "complete")
mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["incident", "applyExecuted"], True)
mutate(["incident", "observedStateSha256"], "0" * 64)
mutate(["incident", "completedOperationalCommands"], ["terraform-apply"])
mutate(["normalizationGate", "onlyChangedTopLevelKey"], "resources")
mutate(["normalizationGate", "serialUnchanged"], False)
mutate(["normalizationGate", "resourcesUnchanged"], False)
mutate(["verifyBoundary", "terraformCommands"], True)
mutate(["verifyBoundary", "applyAuthorizedByVerify"], True)
mutate(["executeBoundary", "terraformPlan"], True)
mutate(["executeBoundary", "unsavedApply"], True)
mutate(["executeBoundary", "statePush"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "remoteResourceActions"], 1)
mutate(["successGate", "stateSerialIncrement"], 2)
mutate(["successGate", "plannedValuesExactlyPersisted"], False)
mutate(["failurePolicy", "automaticRetry"], True)
mutate(["privacyBoundary", "publishesStateBytes"], True)
mutate(["successor", "ordinaryPlanAuthorizedByThisIncrement"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

spec = importlib.util.spec_from_file_location("normalization_repair_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
example = json.loads(example_path.read_text())
example["expectedMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)

source = executor_path.read_text()
for forbidden in ('"plan",', '"init"', '"state", "push"', '"force-unlock"', '"s3api", "put-object"', '"s3api", "delete-object"'):
    require(forbidden not in source, f"repair executor contains forbidden command: {forbidden}")
for marker in ("allow_existing_output=True", "validate_check_results_normalization", "execute_verified"):
    require(marker in source, f"repair delegation marker missing: {marker}")

tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))], capture_output=True, text=True, check=True).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("stopped before apply", "only the top-level `check_results`", "does not establish a", "without retry"):
    require(marker in documentation, f"documentation marker missing: {marker}")
public_text = contract_path.read_text() + example_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public artifact contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public artifact contains an AWS account")
require("VersionId\"" not in public_text, "public artifact contains an object version ID")

print(f"v0.12.2.3.1.0.2.0.1 normalization-repair contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.2-reviewed-refresh-only-state-reconciliation.sh"

echo "v0.12.2.3.1.0.2.0.1 exact state-pull check_results normalization repair passed offline; no AWS or Terraform command was executed."

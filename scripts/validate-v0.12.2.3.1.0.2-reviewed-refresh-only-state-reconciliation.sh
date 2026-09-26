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
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2-reviewed-refresh-only-state-reconciliation.json"
predecessor_path = root / "delivery/contracts/v0.12.2.3.1.0.1.0.1-refresh-only-plan-evidence-recovery.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.2-refresh-only-state-reconciliation-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.2-reviewed-refresh-only-state-reconciliation.sh"
doc_path = root / "docs/V0.12.2.3.1.0.2_REVIEWED_REFRESH_ONLY_STATE_RECONCILIATION.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.2-reviewed-refresh-only-state-reconciliation-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.2", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-exact-saved-plan-apply-approval", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "eb6af48ca1e50c64e0db7e54a6bdee62c220fe2f", "baseline drift")
    evidence = value.get("reviewedEvidence")
    expected = {
        "recoveryControlPlaneCommit": "eb6af48ca1e50c64e0db7e54a6bdee62c220fe2f",
        "privateRecoveryRequestSha256": "c1348c8aa3da406109534cdb1faffcd99ec065fd2ab184f72d435b576a7962b5",
        "recoveryResultSha256": "737211cfbf8331bcfc79e8d768f6e911dd4caf7c17a1749f31b6e0071b91cee9",
        "validationSha256": "8776a11aba093bca353de48f0b2b9aff1b1bf8730dc43af9f2a2850766931611",
        "binaryRefreshPlanSha256": "25e0d13ea279af093fc138c9f6d946694e3e399df5c5c6c2648e401ce789f74c",
        "refreshPlanJsonSha256": "b89d89f3590f8cf7aab5bab15fa5d0dc2e522cb8d9c56098bcb6ea02a11887ad",
        "refreshPlanTextSha256": "746ef94f5ddb6bd3630006011745bf2f67d8ce7a43eff54642d7d54193e67d98",
        "resourceDriftSha256": "cda2f5fefc620e11747c88e38db673e906fb7c4a29a5a5c886a5f7ec0140ab7a",
        "canonicalRemoteStateSha256": "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139",
    }
    require(all(evidence.get(key) == expected_value for key, expected_value in expected.items()), "reviewed evidence drift")
    require(evidence.get("resourceDriftCount") == 7 and evidence.get("resourceChangeCount") == 0 and evidence.get("outputChangeCount") == 7 and evidence.get("humanReviewPassed") is True, "reviewed plan shape drift")
    verify = value.get("verifyBoundary")
    require(all(verify.get(key) is False for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence", "applyAuthorizedByVerify")), "verify boundary drift")
    require(verify.get("revalidatesExactSavedPlanAndRecoveryChain") is True, "verify chain drift")
    execute = value.get("executeBoundary")
    require(all(execute.get(key) is True for key in ("awsIdentityAndS3Read", "terraformStatePullAndList", "exactSavedRefreshPlanApply")), "execution authority drift")
    require(all(execute.get(key) is False for key in ("terraformInit", "terraformPlan", "unsavedApply", "statePush", "destroy", "iamPolicyAttachment", "directS3Mutation", "forceUnlock", "automaticRetry", "automaticRollback")), "forbidden authority drift")
    success = value.get("successGate")
    require(success.get("applyExitCode") == 0 and success.get("remoteResourceActions") == 0 and success.get("stateSerialIncrement") == 1, "apply success drift")
    require(success.get("managedAddressCount") == 13 and success.get("dataAddressCount") == 9, "address count drift")
    require(success.get("stateObjectVersionDelta") == 1 and success.get("stateDeleteMarkerDelta") == 0 and success.get("lockObjectVersionDelta") == 1 and success.get("lockDeleteMarkerDelta") == 1, "object history delta drift")
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
require(predecessor.get("version") == "v0.12.2.3.1.0.1.0.1", "predecessor changed")

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
mutate(["reviewedEvidence", "privateRecoveryRequestSha256"], "0" * 64)
mutate(["reviewedEvidence", "binaryRefreshPlanSha256"], "0" * 64)
mutate(["reviewedEvidence", "resourceChangeCount"], 13)
mutate(["reviewedEvidence", "humanReviewPassed"], False)
mutate(["verifyBoundary", "terraformCommands"], True)
mutate(["verifyBoundary", "applyAuthorizedByVerify"], True)
mutate(["executeBoundary", "terraformPlan"], True)
mutate(["executeBoundary", "unsavedApply"], True)
mutate(["executeBoundary", "statePush"], True)
mutate(["executeBoundary", "directS3Mutation"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "remoteResourceActions"], 1)
mutate(["successGate", "stateSerialIncrement"], 2)
mutate(["successGate", "plannedValuesExactlyPersisted"], False)
mutate(["successGate", "stateObjectVersionDelta"], 2)
mutate(["successGate", "stateDeleteMarkerDelta"], 1)
mutate(["successGate", "lockObjectAbsent"], False)
mutate(["failurePolicy", "automaticRetry"], True)
mutate(["failurePolicy", "preserveAnyWrittenState"], False)
mutate(["privacyBoundary", "publishesPlanContents"], True)
mutate(["successor", "ordinaryPlanAuthorizedByThisIncrement"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

spec = importlib.util.spec_from_file_location("state_reconciliation_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
example = json.loads(example_path.read_text())
example["expectedMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["recoveryStateHeadSha256"] = "2" * 64
example["recoveryObjectVersionsSha256"] = "3" * 64
example["humanReview"]["reviewedAtUtc"] = "2026-09-26T00:00:00Z"
example["approval"] = {"notBeforeUtc": "2026-09-26T00:01:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)

source = executor_path.read_text()
for forbidden in ('"plan",', '"init"', '"state", "push"', '"force-unlock"', '"s3api", "put-object"', '"s3api", "delete-object"'):
    require(forbidden not in source, f"executor contains forbidden command: {forbidden}")
for marker in ('"apply", "-input=false"', '"state", "pull"', '"state", "list"', '"show", "-json"', '"head-object"', '"list-object-versions"'):
    require(marker in source, f"executor marker missing: {marker}")

tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))], capture_output=True, text=True, check=True).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("exact previously saved", "does not generate another plan", "serial advanced exactly once", "forbids automatic retry"):
    require(marker in documentation, f"documentation marker missing: {marker}")
public_text = contract_path.read_text() + example_path.read_text() + documentation
require(re.search(r"arn:aws:", public_text) is None, "public artifact contains an AWS ARN")
require(re.search(r'\b[0-9]{12}\b', public_text) is None, "public artifact contains an AWS account")
require("VersionId\"" not in public_text, "public artifact contains an object version ID")

print(f"v0.12.2.3.1.0.2 state-reconciliation contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.1.0.1-refresh-only-plan-evidence-recovery.sh"

echo "v0.12.2.3.1.0.2 reviewed refresh-only state reconciliation passed offline; no AWS or Terraform command was executed."

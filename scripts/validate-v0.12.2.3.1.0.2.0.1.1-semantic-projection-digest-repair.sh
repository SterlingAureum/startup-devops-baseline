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
import subprocess

root = Path(os.environ["ROOT_DIR"])
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1.1-semantic-projection-digest-repair.json"
normalization_contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-repair.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.2.0.1.1-semantic-projection-digest-repair.sh"
doc_path = root / "docs/V0.12.2.3.1.0.2.0.1.1_SEMANTIC_PROJECTION_DIGEST_REPAIR.md"
corrected = "1d21a9edbfe82d1d1496b312c8a31996c20f9f4bf8505604a277cbdede2f8d15"
incorrect = "14715b5d56f06089cdb81056dbce3a05b0475608a65d96a51541854f9efc8822"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.2.0.1.1-semantic-projection-digest-repair-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.2.0.1.1", "version drift")
    require(value.get("status") == "delivered-offline-superseding-incorrect-projection-digest", "status drift")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "0f5edb811def20a5b004a67026d3b259079f1953", "baseline drift")
    incident = value.get("incident")
    require(incident.get("phase") == "command-free-verify", "incident phase drift")
    require(incident.get("awsCommandsExecuted") == 0 and incident.get("terraformCommandsExecuted") == 0, "incident command drift")
    require(incident.get("applyExecuted") is False and incident.get("stateContentMutated") is False, "incident mutation drift")
    require(incident.get("failure") == "state-semantic-projection-digest-mismatch", "incident failure drift")
    correction = value.get("correction")
    require(correction.get("projectionKeys") == ["lineage", "outputs", "resources", "serial", "terraform_version", "version"], "projection keys drift")
    require(correction.get("excludedKey") == "check_results", "projection exclusion drift")
    require(correction.get("encoding") == "json-sort-keys-compact-with-one-trailing-lf", "projection encoding drift")
    require(correction.get("incorrectSha256") == incorrect and correction.get("correctedSha256") == corrected, "projection digest drift")
    require(correction.get("observedStateSha256") == "5ff0cb562fa7bf6d99cd2068c373646fca50f06cbaa08f3f5a3e3392bf2c55e1", "observed state drift")
    require(correction.get("onlyChangedTopLevelKey") == "check_results" and correction.get("semanticProjectionEqual") is True, "normalization boundary drift")
    authority = value.get("authority")
    require(all(authority.get(key) is False for key in ("addsAwsAuthority", "addsTerraformAuthority", "addsApplyAuthority", "addsStateMutationAuthority", "widensAcceptedStateShape", "widensAcceptedStateDigest")), "authority drift")
    require(authority.get("requiresFreshPostMergeRequest") is True and authority.get("requiresSeparateExecutionApproval") is True, "fresh approval drift")
    failure = value.get("failurePolicy")
    require(failure.get("preservePrivateEvidence") is True and failure.get("reuseExpiredRequest") is False, "failure evidence drift")
    require(failure.get("automaticRetry") is False and failure.get("automaticRollback") is False, "failure retry drift")
    privacy = value.get("privacyBoundary")
    require(all(privacy.get(key) is False for key in ("publishesAwsAccount", "publishesResourceIdentity", "publishesStateBytes", "publishesPrivatePaths")), "privacy drift")
    require(privacy.get("allowsPublicDigestsAndBooleans") is True, "privacy output drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "package producer drift")


contract = json.loads(contract_path.read_text())
validate(contract)

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
mutate(["incident", "awsCommandsExecuted"], 1)
mutate(["incident", "applyExecuted"], True)
mutate(["correction", "projectionKeys"], ["resources", "outputs"])
mutate(["correction", "excludedKey"], "resources")
mutate(["correction", "encoding"], "json-default")
mutate(["correction", "correctedSha256"], "0" * 64)
mutate(["correction", "onlyChangedTopLevelKey"], "outputs")
mutate(["correction", "semanticProjectionEqual"], False)
mutate(["authority", "addsTerraformAuthority"], True)
mutate(["authority", "addsApplyAuthority"], True)
mutate(["authority", "widensAcceptedStateShape"], True)
mutate(["authority", "requiresFreshPostMergeRequest"], False)
mutate(["failurePolicy", "reuseExpiredRequest"], True)
mutate(["failurePolicy", "automaticRetry"], True)
mutate(["privacyBoundary", "publishesStateBytes"], True)
for index, item in enumerate(mutations, 1):
    try:
        validate(item)
    except (AttributeError, KeyError, TypeError, ValueError):
        continue
    raise ValueError(f"fail-open contract mutation {index}")

normalization_contract = json.loads(normalization_contract_path.read_text())
require(normalization_contract["normalizationGate"]["semanticProjectionSha256"] == corrected, "normalization contract still uses incorrect digest")
example = json.loads(example_path.read_text())
require(example["semanticProjectionSha256"] == corrected, "request example still uses incorrect digest")

spec = importlib.util.spec_from_file_location("projection_digest_repair_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(executor)
require(executor.SEMANTIC_PROJECTION_SHA256 == corrected, "executor still uses incorrect digest")
require(incorrect not in executor_path.read_text(), "executor retains incorrect digest")

tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))], capture_output=True, text=True, check=True).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable Git index mode drift")

documentation = doc_path.read_text()
for marker in ("command-free verification", "six state keys", "exactly one LF byte", "does not add any live"):
    require(marker in documentation, f"documentation marker missing: {marker}")

print(f"v0.12.2.3.1.0.2.0.1.1 digest repair and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization-repair.sh"

echo "v0.12.2.3.1.0.2.0.1.1 semantic-projection digest repair passed offline; no AWS or Terraform command was executed."

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
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.sh"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.2.0.1.2", "version drift")
    require(value.get("implementationBaselineCommit") == "ff6c2ca6deefa3bc5e3ef4a76e19d4404d219c3c", "baseline drift")
    incident = value.get("incident")
    require(incident.get("failedNormalizationRequestSha256") == "e52450132124cd97be2a234f2a360936c0f0c9cf1d884c2ffdcd1f706ca6c741", "incident drift")
    require(incident.get("applyExecuted") is False and incident.get("observedStateWasReviewedCanonical") is True, "incident boundary drift")
    forms = value.get("acceptedPreApplyForms")
    require(forms.get("reviewedCanonicalSha256") == "7c85df95076c480eaa0a618b78ad946be64ff2288c918d529395ff4346bcd139", "canonical form drift")
    require(forms.get("reviewedNormalizedSha256") == "5ff0cb562fa7bf6d99cd2068c373646fca50f06cbaa08f3f5a3e3392bf2c55e1", "normalized form drift")
    require(forms.get("onlyDifference") == "check_results" and forms.get("finiteSetSize") == 2 and forms.get("unknownFormRejected") is True, "finite form gate drift")
    require(forms.get("semanticProjectionSha256") == "1d21a9edbfe82d1d1496b312c8a31996c20f9f4bf8505604a277cbdede2f8d15", "projection drift")
    execute = value.get("executeBoundary")
    require(execute.get("exactSavedRefreshPlanApply") is True and all(execute.get(key) is False for key in ("terraformInit", "terraformPlan", "unsavedApply", "statePush", "remoteResourceActions", "automaticRetry", "automaticRollback")), "authority drift")
    success = value.get("successGate")
    require(success.get("stateSerialIncrement") == 1 and all(success.get(key) is True for key in ("stateLineageUnchanged", "plannedValuesExactlyPersisted", "lockObjectAbsent")), "success drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "producer drift")

contract = json.loads(contract_path.read_text())
validate(contract)
mutations = []
def mutate(path, replacement):
    item = deepcopy(contract); cursor = item
    for key in path[:-1]: cursor = cursor[key]
    cursor[path[-1]] = replacement; mutations.append(item)
mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["incident", "applyExecuted"], True)
mutate(["acceptedPreApplyForms", "finiteSetSize"], 3)
mutate(["acceptedPreApplyForms", "onlyDifference"], "resources")
mutate(["acceptedPreApplyForms", "unknownFormRejected"], False)
mutate(["acceptedPreApplyForms", "semanticProjectionSha256"], "0" * 64)
mutate(["executeBoundary", "terraformPlan"], True)
mutate(["executeBoundary", "unsavedApply"], True)
mutate(["executeBoundary", "automaticRetry"], True)
mutate(["successGate", "stateSerialIncrement"], 2)
for index, item in enumerate(mutations, 1):
    try: validate(item)
    except (AttributeError, KeyError, TypeError, ValueError): continue
    raise ValueError(f"fail-open mutation {index}")

spec = importlib.util.spec_from_file_location("dual_form_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec); spec.loader.exec_module(executor)
example = json.loads(example_path.read_text())
example["expectedMainCommit"] = "1" * 40; example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)
source = executor_path.read_text()
for marker in ("accepted_pre_apply_state_forms", "reviewed-canonical", "reviewed-check-results-normalized", "execute_verified"):
    require(marker in source, f"executor marker missing: {marker}")
tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))], capture_output=True, text=True, check=True).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable mode drift")
print(f"v0.12.2.3.1.0.2.0.1.2 dual-form contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2-refresh-only-state-reconciliation.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1-state-pull-check-results-normalization.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.2.0.1.1-semantic-projection-digest-repair.sh"

echo "v0.12.2.3.1.0.2.0.1.2 exact dual-form pre-apply state gate passed offline; no AWS or Terraform command was executed."

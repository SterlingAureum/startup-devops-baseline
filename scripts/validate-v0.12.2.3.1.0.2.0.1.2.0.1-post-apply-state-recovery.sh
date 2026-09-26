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
contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.json"
example_path = root / "delivery/examples/v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"
test_path = root / "scripts/test-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"
validator_path = root / "scripts/validate-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.sh"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def validate(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery-v1", "schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.2.0.1.2.0.1", "version drift")
    require(value.get("implementationBaselineCommit") == "b4f9f7dfee8ffecb42edf9f67d2ced55f431e0e8", "baseline drift")
    incident = value.get("incident")
    require(incident.get("dualFormRequestSha256") == "e2b13a02d47b5a7fa45fa723b17e99ea9b01048e8234e1949d6241d10d9f7262", "request drift")
    require(incident.get("savedRefreshOnlyPlanAppliedOnce") is True and incident.get("remoteResourceChanges") == 0, "apply result drift")
    require(incident.get("priorSerial") == 1 and incident.get("reconciledSerial") == 2 and incident.get("lineageUnchanged") is True, "state identity drift")
    require(incident.get("postApplyStateSha256") == "5b97b9ab595c7d072f420edf029435948135711a31b9251b7799ab3a0034b156", "post-state drift")
    transition = value.get("reviewedStateTransition")
    require(transition.get("managedRefreshCount") == 7 and transition.get("managedAfterValuesMatchReviewedDrift") is True, "managed refresh drift")
    require(transition.get("callerIdentitySessionRefreshCount") == 1 and transition.get("callerIdentityChangedFields") == ["arn", "user_id"] and transition.get("callerIdentityAccountUnchanged") is True, "caller projection drift")
    require(transition.get("allOtherInstancesUnchanged") is True, "unreviewed instance drift")
    boundary = value.get("recoveryBoundary")
    require(boundary.get("awsAndS3ReadOnly") is True and boundary.get("terraformStatePullListShowOnly") is True, "read boundary drift")
    require(all(boundary.get(key) is False for key in ("terraformInit", "terraformPlan", "terraformApply", "statePush", "remoteResourceMutation", "automaticRetry", "automaticRollback")), "mutation authority drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "producer drift")

contract = json.loads(contract_path.read_text())
validate(contract)
mutations = []
def mutate(path, replacement):
    item = deepcopy(contract); cursor = item
    for key in path[:-1]: cursor = cursor[key]
    cursor[path[-1]] = replacement; mutations.append(item)
mutate(["implementationBaselineCommit"], "0" * 40)
mutate(["incident", "savedRefreshOnlyPlanAppliedOnce"], False)
mutate(["incident", "remoteResourceChanges"], 1)
mutate(["incident", "reconciledSerial"], 3)
mutate(["reviewedStateTransition", "managedRefreshCount"], 8)
mutate(["reviewedStateTransition", "callerIdentityChangedFields"], ["account_id"])
mutate(["reviewedStateTransition", "callerIdentityAccountUnchanged"], False)
mutate(["recoveryBoundary", "terraformPlan"], True)
mutate(["recoveryBoundary", "terraformApply"], True)
mutate(["recoveryBoundary", "statePush"], True)
mutate(["recoveryBoundary", "automaticRetry"], True)
for index, item in enumerate(mutations, 1):
    try: validate(item)
    except (AttributeError, KeyError, TypeError, ValueError): continue
    raise ValueError(f"fail-open mutation {index}")

spec = importlib.util.spec_from_file_location("post_apply_recovery_validator", executor_path)
require(spec is not None and spec.loader is not None, "executor import failed")
executor = importlib.util.module_from_spec(spec); spec.loader.exec_module(executor)
example = json.loads(example_path.read_text())
example["expectedMainCommit"] = "1" * 40
example["expectedAwsAccountId"] = "1" * 12
example["approval"] = {"notBeforeUtc": "2026-09-26T00:00:00Z", "expiresAtUtc": "2026-09-26T01:00:00Z"}
executor.validate_request(example)
source = executor_path.read_text()
for marker in ("prior_saved_plan_apply_succeeded", "caller_identity_session_refresh_count", "terraform_apply_reexecuted", "Current state semantic projection changed"):
    require(marker in source, f"executor marker missing: {marker}")
tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))], capture_output=True, text=True, check=True).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable mode drift")
print(f"v0.12.2.3.1.0.2.0.1.2.0.1 recovery contract and {len(mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.sh"

echo "v0.12.2.3.1.0.2.0.1.2.0.1 post-apply recovery passed offline; no AWS or Terraform command was executed."

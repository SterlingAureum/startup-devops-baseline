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
repair_contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1.2.0.1.1-refresh-plan-shape-repair.json"
terminal_contract_path = root / "delivery/contracts/v0.12.2.3.1.0.2.0.1.2.0.1.2-terminal-recovery-evidence.json"
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

def validate_terminal(value):
    require(value.get("schemaVersion") == "v0.12.2.3.1.0.2.0.1.2.0.1.2-terminal-recovery-evidence-v1", "terminal schema drift")
    require(value.get("version") == "v0.12.2.3.1.0.2.0.1.2.0.1.2", "terminal version drift")
    require(value.get("status") == "state-migration-rehearsal-complete", "terminal status drift")
    require(value.get("implementationBaselineCommit") == "25578fdeb70fa9c56ac0a3441e3bb1993bcfeebe", "terminal baseline drift")
    execution = value.get("recoveryExecution")
    require(execution.get("completedAtUtc") == "2026-09-28T09:13:27.586977Z", "terminal completion drift")
    require(execution.get("controlPlaneCommit") == "25578fdeb70fa9c56ac0a3441e3bb1993bcfeebe", "terminal control-plane drift")
    require(execution.get("privateRecoveryRequestSha256") == "5844c024460c01d21e3eabfad5374d4b711fca34955bf32fb57966a61cdb1dbc", "terminal request drift")
    require(execution.get("recoveryEvidenceSha256") == "c8759d845677261225a08193800421a8b5c904eda9867555e10977aa1ae85b98", "terminal evidence drift")
    require(execution.get("recoveryResultSha256") == "e2d456ee5a753849d3172862f26cc9e9670942067ca961cc25d61c0b522e2b9c", "terminal result drift")
    state = value.get("validatedState")
    require(state == {
        "sha256": "5b97b9ab595c7d072f420edf029435948135711a31b9251b7799ab3a0034b156",
        "priorSerial": 1, "reconciledSerial": 2, "lineageUnchanged": True,
        "managedAddressCount": 13, "dataAddressCount": 9,
        "reviewedManagedRefreshCount": 7, "callerIdentitySessionRefreshCount": 1,
    }, "terminal state drift")
    history = value.get("validatedObjectHistory")
    require(history == {
        "stateObjectVersionDelta": 1, "stateDeleteMarkerDelta": 0,
        "lockObjectVersionDelta": 1, "lockDeleteMarkerDelta": 1,
        "lockObjectAbsent": True,
    }, "terminal object-history drift")
    prohibited = value.get("prohibitedOperations")
    require(prohibited and all(item is False for item in prohibited.values()), "terminal mutation authority enabled")
    closure = value.get("closureDecision")
    require(closure == {
        "stateMigrationRehearsalComplete": True,
        "renewedZeroChangeProofRequired": False,
        "futureInfrastructureChangesUseNormalReviewedPlanFlow": True,
        "privateLocalStateCopiesAreEvidenceOnly": True,
        "remoteS3StateIsOperationalSourceOfTruth": True,
    }, "terminal closure drift")
    require(value.get("privacy") == {"resourceIdentityEmitted": False, "objectVersionIdEmitted": False, "privatePathsCommitted": False}, "terminal privacy drift")
    require(value.get("packageProducer") == {"runsAws": False, "runsTerraform": False, "readsPrivateEvidence": False, "grantsLiveAuthority": False}, "terminal producer drift")

contract = json.loads(contract_path.read_text())
validate(contract)
repair = json.loads(repair_contract_path.read_text())
require(repair == {
    "schemaVersion": "v0.12.2.3.1.0.2.0.1.2.0.1.1-refresh-plan-shape-repair-v1",
    "version": "v0.12.2.3.1.0.2.0.1.2.0.1.1",
    "status": "delivered-awaiting-fresh-request-and-separate-read-only-approval",
    "repository": "SterlingAureum/startup-devops-baseline",
    "implementationBaselineCommit": "d46b947adac45646b39edf65a64e9ad52754ad9f",
    "failedVerification": {
        "privateRequestSha256": "995d38ad01aff1ebd47dda93e39b43ab22d3cc84e2336aeafe486f544d91a47f",
        "operationalCommandsExecuted": [],
        "savedPlanApplyReexecuted": False,
        "failure": "reviewed-refresh-only-plan-resource-changes-key-omitted"
    },
    "repair": {
        "acceptMissingResourceChangesAsZero": True,
        "acceptExplicitEmptyResourceChanges": True,
        "rejectNonEmptyResourceChanges": True,
        "reviewedResourceDriftCount": 7,
        "liveAuthorityAdded": False
    },
    "executionBoundary": {
        "awsAndS3ReadOnly": True,
        "terraformStatePullListShowOnly": True,
        "terraformInit": False,
        "terraformPlan": False,
        "terraformApply": False,
        "statePush": False,
        "destroy": False,
        "directS3Mutation": False,
        "automaticRetry": False,
        "automaticRollback": False
    },
    "packageProducer": {
        "runsAws": False,
        "runsTerraform": False,
        "readsPrivateEvidence": False,
        "grantsLiveAuthority": False
    }
}, "shape-repair contract drift")
terminal = json.loads(terminal_contract_path.read_text())
validate_terminal(terminal)
terminal_mutations = []
def mutate_terminal(path, replacement):
    item = deepcopy(terminal); cursor = item
    for key in path[:-1]: cursor = cursor[key]
    cursor[path[-1]] = replacement; terminal_mutations.append(item)
mutate_terminal(["implementationBaselineCommit"], "0" * 40)
mutate_terminal(["recoveryExecution", "recoveryResultSha256"], "0" * 64)
mutate_terminal(["validatedState", "reconciledSerial"], 3)
mutate_terminal(["validatedState", "managedAddressCount"], 12)
mutate_terminal(["validatedObjectHistory", "lockObjectAbsent"], False)
mutate_terminal(["prohibitedOperations", "terraformApplyReexecuted"], True)
mutate_terminal(["closureDecision", "renewedZeroChangeProofRequired"], True)
mutate_terminal(["closureDecision", "remoteS3StateIsOperationalSourceOfTruth"], False)
mutate_terminal(["privacy", "objectVersionIdEmitted"], True)
for index, item in enumerate(terminal_mutations, 1):
    try: validate_terminal(item)
    except (AttributeError, KeyError, TypeError, ValueError): continue
    raise ValueError(f"terminal fail-open mutation {index}")
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
for marker in ("prior_saved_plan_apply_succeeded", "caller_identity_session_refresh_count", "terraform_apply_reexecuted", "Current state semantic projection changed", 'plan.get("resource_changes", [])'):
    require(marker in source, f"executor marker missing: {marker}")
tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", str(executor_path.relative_to(root)), str(test_path.relative_to(root)), str(validator_path.relative_to(root))], capture_output=True, text=True, check=True).stdout.splitlines()
require(len(tracked) == 3 and all(line.startswith("100755 ") for line in tracked), "executable mode drift")
print(f"v0.12.2.3.1.0.2.0.1.2.0.1 recovery contracts and {len(mutations) + len(terminal_mutations)} fail-closed mutations passed offline.")
PY

python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.3.1.0.2.0.1.2.0.1-post-apply-state-recovery.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.3.1.0.2.0.1.2-dual-form-pre-apply-state.sh"

echo "v0.12.2.3.1.0.2.0.1.2.0.1 post-apply recovery passed offline; no AWS or Terraform command was executed."

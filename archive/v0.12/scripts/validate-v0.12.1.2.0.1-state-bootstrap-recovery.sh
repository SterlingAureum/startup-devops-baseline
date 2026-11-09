#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

bash -n "${BASH_SOURCE[0]}"

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PYTHON'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.1.2.0.1-state-bootstrap-post-apply-recovery.json"
predecessor_path = root / "delivery/contracts/v0.12.1.2-reviewed-state-bootstrap-apply.json"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Missing file: {path.relative_to(root)}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"Expected JSON object: {path.relative_to(root)}")
    return value


def git_index_mode(relative: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "--", relative],
        capture_output=True,
        text=True,
        check=False,
    )
    require(result.returncode == 0 and result.stdout.strip(), f"missing index entry: {relative}")
    return result.stdout.split()[0]


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(
        value.get("schemaVersion") == "v0.12.1.2.0.1-state-bootstrap-post-apply-recovery-v1",
        "schema drift",
    )
    require(value.get("version") == "v0.12.1.2.0.1", "version drift")
    require(
        value.get("status")
        == "delivered-read-only-recovery-entrypoint-awaiting-separate-live-recovery-approval",
        "unsafe status",
    )
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.1.2", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    if check_files:
        require(load(predecessor_path).get("version") == "v0.12.1.2", "invalid predecessor")

    repair = value.get("defectRepair")
    require(isinstance(repair, dict), "missing defect repair")
    require(repair.get("unsupportedInputRemoved") == "kms-alias", "alias defect not removed")
    require(repair.get("requiredInput") == "kms-key-arn", "KMS ARN requirement missing")
    require(repair.get("futureApplyReexecutionRequired") is False, "future apply retry claimed")

    entrypoint = value.get("recoveryEntrypoint")
    require(isinstance(entrypoint, dict), "missing recovery entrypoint")
    require(
        entrypoint.get("path") == "scripts/execute-v0.12.1.2.0.1-state-bootstrap-recovery.py",
        "entrypoint drift",
    )
    require(entrypoint.get("phases") == ["verify", "execute"], "phase drift")
    require(
        entrypoint.get("operation") == "complete-read-only-state-bootstrap-post-apply-validation",
        "operation drift",
    )
    require(entrypoint.get("confirmationVariable") == "CONFIRM_STATE_BOOTSTRAP_RECOVERY", "confirmation drift")
    require(entrypoint.get("confirmationValue") == entrypoint.get("operation"), "confirmation value drift")

    bindings = value.get("incidentBindings")
    require(isinstance(bindings, dict) and all(item is True for item in bindings.values()), "incident binding disabled")
    proof = value.get("priorApplyProof")
    require(isinstance(proof, dict), "missing prior apply proof")
    require(proof.get("expectedManagedStateAddressCount") == 13, "managed state count drift")
    for key, item in proof.items():
        if key == "expectedManagedStateAddressCount":
            continue
        if key in {"unreviewedManagedStateAllowed", "unreviewedDataStateAllowed"}:
            require(item is False, f"unsafe state allowed: {key}")
        else:
            require(item is True, f"prior apply proof disabled: {key}")

    boundary = value.get("recoveryCommandBoundary")
    require(isinstance(boundary, dict), "missing recovery command boundary")
    for key in (
        "executeMayReadAwsIdentity",
        "executeMayRunReadOnlyS3Validation",
        "executeMayRunReadOnlyKmsValidation",
        "executeMayRunReadOnlyIamPolicyValidation",
    ):
        require(boundary.get(key) is True, f"required read-only command missing: {key}")
    for key in (
        "verifyRunsOperationalCommands",
        "terraformInitAllowed",
        "terraformPlanAllowed",
        "terraformApplyAllowed",
        "terraformDestroyAllowed",
        "terraformStateMutationAllowed",
        "backendMigrationAllowed",
        "iamPolicyAttachmentAllowed",
        "kubernetesAccessAllowed",
        "githubMutationAllowed",
        "automaticRetryOfPriorApplyAllowed",
    ):
        require(boundary.get(key) is False, f"unsafe recovery command enabled: {key}")

    live = value.get("liveValidation")
    require(isinstance(live, dict), "missing live validation")
    require(live.get("rootStatePolicyCount") == 5, "policy count drift")
    for key, item in live.items():
        if key == "rootStatePolicyCount":
            continue
        require(item is True, f"live validation disabled: {key}")

    approval = value.get("approvalBoundary")
    require(isinstance(approval, dict), "missing approval boundary")
    require(approval.get("maximumWindowSeconds") == 3600, "approval window drift")
    require(approval.get("minimumRemainingSeconds") == 900, "remaining window drift")
    require(approval.get("separateRecoveryApprovalRequired") is True, "separate approval disabled")
    require(approval.get("cleanExactProtectedRecoveryMainRequired") is True, "protected main disabled")

    failure = value.get("failureBoundary")
    require(isinstance(failure, dict), "missing failure boundary")
    for key in ("preservePriorApplyEvidence", "preserveAppliedLocalState", "preserveRecoveryEvidence"):
        require(failure.get(key) is True, f"failure preservation disabled: {key}")
    for key in ("automaticApplyRetry", "automaticDestroy", "manualCloudMutation", "uncertaintyMeansSuccess"):
        require(failure.get(key) is False, f"unsafe failure behavior enabled: {key}")

    producer = value.get("packageProducer")
    require(isinstance(producer, dict) and all(item is False for item in producer.values()), "package claims live action")
    successor = value.get("successor")
    require(isinstance(successor, dict), "missing successor")
    require(successor.get("version") == "v0.12.1.2.1", "successor drift")

    if check_files:
        for relative in (
            entrypoint["path"],
            "scripts/test-v0.12.1.2.0.1-state-bootstrap-recovery.py",
            "scripts/validate-v0.12.1.2.0.1-state-bootstrap-recovery.sh",
        ):
            path = root / relative
            require(path.is_file() and not path.is_symlink(), f"missing executable: {relative}")
            require(git_index_mode(relative) == "100755", f"Git executable mode drift: {relative}")
        for relative in (
            "delivery/examples/v0.12.1.2.0.1-state-bootstrap-recovery-request.example.json",
            "docs/V0.12.1.2.0.1_STATE_BOOTSTRAP_POST_APPLY_RECOVERY.md",
        ):
            require((root / relative).is_file(), f"missing surface: {relative}")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("alias retained", lambda item: item["defectRepair"].__setitem__("unsupportedInputRemoved", "none")),
    ("state hash unbound", lambda item: item["incidentBindings"].__setitem__("appliedStateSha256", False)),
    ("failure reason unbound", lambda item: item["incidentBindings"].__setitem__("invalidArnExceptionRequired", False)),
    ("state mismatch allowed", lambda item: item["priorApplyProof"].__setitem__("workingStateAndPreservedCopyMustMatch", False)),
    ("unexpected managed state allowed", lambda item: item["priorApplyProof"].__setitem__("unreviewedManagedStateAllowed", True)),
    ("verify runs commands", lambda item: item["recoveryCommandBoundary"].__setitem__("verifyRunsOperationalCommands", True)),
    ("init enabled", lambda item: item["recoveryCommandBoundary"].__setitem__("terraformInitAllowed", True)),
    ("plan enabled", lambda item: item["recoveryCommandBoundary"].__setitem__("terraformPlanAllowed", True)),
    ("apply enabled", lambda item: item["recoveryCommandBoundary"].__setitem__("terraformApplyAllowed", True)),
    ("destroy enabled", lambda item: item["recoveryCommandBoundary"].__setitem__("terraformDestroyAllowed", True)),
    ("migration enabled", lambda item: item["recoveryCommandBoundary"].__setitem__("backendMigrationAllowed", True)),
    ("retry enabled", lambda item: item["recoveryCommandBoundary"].__setitem__("automaticRetryOfPriorApplyAllowed", True)),
    ("KMS ARN check disabled", lambda item: item["liveValidation"].__setitem__("kmsKeyArnUsedForRotationRead", False)),
    ("policy attachment check disabled", lambda item: item["liveValidation"].__setitem__("rootStatePoliciesUnattached", False)),
    ("approval extended", lambda item: item["approvalBoundary"].__setitem__("maximumWindowSeconds", 7200)),
    ("uncertainty accepted", lambda item: item["failureBoundary"].__setitem__("uncertaintyMeansSuccess", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

example = load(root / "delivery/examples/v0.12.1.2.0.1-state-bootstrap-recovery-request.example.json")
require(
    example.get("operation") == "complete-read-only-state-bootstrap-post-apply-validation",
    "example operation drift",
)
for key in (
    "expectedRecoveryMainCommit",
    "incidentControlPlaneCommit",
    "expectedAwsAccountId",
    "privateApplyRequestSha256",
    "planRecordSha256",
    "binaryPlanSha256",
    "failedKmsRotationStderrSha256",
    "appliedStateSha256",
):
    require("REPLACE" in example.get(key, ""), f"example contains concrete private value: {key}")
require(example["executionBoundary"]["terraformApply"] is False, "example enables apply")
require(example["executionBoundary"]["awsReadOnlyLiveValidation"] is True, "example disables live validation")

apply_executor = (root / "scripts/execute-v0.12.1.2-state-bootstrap-apply.py").read_text()
require(
    '["kms", "get-key-rotation-status", "--key-id", identities["kms_arn"]]' in apply_executor,
    "future apply still passes an alias to KMS rotation status",
)
require(
    '["kms", "describe-key", "--key-id", identities["kms_arn"]]' in apply_executor,
    "future apply KMS description is not ARN-bound",
)

recovery_executor = (root / contract["recoveryEntrypoint"]["path"]).read_text()
for fragment in (
    'choices=("verify", "execute")',
    'InvalidArnException',
    'managed == PLAN_GATE.EXPECTED_MANAGED_ADDRESSES',
    'CONFIRM_STATE_BOOTSTRAP_RECOVERY',
    'terraform_apply_reexecuted": False',
    'automatic_retry_performed": False',
):
    require(fragment in recovery_executor, f"recovery executor marker missing: {fragment}")

docs = (root / "docs/V0.12.1.2.0.1_STATE_BOOTSTRAP_POST_APPLY_RECOVERY.md").read_text()
for fragment in (
    "does not support a KMS alias",
    "cannot run Terraform init, plan, apply or destroy",
    "separately approved recovery execution",
    "v0.12.1.2.1",
    "v0.12.2",
):
    require(fragment.lower() in docs.lower(), f"operator boundary missing: {fragment}")

print("v0.12.1.2.0.1 recovery contract and 16 fail-closed mutations passed offline.")
PYTHON

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.1.2-state-bootstrap-apply.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.1.2.0.1-state-bootstrap-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.1.2.0.1-state-bootstrap-recovery.py"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.1.2.0.1-state-bootstrap-recovery.py"

"${ROOT_DIR}/scripts/validate-v0.12.1.2-reviewed-state-bootstrap-apply.sh"

echo "v0.12.1.2.0.1 post-apply recovery passed offline; no AWS or Terraform command was executed."

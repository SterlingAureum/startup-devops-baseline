#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash git python3; do
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
contract_path = root / "delivery/contracts/v0.12.1.2-reviewed-state-bootstrap-apply.json"
predecessor_path = root / "delivery/contracts/v0.12.1.1-guarded-state-bootstrap-plan.json"


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
    require(value.get("schemaVersion") == "v0.12.1.2-reviewed-state-bootstrap-apply-v1", "schema drift")
    require(value.get("version") == "v0.12.1.2", "version drift")
    require(
        value.get("status")
        == "delivered-guarded-apply-entrypoint-awaiting-separate-live-plan-and-apply-approvals",
        "unsafe status",
    )
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.1.1", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    if check_files:
        require(load(predecessor_path).get("version") == "v0.12.1.1", "invalid predecessor")

    sequence = value.get("sequence")
    require(isinstance(sequence, dict), "missing sequence")
    for key in (
        "implementationMustMergeBeforeFreshPlan",
        "freshPlanMainMustContainApplyExecutor",
        "humanPlanReviewRequired",
        "separateApplyApprovalRequired",
    ):
        require(sequence.get(key) is True, f"sequence control disabled: {key}")
    require(sequence.get("maximumApplyApprovalWindowSeconds") == 3600, "approval window drift")
    require(sequence.get("minimumRemainingPlanAndApprovalSeconds") == 900, "minimum window drift")

    entrypoint = value.get("entrypoint")
    require(isinstance(entrypoint, dict), "missing entrypoint")
    require(entrypoint.get("path") == "scripts/execute-v0.12.1.2-state-bootstrap-apply.py", "entrypoint drift")
    require(entrypoint.get("phases") == ["verify", "execute"], "phase drift")
    require(entrypoint.get("operation") == "apply-reviewed-state-backend-foundation", "operation drift")
    require(entrypoint.get("confirmationVariable") == "CONFIRM_STATE_BOOTSTRAP_APPLY", "confirmation drift")
    require(entrypoint.get("confirmationValue") == entrypoint.get("operation"), "confirmation value drift")

    bindings = value.get("artifactBindings")
    require(isinstance(bindings, dict) and bindings, "missing artifact bindings")
    require(all(item is True for item in bindings.values()), "artifact binding disabled")
    pre_apply = value.get("preApplyBoundary")
    require(isinstance(pre_apply, dict) and pre_apply, "missing pre-apply boundary")
    require(all(item is True for item in pre_apply.values()), "pre-apply control disabled")

    commands = value.get("commandBoundary")
    require(isinstance(commands, dict), "missing command boundary")
    for key in (
        "executeMayReadAwsIdentity",
        "executeMayRunTerraformShow",
        "executeMayRunTerraformApplyExactSavedPlan",
        "executeMayRunTerraformStateList",
        "executeMayRunTerraformOutput",
        "executeMayRunReadOnlyAwsValidation",
    ):
        require(commands.get(key) is True, f"required command missing: {key}")
    for key in (
        "verifyRunsTerraform",
        "verifyAccessesAws",
        "terraformInitAllowed",
        "terraformPlanAllowed",
        "terraformDestroyAllowed",
        "terraformStatePullAllowed",
        "terraformStatePushAllowed",
        "backendMigrationAllowed",
        "iamPolicyAttachmentAllowed",
        "kubernetesAccessAllowed",
        "githubMutationAllowed",
        "automaticRetryAllowed",
    ):
        require(commands.get(key) is False, f"unsafe command enabled: {key}")

    post_apply = value.get("postApplyBoundary")
    require(isinstance(post_apply, dict), "missing post-apply boundary")
    require(post_apply.get("expectedManagedStateAddressCount") == 13, "state inventory drift")
    require(post_apply.get("rootStatePolicyCount") == 5, "policy count drift")
    require(post_apply.get("unreviewedStateAddressAllowed") is False, "unreviewed state allowed")
    for key, item in post_apply.items():
        if key in {"expectedManagedStateAddressCount", "rootStatePolicyCount", "unreviewedStateAddressAllowed"}:
            continue
        require(item is True, f"post-apply control disabled: {key}")

    failure = value.get("failureBoundary")
    require(isinstance(failure, dict), "missing failure boundary")
    for key in ("preservePrivateApplyEvidence", "preserveLocalBootstrapState", "partialApplyRequiresManualReview"):
        require(failure.get(key) is True, f"failure preservation disabled: {key}")
    for key in ("automaticReplan", "automaticRetry", "automaticDestroy", "uncertaintyMeansSuccess"):
        require(failure.get(key) is False, f"unsafe failure behavior enabled: {key}")

    producer = value.get("packageProducer")
    require(isinstance(producer, dict) and all(item is False for item in producer.values()), "package claims live action")
    successor = value.get("successor")
    require(isinstance(successor, dict), "missing successor")
    require(successor.get("version") == "v0.12.1.2.1", "successor drift")
    require("execution-evidence" in successor.get("scope", ""), "successor evidence scope missing")

    if check_files:
        for relative in (
            entrypoint["path"],
            "scripts/test-v0.12.1.2-state-bootstrap-apply.py",
            "scripts/validate-v0.12.1.2-reviewed-state-bootstrap-apply.sh",
        ):
            path = root / relative
            require(path.is_file() and not path.is_symlink(), f"missing executable: {relative}")
            require(git_index_mode(relative) == "100755", f"Git executable mode drift: {relative}")
        for relative in (
            "delivery/examples/v0.12.1.2-state-bootstrap-apply-request.example.json",
            "docs/V0.12.1.2_REVIEWED_STATE_BOOTSTRAP_APPLY.md",
        ):
            require((root / relative).is_file(), f"missing surface: {relative}")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("plan before implementation", lambda item: item["sequence"].__setitem__("implementationMustMergeBeforeFreshPlan", False)),
    ("review disabled", lambda item: item["sequence"].__setitem__("humanPlanReviewRequired", False)),
    ("long approval", lambda item: item["sequence"].__setitem__("maximumApplyApprovalWindowSeconds", 7200)),
    ("binary plan unbound", lambda item: item["artifactBindings"].__setitem__("binaryPlanSha256", False)),
    ("source unbound", lambda item: item["artifactBindings"].__setitem__("sourceManifestSha256", False)),
    ("plan gate skipped", lambda item: item["preApplyBoundary"].__setitem__("planGateMustPassAgain", False)),
    ("existing bucket allowed", lambda item: item["preApplyBoundary"].__setitem__("stateBucketMustBeAbsent", False)),
    ("verify accesses AWS", lambda item: item["commandBoundary"].__setitem__("verifyAccessesAws", True)),
    ("init enabled", lambda item: item["commandBoundary"].__setitem__("terraformInitAllowed", True)),
    ("plan enabled", lambda item: item["commandBoundary"].__setitem__("terraformPlanAllowed", True)),
    ("destroy enabled", lambda item: item["commandBoundary"].__setitem__("terraformDestroyAllowed", True)),
    ("migration enabled", lambda item: item["commandBoundary"].__setitem__("backendMigrationAllowed", True)),
    ("attachment enabled", lambda item: item["commandBoundary"].__setitem__("iamPolicyAttachmentAllowed", True)),
    ("retry enabled", lambda item: item["commandBoundary"].__setitem__("automaticRetryAllowed", True)),
    ("unreviewed state allowed", lambda item: item["postApplyBoundary"].__setitem__("unreviewedStateAddressAllowed", True)),
    ("bucket may be nonempty", lambda item: item["postApplyBoundary"].__setitem__("s3ObjectInventoryMustRemainEmpty", False)),
    ("uncertainty accepted", lambda item: item["failureBoundary"].__setitem__("uncertaintyMeansSuccess", True)),
    ("skip evidence successor", lambda item: item["successor"].__setitem__("version", "v0.12.2")),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

example = load(root / "delivery/examples/v0.12.1.2-state-bootstrap-apply-request.example.json")
require(example.get("operation") == "apply-reviewed-state-backend-foundation", "example operation drift")
require("REPLACE" in example.get("expectedMainCommit", ""), "example contains concrete main")
require("REPLACE" in example.get("expectedAwsAccountId", ""), "example contains concrete account")
for key in (
    "privatePlanRequestSha256",
    "planRecordSha256",
    "binaryPlanSha256",
    "terraformPlanJsonSha256",
    "terraformPlanTextSha256",
    "planGateSha256",
    "sourceManifestSha256",
    "terraformVersionJsonSha256",
):
    require("REPLACE" in example.get(key, ""), f"example contains concrete digest: {key}")

executor = (root / contract["entrypoint"]["path"]).read_text()
for fragment in (
    'choices=("verify", "execute")',
    '"apply", "-input=false", "-auto-approve", str(binary_plan)',
    'CONFIRM_STATE_BOOTSTRAP_APPLY',
    'validate_live_foundation',
    'state_migration_executed": False',
    'automatic_retry_performed": False',
):
    require(fragment in executor, f"executor marker missing: {fragment}")

docs = (root / "docs/V0.12.1.2_REVIEWED_STATE_BOOTSTRAP_APPLY.md").read_text()
for fragment in (
    "merge v0.12.1.2 before producing the fresh plan",
    "exact saved plan",
    "must not be retried automatically",
    "v0.12.1.2.1",
    "v0.12.2",
):
    require(fragment in docs, f"operator boundary missing: {fragment}")

for relative in (
    "README.md",
    "CHANGELOG.md",
    "docs/ROADMAP.md",
    "docs/CURRENT_AUTHORITATIVE_SURFACE.md",
    "docs/TERRAFORM_STATE_MANAGEMENT.md",
):
    require("v0.12.1.2" in (root / relative).read_text(), f"version surface not updated: {relative}")

print("v0.12.1.2 guarded apply contract and 18 fail-closed mutations passed offline.")
PYTHON

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.1.2-state-bootstrap-apply.py" \
  "${ROOT_DIR}/scripts/test-v0.12.1.2-state-bootstrap-apply.py"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.1.2-state-bootstrap-apply.py"

"${ROOT_DIR}/scripts/validate-v0.12.1.1-guarded-state-bootstrap-plan.sh"

echo "v0.12.1.2 guarded apply entrypoint passed offline; no AWS or Terraform command was executed."

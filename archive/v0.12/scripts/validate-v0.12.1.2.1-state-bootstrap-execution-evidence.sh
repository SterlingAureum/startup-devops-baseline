#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3 git; do
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
import re
import subprocess
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.1.2.1-state-bootstrap-execution-evidence.json"
apply_contract_path = root / "delivery/contracts/v0.12.1.2-reviewed-state-bootstrap-apply.json"
recovery_contract_path = root / "delivery/contracts/v0.12.1.2.0.1-state-bootstrap-post-apply-recovery.json"
document_path = root / "docs/V0.12.1.2.1_STATE_BOOTSTRAP_EXECUTION_EVIDENCE.md"


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
        value.get("schemaVersion") == "v0.12.1.2.1-state-bootstrap-execution-evidence-v1",
        "schema drift",
    )
    require(value.get("version") == "v0.12.1.2.1", "version drift")
    require(
        value.get("status") == "completed-state-bootstrap-created-recovered-and-live-validated",
        "terminal status drift",
    )
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("completedAtUtc") == "2026-09-25T08:21:14Z", "completion time drift")

    predecessors = value.get("predecessors")
    require(
        predecessors
        == [
            {
                "version": "v0.12.1.2",
                "contract": str(apply_contract_path.relative_to(root)),
            },
            {
                "version": "v0.12.1.2.0.1",
                "contract": str(recovery_contract_path.relative_to(root)),
            },
        ],
        "predecessor chain drift",
    )
    if check_files:
        require(load(apply_contract_path).get("version") == "v0.12.1.2", "apply predecessor invalid")
        require(load(recovery_contract_path).get("version") == "v0.12.1.2.0.1", "recovery predecessor invalid")

    control = value.get("controlPlane")
    require(isinstance(control, dict), "missing control plane")
    require(
        control.get("incidentMainCommit") == "bcd653ca3705df177864c5a3f12201f9a987191f",
        "incident main drift",
    )
    require(
        control.get("recoveryMainCommit") == "10c018fa935f777d6bd04c43fa856e5e650f53b5",
        "recovery main drift",
    )
    require(control.get("trustedRef") == "refs/heads/main", "trusted ref drift")

    expected_bindings = {
        "privatePlanRequestSha256": "9f041fa9b98c15b7309df8b87af79bb50d3871eb0501b9977bbdb772c41a326b",
        "privateApplyRequestSha256": "91406ddbac3f75415c383da3b369070ec93c0c8874a11023ee1a7b50e307de07",
        "privateRecoveryRequestSha256": "cd31e26adc15932215985f27db865717a674382d22b34d8f0d2327e977a6c7a7",
        "planRecordSha256": "b15e169dec207dfdbdd966d4940e3b5ee3d14e0de9b2fbdfd5cb179a634504a9",
        "binaryPlanSha256": "7b27f5ee122fd4289c5532f995604a084b1a5e7b10a065ae82f29477441c254f",
        "terraformPlanJsonSha256": "adab49c6018cf33bc709b32edaf48e943df93eddfbf8574b9a898ef5101510ca",
        "terraformPlanTextSha256": "e13599ef67f06828634ea578c03e74a4cee01eb04b92bc0779da2dbc0a3cb08c",
        "planGateSha256": "379cf7996ca60ba37492b61ed150f761cf09e35b55c54d5bf2a41ca790f38db6",
        "privateTfvarsSha256": "1eccb524be6254e2939130b7c2300fbdc3ef76fe3672339ea05f4cdd3e1ddf18",
        "appliedStateSha256": "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995",
        "liveValidationSha256": "6f929213b687c44652c5f265f577767dcc422ab363f4cb598ed1c68395c1c091",
        "recoveryResultSha256": "c65f405bdb67779af4a9b074e5760ba62b2aff78f075ff10985108ba70ba4365",
    }
    require(value.get("artifactBindings") == expected_bindings, "artifact binding drift")
    require(all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in expected_bindings.values()), "invalid digest")

    plan = value.get("reviewedPlan")
    require(isinstance(plan, dict), "missing reviewed plan")
    require(plan.get("managedCreateCount") == 13, "managed create count drift")
    require(plan.get("dataChangeCount") == 6, "data change count drift")
    for key in (
        "updateCount",
        "deleteCount",
        "replaceCount",
        "importCount",
        "unexpectedResourceCount",
        "iamAttachmentCount",
    ):
        require(plan.get(key) == 0, f"unsafe reviewed plan count: {key}")
    require(plan.get("humanReviewPassed") is True, "human review not recorded")

    incident = value.get("incident")
    require(isinstance(incident, dict), "missing incident")
    require(incident.get("stage") == "post-apply-live-validation", "incident stage drift")
    require(incident.get("errorCode") == "InvalidArnException", "incident code drift")
    require(
        incident.get("rootCause") == "kms-alias-used-where-key-id-or-arn-was-required",
        "incident root cause drift",
    )
    require(incident.get("terraformApplySucceededBeforeFailure") is True, "successful apply not retained")
    require(incident.get("automaticRetryPerformed") is False, "automatic retry claimed")
    require(incident.get("repairVersion") == "v0.12.1.2.0.1", "repair version drift")
    require(incident.get("recoveryWasReadOnly") is True, "recovery mutation claimed")

    outcome = value.get("validatedOutcome")
    require(isinstance(outcome, dict), "missing validated outcome")
    require(outcome.get("managedStateAddressCount") == 13, "managed state count drift")
    require(outcome.get("stateBucketObjectVersionCount") == 0, "state bucket not empty")
    require(outcome.get("rootStatePolicyCount") == 5, "root policy count drift")
    require(outcome.get("attachedRootStatePolicyCount") == 0, "root policy attachment detected")
    require(outcome.get("kmsKeyManager") == "CUSTOMER", "KMS manager drift")
    for key in (
        "backendFoundationCreated",
        "priorTerraformApplySucceeded",
        "stateCopiesMatchedBeforeRecovery",
        "s3VersioningEnabled",
        "s3BucketOwnerEnforced",
        "s3PublicAccessBlocked",
        "s3SseKmsEnabled",
        "s3BucketKeyEnabled",
        "s3TlsOnlyPolicy",
        "s3PolicyNotPublic",
        "kmsRotationEnabled",
        "kmsKeyEnabled",
        "bootstrapStateRemainsLocalAndPrivate",
    ):
        require(outcome.get(key) is True, f"validated control missing: {key}")

    negative = value.get("negativeExecutionEvidence")
    require(isinstance(negative, dict), "missing negative execution evidence")
    require(negative and all(item is False for item in negative.values()), "unexpected execution recorded")

    privacy = value.get("privacyBoundary")
    require(isinstance(privacy, dict), "missing privacy boundary")
    for key, item in privacy.items():
        if key == "allowedPublicMaterial":
            continue
        require(item is False, f"private material publication enabled: {key}")
    require(
        privacy.get("allowedPublicMaterial")
        == [
            "protected-main-commit",
            "sha256-digest",
            "bounded-count",
            "boolean-control-result",
            "terminal-status",
            "completion-time",
        ],
        "public material boundary drift",
    )

    producer = value.get("packageProducer")
    require(isinstance(producer, dict) and producer and all(item is False for item in producer.values()), "package claims live action")
    successor = value.get("successor")
    require(isinstance(successor, dict), "missing successor")
    require(successor.get("version") == "v0.12.2", "successor drift")
    require(successor.get("migrationAuthorizedByThisEvidence") is False, "migration authority leaked")

    if check_files:
        require(document_path.is_file() and not document_path.is_symlink(), "missing evidence document")
        validator = "scripts/validate-v0.12.1.2.1-state-bootstrap-execution-evidence.sh"
        require(git_index_mode(validator) == "100755", "Git executable mode drift: evidence validator")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("terminal status weakened", lambda item: item.__setitem__("status", "partial")),
    ("completion time changed", lambda item: item.__setitem__("completedAtUtc", "2026-09-25T08:21:15Z")),
    ("incident main changed", lambda item: item["controlPlane"].__setitem__("incidentMainCommit", "0" * 40)),
    ("recovery main changed", lambda item: item["controlPlane"].__setitem__("recoveryMainCommit", "0" * 40)),
    ("plan request unbound", lambda item: item["artifactBindings"].__setitem__("privatePlanRequestSha256", "0" * 64)),
    ("apply request unbound", lambda item: item["artifactBindings"].__setitem__("privateApplyRequestSha256", "0" * 64)),
    ("recovery request unbound", lambda item: item["artifactBindings"].__setitem__("privateRecoveryRequestSha256", "0" * 64)),
    ("state digest unbound", lambda item: item["artifactBindings"].__setitem__("appliedStateSha256", "0" * 64)),
    ("result digest unbound", lambda item: item["artifactBindings"].__setitem__("recoveryResultSha256", "0" * 64)),
    ("plan update accepted", lambda item: item["reviewedPlan"].__setitem__("updateCount", 1)),
    ("plan delete accepted", lambda item: item["reviewedPlan"].__setitem__("deleteCount", 1)),
    ("human review removed", lambda item: item["reviewedPlan"].__setitem__("humanReviewPassed", False)),
    ("apply success removed", lambda item: item["incident"].__setitem__("terraformApplySucceededBeforeFailure", False)),
    ("automatic retry claimed", lambda item: item["incident"].__setitem__("automaticRetryPerformed", True)),
    ("state bucket nonempty", lambda item: item["validatedOutcome"].__setitem__("stateBucketObjectVersionCount", 1)),
    ("policy attached", lambda item: item["validatedOutcome"].__setitem__("attachedRootStatePolicyCount", 1)),
    ("migration executed", lambda item: item["negativeExecutionEvidence"].__setitem__("stateMigrationExecuted", True)),
    ("identity emitted", lambda item: item["negativeExecutionEvidence"].__setitem__("privateResourceIdentityEmitted", True)),
    ("ARN publication enabled", lambda item: item["privacyBoundary"].__setitem__("publishesResourceArn", True)),
    ("package migration claimed", lambda item: item["packageProducer"].__setitem__("migratesState", True)),
    ("migration authority leaked", lambda item: item["successor"].__setitem__("migrationAuthorizedByThisEvidence", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

public_text = contract_path.read_text() + "\n" + document_path.read_text()
for pattern, label in (
    (r"arn:aws(?:-[a-z]+)?:", "AWS ARN"),
    (r"(?<![0-9])[0-9]{12}(?![0-9])", "AWS account-like identifier"),
    (r"/(?:home|Users)/[^/\s]+/", "user home path"),
):
    require(re.search(pattern, public_text) is None, f"public evidence contains {label}")

document = " ".join(document_path.read_text().split())
for fragment in (
    "2026-09-25T08:21:14Z",
    "InvalidArnException",
    "13 managed creates",
    "zero object versions",
    "five root-scoped IAM policies with zero attachments",
    "bootstrap state remains a private local artifact",
    "v0.12.2 remains a separate change and approval boundary",
    "no AWS account ID, bucket identity, resource ARN, state bytes, plan bytes",
):
    require(fragment.lower() in document.lower(), f"evidence document marker missing: {fragment}")

readme = " ".join((root / "README.md").read_text().split())
roadmap = " ".join((root / "docs/ROADMAP.md").read_text().split())
surface = " ".join((root / "docs/CURRENT_AUTHORITATIVE_SURFACE.md").read_text().split())
state_doc = " ".join((root / "docs/TERRAFORM_STATE_MANAGEMENT.md").read_text().split())
for text, fragment, label in (
    (readme, "v0.12.1.2.1-state-bootstrap-execution-evidence", "README current checkpoint"),
    (roadmap, "v0.12.1.2.1 - redacted state-bootstrap apply and live-validation execution evidence - completed", "roadmap completion"),
    (surface, str(contract_path.relative_to(root)), "authoritative contract"),
    (surface, str(document_path.relative_to(root)), "authoritative document"),
    (state_doc, "foundation has now been created and live-validated", "state-management outcome"),
):
    require(fragment.lower() in text.lower(), f"missing version surface: {label}")

for relative in (
    "scripts/validate-v0.12.1.1-guarded-state-bootstrap-plan.sh",
    "scripts/validate-v0.12.1.2-reviewed-state-bootstrap-apply.sh",
):
    validator_source = (root / relative).read_text()
    require("def git_index_mode(relative: str) -> str:" in validator_source, f"Git mode helper missing: {relative}")
    require('git_index_mode(' in validator_source, f"Git mode check missing: {relative}")
    require("stat.S_IMODE" not in validator_source, f"host POSIX mode check retained: {relative}")

print("v0.12.1.2.1 execution evidence contract and 21 fail-closed mutations passed offline.")
PYTHON

bash "${ROOT_DIR}/scripts/validate-v0.12.1.2.0.1-state-bootstrap-recovery.sh"

echo "v0.12.1.2.1 redacted execution evidence passed offline; no AWS or Terraform command was executed."

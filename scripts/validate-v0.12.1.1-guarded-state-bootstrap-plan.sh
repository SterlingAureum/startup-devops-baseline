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
import re
import stat
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.1.1-guarded-state-bootstrap-plan.json"
predecessor_path = root / "delivery/contracts/v0.12.1.0.1-ci-compatibility-repair.json"
foundation_path = root / "delivery/contracts/v0.12.1-remote-state-foundation.json"


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


expected_managed = {
    'aws_iam_policy.root_state_access["bootstrap"]',
    'aws_iam_policy.root_state_access["runtime-identities"]',
    'aws_iam_policy.root_state_access["dev"]',
    'aws_iam_policy.root_state_access["test"]',
    'aws_iam_policy.root_state_access["prod"]',
    "aws_kms_alias.state",
    "aws_kms_key.state",
    "aws_s3_bucket.state",
    "aws_s3_bucket_ownership_controls.state",
    "aws_s3_bucket_policy.state",
    "aws_s3_bucket_public_access_block.state",
    "aws_s3_bucket_server_side_encryption_configuration.state",
    "aws_s3_bucket_versioning.state",
}


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.1.1-guarded-state-bootstrap-plan-v1", "schema drift")
    require(value.get("version") == "v0.12.1.1", "version drift")
    require(
        value.get("status") == "delivered-guarded-plan-entrypoint-awaiting-separate-live-plan-approval",
        "unsafe status",
    )
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.1.0.1", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    require(predecessor.get("foundationVersion") == "v0.12.1", "foundation version drift")
    require(
        predecessor.get("foundationContract") == str(foundation_path.relative_to(root)),
        "foundation path drift",
    )
    if check_files:
        previous = load(predecessor_path)
        require(previous.get("version") == "v0.12.1.0.1", "invalid predecessor contract")
        foundation = load(foundation_path)
        require(foundation.get("version") == "v0.12.1", "invalid foundation contract")

    entrypoint = value.get("entrypoint")
    require(isinstance(entrypoint, dict), "missing entrypoint")
    require(entrypoint.get("path") == "scripts/execute-v0.12.1.1-state-bootstrap-plan.py", "entrypoint drift")
    require(entrypoint.get("phases") == ["verify", "execute"], "phase boundary drift")
    require(entrypoint.get("targetRoot") == "infra/terraform/aws/state-bootstrap", "target root drift")
    require(entrypoint.get("operation") == "plan-state-backend-foundation", "operation drift")
    require(entrypoint.get("confirmationVariable") == "CONFIRM_STATE_BOOTSTRAP_PLAN", "confirmation variable drift")
    require(entrypoint.get("confirmationValue") == "plan-state-backend-foundation", "confirmation value drift")

    identity = value.get("identityGates")
    require(isinstance(identity, dict), "missing identity gates")
    for key in ("cleanExactProtectedMain", "headEqualsOriginMain", "expectedAccountPrivate", "stsAccountMustMatch"):
        require(identity.get(key) is True, f"identity gate disabled: {key}")
    require(identity.get("awsRegion") == "us-east-1", "region drift")
    require(identity.get("privateRequestMode") == "0600", "request mode drift")
    require(identity.get("privateTfvarsMode") == "0600", "tfvars mode drift")
    require(identity.get("privateParentMode") == "0700", "parent mode drift")
    require(identity.get("maximumApprovalWindowSeconds") == 3600, "approval window drift")
    require(identity.get("minimumRemainingWindowSeconds") == 900, "minimum window drift")

    gate = value.get("terraformPlanGate")
    require(isinstance(gate, dict), "missing plan gate")
    require(gate.get("minimumTerraformVersion") == "1.11.0", "Terraform floor drift")
    require(gate.get("maximumTerraformMajorExclusive") == 2, "Terraform ceiling drift")
    for key in ("stagedExactSourceCopy", "savedPlanRequired", "rawPlanPublic", "rawAwsOutputPublic"):
        expected = key not in {"rawPlanPublic", "rawAwsOutputPublic"}
        require(gate.get(key) is expected, f"plan control drift: {key}")
    require(gate.get("initBackend") is False, "remote backend initialized early")
    require(gate.get("privatePlanMode") == "0600", "plan mode drift")
    require(gate.get("expectedManagedCreateCount") == 13, "managed create count drift")
    require(gate.get("allowedManagedActions") == [["create"]], "managed actions widened")
    require(gate.get("allowedDataActions") == [["read"], ["no-op"]], "data actions widened")
    for key in (
        "updateAllowed",
        "deleteAllowed",
        "replacementAllowed",
        "importAllowed",
        "policyAttachmentAllowed",
        "eksResourceAllowed",
    ):
        require(gate.get(key) is False, f"unsafe plan capability enabled: {key}")
    require(set(value.get("expectedManagedResources", [])) == expected_managed, "managed inventory drift")

    evidence = value.get("evidence")
    require(isinstance(evidence, dict), "missing evidence boundary")
    for key in (
        "privateBundleOnly",
        "binaryPlanSha256",
        "planJsonSha256",
        "planTextSha256",
        "tfvarsSha256",
        "sourceManifestSha256",
        "redactedStdout",
    ):
        require(evidence.get(key) is True, f"evidence control disabled: {key}")
    for key in ("accountIdEmitted", "bucketNameEmitted", "principalArnEmitted"):
        require(evidence.get(key) is False, f"private identity emission enabled: {key}")

    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict), "missing execution boundary")
    for key in (
        "verificationRunsTerraform",
        "verificationAccessesAws",
        "terraformApplyAllowed",
        "backendResourceMutationAllowed",
        "iamPolicyAttachmentAllowed",
        "stateMigrationAllowed",
        "statePullAllowed",
        "statePushAllowed",
        "stateRestoreAllowed",
        "kubernetesAccessAllowed",
        "githubMutationAllowed",
        "automaticRetryAllowed",
    ):
        require(boundary.get(key) is False, f"unsafe execution capability enabled: {key}")
    for key in (
        "executionMayReadAwsIdentity",
        "executionMayRunTerraformInitBackendFalse",
        "executionMayRunTerraformPlan",
        "executionMayRunTerraformShow",
    ):
        require(boundary.get(key) is True, f"plan-only capability missing: {key}")

    successor = value.get("successor")
    require(isinstance(successor, dict), "missing successor")
    require(successor.get("version") == "v0.12.1.2", "successor version drift")
    require("saved-plan-apply" in successor.get("scope", ""), "successor apply scope missing")

    if check_files:
        for path in value["documents"].values():
            require((root / path).is_file(), f"missing document: {path}")
        for path in (
            entrypoint["path"],
            "scripts/check-v0.12.1.1-state-bootstrap-terraform-plan.py",
            "scripts/test-v0.12.1.1-state-bootstrap-plan.py",
            "scripts/validate-v0.12.1.1-guarded-state-bootstrap-plan.sh",
        ):
            target = root / path
            require(target.is_file() and not target.is_symlink(), f"missing executable: {path}")
            require(stat.S_IMODE(target.stat().st_mode) == 0o755, f"executable mode drift: {path}")
        require(
            (root / "delivery/examples/v0.12.1.1-state-bootstrap-plan-request.example.json").is_file(),
            "missing private request example",
        )


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("apply enabled", lambda item: item["executionBoundary"].__setitem__("terraformApplyAllowed", True)),
    ("migration enabled", lambda item: item["executionBoundary"].__setitem__("stateMigrationAllowed", True)),
    ("backend enabled", lambda item: item["terraformPlanGate"].__setitem__("initBackend", True)),
    ("delete enabled", lambda item: item["terraformPlanGate"].__setitem__("deleteAllowed", True)),
    ("update enabled", lambda item: item["terraformPlanGate"].__setitem__("updateAllowed", True)),
    ("replacement enabled", lambda item: item["terraformPlanGate"].__setitem__("replacementAllowed", True)),
    ("import enabled", lambda item: item["terraformPlanGate"].__setitem__("importAllowed", True)),
    ("attachment enabled", lambda item: item["terraformPlanGate"].__setitem__("policyAttachmentAllowed", True)),
    ("raw plan public", lambda item: item["terraformPlanGate"].__setitem__("rawPlanPublic", True)),
    ("account emitted", lambda item: item["evidence"].__setitem__("accountIdEmitted", True)),
    ("long approval", lambda item: item["identityGates"].__setitem__("maximumApprovalWindowSeconds", 7200)),
    ("old Terraform", lambda item: item["terraformPlanGate"].__setitem__("minimumTerraformVersion", "1.8.0")),
    ("unexpected resource", lambda item: item["expectedManagedResources"].append("aws_eks_cluster.state")),
    ("direct v0.12.2 successor", lambda item: item["successor"].__setitem__("version", "v0.12.2")),
    ("repair predecessor bypass", lambda item: item["predecessor"].__setitem__("version", "v0.12.1")),
    ("foundation drift", lambda item: item["predecessor"].__setitem__("foundationVersion", "v0.12.0")),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

example = load(root / "delivery/examples/v0.12.1.1-state-bootstrap-plan-request.example.json")
require(example.get("operation") == "plan-state-backend-foundation", "request example operation drift")
require("REPLACE" in example.get("expectedMainCommit", ""), "request example contains a concrete main")
require("REPLACE" in example.get("expectedAwsAccountId", ""), "request example contains a concrete account")
require("REPLACE" in example["expectedInputs"].get("stateBucketName", ""), "request example contains a real bucket")

executor = (root / contract["entrypoint"]["path"]).read_text()
require('choices=("verify", "execute")' in executor, "verify/execute CLI split missing")
require('"init", "-backend=false", "-input=false"' in executor, "backend-disabled init missing")
require('CONFIRM_STATE_BOOTSTRAP_PLAN' in executor, "plan confirmation missing")
require('terraform_apply_executed": False' in executor, "apply boundary output missing")
require('state_migration_executed": False' in executor, "migration boundary output missing")

docs = (root / contract["documents"]["operatorBoundary"]).read_text()
for fragment in (
    "cannot apply that plan",
    "exactly 13 managed `create` actions",
    "v0.12.1.2",
    "v0.12.2 remains the sole owner",
    "Keep the real bucket name, account ID",
):
    require(fragment in docs, f"operator boundary missing: {fragment}")

for path in (
    root / "README.md",
    root / "CHANGELOG.md",
    root / "docs/ROADMAP.md",
    root / "docs/CURRENT_AUTHORITATIVE_SURFACE.md",
    root / "docs/TERRAFORM_STATE_MANAGEMENT.md",
):
    require("v0.12.1.1" in path.read_text(), f"version surface not updated: {path.relative_to(root)}")

print("v0.12.1.1 contract and 16 fail-closed mutations passed offline.")
PYTHON

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.1.1-state-bootstrap-terraform-plan.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.1.1-state-bootstrap-plan.py" \
  "${ROOT_DIR}/scripts/test-v0.12.1.1-state-bootstrap-plan.py"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.1.1-state-bootstrap-plan.py"

"${ROOT_DIR}/scripts/validate-v0.12.1-remote-state-foundation.sh"

echo "v0.12.1.1 guarded plan entrypoint passed offline; no AWS or Terraform command was executed."

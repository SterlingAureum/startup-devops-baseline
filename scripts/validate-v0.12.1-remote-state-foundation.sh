#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" <<'PYTHON'
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.1-remote-state-foundation.json"
bootstrap_root = root / "infra/terraform/aws/state-bootstrap"
backend_config_root = root / "infra/terraform/aws/backend-config"


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


expected_keys = {
    "bootstrap": "bootstrap/terraform.tfstate",
    "runtime-identities": "runtime-identities/terraform.tfstate",
    "dev": "environments/dev/terraform.tfstate",
    "test": "environments/test/terraform.tfstate",
    "prod": "environments/prod/terraform.tfstate",
}
expected_examples = {
    name: f"infra/terraform/aws/backend-config/{name}.s3.tfbackend.example"
    for name in expected_keys
}
expected_roots = {
    "runtime-identities": "infra/terraform/aws/runtime-identities",
    "dev": "infra/terraform/aws/environments/dev",
    "test": "infra/terraform/aws/environments/test",
    "prod": "infra/terraform/aws/environments/prod",
}
expected_state_actions = {"s3:GetObject", "s3:PutObject"}
expected_lock_actions = {"s3:GetObject", "s3:PutObject", "s3:DeleteObject"}
expected_kms_actions = {
    "kms:Decrypt",
    "kms:DescribeKey",
    "kms:Encrypt",
    "kms:GenerateDataKey",
}


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.1-remote-state-foundation-v1", "schema drift")
    require(value.get("version") == "v0.12.1", "version drift")
    require(
        value.get("status") == "delivered-offline-implementation-awaiting-reviewed-live-creation",
        "unsafe status",
    )
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")

    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.0", "predecessor version drift")
    require(
        predecessor.get("contract") == "delivery/contracts/v0.12.0-production-readiness-foundation.json",
        "predecessor contract drift",
    )
    if check_files:
        previous = load(root / predecessor["contract"])
        require(previous.get("version") == "v0.12.0", "invalid predecessor contract")

    terraform = value.get("terraform")
    require(isinstance(terraform, dict), "missing Terraform toolchain")
    require(terraform.get("minimumVersion") == "1.11.0", "unsafe Terraform floor")
    require(terraform.get("ciVersion") == "1.16.3", "Terraform CI pin drift")
    require(terraform.get("awsProviderConstraint") == "~> 6.0", "AWS provider scope drift")
    require(terraform.get("nativeS3LockingStable") is True, "native locking disabled")
    require(terraform.get("dynamoDbLocking") is False, "DynamoDB locking added")

    bootstrap = value.get("bootstrapRoot")
    require(isinstance(bootstrap, dict), "missing bootstrap root")
    require(bootstrap.get("path") == "infra/terraform/aws/state-bootstrap", "bootstrap path drift")
    require(bootstrap.get("backendDuringV0121") == "local", "bootstrap migrated early")
    require(bootstrap.get("protectedLocalStateRequired") is True, "bootstrap state protection removed")
    require(bootstrap.get("remoteKeyAfterV0122Migration") == expected_keys["bootstrap"], "bootstrap key drift")
    require(bootstrap.get("dependsOnEks") is False, "bootstrap depends on EKS")
    require(bootstrap.get("normalEnvironmentTeardownMayDestroy") is False, "teardown can destroy backend")

    foundation = value.get("backendFoundation")
    require(isinstance(foundation, dict), "missing backend foundation")
    require(foundation.get("type") == "s3", "backend type drift")
    require(foundation.get("declaredNotCreatedByThisOfflineCheckpoint") is True, "live creation overclaim")
    require(foundation.get("stateKeys") == expected_keys, "state-key topology drift")
    require(foundation.get("backendConfigExamples") == expected_examples, "backend example inventory drift")
    require(foundation.get("partialConfiguration") is True, "partial backend disabled")
    require(foundation.get("credentialsInTrackedConfiguration") is False, "tracked credentials enabled")
    require(foundation.get("accountIdentityInTrackedConfiguration") is False, "tracked account identity enabled")
    require(foundation.get("sharedCliWorkspaces") is False, "shared workspaces enabled")

    resources = foundation.get("resources")
    require(isinstance(resources, dict), "missing resource controls")
    for key in (
        "singleStateBucket",
        "bucketOwnerEnforced",
        "versioning",
        "sseKms",
        "kmsKeyRotation",
        "bucketKeyEnabled",
        "publicAccessBlocked",
        "tlsOnlyBucketPolicy",
        "bucketPreventDestroy",
        "kmsPreventDestroy",
    ):
        require(resources.get(key) is True, f"backend control disabled: {key}")
    require(resources.get("kmsDeletionWindowDays") == 30, "KMS deletion window drift")
    require(resources.get("bucketForceDestroy") is False, "force_destroy enabled")

    iam = value.get("iamBoundary")
    require(isinstance(iam, dict), "missing IAM boundary")
    for key in (
        "oneManagedPolicyPerRoot",
        "listRestrictedToExactStateAndLockKeys",
        "kmsUseRestrictedThroughS3",
    ):
        require(iam.get(key) is True, f"IAM control disabled: {key}")
    for key in (
        "policyAttachmentsCreated",
        "applicationDeliveryReceivesStateAccess",
        "githubRuntimeRolesReceiveStateAccess",
        "stateObjectDeleteAllowed",
    ):
        require(iam.get(key) is False, f"unsafe IAM capability enabled: {key}")
    require(set(iam.get("stateObjectActions", [])) == expected_state_actions, "state actions drift")
    require(set(iam.get("lockObjectActions", [])) == expected_lock_actions, "lock actions drift")
    require(set(iam.get("kmsActions", [])) == expected_kms_actions, "KMS actions drift")

    roots = value.get("existingRoots")
    require(isinstance(roots, dict) and set(roots) == set(expected_roots), "existing root inventory drift")
    for name, path in expected_roots.items():
        require(roots[name].get("path") == path, f"root path drift: {name}")
        require(roots[name].get("backendDuringV0121") == "local", f"root migrated early: {name}")

    migration = value.get("migrationBoundary")
    require(isinstance(migration, dict), "missing migration boundary")
    require(migration.get("ownerIncrement") == "v0.12.2", "migration owner drift")
    require(migration.get("emptyStateAcceptedAsEvidence") is False, "empty migration accepted")
    for key in (
        "existingBackendBlocksChanged",
        "terraformInitMigrateStateExecuted",
        "statePulled",
        "statePushed",
        "stateRestored",
        "combinedWithRefactor",
        "combinedWithPlatformUpgrade",
    ):
        require(migration.get(key) is False, f"migration boundary violated: {key}")

    live = value.get("liveCreationBoundary")
    require(isinstance(live, dict), "missing live creation boundary")
    for key in (
        "requiresProtectedMain",
        "requiresPrivateTfvars",
        "requiresSeparateReviewedPlan",
        "requiresExactApprovalWindow",
        "requiresPrivateEvidence",
    ):
        require(live.get(key) is True, f"live creation gate disabled: {key}")
    require(live.get("approvedByThisContract") is False, "contract authorizes live creation")
    require(live.get("executedByThisContract") is False, "contract claims live creation")

    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict), "missing execution boundary")
    require(boundary.get("offlineStaticValidationOnly") is True, "checkpoint is not offline-only")
    for key, enabled in boundary.items():
        if key != "offlineStaticValidationOnly":
            require(enabled is False, f"live effect enabled: {key}")

    successor = value.get("successor")
    require(isinstance(successor, dict) and successor.get("version") == "v0.12.2", "successor drift")

    if check_files:
        for path in value["documents"].values():
            require((root / path).is_file(), f"missing document: {path}")
        require((root / bootstrap["path"]).is_dir(), "bootstrap root not implemented")
        for path in expected_roots.values():
            require((root / path / "backend.tf").is_file(), f"missing root backend: {path}")
        for path in expected_examples.values():
            require((root / path).is_file(), f"missing backend example: {path}")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("old Terraform floor", lambda item: item["terraform"].__setitem__("minimumVersion", "1.8.0")),
    ("DynamoDB locking", lambda item: item["terraform"].__setitem__("dynamoDbLocking", True)),
    ("versioning disabled", lambda item: item["backendFoundation"]["resources"].__setitem__("versioning", False)),
    ("KMS disabled", lambda item: item["backendFoundation"]["resources"].__setitem__("sseKms", False)),
    ("public access allowed", lambda item: item["backendFoundation"]["resources"].__setitem__("publicAccessBlocked", False)),
    ("TLS-only removed", lambda item: item["backendFoundation"]["resources"].__setitem__("tlsOnlyBucketPolicy", False)),
    ("force destroy", lambda item: item["backendFoundation"]["resources"].__setitem__("bucketForceDestroy", True)),
    ("shared workspace", lambda item: item["backendFoundation"].__setitem__("sharedCliWorkspaces", True)),
    ("policy attached", lambda item: item["iamBoundary"].__setitem__("policyAttachmentsCreated", True)),
    ("application state access", lambda item: item["iamBoundary"].__setitem__("applicationDeliveryReceivesStateAccess", True)),
    ("state delete", lambda item: item["iamBoundary"].__setitem__("stateObjectDeleteAllowed", True)),
    ("early root migration", lambda item: item["existingRoots"]["dev"].__setitem__("backendDuringV0121", "s3")),
    ("empty migration", lambda item: item["migrationBoundary"].__setitem__("emptyStateAcceptedAsEvidence", True)),
    ("migration and upgrade", lambda item: item["migrationBoundary"].__setitem__("combinedWithPlatformUpgrade", True)),
    ("AWS accessed", lambda item: item["executionBoundary"].__setitem__("awsAccessed", True)),
    ("live apply authorized", lambda item: item["executionBoundary"].__setitem__("liveExecutionAuthorized", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

main_tf = (bootstrap_root / "main.tf").read_text()
backend_tf = (bootstrap_root / "backend.tf").read_text()
all_bootstrap_tf = "\n".join(path.read_text() for path in sorted(bootstrap_root.glob("*.tf")))

required_fragments = (
    'resource "aws_s3_bucket" "state"',
    'resource "aws_s3_bucket_versioning" "state"',
    'status = "Enabled"',
    'resource "aws_s3_bucket_server_side_encryption_configuration" "state"',
    'sse_algorithm     = "aws:kms"',
    "bucket_key_enabled = true",
    'resource "aws_s3_bucket_public_access_block" "state"',
    "block_public_acls       = true",
    "block_public_policy     = true",
    "ignore_public_acls      = true",
    "restrict_public_buckets = true",
    'sid    = "DenyInsecureTransport"',
    'variable = "aws:SecureTransport"',
    'values   = ["false"]',
    'resource "aws_kms_key" "state"',
    "enable_key_rotation     = true",
    "deletion_window_in_days = 30",
    "force_destroy = false",
    'object_ownership = "BucketOwnerEnforced"',
    'resource "aws_iam_policy" "root_state_access"',
    'variable = "s3:prefix"',
    'variable = "kms:ViaService"',
)
for fragment in required_fragments:
    require(fragment in main_tf, f"bootstrap declaration missing: {fragment}")
require(main_tf.count("prevent_destroy = true") == 2, "bucket/KMS prevent_destroy drift")
require('backend "s3"' not in backend_tf, "bootstrap migrated before v0.12.2")
require("dynamodb" not in all_bootstrap_tf.lower(), "DynamoDB locking found")
require("aws_iam_role_policy_attachment" not in all_bootstrap_tf, "IAM policy attachment added")
require("aws_iam_user_policy_attachment" not in all_bootstrap_tf, "IAM user attachment added")
for key in expected_keys.values():
    require(f'"{key}"' in main_tf, f"bootstrap missing key: {key}")

for name, path in expected_roots.items():
    current_backend = (root / path / "backend.tf").read_text()
    require('backend "s3"' not in current_backend, f"{name} migrated before v0.12.2")

for name, key in expected_keys.items():
    path = root / expected_examples[name]
    text = path.read_text()
    require(f'key                 = "{key}"' in text, f"backend key drift: {name}")
    require('encrypt             = true' in text, f"encryption disabled: {name}")
    require('use_lockfile        = true' in text, f"native lock disabled: {name}")
    require('allowed_account_ids = ["replace-with-aws-account-id"]' in text, f"account guard missing: {name}")
    require("dynamodb" not in text.lower(), f"DynamoDB found: {name}")
    for forbidden in ("access_key", "secret_key", "profile =", "role_arn"):
        require(forbidden not in text, f"tracked backend identity/credential found in {name}: {forbidden}")

materialized = [path for path in backend_config_root.glob("*.tfbackend") if path.is_file()]
require(not materialized, "materialized private tfbackend file is tracked")

version_roots = [bootstrap_root, *(root / path for path in expected_roots.values())]
for tf_root in version_roots:
    versions = (tf_root / "versions.tf").read_text()
    require('required_version = ">= 1.11.0, < 2.0.0"' in versions, f"Terraform floor drift: {tf_root.relative_to(root)}")
    require('version = "~> 6.0"' in versions, f"AWS provider drift: {tf_root.relative_to(root)}")

workflow = (root / ".github/workflows/terraform-validate.yaml").read_text()
require("terraform_version: 1.16.3" in workflow, "Terraform CI version is not pinned")

terraform_validator = (root / "scripts/validate-terraform.sh").read_text()
require("state-bootstrap runtime-identities environments/dev environments/test environments/prod" in terraform_validator, "five-root Terraform validation missing")

gitignore = (root / ".gitignore").read_text()
require(re.search(r"(?m)^\*\.tfbackend$", gitignore) is not None, "private tfbackend ignore missing")
require(re.search(r"(?m)^!\*\.tfbackend\.example$", gitignore) is not None, "backend examples are ignored")

roadmap = (root / "docs/ROADMAP.md").read_text()
section = roadmap[roadmap.index("## v0.12 - Production Readiness Capstone"):roadmap.index("## v1.0 - Production-ready Commercial Baseline")]
require("v0.12.1" in section and "delivered offline" in section, "roadmap delivery status missing")
require("no state is migrated" in section, "roadmap migration boundary missing")

state_doc = (root / "docs/TERRAFORM_STATE_MANAGEMENT.md").read_text()
for phrase in ("five exact", "attaches none", "v0.12.2", "non-empty reviewed state"):
    require(phrase in state_doc, f"state management document missing: {phrase}")

implementation_doc = (root / "docs/V0.12.1_REMOTE_STATE_FOUNDATION.md").read_text()
for phrase in (
    "complete offline implementation",
    "not authority to execute it",
    "The policies are not attached",
    "Their `backend.tf` files are intentionally unchanged",
):
    require(phrase in implementation_doc, f"implementation boundary missing: {phrase}")

checked_paths = [
    contract_path,
    root / "docs/V0.12.1_REMOTE_STATE_FOUNDATION.md",
    bootstrap_root / "README.md",
    *(root / path for path in expected_examples.values()),
]
for path in checked_paths:
    text = path.read_text()
    require("AKIA" not in text, f"access key material in {path.relative_to(root)}")
    require(re.search(r"(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])", text) is None, f"account identity in {path.relative_to(root)}")

print("v0.12.1 remote-state declaration, five-key IAM boundary and 16 negative mutations passed offline.")
PYTHON

bash "${ROOT_DIR}/scripts/validate-v0.12.0-production-readiness-foundation.sh"
echo "v0.12.1 passed; AWS creation needs separate approval and every state migration remains v0.12.2 work."

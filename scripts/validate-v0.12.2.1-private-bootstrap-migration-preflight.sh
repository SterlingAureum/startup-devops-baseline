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
import re
import subprocess
import sys
from typing import Any, Callable


root = Path(sys.argv[1])
contract_path = root / "delivery/contracts/v0.12.2.1-private-bootstrap-migration-preflight.json"
predecessor_path = root / "delivery/contracts/v0.12.2.0.1-private-bootstrap-state-location-repair.json"
document_path = root / "docs/V0.12.2.1_PRIVATE_BOOTSTRAP_MIGRATION_PREFLIGHT.md"
example_path = root / "delivery/examples/v0.12.2.1-bootstrap-migration-preflight-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.1-bootstrap-migration-preflight.py"
test_path = root / "scripts/test-v0.12.2.1-bootstrap-migration-preflight.py"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"Missing file: {path.relative_to(root)}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"Expected JSON object: {path.relative_to(root)}")
    return value


def git_index_mode(relative: str) -> str:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", relative], capture_output=True, text=True, check=False)
    require(result.returncode == 0 and result.stdout.strip(), f"missing index entry: {relative}")
    return result.stdout.split()[0]


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.2.1-private-bootstrap-migration-preflight-v1", "schema drift")
    require(value.get("version") == "v0.12.2.1", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-private-preflight-approval", "unsafe status")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "236f28ee095aa11c56e1127960efe715b8b4f391", "baseline drift")
    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.2.0.1", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    require(predecessor.get("requiredStatus") == "delivered-offline-private-state-location-repair", "predecessor status drift")
    if check_files:
        require(load(predecessor_path).get("status") == predecessor["requiredStatus"], "predecessor incomplete")

    chain = value.get("privateInputChain")
    require(isinstance(chain, dict), "missing private chain")
    expected = {
        "planRequestSha256": "9f041fa9b98c15b7309df8b87af79bb50d3871eb0501b9977bbdb772c41a326b",
        "applyRequestSha256": "91406ddbac3f75415c383da3b369070ec93c0c8874a11023ee1a7b50e307de07",
        "recoveryRequestSha256": "cd31e26adc15932215985f27db865717a674382d22b34d8f0d2327e977a6c7a7",
        "appliedStateSha256": "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995",
        "recoveryResultSha256": "c65f405bdb67779af4a9b074e5760ba62b2aff78f075ff10985108ba70ba4365",
        "liveValidationSha256": "6f929213b687c44652c5f265f577767dcc422ab363f4cb598ed1c68395c1c091",
    }
    for key, digest in expected.items():
        require(chain.get(key) == digest, f"private chain digest drift: {key}")
    require(chain.get("canonicalStateRelativePath") == "source/terraform.tfstate", "canonical state path drift")
    require(chain.get("preservedStateRelativePath") == "state-bootstrap.tfstate.applied", "preserved state path drift")
    require(chain.get("byteIdentityRequiredBeforeCommands") is True, "byte identity gate disabled")
    require(chain.get("repositoryStateFallbackAllowed") is False, "repository state fallback enabled")

    backend = value.get("partialBackendDeclaration")
    require(isinstance(backend, dict), "missing backend boundary")
    require(backend.get("root") == "infra/terraform/aws/state-bootstrap", "backend root drift")
    require(backend.get("backendType") == "s3" and backend.get("emptyDeclarationOnly") is True, "backend declaration drift")
    require(backend.get("expectedKey") == "bootstrap/terraform.tfstate", "backend key drift")
    require(backend.get("privateConfigRequired") is True and backend.get("useLockfile") is True, "backend guard disabled")
    require(backend.get("credentialsAllowed") is False, "backend credentials enabled")

    verify = value.get("verifyBoundary")
    require(isinstance(verify, dict), "missing verify boundary")
    for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence"):
        require(verify.get(key) is False, f"verify side effect enabled: {key}")
    for key in ("validatesProtectedMain", "validatesPriorPrivateChain", "validatesStateIdentity", "validatesBackendConfig"):
        require(verify.get(key) is True, f"verify guard disabled: {key}")

    execute = value.get("executeBoundary")
    require(isinstance(execute, dict), "missing execute boundary")
    for key in ("awsReadOnlyValidation", "terraformVersionRead", "createsThirdPrivateStateCopy", "createsPrivateStagedMigrationSource", "createsReviewedCommandPlan"):
        require(execute.get(key) is True, f"preflight output disabled: {key}")
    for key in ("terraformInit", "terraformPlan", "terraformApply", "stateMigration", "statePush", "destroy", "iamPolicyAttachment", "automaticRetry"):
        require(execute.get(key) is False, f"unsafe execution enabled: {key}")

    evidence = value.get("privateEvidence")
    require(isinstance(evidence, dict), "missing private evidence")
    require(evidence.get("ownerOnlyDirectoryMode") == "0700" and evidence.get("ownerOnlyFileMode") == "0600", "private mode drift")
    for key in ("recordsStateSha256", "recordsLineageAndSerial", "recordsManagedAndDataAddresses", "recordsResourceIdentitySha256", "recordsCurrentSourceManifest", "recordsLiveFoundationValidation"):
        require(evidence.get(key) is True, f"private evidence omitted: {key}")
    require(evidence.get("publishesPrivatePaths") is False and evidence.get("publishesResourceIdentity") is False, "private identity publication enabled")

    approval = value.get("approval")
    require(approval == {"maximumWindowSeconds": 3600, "minimumRemainingSecondsAtStart": 900, "preflightExecutionRequiresSeparateConfirmation": True, "migrationRequiresNewV01222Window": True}, "approval boundary drift")
    producer = value.get("packageProducer")
    require(isinstance(producer, dict) and producer and all(item is False for item in producer.values()), "package claims live effect")
    successor = value.get("successor")
    require(isinstance(successor, dict) and successor.get("version") == "v0.12.2.2", "successor drift")
    require(successor.get("authorizedByThisPackage") is False, "successor migration pre-authorized")

    if check_files:
        for path in (document_path, example_path, executor_path, test_path):
            require(path.is_file() and not path.is_symlink(), f"missing artifact: {path.relative_to(root)}")
        for relative in (
            "scripts/execute-v0.12.2.1-bootstrap-migration-preflight.py",
            "scripts/test-v0.12.2.1-bootstrap-migration-preflight.py",
            "scripts/validate-v0.12.2.1-private-bootstrap-migration-preflight.sh",
        ):
            require(git_index_mode(relative) == "100755", f"executable mode drift: {relative}")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("unsafe status", lambda item: item.__setitem__("status", "migration-complete")),
    ("plan digest", lambda item: item["privateInputChain"].__setitem__("planRequestSha256", "0" * 64)),
    ("apply digest", lambda item: item["privateInputChain"].__setitem__("applyRequestSha256", "0" * 64)),
    ("recovery digest", lambda item: item["privateInputChain"].__setitem__("recoveryRequestSha256", "0" * 64)),
    ("state digest", lambda item: item["privateInputChain"].__setitem__("appliedStateSha256", "0" * 64)),
    ("repository fallback", lambda item: item["privateInputChain"].__setitem__("repositoryStateFallbackAllowed", True)),
    ("byte gate", lambda item: item["privateInputChain"].__setitem__("byteIdentityRequiredBeforeCommands", False)),
    ("backend credentials", lambda item: item["partialBackendDeclaration"].__setitem__("credentialsAllowed", True)),
    ("wrong key", lambda item: item["partialBackendDeclaration"].__setitem__("expectedKey", "shared/terraform.tfstate")),
    ("verify aws", lambda item: item["verifyBoundary"].__setitem__("awsCommands", True)),
    ("verify write", lambda item: item["verifyBoundary"].__setitem__("writesPrivateEvidence", True)),
    ("no backup", lambda item: item["executeBoundary"].__setitem__("createsThirdPrivateStateCopy", False)),
    ("init enabled", lambda item: item["executeBoundary"].__setitem__("terraformInit", True)),
    ("apply enabled", lambda item: item["executeBoundary"].__setitem__("terraformApply", True)),
    ("migration enabled", lambda item: item["executeBoundary"].__setitem__("stateMigration", True)),
    ("state push enabled", lambda item: item["executeBoundary"].__setitem__("statePush", True)),
    ("retry enabled", lambda item: item["executeBoundary"].__setitem__("automaticRetry", True)),
    ("paths published", lambda item: item["privateEvidence"].__setitem__("publishesPrivatePaths", True)),
    ("long window", lambda item: item["approval"].__setitem__("maximumWindowSeconds", 7200)),
    ("successor authorized", lambda item: item["successor"].__setitem__("authorizedByThisPackage", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

backend_text = (root / "infra/terraform/aws/state-bootstrap/backend.tf").read_text()
require(backend_text.count('backend "s3" {}') == 1, "partial backend declaration drift")
for secret in ("access_key", "secret_key", "session_token"):
    require(secret not in backend_text, f"backend declaration contains credential field: {secret}")
for relative in (
    "infra/terraform/aws/runtime-identities/backend.tf",
    "infra/terraform/aws/environments/dev/backend.tf",
    "infra/terraform/aws/environments/test/backend.tf",
    "infra/terraform/aws/environments/prod/backend.tf",
):
    require('backend "s3"' not in (root / relative).read_text(), f"later root backend activated early: {relative}")

example = load(example_path)
require(example.get("schemaVersion") == "v0.12.2.1-bootstrap-migration-preflight-request-v1", "example schema drift")
require(example.get("executionBoundary", {}).get("stateMigration") is False, "example authorizes migration")
require("REPLACE_WITH_40_CHARACTER_PROTECTED_MAIN_SHA" in example_path.read_text(), "example main placeholder missing")

source = executor_path.read_text()
for marker in (
    'source/terraform.tfstate', 'state-bootstrap.tfstate.applied',
    'canonical_state.read_bytes() == preserved_state.read_bytes()',
    'operational_commands_executed": []', '"terraform_init_executed": False',
    '"state_migration_executed": False', 'validate_live_foundation',
    'bootstrap-state.pre-migration.backup', 'migration-command-plan.json',
):
    require(marker in source, f"executor safety marker missing: {marker}")
for forbidden in ('"apply", "-auto-approve"', '"state", "push"', '["terraform", "destroy"'):
    require(forbidden not in source, f"unsafe executor command present: {forbidden}")

document = " ".join(document_path.read_text().split()).replace("`", "")
for fragment in (
    "runs no AWS or Terraform command", "source/terraform.tfstate",
    "repository-root state file is not an accepted fallback", "executes no AWS or Terraform command",
    "new approval request and a new time window",
):
    require(fragment.lower() in document.lower(), f"document marker missing: {fragment}")

public_text = contract_path.read_text() + "\n" + document_path.read_text() + "\n" + example_path.read_text()
for pattern, label in (
    (r"arn:aws(?:-[a-z]+)?:", "AWS ARN"),
    (r"(?<![0-9])[0-9]{12}(?![0-9])", "AWS account-like identifier"),
    (r"/(?:home|Users)/[^/\s]+/", "user home path"),
):
    require(re.search(pattern, public_text) is None, f"public preflight material contains {label}")

print("v0.12.2.1 migration preflight contract and 20 fail-closed mutations passed offline.")
PYTHON

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.1-bootstrap-migration-preflight.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.1-bootstrap-migration-preflight.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.1-bootstrap-migration-preflight.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.0.1-private-bootstrap-state-location-repair.sh"

echo "v0.12.2.1 private bootstrap migration preflight passed offline; no AWS or Terraform command was executed."

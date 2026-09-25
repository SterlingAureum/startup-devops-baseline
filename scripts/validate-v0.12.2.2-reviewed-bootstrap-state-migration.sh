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
contract_path = root / "delivery/contracts/v0.12.2.2-reviewed-bootstrap-state-migration.json"
predecessor_path = root / "delivery/contracts/v0.12.2.1-private-bootstrap-migration-preflight.json"
document_path = root / "docs/V0.12.2.2_REVIEWED_BOOTSTRAP_STATE_MIGRATION.md"
example_path = root / "delivery/examples/v0.12.2.2-bootstrap-state-migration-request.example.json"
executor_path = root / "scripts/execute-v0.12.2.2-bootstrap-state-migration.py"
test_path = root / "scripts/test-v0.12.2.2-bootstrap-state-migration.py"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing file: {path.relative_to(root)}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path.relative_to(root)}")
    return value


def index_mode(relative: str) -> str:
    result = subprocess.run(["git", "-C", str(root), "ls-files", "-s", "--", relative], capture_output=True, text=True, check=False)
    require(result.returncode == 0 and result.stdout.strip(), f"missing index entry: {relative}")
    return result.stdout.split()[0]


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.2.2-reviewed-bootstrap-state-migration-v1", "schema drift")
    require(value.get("version") == "v0.12.2.2", "version drift")
    require(value.get("status") == "delivered-awaiting-separate-state-migration-approval", "unsafe status")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")
    require(value.get("implementationBaselineCommit") == "33734683159315171e8de9d524691b94806dbc15", "baseline drift")
    predecessor = value.get("predecessor")
    require(isinstance(predecessor, dict), "missing predecessor")
    require(predecessor.get("version") == "v0.12.2.1", "predecessor version drift")
    require(predecessor.get("contract") == str(predecessor_path.relative_to(root)), "predecessor path drift")
    require(predecessor.get("requiredStatus") == "delivered-awaiting-separate-private-preflight-approval", "predecessor status drift")
    require(predecessor.get("humanReviewCompleted") is True, "human review missing")
    if check_files:
        require(load(predecessor_path).get("status") == predecessor["requiredStatus"], "predecessor incomplete")

    bindings = value.get("reviewedPreflightBindings")
    require(isinstance(bindings, dict), "missing preflight bindings")
    expected = {
        "privatePreflightRequestSha256": "1ac1f2be621fd5c5b9da05b82f1bc43eac3b10b0bf4d351179f6905096a77204",
        "preflightResultSha256": "4e5a060e9a8ce7660ce56033b0b29153ae6a37c52a4a5501d8c46921e185add9",
        "stateInventorySha256": "fc25de78ab8d6e86b65a26a4bbbc992e1c631c46623e3dd81925c0d69d1829ff",
        "migrationSourceManifestSha256": "8c9ef5076aeea7ef2cb617faf080f24db24839caf3a134129800ac9b4c3ce9e3",
        "migrationCommandPlanSha256": "16e56fcbf1d59c20bb273291719bf7f24d4d0144da1ba52bce9c17b9c8ddbaab",
        "immutableBackupSha256": "83bca892fef5f5eefffba3de247c4694daccf7201309262ff8dd73b61bc1b995",
        "resourceIdentitySha256": "c59b979c1449d5212ceb72319995fbd01da9715c3dbf99ef9ca08d0bc8e282c4",
        "preflightLiveValidationSha256": "6f929213b687c44652c5f265f577767dcc422ab363f4cb598ed1c68395c1c091",
    }
    for key, expected_digest in expected.items():
        require(bindings.get(key) == expected_digest, f"reviewed digest drift: {key}")
    require(bindings.get("managedAddressCount") == 13, "managed count drift")
    require(bindings.get("remoteStateObjectVersionCount") == 0, "remote backend was not empty")
    require(bindings.get("reviewedCommandExecuted") is False, "preflight command already executed")

    verify = value.get("verifyBoundary")
    require(isinstance(verify, dict), "missing verify boundary")
    for key in ("awsCommands", "terraformCommands", "writesPrivateEvidence", "migrationAuthorizedByVerify"):
        require(verify.get(key) is False, f"verify side effect enabled: {key}")
    for key in ("requiresProtectedMain", "requiresFreshWindow", "revalidatesAllPreflightArtifacts", "revalidatesExactCommand"):
        require(verify.get(key) is True, f"verify guard disabled: {key}")

    execute = value.get("executeBoundary")
    require(isinstance(execute, dict), "missing execute boundary")
    for key in ("exactReviewedTerraformInitMigrateState", "forceCopyReviewedNonInteractiveMigration", "preMigrationAwsReadOnlyValidation", "postMigrationStatePull", "postMigrationStateList", "postMigrationS3ObjectVersionRead"):
        require(execute.get(key) is True, f"required migration step disabled: {key}")
    for key in ("terraformPlan", "terraformApply", "statePush", "destroy", "iamPolicyAttachment", "localBackupDeletion", "automaticRetry", "automaticRollback"):
        require(execute.get(key) is False, f"unsafe migration power enabled: {key}")

    post = value.get("postMigrationGate")
    require(isinstance(post, dict) and post and all(item is True for item in post.values()), "post-migration gate disabled")
    failure = value.get("failureBoundary")
    require(isinstance(failure, dict), "missing failure boundary")
    for key in ("preserveMigrationOutput", "preserveAllPriorPrivateEvidence", "preserveRemoteObjectVersions"):
        require(failure.get(key) is True, f"failure preservation disabled: {key}")
    for key in ("retryWithoutNewReview", "rollbackWithoutNewReview", "uncertaintyMeansSuccess"):
        require(failure.get(key) is False, f"unsafe failure behavior enabled: {key}")

    privacy = value.get("privacyBoundary")
    require(isinstance(privacy, dict), "missing privacy boundary")
    require(privacy.get("allowsPublicDigestsCountsAndBooleans") is True, "public evidence boundary disabled")
    for key, item in privacy.items():
        if key != "allowsPublicDigestsCountsAndBooleans":
            require(item is False, f"private identity publication enabled: {key}")
    producer = value.get("packageProducer")
    require(isinstance(producer, dict) and producer and all(item is False for item in producer.values()), "package claims live effect")
    successor = value.get("successor")
    require(isinstance(successor, dict) and successor.get("version") == "v0.12.2.3", "successor drift")
    require(successor.get("authorizedByThisPackage") is False, "successor pre-authorized")

    if check_files:
        for path in (document_path, example_path, executor_path, test_path):
            require(path.is_file() and not path.is_symlink(), f"missing artifact: {path.relative_to(root)}")
        for relative in (
            "scripts/execute-v0.12.2.2-bootstrap-state-migration.py",
            "scripts/test-v0.12.2.2-bootstrap-state-migration.py",
            "scripts/validate-v0.12.2.2-reviewed-bootstrap-state-migration.sh",
        ):
            require(index_mode(relative) == "100755", f"executable mode drift: {relative}")


contract = load(contract_path)
validate(contract)
mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("unsafe status", lambda item: item.__setitem__("status", "migration-complete")),
    ("human review missing", lambda item: item["predecessor"].__setitem__("humanReviewCompleted", False)),
    ("request drift", lambda item: item["reviewedPreflightBindings"].__setitem__("privatePreflightRequestSha256", "0" * 64)),
    ("result drift", lambda item: item["reviewedPreflightBindings"].__setitem__("preflightResultSha256", "0" * 64)),
    ("command drift", lambda item: item["reviewedPreflightBindings"].__setitem__("migrationCommandPlanSha256", "0" * 64)),
    ("backup drift", lambda item: item["reviewedPreflightBindings"].__setitem__("immutableBackupSha256", "0" * 64)),
    ("nonempty backend", lambda item: item["reviewedPreflightBindings"].__setitem__("remoteStateObjectVersionCount", 1)),
    ("verify aws", lambda item: item["verifyBoundary"].__setitem__("awsCommands", True)),
    ("verify authorizes", lambda item: item["verifyBoundary"].__setitem__("migrationAuthorizedByVerify", True)),
    ("unreviewed command", lambda item: item["verifyBoundary"].__setitem__("revalidatesExactCommand", False)),
    ("plan enabled", lambda item: item["executeBoundary"].__setitem__("terraformPlan", True)),
    ("apply enabled", lambda item: item["executeBoundary"].__setitem__("terraformApply", True)),
    ("state push enabled", lambda item: item["executeBoundary"].__setitem__("statePush", True)),
    ("backup delete", lambda item: item["executeBoundary"].__setitem__("localBackupDeletion", True)),
    ("retry enabled", lambda item: item["executeBoundary"].__setitem__("automaticRetry", True)),
    ("lineage unchecked", lambda item: item["postMigrationGate"].__setitem__("lineageMustMatch", False)),
    ("identity unchecked", lambda item: item["postMigrationGate"].__setitem__("resourceIdentityMustMatch", False)),
    ("retry without review", lambda item: item["failureBoundary"].__setitem__("retryWithoutNewReview", True)),
    ("uncertainty success", lambda item: item["failureBoundary"].__setitem__("uncertaintyMeansSuccess", True)),
    ("version id published", lambda item: item["privacyBoundary"].__setitem__("publishesStateObjectVersionId", True)),
    ("package migrates", lambda item: item["packageProducer"].__setitem__("migratesState", True)),
    ("successor authorized", lambda item: item["successor"].__setitem__("authorizedByThisPackage", True)),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"unsafe mutation accepted: {label}")

example = load(example_path)
require(example.get("schemaVersion") == "v0.12.2.2-bootstrap-state-migration-request-v1", "example schema drift")
require(example.get("executionBoundary", {}).get("terraformApply") is False, "example authorizes apply")
require(example.get("executionBoundary", {}).get("automaticRetry") is False, "example authorizes retry")
source = executor_path.read_text()
for marker in (
    '"-migrate-state",', '"-force-copy",', 'validate_live_foundation',
    '"terraform-state-pull"', '"terraform-state-list"', '"s3-state-head"',
    '"terraform_plan_executed": False', '"terraform_apply_executed": False',
    '"automatic_retry_performed": False', 'private_state_object_version_id_emitted',
    'preserve all private evidence and do not retry',
):
    require(marker in source, f"executor safety marker missing: {marker}")
for forbidden in ('"state", "push"', '["terraform", "apply"', '["terraform", "destroy"'):
    require(forbidden not in source, f"unsafe command present: {forbidden}")
document = " ".join(document_path.read_text().split()).replace("`", "")
for fragment in (
    "does not read private evidence, run AWS or Terraform, or migrate state",
    "new private request, new output directory and new approval window",
    "No reconfigure, plan, apply, state push, destroy",
    "Do not rerun the executor",
    "v0.12.2.3 separately owns lock-contention proof",
):
    require(fragment.lower() in document.lower(), f"document marker missing: {fragment}")
public_text = contract_path.read_text() + "\n" + document_path.read_text() + "\n" + example_path.read_text()
for pattern, label in (
    (r"arn:aws(?:-[a-z]+)?:", "AWS ARN"),
    (r"(?<![0-9])[0-9]{12}(?![0-9])", "AWS account-like identifier"),
    (r"/(?:home|Users)/[^/\s]+/", "user home path"),
):
    require(re.search(pattern, public_text) is None, f"public migration material contains {label}")
print("v0.12.2.2 reviewed migration contract and 22 fail-closed mutations passed offline.")
PYTHON

PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  "${ROOT_DIR}/scripts/execute-v0.12.2.2-bootstrap-state-migration.py" \
  "${ROOT_DIR}/scripts/test-v0.12.2.2-bootstrap-state-migration.py"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.12.2.2-bootstrap-state-migration.py"
bash "${ROOT_DIR}/scripts/validate-v0.12.2.1-private-bootstrap-migration-preflight.sh"

echo "v0.12.2.2 reviewed bootstrap state migration passed offline; no AWS or Terraform command was executed."

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
contract_path = root / "delivery/contracts/v0.12.0-production-readiness-foundation.json"
successor_path = root / "delivery/contracts/v0.12.1-remote-state-foundation.json"


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


expected_roots = [
    "infra/terraform/aws/runtime-identities",
    "infra/terraform/aws/environments/dev",
    "infra/terraform/aws/environments/test",
    "infra/terraform/aws/environments/prod",
]
expected_keys = [
    "bootstrap/terraform.tfstate",
    "runtime-identities/terraform.tfstate",
    "environments/dev/terraform.tfstate",
    "environments/test/terraform.tfstate",
    "environments/prod/terraform.tfstate",
]
expected_increments = [f"v0.12.{number}" for number in range(8)]
required_migration_invariants = {
    "reviewed-nonempty-source-state",
    "immutable-local-backup-and-digest",
    "lineage-preserved",
    "managed-addresses-preserved",
    "resource-identities-preserved",
    "lock-contention-verified",
    "zero-change-plan-after-migration",
    "object-version-recovery-drill",
}


def validate(value: dict[str, Any], *, check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.12.0-production-readiness-foundation-v1", "schema drift")
    require(value.get("version") == "v0.12.0", "version drift")
    require(value.get("status") == "delivered-offline-design-only", "unsafe status")
    require(value.get("repository") == "SterlingAureum/startup-devops-baseline", "repository drift")

    documents = value.get("documents")
    require(isinstance(documents, dict) and set(documents) == {
        "foundation", "roadmap", "terraformState", "authoritativeSurface", "aiPolicy"
    }, "document inventory drift")
    if check_files:
        for path in documents.values():
            require(isinstance(path, str) and (root / path).is_file(), f"missing document: {path}")

    predecessor = value.get("predecessorBoundary")
    require(isinstance(predecessor, dict), "missing predecessor boundary")
    require(predecessor.get("checkpoint") == "v0.11.9.3.6.7.7.20.1", "wrong predecessor")
    require(predecessor.get("v011EvidenceImmutable") is True, "v0.11 evidence made mutable")
    require(predecessor.get("v011DeferralsPreserved") is True, "v0.11 deferrals lost")
    require(predecessor.get("historicalReceiptsGrantLiveAuthority") is False, "historical authority enabled")
    if check_files:
        manifest = load(root / predecessor["evidenceManifest"])
        require(manifest.get("status") == "completed-with-explicit-environment-deferrals", "v0.11 closure status drift")
        require(manifest.get("newLiveExecutionAuthorized") is False, "v0.11 live authority drift")

    increments = value.get("increments")
    require(isinstance(increments, list), "missing increments")
    require([item.get("id") for item in increments] == expected_increments, "increment order drift")
    require(increments[0].get("status") == "delivered-offline", "v0.12.0 delivery status drift")
    require(all(item.get("status") == "planned" for item in increments[1:]), "future increment claims delivery")

    state = value.get("terraformState")
    require(isinstance(state, dict), "missing Terraform state contract")
    require(state.get("implementedBackendAtV0120") == "local", "v0.12.0 claims remote backend")
    require(state.get("implementedRoots") == expected_roots, "implemented root inventory drift")
    require(state.get("plannedBootstrapRoot") == "infra/terraform/aws/state-bootstrap", "bootstrap root drift")
    require(state.get("targetBackend") == "s3", "target backend drift")
    require(state.get("targetKeys") == expected_keys, "target key isolation drift")
    require(set(state.get("migrationInvariants", [])) == required_migration_invariants, "migration invariant drift")
    require(state.get("migrationCombinedWithRefactor") is False, "migration/refactor combined")
    require(state.get("migrationCombinedWithUpgrade") is False, "migration/upgrade combined")
    require(state.get("foundationIncrement") == "v0.12.1", "state foundation phase drift")
    require(state.get("migrationIncrement") == "v0.12.2", "migration phase drift")
    controls = state.get("controls")
    require(isinstance(controls, dict), "missing backend controls")
    for key in ("versioning", "sseKms", "publicAccessBlocked", "tlsOnly", "s3NativeLockfile", "rootScopedIam", "partialBackendConfiguration"):
        require(controls.get(key) is True, f"required backend control disabled: {key}")
    for key in ("dynamoDbLocking", "sharedCliWorkspaces"):
        require(controls.get(key) is False, f"unsafe backend control enabled: {key}")
    if check_files:
        for path in expected_roots:
            require((root / path / "backend.tf").is_file(), f"missing current backend root: {path}")
        if successor_path.is_file():
            successor = load(successor_path)
            require(successor.get("version") == "v0.12.1", "invalid v0.12.1 successor")
            require(
                successor.get("predecessor", {}).get("contract")
                == "delivery/contracts/v0.12.0-production-readiness-foundation.json",
                "v0.12.1 predecessor drift",
            )
            require((root / state["plannedBootstrapRoot"]).is_dir(), "v0.12.1 bootstrap root missing")
        else:
            require(not (root / state["plannedBootstrapRoot"]).exists(), "v0.12.0 unexpectedly implements state bootstrap")

    release = value.get("releaseAndLifecycle")
    require(isinstance(release, dict), "missing release/lifecycle boundary")
    for key in ("buildOnce", "sameDigestAcrossEnvironments", "testPromotionPrPreparedAutomatically", "prodPromotionPrPreparedAutomatically", "pullRequestMergeIsHuman", "prodEnvironmentApprovalRequired"):
        require(release.get(key) is True, f"release control disabled: {key}")
    for key in ("automaticEnvironmentCreation", "automaticEnvironmentDestroy", "automaticProductionMerge", "automaticProductionRollback", "applicationLifecycleOwnsTerraform"):
        require(release.get(key) is False, f"unsafe lifecycle automation enabled: {key}")
    require(release.get("orderedEnvironments") == ["aws-dev", "aws-test", "aws-prod"], "environment order drift")
    require(release.get("absentEnvironmentStatus") == "waiting_environment", "absent environment status drift")
    require(release.get("maximumConcurrentDisposableEksEnvironments") == 1, "concurrent cost boundary drift")

    recovery = value.get("upgradeAndRecovery")
    require(isinstance(recovery, dict), "missing upgrade/recovery boundary")
    for key in ("compatibilityMatrixRequired", "deprecatedApiPreflightRequired", "eksOneMinorAtATime", "rollbackOrRebuildDecisionRequired", "cleanRoomUsesRemoteState", "rtoRpoApprovedBeforeLiveExercise", "rtoRpoMeasuredFromEvidence"):
        require(recovery.get(key) is True, f"recovery control disabled: {key}")
    require(recovery.get("databaseMajorUpgradeCombinedWithEksUpgrade") is False, "database and EKS upgrade combined")
    require(recovery.get("crossRegionActiveActiveRequired") is False, "cross-region scope creep")

    docs = value.get("documentationGovernance")
    require(isinstance(docs, dict), "missing documentation governance")
    require(docs.get("currentIndexRequired") is True, "current index disabled")
    require(docs.get("currentDocsMaintainedWithCapability") is True, "current docs not maintained")
    require(docs.get("archiveIsSupportedProcedure") is False, "archive made current")
    require(docs.get("archiveRewrittenForCurrentWording") is False, "archive rewrite required")

    ai = value.get("aiGovernance")
    require(isinstance(ai, dict), "missing AI governance")
    for key in ("humanUnderstandingAndReviewRequired", "normalCiAndSecurityGatesRequired", "sourceAndLicenseReviewRequired"):
        require(ai.get(key) is True, f"AI governance disabled: {key}")
    for key in ("credentialsAllowedInUnapprovedAi", "terraformStateAllowedInUnapprovedAi", "customerDataAllowedInUnapprovedAi", "privateEvidenceAllowedInUnapprovedAi"):
        require(ai.get(key) is False, f"sensitive AI input enabled: {key}")

    boundary = value.get("executionBoundary")
    require(isinstance(boundary, dict), "missing execution boundary")
    require(boundary.get("designAndOfflineValidationOnly") is True, "v0.12.0 is not offline-only")
    for key, enabled in boundary.items():
        if key != "designAndOfflineValidationOnly":
            require(enabled is False, f"live effect enabled: {key}")


contract = load(contract_path)
validate(contract)

mutations: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("remote backend claimed", lambda item: item["terraformState"].__setitem__("implementedBackendAtV0120", "s3")),
    ("missing root", lambda item: item["terraformState"]["implementedRoots"].pop()),
    ("DynamoDB locking added", lambda item: item["terraformState"]["controls"].__setitem__("dynamoDbLocking", True)),
    ("empty migration accepted", lambda item: item["terraformState"]["migrationInvariants"].remove("reviewed-nonempty-source-state")),
    ("migration and upgrade combined", lambda item: item["terraformState"].__setitem__("migrationCombinedWithUpgrade", True)),
    ("automatic environment creation", lambda item: item["releaseAndLifecycle"].__setitem__("automaticEnvironmentCreation", True)),
    ("automatic production merge", lambda item: item["releaseAndLifecycle"].__setitem__("automaticProductionMerge", True)),
    ("digest identity weakened", lambda item: item["releaseAndLifecycle"].__setitem__("sameDigestAcrossEnvironments", False)),
    ("archive made current", lambda item: item["documentationGovernance"].__setitem__("archiveIsSupportedProcedure", True)),
    ("state allowed in AI", lambda item: item["aiGovernance"].__setitem__("terraformStateAllowedInUnapprovedAi", True)),
    ("live AWS effect enabled", lambda item: item["executionBoundary"].__setitem__("awsAccessed", True)),
    ("future phase claims delivery", lambda item: item["increments"][1].__setitem__("status", "delivered")),
]
for label, mutate in mutations:
    candidate = deepcopy(contract)
    mutate(candidate)
    try:
        validate(candidate, check_files=False)
    except ContractError:
        continue
    raise ContractError(f"Unsafe mutation accepted: {label}")

roadmap = (root / "docs/ROADMAP.md").read_text()
start = roadmap.index("## v0.12 - Production Readiness Capstone")
end = roadmap.index("## v1.0 - Production-ready Commercial Baseline", start)
section = roadmap[start:end]
require("Status: In Progress" in section, "v0.12 roadmap status drift")
for version in expected_increments:
    require(version in section, f"roadmap missing {version}")
require("final integrated dev/test/prod commercial rehearsal remains v1.0 RC work" in section, "v1.0 rehearsal boundary missing")

orchestrator = load(root / "delivery/contracts/demo-api-orchestrator.json")
require(orchestrator["executionBoundary"]["automaticMerge"] is False, "orchestrator auto-merge drift")
require(orchestrator["executionBoundary"]["automaticEnvironmentCreation"] is False, "orchestrator auto-create drift")
require(orchestrator["productionBoundary"]["automaticPromotionPreparation"] is True, "prod PR preparation lost")
require(orchestrator["productionBoundary"]["environmentApprovalRequired"] is True, "prod approval lost")

state_doc = (root / "docs/TERRAFORM_STATE_MANAGEMENT.md").read_text()
for key in expected_keys:
    require(key in state_doc, f"state document missing key: {key}")
require(
    re.search(r"An empty destroyed environment is\s+not accepted as migration evidence", state_doc),
    "non-empty migration rule missing",
)

authority = (root / "docs/CURRENT_AUTHORITATIVE_SURFACE.md").read_text()
require("docs/archive/` is unsupported historical material" in authority, "archive authority drift")
require("v1.0 RC.1" in authority and "v1.0 RC.2" in authority, "RC review boundary missing")

ai_policy = (root / "docs/AI_ASSISTED_CONTRIBUTION_POLICY.md").read_text()
for phrase in ("Terraform state", "customer", "Human Accountability", "Source, License and Similarity Review"):
    require(phrase in ai_policy, f"AI policy missing: {phrase}")

checked_paths = [contract_path, *(root / path for path in contract["documents"].values())]
for path in checked_paths:
    text = path.read_text()
    require("/home/" not in text and "/tmp/" not in text, f"private path in {path.relative_to(root)}")
    require("arn:aws:" not in text and "AKIA" not in text, f"AWS identity in {path.relative_to(root)}")
    require(re.search(r"(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])", text) is None, f"account identity in {path.relative_to(root)}")

print("v0.12.0 production-readiness contract, 12 negative mutations, authority, AI and privacy gates passed.")
PYTHON

bash "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.7.7.20.1-roadmap-status-successor-repair.sh"
echo "v0.12.0 passed; its successor may implement the foundation, while state migration remains v0.12.2 work."

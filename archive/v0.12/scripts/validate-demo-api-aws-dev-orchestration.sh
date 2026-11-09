#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


root = Path(sys.argv[1])


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load(relative: str) -> dict[str, Any]:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"Expected object: {relative}")
    return value


def read(relative: str) -> str:
    path = root / relative
    require(path.is_file(), f"Missing file: {relative}")
    return path.read_text()


contract = load("delivery/contracts/demo-api-orchestrator.json")
snapshot_schema = load("delivery/contracts/orchestration-snapshot.schema.json")
decision_schema = load("delivery/contracts/orchestration-decision.schema.json")
bundle_schema = load("delivery/contracts/qualification-bundle.schema.json")
scope_contract = load("delivery/contracts/demo-api-qualification-scope.json")
test_scope_contract = load("delivery/contracts/demo-api-qualification-scope-aws-test.json")
workflow = read(contract["workflow"])
static_workflow = read(".github/workflows/demo-api-record-release-evidence.yaml")
runtime_workflow = read(".github/workflows/demo-api-runtime-qualification.yaml")
bundle_workflow = read(".github/workflows/demo-api-record-qualification-bundle.yaml")


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.10.7", "Bad orchestrator schema version")
    require(value.get("application") == "demo-api", "Unexpected orchestrator application")
    require(value.get("protectedRef") == "refs/heads/main", "Protected main boundary changed")
    require(value.get("operations") == ["start", "status", "resume", "retry"], "Operation set changed")
    events = value.get("eventModel", {})
    require(events.get("workflowDispatch") == ["start", "status", "resume", "retry"], "Manual operations changed")
    require(events.get("workflowRunChaining") is False, "workflow_run chaining is forbidden")
    require(events.get("pullRequestCode") is False, "PR code cannot enter orchestration")

    derivation = value.get("stateDerivation", {})
    require(derivation.get("stateIsRecomputed") is True, "State must be recomputed")
    require(derivation.get("mutableStateFile") is False, "Mutable current state is forbidden")
    require(derivation.get("releaseIdIsEnvironmentIndependent") is True, "Release ID boundary changed")
    require(derivation.get("qualificationScopes") == {
        "aws-dev": "delivery/contracts/demo-api-qualification-scope.json",
        "aws-test": "delivery/contracts/demo-api-qualification-scope-aws-test.json",
    }, "Scope contracts changed")
    for field in ("snapshotSchema", "decisionSchema", "attemptSchema", "failureRecoveryPolicy", "collector", "planner"):
        require(isinstance(derivation.get(field), str) and derivation[field], f"Missing {field}")
        if check_files:
            require((root / derivation[field]).is_file(), f"Missing orchestration file: {derivation[field]}")
    if check_files:
        for path in derivation["qualificationScopes"].values():
            require((root / path).is_file(), f"Missing orchestration scope: {path}")

    discovery = value.get("pullRequestDiscovery", {})
    require(discovery.get("mode") == "read-only", "PR discovery must remain read-only")
    require(discovery.get("baseBranch") == "main", "PR discovery must target main")
    require(discovery.get("reuseOpenPullRequest") is True, "Matching PR reuse is required")
    require(discovery.get("duplicatePreparationAllowed") is False, "Duplicate preparation forbidden")
    require(value["concurrency"] == {"scope": "application-and-release", "cancelInProgress": False}, "Concurrency boundary changed")

    stale = value.get("staleMain", {})
    require(stale.get("captureBeforeDerivation") is True, "main capture missing")
    require(stale.get("recheckAfterDerivation") is True, "main recheck missing")
    require(stale.get("recheckBeforeEveryMutation") is True, "Mutation stale-main guard missing")
    require(stale.get("onChange") == "blocked-resumable", "Stale main must remain resumable")

    boundary = value.get("executionBoundary", {})
    require(boundary.get("deriveRunner") == "github-hosted", "Derivation runner changed")
    require(boundary.get("derivePermissions") == ["contents-read", "pull-requests-read", "actions-read-for-explicit-retry-attempt"], "Derivation permissions widened")
    require(boundary.get("deriveAwsCredentials") == "none", "Derivation received AWS credentials")
    require(boundary.get("deriveClusterAccess") is False, "Derivation received EKS access")
    require(boundary.get("runtimeRunner") == "ephemeral-self-hosted", "Runtime runner changed")
    require(boundary.get("runtimeEnvironments") == ["aws-dev", "aws-test"], "Runtime environment scope changed")
    require(boundary.get("repositoryMutation") == "target-release-only-or-qualification-bundle-only-pr", "Repository mutation widened")
    require(boundary.get("automaticMerge") is False, "Automatic merge enabled")
    require(boundary.get("automaticEnvironmentCreation") is False, "Automatic environment creation enabled")

    execution = value.get("actionExecution", {})
    require(execution.get("mode") == "bounded-reviewed-promotion", "Unexpected execution mode")
    require(execution.get("dispatchReusableStages") is True, "Stage dispatch is not active")
    require(execution.get("authorizedActions") == ["qualify-aws-dev", "prepare-test-promotion", "qualify-aws-test", "prepare-prod-promotion"], "Authorized action set changed")
    require(execution.get("activationVariables") == {
        "qualify-aws-dev": "DEMO_API_AWS_DEV_QUALIFICATION_ENABLED",
        "prepare-test-promotion": "DEMO_API_AWS_TEST_PROMOTION_ENABLED",
        "qualify-aws-test": "DEMO_API_AWS_TEST_QUALIFICATION_ENABLED",
        "prepare-prod-promotion": "DEMO_API_AWS_PROD_PROMOTION_ENABLED",
    }, "Activation variables changed")
    require(execution.get("activationValue") == "true", "Activation value changed")
    require(execution.get("staticMode") == "artifact-only", "Static stage may create an intermediate PR")
    require(execution.get("sameRunArtifactsRequired") is True, "Cross-run artifacts were enabled")
    require(execution.get("sameAttemptArtifactsRequired") is True, "Cross-attempt artifacts were enabled")
    require(execution.get("statusDispatchAuthorized") is False, "status may dispatch a stage")

    recovery = value.get("failureRecovery", {})
    require(recovery.get("attemptArtifactRetentionDays") == 14, "Attempt retention changed")
    require(recovery.get("attemptIsPromotionEvidence") is False, "Attempt became Promotion evidence")
    require(recovery.get("retryRequiresExactPriorAttempt") is True, "Retry lineage is optional")
    require(recovery.get("automaticSupersededPullRequestClose") is False, "Superseded PRs may close automatically")
    require(recovery.get("minimumPromotionBundleRemainingSeconds") == 3600, "Bundle validity floor changed")
    require(recovery.get("rollbackDispatchAuthorized") is False, "Rollback dispatch was authorized")

    require(value.get("acceptanceInterruption") == {
        "input": "acceptance_interrupt_checkpoint",
        "armedValue": "armed",
        "defaultValue": "disabled",
        "allowedOperation": "resume",
        "requiredPolicy": "reviewed",
        "releaseIdRequired": True,
        "checkpoint": "post-runtime-pre-bundle",
        "maximumHoldSeconds": 540,
        "bundleCreationWhileArmed": False,
    }, "Acceptance interruption boundary changed")

    bundle = value.get("qualificationBundle", {})
    require(bundle.get("workflow") == ".github/workflows/demo-api-record-qualification-bundle.yaml", "Bundle workflow changed")
    require(bundle.get("schema") == "delivery/contracts/qualification-bundle.schema.json", "Bundle schema changed")
    require(bundle.get("scopes") == {
        "aws-dev": "delivery/contracts/demo-api-qualification-scope.json",
        "aws-test": "delivery/contracts/demo-api-qualification-scope-aws-test.json",
    }, "Bundle scopes changed")
    require(bundle.get("automaticMerge") is False, "Bundle PR may merge itself")
    require(bundle.get("legacyEvidenceAcceptedForAutomation") is False, "Legacy evidence entered automation")
    if check_files:
        for field in ("workflow", "schema"):
            require((root / bundle[field]).is_file(), f"Missing Bundle file: {bundle[field]}")
        for path in bundle["scopes"].values():
            require((root / path).is_file(), f"Missing Bundle scope: {path}")

    test_gate = value.get("testCanaryGate", {})
    require(test_gate.get("confirmation") == "reviewed-and-completed", "Test confirmation changed")
    require(test_gate.get("helper") == "scripts/complete-aws-test-rollout.sh", "Guarded helper changed")
    require(test_gate.get("runtimeMutationByAutomation") is False, "Automation gained Rollout mutation")
    require(test_gate.get("qualificationBeforeConfirmation") is False, "Test qualification can bypass review")

    prod_promotion = value.get("productionPromotion", {})
    require(prod_promotion.get("source") == "aws-test", "Production source changed")
    require(prod_promotion.get("target") == "aws-prod", "Production target changed")
    require(prod_promotion.get("qualificationMode") == "qualification-bundle", "Production Bundle gate missing")
    require(prod_promotion.get("sourceBundleRequired") is True, "Production source Bundle is optional")
    require(prod_promotion.get("environmentApprovalRequired") is True, "Production Environment approval missing")
    require(prod_promotion.get("releaseOnlyPullRequest") is True, "Production mutation is not release-only")
    require(prod_promotion.get("automaticMerge") is False, "Production PR may merge itself")
    require(prod_promotion.get("runtimeQualification") is False, "Production runtime qualification enabled")

    production = value.get("productionBoundary", {})
    require(production.get("environmentApprovalRequired") is True, "Production approval missing")
    require(production.get("reviewedPullRequestRequired") is True, "Production PR review missing")
    require(production.get("automaticPromotionPreparation") is True, "Production PR preparation is not active")
    for field in ("automaticMerge", "automaticRollback", "runtimeAccess"):
        require(production.get(field) is False, f"Production boundary enabled: {field}")


validate_contract(contract)
require(snapshot_schema["properties"]["schemaVersion"]["const"] == "v0.10.7", "Snapshot schema version changed")
require("qualificationBundles" in snapshot_schema["required"], "Snapshot omits Qualification Bundles")
require("testRolloutGate" in snapshot_schema["required"], "Snapshot omits the test Rollout gate")
require(decision_schema["properties"]["schemaVersion"]["const"] == "v0.10.7", "Decision schema version changed")
require(decision_schema["properties"]["executionMode"]["const"] == "bounded-reviewed-promotion", "Decision execution mode changed")
require(decision_schema["properties"]["dispatchAuthorized"]["type"] == "boolean", "Dispatch authorization is not explicit")
require("qualify-aws-dev" in decision_schema["properties"]["recommendedAction"]["enum"], "aws-dev action missing")
require(bundle_schema["properties"]["environment"]["enum"] == ["aws-dev", "aws-test"], "Bundle environment set changed")
require(bundle_schema["additionalProperties"] is False, "Bundle schema accepts unknown fields")
require(scope_contract["environment"] == "aws-dev", "Scope contract permits another environment")
require(test_scope_contract["environment"] == "aws-test", "Test scope contract changed")
require(all("evidence/" not in item and not item.startswith("docs/") for item in scope_contract["include"]), "Evidence or docs entered qualification scope")

require("\n  push:\n" in workflow and "\n  workflow_dispatch:\n" in workflow, "Orchestrator entrypoints changed")
require(not re.search(r"(?m)^  (pull_request|pull_request_target|workflow_run|schedule):", workflow), "Unsafe orchestrator trigger")
require("branches:\n      - main" in workflow, "Push is not protected-main only")
derive_block, action_block = workflow.split("\n  prepare-test-promotion:\n", 1)
require("runs-on: ubuntu-latest" in derive_block, "Derive job is not GitHub-hosted")
require(not re.search(r"(?i)configure-aws-credentials|\baws\s+eks\b|\bkubectl\b", derive_block), "Derive job gained AWS/EKS access")
require("DEMO_API_AWS_DEV_QUALIFICATION_ENABLED" in action_block, "Activation variable is not enforced")
require("DEMO_API_AWS_TEST_PROMOTION_ENABLED" in action_block, "Test Promotion variable is not enforced")
require("DEMO_API_AWS_TEST_QUALIFICATION_ENABLED" in action_block, "Test qualification variable is not enforced")
require("DEMO_API_AWS_PROD_PROMOTION_ENABLED" in action_block, "Prod Promotion variable is not enforced")
require("mode: artifact-only" in action_block, "Static stage is not artifact-only")
require("demo-api-runtime-qualification.yaml" in action_block, "Trusted runtime stage is not dispatched")
require("demo-api-record-qualification-bundle.yaml" in action_block, "Bundle stage is not dispatched")
require("acceptance_interrupt_checkpoint:" in workflow, "Deterministic interruption input is missing")
require("The acceptance interruption checkpoint requires a reviewed manual resume with an explicit release_id." in derive_block, "Armed checkpoint request is not narrowly validated")
for marker in ('"${GITHUB_EVENT_NAME}" != "workflow_dispatch"', '"${operation}" != "resume"', '"${policy}" != "reviewed"'):
    require(marker in derive_block, f"Armed checkpoint guard is missing: {marker}")
require("qualification-durability-checkpoint:" in action_block, "Post-runtime interruption checkpoint is missing")
require("needs.qualification-durability-checkpoint.outputs.permit-bundle == 'true'" in action_block, "Bundle creation can bypass the interruption checkpoint")
require("The armed interruption checkpoint was not cancelled within nine minutes." in action_block, "Armed checkpoint does not fail closed")
require(
    action_block.index("qualification-durability-checkpoint:")
    < action_block.index("record-qualification-bundle:"),
    "Interruption checkpoint appears after durable Bundle creation",
)
require("demo-api-promote-environment.yaml" in action_block, "Reviewed test Promotion stage is not dispatched")
require("uses: ./.github/workflows/demo-api-rollback.yaml" not in workflow, "v0.10.7 dispatches rollback")
require("gh pr merge" not in workflow and "--auto" not in workflow, "Orchestrator can merge a PR")

require("mode:" in static_workflow and "artifact-only" in static_workflow, "Static artifact mode missing")
require("expected_control_plane_sha:" in static_workflow, "Static stage is not control-plane bound")
require("same-run static result" in static_workflow.lower(), "Static artifact purpose is not explicit")
require("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in static_workflow, "Static artifact pin changed")
require("aws-prod" not in runtime_workflow, "Runtime workflow permits production")

require("\n  workflow_call:\n" in bundle_workflow, "Bundle workflow is not reusable")
require("\n  workflow_dispatch:\n" not in bundle_workflow, "Bundle workflow accepts arbitrary manual artifacts")
require("inputs.environment == 'aws-dev' || inputs.environment == 'aws-test'" in bundle_workflow, "Bundle target set changed")
require("actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131" in bundle_workflow, "Bundle download pin changed")
require("run-id:" not in bundle_workflow and "github-token:" not in bundle_workflow, "Bundle can download another run")
require("gh pr create" in bundle_workflow, "Bundle PR is not created")
require("gh pr merge" not in bundle_workflow and "--auto" not in bundle_workflow, "Bundle can merge itself")
require("demo-api-promote-environment" not in bundle_workflow, "Bundle workflow promotes an environment")
require("kubectl" not in bundle_workflow and "configure-aws-credentials" not in bundle_workflow, "Bundle writer gained AWS/EKS access")

mutations = [
    ("PR code", lambda c: c["eventModel"].__setitem__("pullRequestCode", True)),
    ("cross-run artifact", lambda c: c["actionExecution"].__setitem__("sameRunArtifactsRequired", False)),
    ("production Environment bypass", lambda c: c["productionPromotion"].__setitem__("environmentApprovalRequired", False)),
    ("production auto-merge", lambda c: c["productionPromotion"].__setitem__("automaticMerge", True)),
    ("runtime scope", lambda c: c["executionBoundary"]["runtimeEnvironments"].append("aws-prod")),
    ("automatic merge", lambda c: c["qualificationBundle"].__setitem__("automaticMerge", True)),
    ("production runtime", lambda c: c["productionBoundary"].__setitem__("runtimeAccess", True)),
    ("armed bundle creation", lambda c: c["acceptanceInterruption"].__setitem__("bundleCreationWhileArmed", True)),
    ("unbounded hold", lambda c: c["acceptanceInterruption"].__setitem__("maximumHoldSeconds", 0)),
]
for name, mutate in mutations:
    candidate = copy.deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValidationError:
        continue
    raise ValidationError(f"Unsafe orchestrator mutation was accepted: {name}")

spec = importlib.util.spec_from_file_location("demo_api_planner", root / "scripts/derive-demo-api-orchestration-plan.py")
require(spec is not None and spec.loader is not None, "Could not load planner")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def identity(source: str, digest_hex: str, run_id: str) -> dict[str, str]:
    return {
        "releaseId": f"demo-api-{source[:12]}-{digest_hex[:12]}",
        "sourceRepository": "SterlingAureum/startup-devops-baseline",
        "sourceCommit": source,
        "imageRepository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
        "imageTag": f"sha-{source[:7]}",
        "imageDigest": f"sha256:{digest_hex}",
        "buildWorkflowRunId": run_id,
    }


old = identity("a" * 40, "1" * 64, "100")
new = identity("b" * 40, "2" * 64, "200")


def fact(state: str = "missing") -> dict[str, Any]:
    if state == "missing":
        return {"state": "missing", "id": None, "ref": None, "sha256": None}
    return {"state": state, "id": "300-1", "ref": "evidence/fixture.json", "sha256": "9" * 64}


def bundle_fact(state: str = "missing") -> dict[str, Any]:
    return {
        "state": state,
        "reason": "not_found" if state == "missing" else "valid",
        "id": None if state == "missing" else "300-1",
        "ref": None if state == "missing" else "evidence/fixture.json",
        "sha256": None if state == "missing" else "9" * 64,
        "expiresAt": None if state == "missing" else "2026-08-13T00:00:00Z",
        "remainingSeconds": None if state == "missing" else 86400,
    }


def base() -> dict[str, Any]:
    return {
        "schemaVersion": "v0.10.7",
        "application": "demo-api",
        "operation": "resume",
        "policy": "reviewed",
        "trigger": {"eventName": "fixture", "ref": "refs/heads/main", "sourceCommit": None},
        "capturedMainRevision": "c" * 40,
        "observedMainRevision": "c" * 40,
        "requestedReleaseId": None,
        "retryAttempt": None,
        "testRolloutGate": "not-reviewed",
        "activeRelease": copy.deepcopy(new),
        "releaseOrderState": "current",
        "supersedingRelease": None,
        "releases": {
            environment: {
                "path": f"apps/demo-api/helm/values/releases/{environment}.yaml",
                "sha256": str(index) * 64,
                "identity": copy.deepcopy(old),
            }
            for index, environment in enumerate(("aws-dev", "aws-test", "aws-prod"), start=3)
        },
        "evidence": {
            environment: {"static": fact(), "runtime": fact()}
            for environment in ("aws-dev", "aws-test")
        },
        "qualificationBundles": {"aws-dev": bundle_fact(), "aws-test": bundle_fact()},
        "pullRequests": [],
        "environmentAvailability": {environment: "unknown" for environment in ("aws-dev", "aws-test", "aws-prod")},
        "derivedAt": "2026-08-12T00:00:00Z",
    }


def pr(number: int, environment: str, kind: str = "environment-release") -> dict[str, Any]:
    return {
        "number": number,
        "url": f"https://github.com/example/repo/pull/{number}",
        "kind": kind,
        "targetEnvironment": environment,
        "releaseId": new["releaseId"],
        "releaseSha256": "3" * 64 if environment == "aws-dev" else "4" * 64,
        "headRefName": f"fixture/{number}",
        "baseRefName": "main",
    }


cases: list[tuple[str, dict[str, Any], tuple[str, str, str, bool]]] = []
value = base()
value["operation"] = "start"
value["trigger"]["sourceCommit"] = "b" * 40
value["activeRelease"] = None
cases.append(("source start", value, ("source", "progressing", "publish-image-and-prepare-dev", False)))

value = base()
value["pullRequests"] = [pr(10, "aws-dev")]
cases.append(("dev release review", value, ("dev-release", "waiting_review", "wait-for-review", False)))

value = base()
value["releases"]["aws-dev"]["identity"] = copy.deepcopy(new)
cases.append(("dev qualification dispatch", value, ("dev-qualification", "progressing", "qualify-aws-dev", True)))

value = copy.deepcopy(value)
value["pullRequests"] = [pr(11, "aws-dev", "qualification-bundle")]
cases.append(("bundle review", value, ("dev-qualification", "waiting_review", "wait-for-review", False)))

value = copy.deepcopy(value)
value["pullRequests"] = []
value["qualificationBundles"]["aws-dev"] = bundle_fact("fresh")
cases.append(("test boundary", value, ("test-release", "progressing", "prepare-test-promotion", True)))

value = copy.deepcopy(value)
value["operation"] = "status"
cases.append(("strict read-only status", value, ("test-release", "progressing", "prepare-test-promotion", False)))

value = base()
value["observedMainRevision"] = "d" * 40
cases.append(("stale main", value, ("image", "blocked", "retry-after-main-stabilizes", False)))

value = base()
for environment in ("aws-dev", "aws-test", "aws-prod"):
    value["releases"][environment]["identity"] = copy.deepcopy(new)
cases.append(("complete", value, ("complete", "completed", "none", False)))

for name, snapshot, expected in cases:
    result = planner.derive(snapshot)
    actual = (result["phase"], result["status"], result["recommendedAction"], result["dispatchAuthorized"])
    require(actual == expected, f"{name}: expected {expected}, got {actual}")
    require(result["executionMode"] == "bounded-reviewed-promotion", f"{name}: bad execution mode")

duplicate = base()
duplicate["releases"]["aws-dev"]["identity"] = copy.deepcopy(new)
duplicate["pullRequests"] = [pr(20, "aws-dev", "qualification-bundle"), pr(21, "aws-dev", "qualification-bundle")]
try:
    planner.derive(duplicate)
except SystemExit:
    pass
else:
    raise ValidationError("Duplicate Qualification Bundle PRs were accepted")

print("Automated aws-dev qualification and dev-to-test boundary contracts passed.")
PY

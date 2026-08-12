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
workflow = read(contract["workflow"])
static_workflow = read(".github/workflows/demo-api-record-release-evidence.yaml")
runtime_workflow = read(".github/workflows/demo-api-runtime-qualification.yaml")
bundle_workflow = read(".github/workflows/demo-api-record-qualification-bundle.yaml")


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.10.4", "Bad orchestrator schema version")
    require(value.get("application") == "demo-api", "Unexpected orchestrator application")
    require(value.get("protectedRef") == "refs/heads/main", "Protected main boundary changed")
    require(value.get("operations") == ["start", "status", "resume"], "Operation set changed")
    events = value.get("eventModel", {})
    require(events.get("workflowDispatch") == ["start", "status", "resume"], "Manual operations changed")
    require(events.get("workflowRunChaining") is False, "workflow_run chaining is forbidden")
    require(events.get("pullRequestCode") is False, "PR code cannot enter orchestration")

    derivation = value.get("stateDerivation", {})
    require(derivation.get("stateIsRecomputed") is True, "State must be recomputed")
    require(derivation.get("mutableStateFile") is False, "Mutable current state is forbidden")
    require(derivation.get("releaseIdIsEnvironmentIndependent") is True, "Release ID boundary changed")
    require(derivation.get("qualificationScope") == "delivery/contracts/demo-api-qualification-scope.json", "Scope contract changed")
    for field in ("snapshotSchema", "decisionSchema", "collector", "planner", "qualificationScope"):
        require(isinstance(derivation.get(field), str) and derivation[field], f"Missing {field}")
        if check_files:
            require((root / derivation[field]).is_file(), f"Missing orchestration file: {derivation[field]}")

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
    require(boundary.get("derivePermissions") == ["contents-read", "pull-requests-read"], "Derivation permissions widened")
    require(boundary.get("deriveAwsCredentials") == "none", "Derivation received AWS credentials")
    require(boundary.get("deriveClusterAccess") is False, "Derivation received EKS access")
    require(boundary.get("runtimeRunner") == "ephemeral-self-hosted", "Runtime runner changed")
    require(boundary.get("runtimeEnvironments") == ["aws-dev"], "v0.10.4 runtime scope widened")
    require(boundary.get("repositoryMutation") == "qualification-bundle-only-pr", "Repository mutation widened")
    require(boundary.get("automaticMerge") is False, "Automatic merge enabled")
    require(boundary.get("automaticEnvironmentCreation") is False, "Automatic environment creation enabled")

    execution = value.get("actionExecution", {})
    require(execution.get("mode") == "bounded-aws-dev-qualification", "Unexpected execution mode")
    require(execution.get("dispatchReusableStages") is True, "aws-dev stage dispatch is not active")
    require(execution.get("authorizedActions") == ["qualify-aws-dev"], "Authorized action set widened")
    require(execution.get("activationVariable") == "DEMO_API_AWS_DEV_QUALIFICATION_ENABLED", "Activation variable changed")
    require(execution.get("activationValue") == "true", "Activation value changed")
    require(execution.get("staticMode") == "artifact-only", "Static stage may create an intermediate PR")
    require(execution.get("sameRunArtifactsRequired") is True, "Cross-run artifacts were enabled")

    bundle = value.get("qualificationBundle", {})
    require(bundle.get("workflow") == ".github/workflows/demo-api-record-qualification-bundle.yaml", "Bundle workflow changed")
    require(bundle.get("schema") == "delivery/contracts/qualification-bundle.schema.json", "Bundle schema changed")
    require(bundle.get("scope") == "delivery/contracts/demo-api-qualification-scope.json", "Bundle scope changed")
    require(bundle.get("automaticMerge") is False, "Bundle PR may merge itself")
    require(bundle.get("legacyEvidenceAcceptedForAwsDevAutomation") is False, "Legacy evidence entered aws-dev automation")
    if check_files:
        for field in ("workflow", "schema", "scope"):
            require((root / bundle[field]).is_file(), f"Missing Bundle file: {bundle[field]}")

    production = value.get("productionBoundary", {})
    require(production.get("environmentApprovalRequired") is True, "Production approval missing")
    require(production.get("reviewedPullRequestRequired") is True, "Production PR review missing")
    for field in ("automaticMerge", "automaticRollback", "automaticPromotion", "runtimeAccess"):
        require(production.get(field) is False, f"Production boundary enabled: {field}")


validate_contract(contract)
require(snapshot_schema["properties"]["schemaVersion"]["const"] == "v0.10.4", "Snapshot schema version changed")
require("qualificationBundles" in snapshot_schema["required"], "Snapshot omits Qualification Bundles")
require(decision_schema["properties"]["schemaVersion"]["const"] == "v0.10.4", "Decision schema version changed")
require(decision_schema["properties"]["executionMode"]["const"] == "aws-dev-qualification", "Decision execution mode changed")
require(decision_schema["properties"]["dispatchAuthorized"]["type"] == "boolean", "Dispatch authorization is not explicit")
require("qualify-aws-dev" in decision_schema["properties"]["recommendedAction"]["enum"], "aws-dev action missing")
require(bundle_schema["properties"]["environment"]["const"] == "aws-dev", "Bundle schema permits another environment")
require(bundle_schema["additionalProperties"] is False, "Bundle schema accepts unknown fields")
require(scope_contract["environment"] == "aws-dev", "Scope contract permits another environment")
require(all("evidence/" not in item and not item.startswith("docs/") for item in scope_contract["include"]), "Evidence or docs entered qualification scope")

require("\n  push:\n" in workflow and "\n  workflow_dispatch:\n" in workflow, "Orchestrator entrypoints changed")
require(not re.search(r"(?m)^  (pull_request|pull_request_target|workflow_run|schedule):", workflow), "Unsafe orchestrator trigger")
require("branches:\n      - main" in workflow, "Push is not protected-main only")
derive_block, action_block = workflow.split("\n  static-qualification:\n", 1)
require("runs-on: ubuntu-latest" in derive_block, "Derive job is not GitHub-hosted")
require(not re.search(r"(?i)configure-aws-credentials|\baws\s+eks\b|\bkubectl\b", derive_block), "Derive job gained AWS/EKS access")
require("DEMO_API_AWS_DEV_QUALIFICATION_ENABLED" in action_block, "Activation variable is not enforced")
require("mode: artifact-only" in action_block, "Static stage is not artifact-only")
require("demo-api-runtime-qualification.yaml" in action_block, "Trusted runtime stage is not dispatched")
require("demo-api-record-qualification-bundle.yaml" in action_block, "Bundle stage is not dispatched")
require("demo-api-promote-environment.yaml" not in workflow, "v0.10.4 dispatches Promotion")
require("demo-api-rollback.yaml" not in workflow, "v0.10.4 dispatches rollback")
require("gh pr merge" not in workflow and "--auto" not in workflow, "Orchestrator can merge a PR")

require("mode:" in static_workflow and "artifact-only" in static_workflow, "Static artifact mode missing")
require("expected_control_plane_sha:" in static_workflow, "Static stage is not control-plane bound")
require("same-run static result" in static_workflow.lower(), "Static artifact purpose is not explicit")
require("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in static_workflow, "Static artifact pin changed")
require("aws-prod" not in runtime_workflow, "Runtime workflow permits production")

require("\n  workflow_call:\n" in bundle_workflow, "Bundle workflow is not reusable")
require("\n  workflow_dispatch:\n" not in bundle_workflow, "Bundle workflow accepts arbitrary manual artifacts")
require("if: inputs.environment == 'aws-dev'" in bundle_workflow, "Bundle target is not exact aws-dev")
require("actions/download-artifact@37930b1c2abaa49bbe596cd826c3c89aef350131" in bundle_workflow, "Bundle download pin changed")
require("run-id:" not in bundle_workflow and "github-token:" not in bundle_workflow, "Bundle can download another run")
require("gh pr create" in bundle_workflow, "Bundle PR is not created")
require("gh pr merge" not in bundle_workflow and "--auto" not in bundle_workflow, "Bundle can merge itself")
require("demo-api-promote-environment" not in bundle_workflow, "Bundle workflow promotes an environment")
require("kubectl" not in bundle_workflow and "configure-aws-credentials" not in bundle_workflow, "Bundle writer gained AWS/EKS access")

mutations = [
    ("PR code", lambda c: c["eventModel"].__setitem__("pullRequestCode", True)),
    ("cross-run artifact", lambda c: c["actionExecution"].__setitem__("sameRunArtifactsRequired", False)),
    ("test dispatch", lambda c: c["actionExecution"]["authorizedActions"].append("prepare-test-promotion")),
    ("runtime scope", lambda c: c["executionBoundary"]["runtimeEnvironments"].append("aws-test")),
    ("automatic merge", lambda c: c["qualificationBundle"].__setitem__("automaticMerge", True)),
    ("production runtime", lambda c: c["productionBoundary"].__setitem__("runtimeAccess", True)),
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


def base() -> dict[str, Any]:
    return {
        "schemaVersion": "v0.10.4",
        "application": "demo-api",
        "operation": "resume",
        "policy": "reviewed",
        "trigger": {"eventName": "fixture", "ref": "refs/heads/main", "sourceCommit": None},
        "capturedMainRevision": "c" * 40,
        "observedMainRevision": "c" * 40,
        "requestedReleaseId": None,
        "activeRelease": copy.deepcopy(new),
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
        "qualificationBundles": {"aws-dev": fact()},
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
value["qualificationBundles"]["aws-dev"] = fact("fresh")
cases.append(("test boundary", value, ("test-release", "progressing", "prepare-test-promotion", False)))

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
    require(result["executionMode"] == "aws-dev-qualification", f"{name}: bad execution mode")

duplicate = base()
duplicate["releases"]["aws-dev"]["identity"] = copy.deepcopy(new)
duplicate["pullRequests"] = [pr(20, "aws-dev", "qualification-bundle"), pr(21, "aws-dev", "qualification-bundle")]
try:
    planner.derive(duplicate)
except SystemExit:
    pass
else:
    raise ValidationError("Duplicate Qualification Bundle PRs were accepted")

print("Automated aws-dev qualification orchestration contracts passed.")
PY

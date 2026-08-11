#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

printf '[]\n' > "${WORK_DIR}/open-prs.json"

"${ROOT_DIR}/scripts/collect-demo-api-orchestration-snapshot.py" \
  --root "${ROOT_DIR}" \
  --operation status \
  --policy reviewed \
  --event-name fixture \
  --ref refs/heads/main \
  --captured-main-revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --observed-main-revision aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --repository SterlingAureum/startup-devops-baseline \
  --open-prs-json "${WORK_DIR}/open-prs.json" \
  --now 2026-08-11T00:00:00Z \
  --output "${WORK_DIR}/snapshot.json" >/dev/null

"${ROOT_DIR}/scripts/derive-demo-api-orchestration-plan.py" \
  --snapshot "${WORK_DIR}/snapshot.json" \
  --output "${WORK_DIR}/decision.json" >/dev/null

python3 - "${ROOT_DIR}" "${WORK_DIR}" <<'PY'
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


root = Path(sys.argv[1])
work = Path(sys.argv[2])


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"Expected object: {path}")
    return value


contract = load(root / "delivery/contracts/demo-api-orchestrator.json")
snapshot_schema = load(root / "delivery/contracts/orchestration-snapshot.schema.json")
decision_schema = load(root / "delivery/contracts/orchestration-decision.schema.json")
workflow_path = root / contract["workflow"]
workflow = workflow_path.read_text()


def validate_contract(value: dict[str, Any], check_files: bool = True) -> None:
    require(value.get("schemaVersion") == "v0.10.2", "Bad orchestrator schema version")
    require(value.get("application") == "demo-api", "Unexpected orchestrator application")
    require(value.get("protectedRef") == "refs/heads/main", "Protected main boundary changed")
    require(value.get("operations") == ["start", "status", "resume"], "Operation set changed")

    events = value.get("eventModel", {})
    require(events.get("workflowDispatch") == ["start", "status", "resume"], "Manual operation set changed")
    require(events.get("workflowRunChaining") is False, "workflow_run chaining is forbidden")
    require(events.get("pullRequestCode") is False, "PR code cannot enter orchestration")

    derivation = value.get("stateDerivation", {})
    require(derivation.get("stateIsRecomputed") is True, "State must be recomputed")
    require(derivation.get("mutableStateFile") is False, "Mutable current state is forbidden")
    require(derivation.get("releaseIdIsEnvironmentIndependent") is True, "Release ID boundary changed")
    for field in ("snapshotSchema", "decisionSchema", "collector", "planner"):
        require(isinstance(derivation.get(field), str) and derivation[field], f"Missing {field}")
        if check_files:
            require((root / derivation[field]).is_file(), f"Missing orchestration file: {derivation[field]}")

    discovery = value.get("pullRequestDiscovery", {})
    require(discovery.get("mode") == "read-only", "PR discovery must remain read-only")
    require(discovery.get("baseBranch") == "main", "PR discovery must target main")
    require(discovery.get("reuseOpenPullRequest") is True, "Open PR reuse is required")
    require(discovery.get("duplicatePreparationAllowed") is False, "Duplicate PR preparation forbidden")

    concurrency = value.get("concurrency", {})
    require(concurrency.get("scope") == "application-and-release", "Bad concurrency scope")
    require(concurrency.get("cancelInProgress") is False, "Release runs cannot cancel each other")

    stale = value.get("staleMain", {})
    require(stale.get("captureBeforeDerivation") is True, "main capture missing")
    require(stale.get("recheckAfterDerivation") is True, "main recheck missing")
    require(stale.get("onChange") == "blocked-resumable", "Stale main must be resumable")

    boundary = value.get("executionBoundary", {})
    require(boundary.get("runner") == "github-hosted", "Unexpected runner boundary")
    require(boundary.get("permissions") == ["contents-read", "pull-requests-read"], "Unexpected permissions")
    require(boundary.get("awsCredentials") == "none", "AWS credentials forbidden")
    for field in ("clusterAccess", "repositoryMutation", "automaticMerge", "automaticEnvironmentCreation"):
        require(boundary.get(field) is False, f"Unsafe execution boundary: {field}")

    execution = value.get("actionExecution", {})
    require(execution.get("mode") == "plan-only", "Stage execution activated too early")
    require(execution.get("dispatchReusableStages") is False, "Reusable stage dispatch must remain off")
    require(execution.get("deferredActivation") == {
        "trustedRuntime": "v0.10.3",
        "awsDev": "v0.10.4",
        "awsTest": "v0.10.5",
        "awsProd": "v0.10.6",
    }, "Deferred activation map changed")

    production = value.get("productionBoundary", {})
    require(production.get("environmentApprovalRequired") is True, "Production approval missing")
    require(production.get("reviewedPullRequestRequired") is True, "Production PR review missing")
    require(production.get("automaticMerge") is False, "Production auto-merge forbidden")
    require(production.get("automaticRollback") is False, "Production automatic rollback forbidden")


validate_contract(contract)
require(snapshot_schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "Bad snapshot schema draft")
require(decision_schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", "Bad decision schema draft")
require(snapshot_schema.get("additionalProperties") is False, "Snapshot must reject extra fields")
require(decision_schema.get("additionalProperties") is False, "Decision must reject extra fields")
require(decision_schema["properties"]["executionMode"].get("const") == "plan-only", "Decision can execute")
require(decision_schema["properties"]["dispatchAuthorized"].get("const") is False, "Decision can authorize dispatch")

require(workflow_path.is_file(), "Orchestrator workflow is missing")
require("\n  push:\n" in workflow, "main push event is missing")
require("\n  workflow_dispatch:\n" in workflow, "manual operations are missing")
require(not re.search(r"(?m)^  (pull_request|workflow_run|schedule):", workflow), "Unsafe workflow trigger")
require("branches:\n      - main" in workflow, "Push trigger is not restricted to main")
for operation in ("start", "status", "resume"):
    require(f"          - {operation}" in workflow, f"Missing operation: {operation}")
require("contents: read" in workflow and "pull-requests: read" in workflow, "Read permissions missing")
require(not re.search(r"(?m)^\s+(contents|pull-requests|packages|id-token): write\s*$", workflow), "Write permission added")
require("cancel-in-progress: false" in workflow, "Concurrency cancellation must remain disabled")
require("gh pr create" not in workflow and "gh pr merge" not in workflow and "--auto" not in workflow, "PR mutation added")
require(not re.search(r"(?i)configure-aws-credentials|\baws\s+eks\b|\bkubectl\b", workflow), "AWS/EKS access added")
require("demo-api-image-publish.yaml" not in workflow, "Image stage dispatch activated early")
require("demo-api-promote-environment.yaml" not in workflow, "Promotion stage dispatch activated early")
require("git/ref/heads/main" in workflow, "Protected main is not rechecked")
require("runtime-executor" not in workflow, "Runtime executor entered hosted workflow")

mutations = [
    ("PR code", lambda c: c["eventModel"].__setitem__("pullRequestCode", True)),
    ("workflow run chaining", lambda c: c["eventModel"].__setitem__("workflowRunChaining", True)),
    ("mutable state", lambda c: c["stateDerivation"].__setitem__("mutableStateFile", True)),
    ("PR mutation", lambda c: c["pullRequestDiscovery"].__setitem__("mode", "write")),
    ("duplicate PR", lambda c: c["pullRequestDiscovery"].__setitem__("duplicatePreparationAllowed", True)),
    ("cancel release", lambda c: c["concurrency"].__setitem__("cancelInProgress", True)),
    ("stale main ignored", lambda c: c["staleMain"].__setitem__("recheckAfterDerivation", False)),
    ("AWS credentials", lambda c: c["executionBoundary"].__setitem__("awsCredentials", "oidc")),
    ("cluster access", lambda c: c["executionBoundary"].__setitem__("clusterAccess", True)),
    ("stage dispatch", lambda c: c["actionExecution"].__setitem__("dispatchReusableStages", True)),
    ("production auto merge", lambda c: c["productionBoundary"].__setitem__("automaticMerge", True)),
]
for name, mutate in mutations:
    candidate = copy.deepcopy(contract)
    mutate(candidate)
    try:
        validate_contract(candidate, check_files=False)
    except ValidationError:
        continue
    raise ValidationError(f"Unsafe orchestrator mutation was accepted: {name}")

spec = importlib.util.spec_from_file_location(
    "demo_api_planner", root / "scripts/derive-demo-api-orchestration-plan.py"
)
require(spec is not None and spec.loader is not None, "Could not load planner")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def identity(source: str, digest: str, run_id: str) -> dict[str, str]:
    return {
        "releaseId": f"demo-api-{source[:12]}-{digest[:12]}",
        "sourceRepository": "SterlingAureum/startup-devops-baseline",
        "sourceCommit": source,
        "imageRepository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
        "imageTag": f"sha-{source[:7]}",
        "imageDigest": f"sha256:{digest}",
        "buildWorkflowRunId": run_id,
    }


old = identity("a" * 40, "1" * 64, "100")
new = identity("b" * 40, "2" * 64, "200")

pr_release_text = f'''image:
  repository: ghcr.io/sterlingaureum/startup-devops-baseline/demo-api
  tag: "{new["imageTag"]}"
  digest: "{new["imageDigest"]}"

release:
  applicationVersion: "{new["imageTag"]}"

delivery:
  sourceRepository: "{new["sourceRepository"]}"
  sourceCommit: "{new["sourceCommit"]}"
  workflowRunId: "{new["buildWorkflowRunId"]}"
'''
pr_fixture = [
    {
        "number": 99,
        "url": "https://github.com/example/repo/pull/99",
        "title": "release: fixture title is not trusted",
        "headRefName": "arbitrary-head-name",
        "headRefOid": "f" * 40,
        "baseRefName": "main",
        "totalFiles": 1,
        "files": [
            {
                "path": "apps/demo-api/helm/values/releases/aws-dev.yaml",
                "content": pr_release_text,
            }
        ],
    }
]
pr_fixture_path = work / "classified-prs.json"
pr_fixture_path.write_text(json.dumps(pr_fixture))
collected_pr_snapshot = work / "classified-pr-snapshot.json"
collected_pr_decision = work / "classified-pr-decision.json"
subprocess.run(
    [
        sys.executable,
        str(root / "scripts/collect-demo-api-orchestration-snapshot.py"),
        "--root", str(root),
        "--operation", "resume",
        "--policy", "reviewed",
        "--event-name", "fixture",
        "--ref", "refs/heads/main",
        "--captured-main-revision", "c" * 40,
        "--observed-main-revision", "c" * 40,
        "--repository", "SterlingAureum/startup-devops-baseline",
        "--open-prs-json", str(pr_fixture_path),
        "--now", "2026-08-11T00:00:00Z",
        "--output", str(collected_pr_snapshot),
    ],
    check=True,
    stdout=subprocess.DEVNULL,
)
subprocess.run(
    [
        sys.executable,
        str(root / "scripts/derive-demo-api-orchestration-plan.py"),
        "--snapshot", str(collected_pr_snapshot),
        "--output", str(collected_pr_decision),
    ],
    check=True,
    stdout=subprocess.DEVNULL,
)
classified_decision = load(collected_pr_decision)
require(
    (
        classified_decision["phase"],
        classified_decision["status"],
        classified_decision["openPullRequest"]["number"],
    )
    == ("dev-release", "waiting_review", 99),
    "Collector did not derive the exact release identity from PR file content",
)


def missing() -> dict[str, Any]:
    return {"state": "missing", "id": None, "ref": None, "sha256": None}


def fresh(kind: str, environment: str) -> dict[str, Any]:
    return {
        "state": "fresh",
        "id": "300" if kind == "static" else "20260811000000",
        "ref": f"evidence/demo-api/{'' if kind == 'static' else 'runtime/'}{environment}/record.json",
        "sha256": "9" * 64,
    }


def base() -> dict[str, Any]:
    return {
        "schemaVersion": "v0.10.2",
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
            environment: {"static": missing(), "runtime": missing()}
            for environment in ("aws-dev", "aws-test")
        },
        "pullRequests": [],
        "environmentAvailability": {environment: "unknown" for environment in ("aws-dev", "aws-test", "aws-prod")},
        "derivedAt": "2026-08-11T00:00:00Z",
    }


def pr(number: int, environment: str, kind: str = "environment-release") -> dict[str, Any]:
    return {
        "number": number,
        "url": f"https://github.com/example/repo/pull/{number}",
        "kind": kind,
        "targetEnvironment": environment,
        "releaseId": new["releaseId"],
        "releaseSha256": "3" * 64 if environment == "aws-dev" else ("4" * 64 if environment == "aws-test" else "5" * 64),
        "headRefName": f"release/{new['releaseId']}-{environment}",
        "baseRefName": "main",
    }


cases: list[tuple[str, dict[str, Any], tuple[str, str, str]]] = []
value = base()
value["operation"] = "start"
value["trigger"]["sourceCommit"] = "b" * 40
value["activeRelease"] = None
cases.append(("source start", value, ("source", "progressing", "publish-image-and-prepare-dev")))

value = base()
value["pullRequests"] = [pr(10, "aws-dev")]
cases.append(("dev PR review", value, ("dev-release", "waiting_review", "wait-for-review")))

value = base()
value["releases"]["aws-dev"]["identity"] = copy.deepcopy(new)
cases.append(("dev runtime wait", value, ("dev-qualification", "waiting_runtime", "collect-runtime-evidence")))

value = copy.deepcopy(value)
value["evidence"]["aws-dev"]["runtime"] = fresh("runtime", "aws-dev")
cases.append(("dev static qualification", value, ("dev-qualification", "progressing", "record-static-evidence")))

value = copy.deepcopy(value)
value["evidence"]["aws-dev"]["static"] = fresh("static", "aws-dev")
cases.append(("test promotion ready", value, ("test-release", "progressing", "prepare-test-promotion")))

value = copy.deepcopy(value)
value["pullRequests"] = [pr(11, "aws-test")]
cases.append(("test PR review", value, ("test-release", "waiting_review", "wait-for-review")))

value = base()
value["releases"]["aws-dev"]["identity"] = copy.deepcopy(new)
value["releases"]["aws-test"]["identity"] = copy.deepcopy(new)
value["environmentAvailability"]["aws-test"] = "absent"
cases.append(("test environment absent", value, ("test-qualification", "waiting_environment", "restore-environment")))

value = copy.deepcopy(value)
value["environmentAvailability"]["aws-test"] = "unknown"
value["evidence"]["aws-test"] = {
    "static": fresh("static", "aws-test"),
    "runtime": fresh("runtime", "aws-test"),
}
cases.append(("production approval", value, ("prod-approval", "waiting_review", "prepare-prod-promotion")))

value = copy.deepcopy(value)
value["pullRequests"] = [pr(12, "aws-prod")]
cases.append(("prod PR review", value, ("prod-release", "waiting_review", "wait-for-review")))

value = base()
for environment in ("aws-dev", "aws-test", "aws-prod"):
    value["releases"][environment]["identity"] = copy.deepcopy(new)
cases.append(("complete", value, ("complete", "completed", "none")))

value = base()
value["observedMainRevision"] = "d" * 40
cases.append(("stale main", value, ("image", "blocked", "retry-after-main-stabilizes")))

for name, snapshot, expected in cases:
    result = planner.derive(snapshot)
    actual = (result["phase"], result["status"], result["recommendedAction"])
    require(actual == expected, f"{name}: expected {expected}, got {actual}")
    require(result["executionMode"] == "plan-only", f"{name}: execution mode changed")
    require(result["dispatchAuthorized"] is False, f"{name}: stage dispatch authorized")

duplicate = base()
duplicate["pullRequests"] = [pr(20, "aws-dev"), pr(21, "aws-dev")]
try:
    planner.derive(duplicate)
except SystemExit:
    pass
else:
    raise ValidationError("Duplicate open release PRs were accepted")

collected = load(work / "decision.json")
require(collected["phase"] == "complete" and collected["status"] == "completed", "Repository snapshot did not derive complete")
require(collected["dispatchAuthorized"] is False, "Repository snapshot authorized dispatch")

print("Event-driven demo-api orchestration contracts and behavior tests passed.")
PY

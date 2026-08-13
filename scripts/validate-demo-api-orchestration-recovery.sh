#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

for command in git jq python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

python3 - "${ROOT_DIR}" "${WORK_DIR}" <<'PY'
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
work = Path(sys.argv[2])
sys.path.insert(0, str(root / "scripts"))
from demo_api_orchestration_attempt import validate as validate_attempt


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


policy = json.loads((root / "delivery/contracts/demo-api-failure-recovery-policy.json").read_text())
require(policy["operations"]["status"]["mutationAllowed"] is False, "status mutation policy changed")
require(policy["operations"]["retry"]["priorAttemptRequired"] is True, "retry lineage is optional")
require(policy["automaticPullRequestClose"] is False, "Superseded PR auto-close enabled")
require(policy["releasePullRequestCurrentnessCheck"]["requiredByBranchProtection"] is True, "Supersede PR check is not required")
require(policy["automaticRollback"] is False, "Automatic rollback enabled")
require(policy["productionRuntimeQualification"] is False, "Production runtime enabled")

decision = {
    "schemaVersion": "v0.10.7",
    "application": "demo-api",
    "operation": "resume",
    "releaseId": f"demo-api-{'b' * 12}-{'2' * 12}",
    "phase": "dev-qualification",
    "status": "progressing",
    "reason": "qualification-missing",
    "recommendedAction": "qualify-aws-dev",
    "targetEnvironment": "aws-dev",
    "openPullRequest": None,
    "supersededByReleaseId": None,
    "executionMode": "bounded-reviewed-promotion",
    "dispatchAuthorized": True,
    "capturedMainRevision": "c" * 40,
    "observedMainRevision": "c" * 40,
    "derivedAt": "2026-08-12T00:00:00Z",
}
decision_file = work / "decision.json"
decision_file.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
stages = {
    "testPromotion": {"result": "skipped", "status": "", "reason": "", "url": ""},
    "prodPromotion": {"result": "skipped", "status": "", "reason": "", "url": ""},
    "static": {"result": "success", "status": "qualified", "reason": "", "url": ""},
    "runtime": {"result": "success", "status": "blocked", "reason": "endpoint_unreachable", "url": ""},
    "bundle": {"result": "skipped", "status": "", "reason": "", "url": ""},
    "disabled": {"testPromotion": "skipped", "prodPromotion": "skipped", "qualification": "skipped"},
}
stages_file = work / "stages.json"
stages_file.write_text(json.dumps(stages, indent=2, sort_keys=True) + "\n")
attempt_file = work / "attempt.json"
run(
    sys.executable, str(root / "scripts/write-demo-api-orchestration-attempt.py"),
    "--decision", str(decision_file),
    "--stage-results", str(stages_file),
    "--operation", "resume",
    "--control-plane-sha", "c" * 40,
    "--repository", "SterlingAureum/startup-devops-baseline",
    "--run-id", "700",
    "--run-attempt", "1",
    "--actor", "SterlingAureum",
    "--run-url", "https://github.com/SterlingAureum/startup-devops-baseline/actions/runs/700",
    "--started-at", "2026-08-12T00:00:00Z",
    "--completed-at", "2026-08-12T00:05:00Z",
    "--output", str(attempt_file),
)
attempt = json.loads(attempt_file.read_text())
require(attempt["execution"]["outcome"] == "blocked", "Blocked runtime Attempt was not preserved")
require(attempt["execution"]["retryClass"] == "safe-new-attempt", "Transient runtime is not retryable")

unsafe = copy.deepcopy(attempt)
unsafe["operation"] = "status"
unsafe["decision"]["dispatchAuthorized"] = True
unsafe["retryOf"] = None
try:
    validate_attempt(unsafe)
except ValueError:
    pass
else:
    raise SystemExit("A mutating status Attempt was accepted")

spec = importlib.util.spec_from_file_location("planner", root / "scripts/derive-demo-api-orchestration-plan.py")
require(spec is not None and spec.loader is not None, "Could not load planner")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def identity(source, digest, run_id):
    return {
        "releaseId": f"demo-api-{source[:12]}-{digest[:12]}",
        "sourceRepository": "SterlingAureum/startup-devops-baseline",
        "sourceCommit": source,
        "imageRepository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
        "imageTag": f"sha-{source[:7]}",
        "imageDigest": f"sha256:{digest}",
        "buildWorkflowRunId": run_id,
    }


current = identity("b" * 40, "2" * 64, "200")
older = identity("a" * 40, "1" * 64, "100")


def evidence():
    return {"state": "missing", "id": None, "ref": None, "sha256": None}


def bundle(state="missing"):
    return {
        "state": state,
        "reason": "not_found" if state == "missing" else "valid",
        "id": None if state == "missing" else "700-1",
        "ref": None if state == "missing" else "evidence/fixture.json",
        "sha256": None if state == "missing" else "9" * 64,
        "expiresAt": None if state == "missing" else "2026-08-13T00:00:00Z",
        "remainingSeconds": None if state == "missing" else 86400,
    }


def snapshot():
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
        "activeRelease": copy.deepcopy(current),
        "releaseOrderState": "current",
        "supersedingRelease": None,
        "releases": {
            env: {
                "path": f"apps/demo-api/helm/values/releases/{env}.yaml",
                "sha256": str(index) * 64,
                "identity": copy.deepcopy(current if env == "aws-dev" else older),
            }
            for index, env in enumerate(("aws-dev", "aws-test", "aws-prod"), start=3)
        },
        "evidence": {env: {"static": evidence(), "runtime": evidence()} for env in ("aws-dev", "aws-test")},
        "qualificationBundles": {"aws-dev": bundle(), "aws-test": bundle()},
        "pullRequests": [],
        "environmentAvailability": {env: "unknown" for env in ("aws-dev", "aws-test", "aws-prod")},
        "derivedAt": "2026-08-12T00:00:00Z",
    }


value = snapshot()
value["operation"] = "status"
result = planner.derive(value)
require(result["recommendedAction"] == "qualify-aws-dev" and result["dispatchAuthorized"] is False, "status authorized execution")

value = snapshot()
value["operation"] = "retry"
value["requestedReleaseId"] = current["releaseId"]
value["retryAttempt"] = {
    "runId": "700", "runAttempt": 1, "releaseId": current["releaseId"],
    "outcome": "blocked", "retryClass": "safe-new-attempt",
    "recommendedAction": "qualify-aws-dev", "controlPlaneSha": "c" * 40,
}
result = planner.derive(value)
require(result["recommendedAction"] == "qualify-aws-dev" and result["dispatchAuthorized"] is True, "Exact safe retry was not authorized")

value = snapshot()
value["activeRelease"] = copy.deepcopy(older)
value["requestedReleaseId"] = older["releaseId"]
value["releases"]["aws-prod"]["identity"] = identity("0" * 40, "3" * 64, "50")
value["releaseOrderState"] = "superseded"
value["supersedingRelease"] = copy.deepcopy(current)
result = planner.derive(value)
require(result["status"] == "superseded", "Older release was not superseded")
require(result["dispatchAuthorized"] is False, "Superseded release may still execute")
require(result["supersededByReleaseId"] == current["releaseId"], "Superseding identity missing")

collector_spec = importlib.util.spec_from_file_location("collector", root / "scripts/collect-demo-api-orchestration-snapshot.py")
require(collector_spec is not None and collector_spec.loader is not None, "Could not load collector")
collector = importlib.util.module_from_spec(collector_spec)
collector_spec.loader.exec_module(collector)
order_repo = work / "order-repo"
order_repo.mkdir()
run("git", "init", "-q", cwd=order_repo)
run("git", "config", "user.name", "Fixture", cwd=order_repo)
run("git", "config", "user.email", "fixture@example.invalid", cwd=order_repo)
(order_repo / "source.txt").write_text("old\n")
run("git", "add", "source.txt", cwd=order_repo)
run("git", "commit", "-q", "-m", "old source", cwd=order_repo)
old_source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=order_repo, text=True).strip()
(order_repo / "source.txt").write_text("new\n")
run("git", "add", "source.txt", cwd=order_repo)
run("git", "commit", "-q", "-m", "new source", cwd=order_repo)
new_source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=order_repo, text=True).strip()
ordered_old = identity(old_source, "4" * 64, "10")
ordered_new = identity(new_source, "5" * 64, "11")
order_state, superseding = collector.release_order(
    order_repo,
    ordered_old,
    {"aws-dev": {"identity": ordered_new}},
    [],
)
require(order_state == "superseded" and superseding["releaseId"] == ordered_new["releaseId"], "Collector did not use source ancestry for supersede")
currentness_spec = importlib.util.spec_from_file_location("currentness", root / "scripts/validate-demo-api-release-pr-currentness.py")
require(currentness_spec is not None and currentness_spec.loader is not None, "Could not load PR currentness validator")
currentness = importlib.util.module_from_spec(currentness_spec)
currentness_spec.loader.exec_module(currentness)
main_release = order_repo / "apps/demo-api/helm/values/releases/aws-dev.yaml"
main_release.parent.mkdir(parents=True)


def release_text(item):
    return f'''image:\n  repository: "{item["imageRepository"]}"\n  tag: "{item["imageTag"]}"\n  digest: "{item["imageDigest"]}"\nrelease:\n  applicationVersion: "{item["imageTag"]}"\ndelivery:\n  sourceRepository: "SterlingAureum/startup-devops-baseline"\n  sourceCommit: "{item["sourceCommit"]}"\n  workflowRunId: "{item["buildWorkflowRunId"]}"\n'''


main_release.write_text(release_text(ordered_new))
old_pr = {
    "number": 10,
    "headRefOid": "a" * 40,
    "files": [{"path": "apps/demo-api/helm/values/releases/aws-test.yaml", "content": release_text(ordered_old)}],
}
try:
    currentness.validate_currentness(order_repo, "SterlingAureum/startup-devops-baseline", 10, old_pr, [old_pr])
except SystemExit:
    pass
else:
    raise SystemExit("Required PR gate accepted a superseded release")
current_pr = copy.deepcopy(old_pr)
current_pr["files"][0]["content"] = release_text(ordered_new)
require(
    currentness.validate_currentness(order_repo, "SterlingAureum/startup-devops-baseline", 10, current_pr, [current_pr]) == "current",
    "Required PR gate rejected the current release",
)

fixture = work / "rollback-repo"
fixture.mkdir()
run("git", "init", "-q", cwd=fixture)
run("git", "config", "user.name", "Fixture", cwd=fixture)
run("git", "config", "user.email", "fixture@example.invalid", cwd=fixture)
(fixture / "README.md").write_text("fixture\n")
run("git", "add", "README.md", cwd=fixture)
run("git", "commit", "-q", "-m", "fixture root", cwd=fixture)
release_path = fixture / "apps/demo-api/helm/values/releases/aws-test.yaml"
release_path.parent.mkdir(parents=True)


release_path.write_text(release_text(older))
run("git", "add", str(release_path.relative_to(fixture)), cwd=fixture)
run("git", "commit", "-q", "-m", "release: old test", cwd=fixture)
old_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=fixture, text=True).strip()
release_path.write_text(release_text(current))
run("git", "add", str(release_path.relative_to(fixture)), cwd=fixture)
run("git", "commit", "-q", "-m", "release: current test", cwd=fixture)
handoff = work / "handoff.json"
run(
    sys.executable, str(root / "scripts/resolve-demo-api-rollback-candidate.py"),
    "--root", str(fixture),
    "--environment", "aws-test",
    "--failed-release-id", current["releaseId"],
    "--failure-reason", "analysis_failed",
    "--output", str(handoff),
)
handoff_value = json.loads(handoff.read_text())
require(handoff_value["rollbackToRevision"] == old_revision, "Rollback handoff did not select the prior target-only release")
require(handoff_value["previousReleaseId"] == older["releaseId"], "Rollback previous identity changed")

workflow = (root / ".github/workflows/demo-api-release-orchestrator.yaml").read_text()
rollback = (root / ".github/workflows/demo-api-rollback.yaml").read_text()
require("uses: ./.github/workflows/demo-api-rollback.yaml" not in workflow, "Orchestrator dispatches rollback")
require("expected_current_release_id:" in rollback, "Rollback does not recheck the failed release")
require("gh pr merge" not in workflow and "gh pr merge" not in rollback, "Recovery may merge a PR")
require("gh pr close" not in workflow, "Superseded PRs close automatically")

print("Retry, Attempt, supersede, expiry policy, and governed rollback handoff tests passed.")
PY

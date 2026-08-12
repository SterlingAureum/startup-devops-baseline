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
import sys


root = Path(sys.argv[1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


workflow = (root / ".github/workflows/demo-api-release-orchestrator.yaml").read_text()
promotion = (root / ".github/workflows/demo-api-promote-environment.yaml").read_text()
contract = json.loads((root / "delivery/contracts/demo-api-orchestrator.json").read_text())

for token in (
    "prepare-prod-promotion:",
    "DEMO_API_AWS_PROD_PROMOTION_ENABLED",
    "source_environment: aws-test",
    "target_environment: aws-prod",
    "qualification_mode: qualification-bundle",
):
    require(token in workflow, f"Production orchestration token missing: {token}")
require('bundle_environment="aws-test"' in workflow, "Prod Promotion does not select the test Bundle")
require("aws-dev-\\>aws-test|aws-test-\\>aws-prod" in promotion, "Bundle mode does not enforce both ordered edges")
require("qualification/${SOURCE_ENVIRONMENT}/${RELEASE_ID}" in promotion, "Bundle path is not source-environment bound")
require('--arg environment "${SOURCE_ENVIRONMENT}"' in promotion, "Bundle content is not source-environment bound")
require("environment:\n      name: ${{ inputs.target_environment }}" in promotion, "Promotion does not enter the target GitHub Environment")
require("gh pr merge" not in promotion and "--auto" not in promotion, "Production Promotion may merge itself")
require("kubectl" not in promotion, "Production Promotion gained Kubernetes access")
require("configure-aws-credentials" not in promotion and "aws eks" not in promotion, "Production Promotion gained AWS/EKS access")
require("demo-api-runtime-qualification.yaml" not in workflow.split("  prepare-prod-promotion:", 1)[1].split("  prod-promotion-disabled:", 1)[0], "Prod stage invokes runtime qualification")

prod = contract["productionPromotion"]
require(prod["source"] == "aws-test" and prod["target"] == "aws-prod", "Production edge changed")
require(prod["sourceBundleRequired"] is True, "Production source Bundle is optional")
require(prod["environmentApprovalRequired"] is True, "Production Environment approval is optional")
require(prod["releaseOnlyPullRequest"] is True, "Production change is not release-only")
require(prod["automaticMerge"] is False, "Production auto-merge enabled")
require(prod["runtimeQualification"] is False, "Production runtime qualification enabled")

spec = importlib.util.spec_from_file_location("planner", root / "scripts/derive-demo-api-orchestration-plan.py")
require(spec is not None and spec.loader is not None, "Could not load planner")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

identity = {
    "releaseId": f"demo-api-{'b' * 12}-{'2' * 12}",
    "sourceRepository": "SterlingAureum/startup-devops-baseline",
    "sourceCommit": "b" * 40,
    "imageRepository": "ghcr.io/sterlingaureum/startup-devops-baseline/demo-api",
    "imageTag": "sha-bbbbbbb",
    "imageDigest": "sha256:" + "2" * 64,
    "buildWorkflowRunId": "200",
}
old = copy.deepcopy(identity)
old.update({
    "releaseId": f"demo-api-{'a' * 12}-{'1' * 12}",
    "sourceCommit": "a" * 40,
    "imageTag": "sha-aaaaaaa",
    "imageDigest": "sha256:" + "1" * 64,
    "buildWorkflowRunId": "100",
})


def fact(state: str = "missing", environment: str = "aws-test") -> dict[str, object]:
    if state == "missing":
        return {"state": "missing", "id": None, "ref": None, "sha256": None}
    return {
        "state": state,
        "id": "500-3",
        "ref": f"evidence/demo-api/qualification/{environment}/{identity['releaseId']}/500-3.json",
        "sha256": "9" * 64,
    }


def snapshot() -> dict[str, object]:
    return {
        "schemaVersion": "v0.10.6",
        "application": "demo-api",
        "operation": "resume",
        "policy": "reviewed",
        "trigger": {"eventName": "fixture", "ref": "refs/heads/main", "sourceCommit": None},
        "capturedMainRevision": "d" * 40,
        "observedMainRevision": "d" * 40,
        "requestedReleaseId": None,
        "testRolloutGate": "reviewed-and-completed",
        "activeRelease": copy.deepcopy(identity),
        "releases": {
            "aws-dev": {"path": "apps/demo-api/helm/values/releases/aws-dev.yaml", "sha256": "3" * 64, "identity": copy.deepcopy(identity)},
            "aws-test": {"path": "apps/demo-api/helm/values/releases/aws-test.yaml", "sha256": "4" * 64, "identity": copy.deepcopy(identity)},
            "aws-prod": {"path": "apps/demo-api/helm/values/releases/aws-prod.yaml", "sha256": "5" * 64, "identity": copy.deepcopy(old)},
        },
        "evidence": {environment: {"static": fact(), "runtime": fact()} for environment in ("aws-dev", "aws-test")},
        "qualificationBundles": {"aws-dev": fact("fresh", "aws-dev"), "aws-test": fact("fresh")},
        "pullRequests": [],
        "environmentAvailability": {environment: "unknown" for environment in ("aws-dev", "aws-test", "aws-prod")},
        "derivedAt": "2026-08-12T02:00:00Z",
    }


value = snapshot()
decision = planner.derive(value)
require(
    (
        decision["phase"],
        decision["status"],
        decision["reason"],
        decision["recommendedAction"],
        decision["targetEnvironment"],
        decision["dispatchAuthorized"],
    )
    == (
        "prod-approval",
        "waiting_review",
        "production-environment-approval-required",
        "prepare-prod-promotion",
        "aws-prod",
        True,
    ),
    "Fresh test Bundle did not authorize protected prod PR preparation",
)

value["pullRequests"] = [{
    "number": 42,
    "url": "https://github.com/example/repo/pull/42",
    "kind": "environment-release",
    "targetEnvironment": "aws-prod",
    "releaseId": identity["releaseId"],
    "releaseSha256": "5" * 64,
    "headRefName": "release/prod-fixture",
    "baseRefName": "main",
}]
decision = planner.derive(value)
require(
    (decision["phase"], decision["status"], decision["recommendedAction"], decision["dispatchAuthorized"])
    == ("prod-release", "waiting_review", "wait-for-review", False),
    "Open prod PR was not reused as a human review boundary",
)

value["pullRequests"] = []
value["releases"]["aws-prod"]["identity"] = copy.deepcopy(identity)
decision = planner.derive(value)
require(
    (decision["phase"], decision["status"], decision["recommendedAction"], decision["dispatchAuthorized"])
    == ("complete", "completed", "none", False),
    "Merged prod release did not complete the GitOps release chain",
)

value = snapshot()
value["qualificationBundles"]["aws-test"] = fact("stale")
decision = planner.derive(value)
require(
    (decision["phase"], decision["status"], decision["recommendedAction"], decision["dispatchAuthorized"])
    == ("test-qualification", "blocked", "qualify-aws-test", True),
    "Stale test Bundle was allowed to prepare production",
)

print("Controlled test-to-production Promotion contracts passed.")
PY

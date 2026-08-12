#!/usr/bin/env bash
set -Eeuo pipefail
export PYTHONDONTWRITEBYTECODE=1

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

for command in bash python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

CONTROL_PLANE_SHA="dddddddddddddddddddddddddddddddddddddddd"
RUN_ID="500"
RUN_ATTEMPT="3"
STATIC_RESULT="${WORK_DIR}/static.json"
RUNTIME_RESULT="${WORK_DIR}/runtime.json"
SCOPE_RESULT="${WORK_DIR}/scope.json"
BUNDLE_FILE="${WORK_DIR}/bundle.json"

ENVIRONMENT=aws-test \
RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml" \
OUTPUT_FILE="${STATIC_RESULT}" \
VALIDATED_REPOSITORY_REVISION="${CONTROL_PLANE_SHA}" \
EVIDENCE_RUN_ID="${RUN_ID}" \
EVIDENCE_RUN_ATTEMPT="${RUN_ATTEMPT}" \
EVIDENCE_ACTOR=SterlingAureum \
RECORDED_AT=2026-08-12T00:00:00Z \
  "${ROOT_DIR}/scripts/write-demo-api-release-evidence.sh" >/dev/null

python3 - "${STATIC_RESULT}" "${RUNTIME_RESULT}" "${CONTROL_PLANE_SHA}" "${RUN_ID}" "${RUN_ATTEMPT}" <<'PY'
from pathlib import Path
import json
import sys

static_path, output_path, revision, run_id, run_attempt = sys.argv[1:]
release = json.loads(Path(static_path).read_text())["release"]
release_id = f"demo-api-{release['sourceCommit'][:12]}-{release['imageDigest'].removeprefix('sha256:')[:12]}"
runtime = {
    "schemaVersion": "v0.10.3",
    "application": "demo-api",
    "environment": "aws-test",
    "releaseId": release_id,
    "status": "qualified",
    "reason": "all_checks_passed",
    "recordedAt": "2026-08-12T00:30:00Z",
    "expiresAt": "2026-08-13T00:30:00Z",
    "controlPlane": {
        "repository": "SterlingAureum/startup-devops-baseline",
        "ref": "refs/heads/main",
        "revision": revision,
        "releaseFile": "apps/demo-api/helm/values/releases/aws-test.yaml",
        "releaseFileSha256": release["sha256"],
    },
    "expected": {
        "sourceCommit": release["sourceCommit"],
        "imageDigest": release["imageDigest"],
        "imageReference": f"{release['imageRepository']}@{release['imageDigest']}",
    },
    "executor": {
        "kind": "ephemeral-self-hosted",
        "githubEnvironment": "aws-test-runtime",
        "runnerName": "fixture-runner",
        "workflowRunId": run_id,
        "workflowRunAttempt": run_attempt,
        "awsCallerArn": "arn:aws:sts::123456789012:assumed-role/fixture/runtime",
        "clusterName": "startup-devops-baseline-test",
    },
    "runtime": {
        "argoApplication": "demo-api-aws-test",
        "argoRevision": revision,
        "workloadKind": "Rollout",
        "workloadName": "demo-api",
        "rolloutPhase": "Healthy",
        "analysisRunName": "demo-api-fixture-analysis",
        "analysisRunPhase": "Successful",
        "httpsHostname": "demo.test.aureumstack.com",
        "readyPodCount": 2,
        "observedImageIds": [f"{release['imageRepository']}@{release['imageDigest']}"],
        "checks": [
            "argocd-synced-healthy",
            "release-annotations-match",
            "all-pods-ready",
            "immutable-pod-image-id-match",
            "https-health",
            "https-ready-database",
            "https-version-identity",
            "read-only-rbac-boundary",
        ],
    },
}
Path(output_path).write_text(json.dumps(runtime, indent=2, sort_keys=True) + "\n")
PY

"${ROOT_DIR}/scripts/calculate-demo-api-qualification-scope.py" \
  --environment aws-test \
  --output "${SCOPE_RESULT}" >/dev/null
"${ROOT_DIR}/scripts/write-demo-api-qualification-bundle.py" \
  --environment aws-test \
  --static-result "${STATIC_RESULT}" \
  --runtime-result "${RUNTIME_RESULT}" \
  --scope-result "${SCOPE_RESULT}" \
  --control-plane-sha "${CONTROL_PLANE_SHA}" \
  --workflow-run-id "${RUN_ID}" \
  --workflow-run-attempt "${RUN_ATTEMPT}" \
  --actor SterlingAureum \
  --recorded-at 2026-08-12T01:00:00Z \
  --output "${BUNDLE_FILE}" >/dev/null
"${ROOT_DIR}/scripts/validate-demo-api-qualification-bundle.py" \
  --bundle "${BUNDLE_FILE}" \
  --now 2026-08-12T02:00:00Z >/dev/null

python3 - "${ROOT_DIR}" "${BUNDLE_FILE}" <<'PY'
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
bundle = json.loads(Path(sys.argv[2]).read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


workflow = (root / ".github/workflows/demo-api-release-orchestrator.yaml").read_text()
promotion = (root / ".github/workflows/demo-api-promote-environment.yaml").read_text()
collector = (root / "scripts/collect-demo-api-runtime-qualification-aws.sh").read_text()
require("test_rollout_gate:" in workflow and "reviewed-and-completed" in workflow, "Manual test gate is missing")
require("DEMO_API_AWS_TEST_PROMOTION_ENABLED" in workflow, "Test Promotion gate is missing")
require("DEMO_API_AWS_TEST_QUALIFICATION_ENABLED" in workflow, "Test qualification gate is missing")
require("qualification_mode: qualification-bundle" in workflow, "Orchestrator does not use Bundle mode")
require("qualification-bundle" in promotion and "legacy-evidence" in promotion, "Promotion dual-mode contract is missing")
require("Legacy and Qualification Bundle inputs may not be mixed" in promotion, "Promotion does not reject mixed evidence")
require("aws-dev->aws-test" in promotion, "Bundle mode edge is not exact")
require("gh pr merge" not in promotion and "--auto" not in promotion, "Promotion may merge itself")
require("kubectl" not in promotion and "configure-aws-credentials" not in promotion, "Promotion gained cluster access")
require(".status.phase == \"Healthy\"" in collector, "Runtime does not require a completed Rollout")
require(".status.phase == \"Successful\"" in collector, "Runtime does not require a successful AnalysisRun")
for token in ("expected-environment", "image-digest", "source-commit"):
    require(token in collector, f"Runtime AnalysisRun identity check missing: {token}")
require(bundle["environment"] == "aws-test", "Test Bundle environment mismatch")
require(bundle["release"]["path"].endswith("/aws-test.yaml"), "Test Bundle release path mismatch")
require(bundle["qualificationScope"]["contract"].endswith("-aws-test.json"), "Test Bundle scope mismatch")

spec = importlib.util.spec_from_file_location("planner", root / "scripts/derive-demo-api-orchestration-plan.py")
require(spec is not None and spec.loader is not None, "Could not load planner")
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

identity = {
    "releaseId": bundle["releaseId"],
    **bundle["identity"],
}


def fact(state: str = "missing") -> dict[str, object]:
    if state == "missing":
        return {"state": "missing", "id": None, "ref": None, "sha256": None}
    return {"state": state, "id": "500-3", "ref": "evidence/fixture.json", "sha256": "9" * 64}


def snapshot() -> dict[str, object]:
    old = copy.deepcopy(identity)
    old["releaseId"] = f"demo-api-{'a' * 12}-{'1' * 12}"
    old["sourceCommit"] = "a" * 40
    old["imageTag"] = "sha-aaaaaaa"
    old["imageDigest"] = "sha256:" + "1" * 64
    return {
        "schemaVersion": "v0.10.5",
        "application": "demo-api",
        "operation": "resume",
        "policy": "reviewed",
        "trigger": {"eventName": "fixture", "ref": "refs/heads/main", "sourceCommit": None},
        "capturedMainRevision": "d" * 40,
        "observedMainRevision": "d" * 40,
        "requestedReleaseId": None,
        "testRolloutGate": "not-reviewed",
        "activeRelease": copy.deepcopy(identity),
        "releases": {
            "aws-dev": {"path": "apps/demo-api/helm/values/releases/aws-dev.yaml", "sha256": "3" * 64, "identity": copy.deepcopy(identity)},
            "aws-test": {"path": "apps/demo-api/helm/values/releases/aws-test.yaml", "sha256": "4" * 64, "identity": copy.deepcopy(identity)},
            "aws-prod": {"path": "apps/demo-api/helm/values/releases/aws-prod.yaml", "sha256": "5" * 64, "identity": old},
        },
        "evidence": {environment: {"static": fact(), "runtime": fact()} for environment in ("aws-dev", "aws-test")},
        "qualificationBundles": {"aws-dev": fact("fresh"), "aws-test": fact()},
        "pullRequests": [],
        "environmentAvailability": {environment: "unknown" for environment in ("aws-dev", "aws-test", "aws-prod")},
        "derivedAt": "2026-08-12T02:00:00Z",
    }


value = snapshot()
decision = planner.derive(value)
require(
    (decision["phase"], decision["status"], decision["recommendedAction"], decision["dispatchAuthorized"])
    == ("test-qualification", "waiting_review", "review-and-complete-test-canary", False),
    "Test qualification bypassed the manual Canary gate",
)
value["testRolloutGate"] = "reviewed-and-completed"
decision = planner.derive(value)
require(
    (decision["phase"], decision["status"], decision["recommendedAction"], decision["dispatchAuthorized"])
    == ("test-qualification", "progressing", "qualify-aws-test", True),
    "Reviewed test gate did not authorize qualification",
)
value["qualificationBundles"]["aws-test"] = fact("fresh")
decision = planner.derive(value)
require(
    (decision["phase"], decision["status"], decision["recommendedAction"], decision["dispatchAuthorized"])
    == ("prod-approval", "waiting_review", "prepare-prod-promotion", False),
    "Test qualification did not stop at production approval",
)
print("Automated dev-to-test Promotion, manual Canary gate, and aws-test qualification contracts passed.")
PY

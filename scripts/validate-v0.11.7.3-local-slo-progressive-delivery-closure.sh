#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf -- "${FIXTURE_DIR}"' EXIT

python3 - "${ROOT_DIR}" "${FIXTURE_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
fixture_dir = Path(sys.argv[2])
def read(relative):
    path = root / relative
    assert path.is_file(), relative
    return path.read_text()

contract_path = "delivery/contracts/v0.11.7.3-local-slo-progressive-delivery-closure.json"
contract = json.loads(read(contract_path))
assert contract["schemaVersion"] == contract["version"] == "v0.11.7.3"
assert contract["predecessor"] == "v0.11.7.2.2"
assert contract["closurePhases"] == ["first-analysis", "human-review", "second-analysis", "final"]
assert contract["policy"]["localDefault"] == "human-governed"
assert contract["policy"]["humanGoverned"] == {
    "manualPauseWeight": 50, "manualPromotionRequired": True, "analysisRunsRequired": 2,
}
assert contract["policy"]["fullyAutomated"]["enabledByThisIncrement"] is False
assert len(contract["negativeMatrix"]) == 11
assert not any(contract["scope"].values())

closure = read("scripts/check-local-slo-progressive-delivery-closure.sh")
for marker in (
    "first-analysis|human-review|second-analysis|final",
    "MINIMUM_MATCHING_ANALYSIS_RUNS=1",
    "MINIMUM_MATCHING_ANALYSIS_RUNS=2",
    '.status.currentStepIndex == 4',
    '.status.currentPodHash == .status.stableRS',
    "check-local-slo-burn-rate-alerts.sh",
    "Fewer than two successful AnalysisRuns",
): assert marker in closure, marker
for forbidden in (
    "rollouts promote ${ROLLOUT_NAME}", "rollouts abort", "rollouts retry",
    "kubectl patch", "kubectl delete", "git push", "git revert",
): assert forbidden not in closure, forbidden

runbook = read(contract["acceptance"]["runbook"])
for marker in (
    "human-governed", "fully automated", "CLOSURE_PHASE=first-analysis",
    "CLOSURE_PHASE=human-review", "CLOSURE_PHASE=second-analysis",
    "CLOSURE_PHASE=final", "kubectl argo rollouts promote demo-api",
    "do not delete AnalysisRuns",
): assert marker in runbook, marker

release_id = "demo-api-local-v0.11.7.3-fixture"
version = "v0.11.7.3-fixture"
def analysis(name, status="Successful"):
    return {
        "metadata": {"name": name},
        "spec": {"args": [{"name": "expected-release-id", "value": release_id}]},
        "status": {"phase": status},
    }
annotations = {
    "platform.startup.dev/application-version": version,
    "platform.startup.dev/release-id": release_id,
}
human = {
    "rollout": {
        "metadata": {"annotations": annotations},
        "spec": {"replicas": 3},
        "status": {
            "phase": "Paused", "currentStepIndex": 4,
            "pauseConditions": [{"reason": "CanaryPauseStep"}],
        },
    },
    "analysisRuns": [analysis("first")],
}
final = {
    "rollout": {
        "metadata": {"annotations": annotations},
        "spec": {"replicas": 3},
        "status": {
            "phase": "Healthy", "currentPodHash": "newhash", "stableRS": "newhash",
            "readyReplicas": 3, "availableReplicas": 3,
        },
    },
    "analysisRuns": [analysis("first"), analysis("second")],
}
wrong_pause = json.loads(json.dumps(human))
wrong_pause["rollout"]["status"]["currentStepIndex"] = 2
one_analysis = json.loads(json.dumps(final))
one_analysis["analysisRuns"] = [analysis("first")]
wrong_release = json.loads(json.dumps(final))
wrong_release["analysisRuns"][1]["spec"]["args"][0]["value"] = "demo-api-local-other"
for name, payload in (("human", human), ("final", final), ("wrong-pause", wrong_pause), ("one-analysis", one_analysis), ("wrong-release", wrong_release)):
    (fixture_dir / f"{name}.json").write_text(json.dumps(payload))

for relative, marker in (
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.7.3-local-slo-progressive-delivery-closure.sh"),
    ("README.md", "v0.11.7.3-local-slo-progressive-delivery-closure"),
    ("CHANGELOG.md", "## v0.11.7.3"),
    ("docs/OBSERVABILITY.md", "v0.11.7.3"),
    ("docs/ROADMAP.md", "v0.11.7.3"),
    (".github/CODEOWNERS", f"/{contract_path} @SterlingAureum"),
): assert marker in read(relative), relative

print("v0.11.7.3 policy, four-phase closure, evidence retention, and negative-matrix contracts passed.")
PY

EXPECTED_APPLICATION_VERSION=v0.11.7.3-fixture \
CLOSURE_PHASE=human-review \
CLOSURE_STATE_FIXTURE="${FIXTURE_DIR}/human.json" \
  "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" >/dev/null

EXPECTED_APPLICATION_VERSION=v0.11.7.3-fixture \
CLOSURE_PHASE=final \
CLOSURE_STATE_FIXTURE="${FIXTURE_DIR}/final.json" \
  "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" >/dev/null

for fixture_phase in wrong-pause:human-review one-analysis:final wrong-release:final; do
  fixture="${fixture_phase%%:*}"
  phase="${fixture_phase##*:}"
  if EXPECTED_APPLICATION_VERSION=v0.11.7.3-fixture \
    CLOSURE_PHASE="${phase}" \
    CLOSURE_STATE_FIXTURE="${FIXTURE_DIR}/${fixture}.json" \
      "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" >"${FIXTURE_DIR}/${fixture}.log" 2>&1; then
    echo "${fixture} closure fixture unexpectedly passed." >&2
    exit 1
  fi
done

if EXPECTED_APPLICATION_VERSION=v0.11.7.3-fixture \
  CLOSURE_PHASE=unsupported \
  CLOSURE_STATE_FIXTURE="${FIXTURE_DIR}/final.json" \
    "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" >"${FIXTURE_DIR}/unsupported.log" 2>&1; then
  echo "Unsupported closure phase unexpectedly passed." >&2
  exit 1
fi

bash -n \
  "${ROOT_DIR}/scripts/check-local-slo-progressive-delivery-closure.sh" \
  "${ROOT_DIR}/scripts/validate-v0.11.7.3-local-slo-progressive-delivery-closure.sh"

echo "v0.11.7.3 human-review, final, wrong-step, one-analysis, wrong-release, and phase fixtures passed."

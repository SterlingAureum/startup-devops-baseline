#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.py"
PREPARE_SECRET="${ROOT_DIR}/scripts/prepare-aws-dev-grafana-secret.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4-aws-dev-guarded-root-application-deploy.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" "${PREPARE_SECRET}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
executor_path = Path(sys.argv[3])
prepare_path = Path(sys.argv[4])

assert contract["schemaVersion"] == "v0.11.9.3.6.4.1"
assert contract["version"] == "v0.11.9.3.6.4.1"
assert contract["predecessor"] == "v0.11.9.3.6.4"
assert contract["status"] == "guarded-aws-dev-monitoring-convergence-repair-implemented-not-executed"
assert contract["implementationBaselineCommit"] == "39b650d57b5609d18502721344cd46ea9b8dcce4"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.5-aws-dev-runtime-qualification"

incident = contract["observedIncident"]
assert incident == {
    "rootApplicationStatus": "Synced/Healthy",
    "demoWorkloadKind": "Deployment",
    "demoDeploymentReady": True,
    "monitoringApplicationStatus": "Synced/Degraded",
    "grafanaDeploymentStatus": "CreateContainerConfigError",
    "cause": "observability-grafana-admin Secret absent",
    "rolloutExpectedInAwsDev": False,
    "analysisRunExpectedInAwsDev": False,
}
assert contract["executor"] == {
    "entrypoint": "scripts/execute-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.py",
    "phases": ["verify", "execute"],
    "secretEntrypoint": "scripts/prepare-aws-dev-grafana-secret.py",
    "requiredBranch": "main",
    "cleanWorktreeRequired": True,
    "headOriginAndRemoteMainMustMatchReviewedCommit": True,
    "rootRedeployAllowed": False,
    "secretValuesMayBePrintedOrPersisted": False,
    "alreadyConvergedExecutionIsIdempotent": True,
    "awsAccountInput": "EXPECTED_AWS_ACCOUNT_ID",
    "awsAccountCommitted": False,
}
assert contract["approvedWriteScope"] == [
    "create observability/observability-grafana-admin only when absent"
]
assert contract["successBoundary"] == {
    "status": "aws-dev-monitoring-convergence-complete",
    "grafanaSecretCreatedOrPreserved": True,
    "grafanaSecretValuesExposed": False,
    "grafanaDeploymentReady": True,
    "monitoringApplicationSynced": True,
    "monitoringApplicationHealthy": True,
    "rootApplicationRedeployed": False,
    "runtimeQualified": False,
    "trafficGenerated": False,
    "progressiveDeliveryPromoted": False,
    "automaticTeardownExecuted": False,
    "nextAction": "review-separate-aws-dev-runtime-qualification",
}
assert all(value is False for value in contract["packageProducer"].values())
assert all(contract["timeWindowPolicy"].values())

source = executor_path.read_text()
tree = ast.parse(source)
for marker in (
    'PREPARE_GRAFANA_SECRET = ROOT / "scripts/prepare-aws-dev-grafana-secret.py"',
    'OBSERVATION_CONFIRMATION = "observe-reviewed-aws-dev-monitoring-convergence"',
    'EXECUTION_CONFIRMATION = "converge-reviewed-aws-dev-monitoring"',
    '["ls-remote", "origin", "refs/heads/main"]',
    '"--ignore-not-found", "-o", "name"',
    'convergence_state = "missing-secret-repair-required"',
    'convergence_state = "already-converged"',
    '"grafana_secret_values_exposed": False',
    '"root_application_redeployed": False',
    '"runtime_qualified": False',
    '"traffic_generated": False',
):
    assert marker in source, marker
for forbidden in (
    "deploy-aws-dev-root-app.sh",
    "rollouts promote",
    "destroy-aws-dev.sh",
    "terraform apply",
    "argocd app sync",
):
    assert forbidden not in source, forbidden
assert not any(
    isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval"
    for node in ast.walk(tree)
)

prepare = prepare_path.read_text()
for marker in (
    "Create-only runtime Secret; never print, persist, or rotate credentials.",
    "Existing independent Grafana Secret preserved.",
    "Independent Grafana Secret prepared. No credential values were printed.",
    "CONFIRM_GRAFANA_SECRET",
):
    assert marker in prepare, marker

for relative, marker in (
    ("README.md", "v0.11.9.3.6.4.1-aws-dev-monitoring-convergence"),
    ("CHANGELOG.md", "## v0.11.9.3.6.4.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.4.1"),
    ("docs/V0.11.9.3.6.4.1_AWS_DEV_MONITORING_CONVERGENCE_REPAIR.md", "Eight-hour timebox and continuation"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.4.1 exact-main, reviewed incident, Secret privacy and convergence boundaries passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
bash "${PREDECESSOR}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.4.1-aws-dev-monitoring-convergence.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.4.1 monitoring convergence repair validation passed; no live operation was executed."

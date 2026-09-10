#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" "${TESTS}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
source = Path(sys.argv[3]).read_text()
tests = Path(sys.argv[4]).read_text()
tree = ast.parse(source)

assert contract["schemaVersion"] == "v0.11.9.3.6.5.1.1"
assert contract["version"] == "v0.11.9.3.6.5.1.1"
assert contract["predecessor"] == "v0.11.9.3.6.5.1"
assert contract["status"] == "aws-dev-runtime-qualification-port-forward-readiness-budget-repaired-not-executed"
assert contract["implementationBaselineCommit"] == "c5dc3e7984c800b6fedfebd015c0625db9276d6f"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "fresh-post-merge-aws-dev-runtime-qualification-preflight-and-approval"

failure = contract["observedFailure"]
assert failure["executorExit"] == 1
assert failure["trafficGenerated"] is False
assert failure["runtimeQualified"] is False
assert failure["portForwardListenerEstablished"] is True
assert failure["forwardedConnectionCount"] == 13
assert failure["residualPortForwardProcessCount"] == 0

cause = contract["rootCause"]
assert cause == {
    "serviceProxyStillUsed": False,
    "portForwardTransportFailure": False,
    "cleanupFailure": False,
    "environmentVariableFailure": False,
    "readinessProbeTimeoutSeconds": 1,
    "readinessProbeBudgetTooSmall": True,
}

repair = contract["repair"]
assert repair["forwardReadyTimeoutSecondsBefore"] == 30
assert repair["forwardReadyTimeoutSecondsAfter"] == 90
assert repair["forwardProbeTimeoutSecondsBefore"] == 1
assert repair["forwardProbeTimeoutSecondsAfter"] == 10
assert repair["prometheusRequestTimeoutSecondsBefore"] == 20
assert repair["prometheusRequestTimeoutSecondsAfter"] == 60
assert repair["forwardStopTimeoutSecondsUnchanged"] == 5
assert repair["lastProbeFailureReported"] is True
assert repair["securityGroupExpanded"] is False
assert repair["networkPolicyExpanded"] is False
assert all(value is False for value in contract["operationBoundary"].values())

for marker in (
    "PROMETHEUS_FORWARD_READY_SECONDS = 90",
    "PROMETHEUS_FORWARD_PROBE_SECONDS = 10",
    "PROMETHEUS_REQUEST_TIMEOUT_SECONDS = 60",
    "PROMETHEUS_FORWARD_STOP_SECONDS = 5",
    'last_probe_error = "readiness probe has not completed"',
    'f"last probe: {last_probe_error}; kubectl: {detail}"',
    'listener.bind(("127.0.0.1", 0))',
    '"--address", "127.0.0.1"',
    "start_new_session=True",
    "stop_port_forward(process)",
):
    assert marker in source, marker

for marker in (
    "test_port_forward_accepts_readiness_needing_more_than_one_second",
    'if timeout <= 1:',
    'self.assertIn("last probe: Prometheus request failed"',
    "test_port_forward_is_cleaned_on_interrupt_and_forcibly_killed_if_needed",
):
    assert marker in tests, marker

for forbidden in (
    "PROMETHEUS_PROXY",
    '"--raw="',
    '"terraform", "apply"',
    '"terraform", "destroy"',
    '"kubectl", "patch"',
    '"kubectl", "delete"',
    '"kubectl", "apply"',
    '"rollouts", "promote"',
):
    assert forbidden not in source, forbidden

assert not any(
    isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "eval"
    for node in ast.walk(tree)
)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair"),
    ("CHANGELOG.md", "## v0.11.9.3.6.5.1.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.5.1.1"),
    ("docs/V0.11.9.3.6.5.1.1_PORT_FORWARD_READINESS_BUDGET_REPAIR.md", "Post-merge continuation"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.5.1.1 delayed readiness, bounded API and diagnostic contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
bash "${PREDECESSOR}"

python3 -m py_compile "${EXECUTOR}" "${TESTS}"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.1.1-port-forward-readiness-budget-repair.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.5.1.1 port-forward readiness budget repair passed; no live operation or traffic was executed."

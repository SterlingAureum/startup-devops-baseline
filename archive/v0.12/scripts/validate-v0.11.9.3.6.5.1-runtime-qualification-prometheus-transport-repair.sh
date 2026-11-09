#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.5-aws-dev-runtime-qualification.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5-aws-dev-runtime-qualification.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - "${ROOT_DIR}" "${CONTRACT}" "${EXECUTOR}" <<'PY'
from __future__ import annotations

import ast
import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
source = Path(sys.argv[3]).read_text()
tree = ast.parse(source)

assert contract["schemaVersion"] == "v0.11.9.3.6.5.1"
assert contract["version"] == "v0.11.9.3.6.5.1"
assert contract["predecessor"] == "v0.11.9.3.6.5"
assert contract["status"] == "aws-dev-runtime-qualification-prometheus-transport-repaired-not-executed"
assert contract["implementationBaselineCommit"] == "d38b5bab283970116320ad85979791edfbff8c82"
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "fresh-post-merge-aws-dev-runtime-qualification-preflight-and-approval"

failure = contract["observedFailure"]
assert failure["executorExit"] == 1
assert failure["trafficGenerated"] is False
assert failure["runtimeQualified"] is False
assert failure["serviceProxyAttempts"] == 3
assert failure["serviceProxySuccessful"] is False
assert failure["prometheusEndpointReady"] is True
assert failure["prometheusContainersReady"] is True

repair = contract["repair"]
assert repair["serviceProxyRemoved"] is True
assert repair["securityGroupExpanded"] is False
assert repair["networkPolicyExpanded"] is False
assert repair["loopbackOnly"] is True
assert repair["forwardReadyTimeoutSeconds"] == 30
assert repair["forwardProbeTimeoutSeconds"] == 1
assert repair["prometheusRequestTimeoutSeconds"] == 20
assert repair["forwardStopTimeoutSeconds"] == 5
assert repair["keyboardInterruptCleanup"] is True
assert repair["keyboardInterruptExitCode"] == 130
assert repair["forcedKillFallback"] is True
assert all(value is False for value in contract["operationBoundary"].values())

for marker in (
    'PROMETHEUS_SERVICE = "observability-metrics-prometheus"',
    'PROMETHEUS_FORWARD_READY_SECONDS =',
    'PROMETHEUS_FORWARD_PROBE_SECONDS =',
    'PROMETHEUS_REQUEST_TIMEOUT_SECONDS =',
    'PROMETHEUS_FORWARD_STOP_SECONDS = 5',
    'listener.bind(("127.0.0.1", 0))',
    'tempfile.TemporaryFile(mode="w+", encoding="utf-8")',
    '"--address", "127.0.0.1"',
    'f"service/{PROMETHEUS_SERVICE}"',
    'start_new_session=True',
    'process.terminate()',
    'process.kill()',
    'finally:',
    'stop_port_forward(process)',
    'parser.exit(130, "aws-dev runtime qualification interrupted; Prometheus port-forward cleaned up',
):
    assert marker in source, marker

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
    ("README.md", "v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair"),
    ("CHANGELOG.md", "## v0.11.9.3.6.5.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.5.1"),
    ("docs/V0.11.9.3.6.5.1_RUNTIME_QUALIFICATION_PROMETHEUS_TRANSPORT_REPAIR.md", "Post-merge continuation"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.5.1 loopback port-forward, timeout and cleanup contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
bash "${PREDECESSOR}"

python3 -m py_compile "${EXECUTOR}" "${TESTS}"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.5.1-runtime-qualification-prometheus-transport-repair.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.5.1 runtime qualification Prometheus transport repair passed; no live operation or traffic was executed."

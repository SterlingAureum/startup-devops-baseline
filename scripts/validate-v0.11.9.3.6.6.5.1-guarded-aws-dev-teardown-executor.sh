#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.5.1-guarded-aws-dev-teardown-executor.json"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.6.5.1-aws-dev-teardown.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.6.5.1-aws-dev-teardown-executor.py"

python3 - "${CONTRACT}" "${EXECUTOR}" <<'PY'
import json, pathlib, sys
contract = json.loads(pathlib.Path(sys.argv[1]).read_text())
source = pathlib.Path(sys.argv[2]).read_text()
assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.6.5.1"
assert contract["implementationBaselineCommit"] == "1dc2bd44a123931fc56e808110179b9e6d902a11"
assert contract["implementationPreflightSha256"] == "03dfc9860cc931e866418928a25cb36ecd701b2335a4e85614aa853f6e649ab6"
assert contract["controls"]["freshPostMergePreflightRequired"] is True
assert contract["boundaries"]["executionAuthorized"] is False
assert contract["boundaries"]["automaticTeardownExecuted"] is False
assert "CONFIRM_AWS_DEV_TEARDOWN_EXECUTION" in source
assert "CONFIRM_AWS_ENVIRONMENT_DESTROY" in source
assert "immediate != reviewed" in source
assert "MAXIMUM_WINDOW_SECONDS" in source
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
python3 -m py_compile "${EXECUTOR}" "${TESTS}"
python3 -m json.tool "${CONTRACT}" >/dev/null
bash -n "$0"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$0"; fi
echo "v0.11.9.3.6.6.5.1 guarded aws-dev teardown executor contracts passed; no live operation was executed."

#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.5-aws-dev-teardown-preflight.json"
PREFLIGHT="${ROOT_DIR}/scripts/preflight-v0.11.9.3.6.6.5-aws-dev-teardown.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.6.5-aws-dev-teardown-preflight.py"

python3 - "${ROOT_DIR}" "${CONTRACT}" "${PREFLIGHT}" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
contract = json.loads(pathlib.Path(sys.argv[2]).read_text())
source = pathlib.Path(sys.argv[3]).read_text()
assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.6.5"
assert contract["implementationBaselineCommit"] == "02878e4e1239f18ab9148f06667ec2eb34f91a8d"
assert contract["executionAuthorized"] is False
assert contract["teardownAuthorized"] is False
for forbidden in ("terraform\", \"destroy", "destroy-aws-dev.sh", "kubectl\", \"delete"):
    assert forbidden not in source
assert "CONFIRM_AWS_ENVIRONMENT_DESTROY" in source
assert "Destructive confirmation must be unset" in source
assert "account_id_emitted" in source and "resource_ids_emitted" in source
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
python3 -m py_compile "${PREFLIGHT}" "${TESTS}"
python3 -m json.tool "${CONTRACT}" >/dev/null
bash -n "$0"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$0"; fi
echo "v0.11.9.3.6.6.5 aws-dev teardown read-only preflight contracts passed; no live operation was executed."

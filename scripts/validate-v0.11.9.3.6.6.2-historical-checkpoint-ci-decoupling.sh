#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.2-historical-checkpoint-ci-decoupling.json"
READINESS="${ROOT_DIR}/scripts/validate-v0.11.9.3.2-protected-main-integration-readiness.sh"
SUCCESSOR="${ROOT_DIR}/scripts/check-v0.11.9.3.6.6.1-aws-test-release-successor.py"

python3 - "${ROOT_DIR}" "${CONTRACT}" "${READINESS}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
readiness = Path(sys.argv[3]).read_text()

assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.6.2"
assert contract["predecessor"] == "v0.11.9.3.6.6.1"
assert contract["implementationBaselineCommit"] == "6052984541d8b46d003ee5f53eec25ab7dc9b1de"
assert all(value is False for value in contract["scope"].values())
assert contract["executionAuthorized"] is False

test_path = "apps/demo-api/helm/values/releases/aws-test.yaml"
prod_path = "apps/demo-api/helm/values/releases/aws-prod.yaml"
assert 'if relative in (' in readiness
assert f'        "{test_path}",' in readiness
assert 'check-v0.11.9.3.6.6.1-aws-test-release-successor.py' in readiness
assert f'(root / relative).read_bytes()' in readiness
assert prod_path in json.loads(
    (root / "delivery/contracts/v0.11.9.3.2-protected-main-integration-readiness.json").read_text()
)["releaseFiles"]
PY

test "$("${SUCCESSOR}" --release-file "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml")" = historical-aws-test
test "$("${SUCCESSOR}" --release-file "${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml")" = reviewed-promoted-candidate

bash "${READINESS}"
python3 -m json.tool "${CONTRACT}" >/dev/null
bash -n "$0" "${READINESS}"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$0" "${READINESS}"; fi

echo "v0.11.9.3.6.6.2 historical checkpoint CI decoupling passed; no live operation was executed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.3-successor-policy-convergence.json"
CHECK_NAME="check-v0.11.9.3.6.6.1-aws-test-release-successor.py"

python3 - "${ROOT_DIR}" "${CONTRACT}" "${CHECK_NAME}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
check_name = sys.argv[3]

assert contract["schemaVersion"] == contract["version"] == "v0.11.9.3.6.6.3"
assert contract["predecessor"] == "v0.11.9.3.6.6.2"
assert contract["implementationBaselineCommit"] == "bdbb7f1224352d12d83b52c17b44254f3275ac75"
assert all(value is False for value in contract["scope"].values())
assert contract["executionAuthorized"] is False

for relative in contract["repairedValidators"]:
    text = (root / relative).read_text()
    assert check_name in text, relative

for relative in (
    "scripts/validate-v0.11.9.3.3-reviewed-main-integration.sh",
    "scripts/validate-v0.11.9.3.4-existing-image-aws-dev-promotion-execution.sh",
    "scripts/validate-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.sh",
):
    text = (root / relative).read_text()
    assert 'aws-prod' in text
PY

for validator in \
  validate-v0.11.9.3.3-reviewed-main-integration.sh \
  validate-v0.11.9.3.4-existing-image-aws-dev-promotion-execution.sh \
  validate-v0.11.9.3.5-aws-dev-live-rehearsal-preflight.sh \
  validate-v0.11.9.3.6.6.1-aws-test-successor-validation-repair.sh \
  validate-v0.11.9.3.6.6.2-historical-checkpoint-ci-decoupling.sh; do
  "${ROOT_DIR}/scripts/${validator}"
done

python3 -m json.tool "${CONTRACT}" >/dev/null
bash -n "$0"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$0"; fi

echo "v0.11.9.3.6.6.3 successor policy convergence passed; no live operation was executed."

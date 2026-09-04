#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-local-release-rehearsal.py"
python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
contract = json.loads((root / 'delivery/contracts/v0.11.9.1.1-local-release-rehearsal-stability.json').read_text())
assert contract['version'] == 'v0.11.9.1.1'
assert contract['post_phase_identity_wait_seconds'] == 120
assert contract['phase_timeout_seconds'] == 900
assert not contract['automatic_promote']
assert not contract['automatic_retry']
assert not contract['automatic_rollback']
runbook = (root / 'docs/V0.11.9.1_LOCAL_RELEASE_REHEARSAL.md').read_text()
for required in ('terminal 1', 'command.log', 'Retry decision table',
                 'Do not enter this assignment form', 'promote demo-api'):
    assert required in runbook, required
runner = (root / 'scripts/local-release-rehearsal.py').read_text()
for required in ('Terminal 1 action:', 'wait_snapshot_identity', 'do not enter REHEARSAL_DIR'):
    assert required in runner, required
PY

echo 'v0.11.9.1.1 offline stability checks passed; no live rollout was executed.'

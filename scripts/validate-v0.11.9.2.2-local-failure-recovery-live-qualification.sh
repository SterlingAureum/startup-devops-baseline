#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-prepare-local-failure-recovery-live-plan.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-show-local-failure-recovery-status.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-local-failure-recovery-rehearsal.py"

python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
read = lambda relative: (root / relative).read_text()
contract = json.loads(read('delivery/contracts/v0.11.9.2.2-local-failure-recovery-live-qualification.json'))
assert contract['version'] == 'v0.11.9.2.2'
assert contract['predecessor'] == 'v0.11.9.2.1'
assert contract['producer_live_executed'] is False
assert contract['runtime_qualified'] is False
for action in ('automatic_promote', 'automatic_retry', 'automatic_abort',
               'automatic_rollback', 'automatic_cleanup', 'aws_mutation'):
    assert contract[action] is False, action

preflight = read('scripts/prepare-local-failure-recovery-live-plan.py')
for required in ('BASE.git_identity()', 'BASE.isolated(args.context', 'BASE.healthy',
                 'BASE.stable_ready', 'FAILURE.assert_fault_isolation',
                 "'execution_started': False", "plan_path.chmod(0o600)"):
    assert required in preflight, required
for forbidden in ('rollouts abort', 'rollouts retry', 'rollouts promote'):
    assert forbidden not in preflight, forbidden

runner = read('scripts/local-failure-recovery-rehearsal.py')
for required in ('Reviewed failed AnalysisRun identity changed', 'assert_gitops_restored',
                 "bundle / 'qualification.json'", "'runtime_qualified': True",
                 'Whole rehearsal exceeded its reviewed time bound',
                 'Recovery exceeded its reviewed time bound'):
    assert required in runner, required

status = read('scripts/show-local-failure-recovery-status.py')
for required in ('unresolved_failures', 'latest_attempts', 'manual_action', 'next_phase'):
    assert required in status, required
assert 'fault-token.private' not in status

successor_fixture = read('scripts/validate-v0.11.4.0.1-helm-successor-coverage.sh')
for required in ('INCLUDE_FAILURE_RECOVERY', 'v0.11.9.2.1-local-failure-recovery-runner.json',
                 'name: rehearsalFault.mode', 'name: rehearsalFault.tokenSha256'):
    assert required in successor_fixture, required

logging_validator = read('scripts/validate-v0.11.6.1.0-structured-demo-api-logging-runtime.sh')
for required in ('failure_recovery_successor', 'allowed_fault_header_read',
                 'main_source.count(allowed_fault_header_read) == 1',
                 'request_logging_source = main_source.replace'):
    assert required in logging_validator, required

runbook = read('docs/V0.11.9.2.2_LOCAL_FAILURE_RECOVERY_LIVE_QUALIFICATION.md')
for required in ('Terminal 1', 'Terminal 2', 'Expected signal', 'Safe retry rule',
                 'manual abort', 'manual retry', 'qualification.json',
                 'show-local-failure-recovery-status.py', 'tail -n 100 -f'):
    assert required in runbook, required
PY

bash "${ROOT_DIR}/scripts/validate-v0.11.9.2.1-local-failure-recovery-runner.sh"
echo 'v0.11.9.2.2 operator-ready checks passed; no live fault, traffic, abort or recovery was executed.'

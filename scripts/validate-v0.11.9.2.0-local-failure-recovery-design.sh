#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-v0.11.9.2.0-failure-recovery-plan.py"
python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
contract = json.loads((root / 'delivery/contracts/v0.11.9.2.0-local-failure-recovery-design.json').read_text())
assert contract['version'] == 'v0.11.9.2.0'
assert contract['predecessor'] == 'v0.11.9.1.1'
assert contract['environment'] == 'local-kind-loopback-only'
assert contract['runtime_qualified'] is False
assert contract['execution_authorized'] is False
assert contract['fault_implemented'] is False
for action in ('automatic_promote', 'automatic_retry', 'automatic_abort',
               'automatic_rollback', 'automatic_cleanup', 'aws_mutation'):
    assert contract[action] is False, action
assert contract['failure_target'] == {
    'service': 'demo-api-canary', 'route': '/version', 'signal': 'http-503',
    'metric': 'canary-availability-error-budget-burn-rate',
    'required_analysis_phase': 'Failed'}
assert contract['bounds'] == {
    'fault_traffic_max_requests': 80, 'fault_traffic_max_seconds': 180,
    'fault_cleanup_max_seconds': 300, 'recovery_max_seconds': 600,
    'whole_rehearsal_max_seconds': 1800}

checker = (root / 'scripts/check-v0.11.9.2.0-failure-recovery-plan.py').read_text()
for forbidden in ('subprocess', 'kubectl', 'argocd', 'boto3', 'requests.'):
    assert forbidden not in checker, forbidden
for required in ('execution_authorized', 'fault_implemented',
                 'provider_error_accepted', 'runtime_image_id'):
    assert required in checker, required

runbook = (root / 'docs/V0.11.9.2.0_LOCAL_FAILURE_RECOVERY_DESIGN.md').read_text()
for required in ('Two-stage same-binary isolation', 'X-Rehearsal-Fault',
                 'Stop and recovery decision matrix', 'No execution is authorized'):
    assert required in runbook, required
PY

bash "${ROOT_DIR}/scripts/validate-v0.11.9.1.1-local-release-rehearsal-stability.sh"
echo 'v0.11.9.2.0 offline failure/recovery design checks passed; no fault or runtime action occurred.'

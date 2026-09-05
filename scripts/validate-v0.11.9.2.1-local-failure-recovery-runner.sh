#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${ROOT_DIR}/apps/demo-api" \
  python3 "${ROOT_DIR}/apps/demo-api/tests/test_rehearsal_fault.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-local-failure-recovery-rehearsal.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.11.9.2.0-failure-recovery-plan.py"

bash -n \
  "${ROOT_DIR}/scripts/deploy-root-app.sh" \
  "${ROOT_DIR}/scripts/deploy-local-feature-gitops.sh" \
  "${ROOT_DIR}/scripts/run-local-candidate-rejection-traffic.sh"

python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
read = lambda relative: (root / relative).read_text()
contract = json.loads(read('delivery/contracts/v0.11.9.2.1-local-failure-recovery-runner.json'))
assert contract['version'] == 'v0.11.9.2.1'
assert contract['predecessor'] == 'v0.11.9.2.0'
assert contract['live_executed_by_producer'] is False
assert contract['runtime_qualified'] is False
for action in ('automatic_promote', 'automatic_retry', 'automatic_abort',
               'automatic_rollback', 'automatic_cleanup', 'aws_mutation'):
    assert contract[action] is False, action
assert contract['phases'] == ['prepare', 'arm', 'traffic', 'rejection-review',
                              'abort-check', 'recovery-approval', 'restore', 'final']
assert contract['traffic']['maximum_request_pairs'] == 80

fault = read('apps/demo-api/src/rehearsal_fault.py')
for required in ('hmac.compare_digest', "environment != 'local'", "mode == DISABLED",
                 "re.fullmatch(r'[0-9a-f]{64}'"):
    assert required in fault, required
main = read('apps/demo-api/src/main.py')
for required in ('REHEARSAL_FAULT_MODE', 'REHEARSAL_FAULT_TOKEN_SHA256',
                 'request.headers.get("X-Rehearsal-Fault")', 'status_code=503'):
    assert required in main, required

for relative in ('apps/demo-api/helm/templates/deployment.yaml',
                 'apps/demo-api/helm/templates/rollout.yaml'):
    rendered = read(relative)
    assert rendered.count('name: REHEARSAL_FAULT_MODE') == 1
    assert rendered.count('name: REHEARSAL_FAULT_TOKEN_SHA256') == 1
values = read('apps/demo-api/helm/values.yaml')
assert 'rehearsalFault:\n  mode: disabled\n  tokenSha256: ""' in values

historical_rendering = read('scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh')
for required in (
        'v0.11.9.2.1-local-failure-recovery-runner.json',
        'failure_recovery_successor = Path(sys.argv[10]).is_file()',
        'fault_parameters = ["rehearsalFault.mode", "rehearsalFault.tokenSha256"]',
        '*fault_parameters,'):
    assert required in historical_rendering, required

traffic = read('scripts/run-local-candidate-rejection-traffic.sh')
for required in ('demo-api-stable', 'demo-api-canary', 'availability-503',
                 "[[ \"${code}\" == '503' ]]", 'MAX_REQUESTS', 'metricResults',
                 'canary-availability-error-budget-burn-rate', '-H @"${work_dir}/fault-header"'):
    assert required in traffic, required
for forbidden in ('kubectl argo rollouts promote', 'kubectl argo rollouts abort',
                  'kubectl argo rollouts retry', 'X-Rehearsal-Fault: ${token}" -'):
    assert forbidden not in traffic, forbidden

runner = read('scripts/local-failure-recovery-rehearsal.py')
for required in ('Phase already passed; do not replay it', 'failed_analysis',
                 "'runtime_qualified': args.phase == 'final'", 'restore-reviewed-local-baseline'):
    assert required in runner, required
for forbidden in ("'promote'", "'retry'", "'abort',", 'rollouts promote'):
    assert forbidden not in runner, forbidden

runbook = read('docs/V0.11.9.2.1_LOCAL_FAILURE_RECOVERY_RUNNER.md')
for required in ('Do not run', 'Phase command map', 'manual abort if needed',
                 'faultMode: disabled', 'tail -n 100 -f', 'no image was built'):
    assert required in runbook, required
PY

if command -v helm >/dev/null 2>&1; then
  helm lint "${ROOT_DIR}/apps/demo-api/helm" >/dev/null
  helm lint "${ROOT_DIR}/clusters/local/platform" >/dev/null
else
  echo 'SKIP: helm is unavailable; CI must run both Helm lint checks.'
fi

bash "${ROOT_DIR}/scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh"
echo 'v0.11.9.2.1 offline runner checks passed; no live fault or recovery was executed.'

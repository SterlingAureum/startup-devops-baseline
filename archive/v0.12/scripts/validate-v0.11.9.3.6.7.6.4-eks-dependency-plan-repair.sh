#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast, hashlib, importlib.util, json, re, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
spec = importlib.util.spec_from_file_location('dependency_gate', root / 'scripts/execute-v0.11.9.3.6.7.6.4-aws-test-teardown.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.source_checks()
assert hashlib.sha256((root / m.CONTRACT).read_bytes()).hexdigest() == 'e202e0369d300b626c3457e4544ccae31c7b5b35b518029ba3ae570f45575ffb'
assert c['version'] == c['schemaVersion'] == 'v0.11.9.3.6.7.6.4'
assert c['implementationBaselineCommit'] == '721419913123e18c37d3c3998256e89c6a81b8c1'
assert c['cleanupCompleteByUtc'] == '2026-09-13T16:00:00Z' and c['minimumTerraformStartSeconds'] == 900
assert m.m.m.projection(c)['estimated_total_usd'] == c['estimatedTotalUsd'] == '35.20'
assert c['budget']['totalLimitUsd'] == '36.00' and c['budget']['historicalBilledSpendUsd'] is None
assert sum(x['count'] for x in c['allowedDefinitions']) == c['exactManagedDeleteCount'] == 50
assert sum(x['count'] for x in c['allowedDefinitions'] if x['module'] == 'module.eks') == 19
assert c['savedPlanTtlSeconds'] == 1800
assert not c['oldApprovalReused'] and not c['originalPlanClockResetAllowed'] and not c['automaticReplanAllowed']
assert not c['existingCandidateClock']['mtimeCanExtendTtl']
assert c['existingCandidateClock']['conservativeExpiresAtUtc'] == '2026-09-13T13:50:04Z'
assert set(c['phases']) == set(m.PHASES)
raw = (json.dumps(c['priorFailureResult'], indent=2, sort_keys=True) + '\n').encode()
assert hashlib.sha256(raw).hexdigest() == c['history']['failure']
assert not any(c['privacyBoundary'].values()) and not any(c['packageProducer'].values())
for name in ('scripts/execute-v0.11.9.3.6.7.6.4-aws-test-teardown.py', 'scripts/test-v0.11.9.3.6.7.6.4-aws-test-teardown.py'):
    ast.parse((root / name).read_text())
for name in (m.CONTRACT, 'docs/V0.11.9.3.6.7.6.4_AWS_TEST_EKS_DEPENDENCY_PLAN_REPAIR.md'):
    text = (root / name).read_text()
    assert not any(x in text for x in ('/home/sterling/', 'arn:aws:', 'secretMetadataSha256', 'AKIA'))
    assert re.search(r'(?<![a-zA-Z0-9])[0-9]{12}(?![a-zA-Z0-9])', text) is None
    assert re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32', text) is None
assert hashlib.sha256((root / '.gitleaksignore').read_bytes()).hexdigest() == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.4 exact dependency/state/history/clock/budget/privacy gates passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6.4-aws-test-teardown.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.3-remaining-cleanup.sh"
echo "v0.11.9.3.6.7.6.4 passed; validation offline; fresh plan/apply need separate approval."

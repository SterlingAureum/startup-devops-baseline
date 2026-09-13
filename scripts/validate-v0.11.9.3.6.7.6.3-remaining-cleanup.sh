#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast, hashlib, importlib.util, json, re, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
spec = importlib.util.spec_from_file_location('remaining_gate', root / 'scripts/execute-v0.11.9.3.6.7.6.3-aws-test-teardown.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
c = m.source_checks()
assert hashlib.sha256((root / m.CONTRACT).read_bytes()).hexdigest() == '672afc566e198fb9ceafb37c68dcd9957f8bdeabce126ce2fd72910d5cd67879'
assert c['version'] == c['schemaVersion'] == 'v0.11.9.3.6.7.6.3'
assert c['implementationBaselineCommit'] == 'b111d58a70b6eae5c9380e1477a84b651e2555ab'
assert c['runtimeStopUtc'] == '2026-09-13T14:30:00Z'
assert c['runtimeLatestStartUtc'] == '2026-09-13T14:10:00Z'
assert c['cleanupCompleteByUtc'] == '2026-09-13T16:00:00Z'
assert c['scheduleRequiresNewExplicitApproval'] and not c['scheduleConfirmationAuthorizesDeletion'] and not c['oldApprovalReused']
assert m.m.projection(c)['estimated_total_usd'] == c['estimatedTotalUsd'] == '35.20'
assert c['budget']['totalLimitUsd'] == '36.00' and c['budget']['historicalBilledSpendUsd'] is None
for field, history_key in (('priorFailureResult', 'failure'), ('esoCleanupResult', 'esoCleanupResult'), ('remainingObservation', 'remainingObservation')):
    raw = (json.dumps(c[field], indent=2, sort_keys=True) + '\n').encode()
    assert hashlib.sha256(raw).hexdigest() == c['history'][history_key]
assert c['orderingDefect']['controllerReady'] and not c['orderingDefect']['controllerPatchAuthorization']
assert c['orderingDefect']['namespaceRoleCount'] == c['orderingDefect']['namespaceRoleBindingCount'] == 0
assert not c['orderingDefect']['namespaceFinalizerForced'] and not c['orderingDefect']['automaticRepairAdded']
assert set(c['phases']) == set(m.PHASES)
assert c['phases']['execute-remaining']['nodepoolDeleteCount'] == 2
assert c['phases']['execute-remaining']['nodeclassDeleteCount'] == 3
assert not c['phases']['execute-remaining']['repeatCompletedRuntimeDeletion']
assert not any(c['privacyBoundary'].values()) and not any(c['packageProducer'].values())
for name in ('scripts/execute-v0.11.9.3.6.7.6.3-aws-test-teardown.py', 'scripts/test-v0.11.9.3.6.7.6.3-aws-test-teardown.py'):
    ast.parse((root / name).read_text())
for name in (m.CONTRACT, 'docs/V0.11.9.3.6.7.6.3_AWS_TEST_REMAINING_CLEANUP.md'):
    text = (root / name).read_text()
    assert not any(x in text for x in ('/home/sterling/', 'arn:aws:', 'secretMetadataSha256', 'AKIA'))
    assert re.search(r'(?<![a-zA-Z0-9])[0-9]{12}(?![a-zA-Z0-9])', text) is None
    assert re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32', text) is None
assert hashlib.sha256((root / '.gitleaksignore').read_bytes()).hexdigest() == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.3 history/candidate-window/config-only/privacy/source gates passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6.3-aws-test-teardown.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.2-runtime-cleanup-resume.sh"
echo "v0.11.9.3.6.7.6.3 passed; validation offline; deletion remains unapproved."

#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
import guarded_runtime_parity_v6776 as parity

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.6-complete-offline-runtime-parity-review.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '2ba483784f30efd79191bee2dac7731878b7c4437ec9db852e575d577da02ad7', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.6'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.5'
assert contract['implementationBaselineCommit'] == 'f8879840d9231b995a5a83b4669aae418f30b779'
assert contract['status'] == 'complete-offline-runtime-parity-reviewed'
assert contract['historicalTeardownAndScopedAuditClosed']
assert not any(contract[key] for key in ('existingLiveAdaptersModified',
    'completeAdapterMigrationImplemented', 'liveMigrationReady',
    'newLiveExecutionAuthorized', 'historicalApprovalsReusable', 'prodQualified'))
for prefix in ('core', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

destroy = json.loads((root / contract['frozenSources'][0]['path']).read_text())
cleanup = json.loads((root / contract['frozenSources'][1]['path']).read_text())
report = parity.review_runtime_parity(destroy, cleanup, contract['parityManifest'])
expected = contract['reviewResult']
for key, value in expected.items():
    assert report[key] == value, key
assert report['status'] == 'offline-runtime-parity-review-complete'
assert report['migrationGapIds'] == [row['id'] for row in contract['parityManifest']['gaps']]
assert report['historicalTeardownAndScopedAuditClosed']
assert not report['endToEndOfflineChainExecutable']
assert not report['liveMigrationReady'] and not report['prodQualified']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 36

tree = ast.parse((root / contract['corePath']).read_text())
allowed = {'__future__', 'guarded_cleanup_rules', 'guarded_runtime_rules'}
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        assert all(item.name in allowed for item in node.names)
    if isinstance(node, ast.ImportFrom):
        assert node.module in allowed
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            assert node.func.id not in {'exec', 'eval', '__import__', 'open', 'print'}
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {'run', 'Popen', 'system', 'getenv', 'now',
                                          'utcnow', 'unlink', 'write_text', 'read_text'}

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.6_COMPLETE_OFFLINE_RUNTIME_PARITY_REVIEW.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.6 source/AST/privacy pins passed; 7/8 stages and 21/24 cells only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.6-runtime-parity-review.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.5-offline-cleanup-adapters.sh"
echo "v0.11.9.3.6.7.7.6 passed; full offline parity gaps remain fail-closed."

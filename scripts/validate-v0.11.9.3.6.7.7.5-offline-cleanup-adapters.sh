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
contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.5-shared-offline-cleanup-adapters.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '267ee834e20ed2df6640eb0b72eb389382b2117063e084fdcc1babeed3fd4aa1', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.5'
assert contract['implementationBaselineCommit'] == 'dee9917b3e462dd21a29ebaca49685cfc3d37489'
assert contract['status'] == 'shared-offline-cleanup-adapters-implemented'
assert contract['historicalTeardownAndScopedAuditClosed']
assert not any(contract[key] for key in ('existingLiveAdaptersModified',
    'completeAdapterMigrationImplemented', 'newLiveExecutionAuthorized',
    'historicalApprovalsReusable', 'prodQualified'))
assert contract['environmentProfiles'] == ['aws-dev', 'aws-test', 'aws-prod']
assert contract['implementedPhases'] == ['drain-external-secrets',
    'delete-business-namespaces', 'drain-runtime', 'delete-node-config',
    'eni-sg-cleanup']
assert contract['successfulFixtureMatrixSize'] == 15
for prefix in ('core', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = sorted(node.name for node in ast.walk(test_tree)
                 if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'))
assert methods == sorted(contract['testMethods'])
assert len(methods) == contract['testMethodCount'] == 41

tree = ast.parse((root / contract['corePath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == set(contract['publicClasses'])
allowed = {'__future__', 'hashlib', 'json', 'pathlib', 're',
           'guarded_attempt_journal', 'guarded_cleanup_rules',
           'guarded_runtime_rules', 'guarded_runtime_simulation_v6774'}
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
             'docs/V0.11.9.3.6.7.7.5_SHARED_OFFLINE_CLEANUP_ADAPTERS.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.5 source/AST/privacy pins passed; fixed fake cleanup adapters only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.5-offline-cleanup-adapters.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.4-offline-destroy-adapters.sh"
echo "v0.11.9.3.6.7.7.5 passed; three-profile cleanup composition validated offline."

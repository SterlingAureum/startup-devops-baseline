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
contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.7-shared-offline-freeze-adapter.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == 'ef82ce618fe0a93e2c678c3f646a2db5ed887be75611dae74fde5cd6fc2f23df', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.7'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.6'
assert contract['implementationBaselineCommit'] == 'd9f9e96972a25f0a5894cd9c93ca018d27c28a96'
assert contract['status'] == 'shared-offline-freeze-adapter-implemented'
assert contract['environmentProfiles'] == ['aws-dev', 'aws-test', 'aws-prod']
assert contract['implementedPhase'] == 'freeze-applications'
assert contract['offlineComposition'] == {
    'orderedStageCount': 8,
    'environmentCount': 3,
    'successfulEnvironmentStageMatrixSize': 24,
    'endToEndOfflineReceiptChainTested': True,
    'syntheticOnly': True,
}
assert contract['historicalTeardownAndScopedAuditClosed']
assert not any(contract[key] for key in ('existingLiveAdaptersModified',
    'completeAdapterMigrationImplemented', 'liveMigrationReady',
    'newLiveExecutionAuthorized', 'historicalApprovalsReusable', 'prodQualified'))
for prefix in ('core', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert methods == contract['testMethods']
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 36

tree = ast.parse((root / contract['corePath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == {'FreezeSimulationStopped', 'FreezeScenarioTransport',
                   'OfflineFreezeAdapter'}
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

effects = contract['effectFlags']
for key in ('cloudTransport', 'kubernetesTransport', 'terraformCommands',
            'systemClockReads', 'cloudMutation', 'kubernetesMutation',
            'secretValueRead', 'automaticRetry'):
    assert effects[key] is False
assert contract['receiptContract']['durableLiveCrossPhaseHandoffImplemented'] is False
for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.7_SHARED_OFFLINE_FREEZE_ADAPTER.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.7 source/AST/privacy pins passed; fixed fake freeze and 24/24 synthetic chain only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.7-offline-freeze-adapter.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.6-runtime-parity-review.sh"
echo "v0.11.9.3.6.7.7.7 passed; eight-stage offline receipt composition validated."

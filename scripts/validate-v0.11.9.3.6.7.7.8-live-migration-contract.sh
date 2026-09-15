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
import guarded_live_migration_contract_v6778 as rules

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.8-live-transport-and-receipt-migration-design.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '2e3da8067481abe8dc3846ec0351d8ffc2cd2879f398952fb41177a3f9272719', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.8'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.7'
assert contract['implementationBaselineCommit'] == '50b27de63e48ff4602f3f4d8680f2ece75bc8adc'
assert contract['status'] == 'versioned-live-migration-contract-designed'
assert contract['designContract'] == rules.expected_design()
report = rules.validate_design(contract['designContract'])
assert report == {
    'status': 'live-migration-design-validated-offline',
    'version': 'v0.11.9.3.6.7.7.8',
    'environment_count': 3,
    'stage_count': 8,
    'operation_count': 23,
    'durable_receipt_designed': True,
    'synthetic_receipt_convertible': False,
    'currently_live_enabled_environment_count': 0,
    'prod_enabled': False,
    'execution_authorized': False,
}
for prefix in ('core', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert methods == contract['testMethods']
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 38

tree = ast.parse((root / contract['corePath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == set()
allowed = {'__future__', 'decimal', 're', 'typing', 'guarded_cleanup_rules',
           'guarded_runtime_rules'}
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

assert contract['reviewResult'] == {
    'environmentSchemaCount': 3,
    'orderedStageCount': 8,
    'closedOperationCount': 23,
    'durableReceiptSchemaDesigned': True,
    'offlineSyntheticReceiptConvertible': False,
    'currentlyLiveEnabledEnvironmentCount': 0,
    'firstFutureMigrationCandidate': 'aws-dev',
    'testRequiresDevMigrationEvidence': True,
    'prodEnabled': False,
}
for key in ('existingLiveAdaptersModified', 'liveTransportImplemented',
            'durableReceiptStoreImplemented', 'approvalCommandImplemented',
            'newLiveExecutionAuthorized', 'historicalApprovalsReusable',
            'prodQualified'):
    assert contract[key] is False
assert contract['historicalTeardownAndScopedAuditClosed'] is True
effects = contract['effectFlags']
for key in ('cloudTransport', 'kubernetesTransport', 'terraformCommands',
            'privateEvidenceReads', 'systemClockReads', 'cloudMutation',
            'kubernetesMutation', 'secretValueRead', 'automaticRetryOrRepair'):
    assert effects[key] is False

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.8_LIVE_TRANSPORT_AND_RECEIPT_MIGRATION_DESIGN.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.8 source/AST/privacy pins passed; design only, no live transport or authorization.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.8-live-migration-contract.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.7-offline-freeze-adapter.sh"
echo "v0.11.9.3.6.7.7.8 passed; live transport and durable receipt migration are design-only."

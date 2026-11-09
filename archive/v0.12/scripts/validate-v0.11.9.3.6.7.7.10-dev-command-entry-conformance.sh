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
import guarded_dev_command_entry_conformance_v67710 as core
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.10-dev-offline-command-entry-conformance.json'
document_path = 'docs/V0.11.9.3.6.7.7.10_DEV_OFFLINE_COMMAND_ENTRY_CONFORMANCE.md'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '4617298230ec3f30d25da104873cd4a975a125f30a9e99170fb4c53fe5cfe883', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.10'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.9'
assert contract['implementationBaselineCommit'] == '850720c1c15b6b26afa284a4e5c80ab0940318e9'
assert contract['status'] == 'dev-offline-command-entry-conformance-implemented'
assert contract['environmentProfile'] == core.ENVIRONMENT == 'aws-dev'
assert tuple(core.CONFIRMATIONS) == STAGES
assert len(core.CONFIRMATIONS) == 8
assert sum(map(len, STAGE_OPERATIONS.values())) == 23

for prefix in ('core', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert methods == contract['testMethods']
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 37

tree = ast.parse((root / contract['corePath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == {
    'CommandEntryStopped', 'FrozenClock', 'FixedPrivateInputReader',
    'DevOfflineCommandEntry',
}
allowed = {
    '__future__', 'hashlib', 'json', 're',
    'guarded_dev_transport_conformance_v6779',
    'guarded_live_migration_contract_v6778', 'guarded_runtime_rules',
}
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        assert all(item.name in allowed for item in node.names)
    if isinstance(node, ast.ImportFrom):
        assert node.module in allowed
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            assert node.func.id not in {
                'exec', 'eval', '__import__', 'open', 'print', 'input',
            }
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                'run', 'Popen', 'system', 'popen', 'getenv', 'putenv',
                'utcnow', 'read_text', 'read_bytes', 'write_text',
                'write_bytes', 'unlink', 'remove', 'rename', 'replace',
            }

assert contract['commandEntry'] == {
    'schema': 'guarded-dev-offline-command-v1',
    'commands': ['verify', 'execute'],
    'implementation': 'programmatic-offline-only',
    'verifyAcceptsTransport': False,
    'executeRequiresReviewedVerifySha256': True,
    'executeRequiresExactPhaseConfirmation': True,
    'executeRereadsExactPrivateInputBytes': True,
    'onePhasePerExecution': True,
    'arbitraryPathOrEndpointAccepted': False,
    'cliImplemented': False,
    'environmentVariableReaderImplemented': False,
}
assert contract['injectedDependencies'] == {
    'clock': 'fixed-in-memory-utc-sequence',
    'privateInputReader': 'fixed-in-memory-canonical-json-by-closed-name',
    'transport': 'v0.11.9.3.6.7.7.9-fixed-fake-only',
    'receiptStore': 'v0.11.9.3.6.7.7.9-local-durable-store',
    'subclassesAccepted': False,
    'systemClockConsulted': False,
    'livePrivateFileRead': False,
}
assert contract['privateInputContract'] == {
    'logicalNames': ['approval', 'evidence', 'reviewed-verify'],
    'verifyExactInputs': ['approval', 'evidence'],
    'executeExactInputs': ['approval', 'evidence', 'reviewed-verify'],
    'canonicalJsonRequired': True,
    'expectedSha256Required': True,
    'privateBytesEmitted': False,
}
assert contract['reviewResult'] == {
    'environment': 'aws-dev',
    'commandCount': 2,
    'orderedStageCount': 8,
    'closedOperationCount': 23,
    'fullVerifyExecuteReceiptChainCompletedOffline': True,
    'freshDependenciesAtEveryStageTested': True,
    'exactPhaseConfirmationCount': 8,
    'testAndProdTargetsRejected': True,
    'currentlyLiveEnabledEnvironmentCount': 0,
}
for key in ('existingLiveAdaptersModified', 'liveTransportImplemented',
            'liveCliImplemented', 'devLiveEnabled', 'testLiveEnabled',
            'prodLiveEnabled', 'newLiveExecutionAuthorized'):
    assert contract[key] is False
assert contract['historicalTeardownAndScopedAuditClosed'] is True
effects = contract['effectFlags']
for key in ('inMemoryPrivateFixtureReads', 'localPrivateReceiptFileWrites'):
    assert effects[key] is True
for key in ('systemClockReads', 'livePrivateEvidenceReads',
            'environmentVariableReads', 'cloudTransport',
            'kubernetesTransport', 'terraformCommands', 'cloudMutation',
            'kubernetesMutation', 'secretValueRead',
            'automaticRetryOrRepair'):
    assert effects[key] is False

for path in (contract_path, document_path):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.10 source/AST/privacy pins passed; injected dev offline command entry only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.10-dev-command-entry-conformance.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.9-dev-transport-conformance.sh"
echo "v0.11.9.3.6.7.7.10 passed; no CLI, live private reader, live transport or execution authorization was added."

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
import guarded_dev_transport_conformance_v6779 as core
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.9-dev-offline-transport-conformance-and-durable-receipts.json'
document_path = 'docs/V0.11.9.3.6.7.7.9_DEV_OFFLINE_TRANSPORT_CONFORMANCE_AND_DURABLE_RECEIPTS.md'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '561523ee050ce672829bbb920371cb0d85569d0a27bd9a4af4d003ee38df9742', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.9'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.8'
assert contract['implementationBaselineCommit'] == '2b117736fbc9152bc6f97a76783df90d0a727800'
assert contract['status'] == 'dev-offline-transport-conformance-and-durable-receipts-implemented'
assert contract['environmentProfile'] == core.ENVIRONMENT == 'aws-dev'
assert contract['stageOrder'] == list(STAGES)
assert contract['closedOperationCount'] == sum(map(len, STAGE_OPERATIONS.values())) == 23
assert tuple(core.FAULT_POINTS) == tuple(contract['faultInjection']['faultPoints'])
assert len(core.FAULT_POINTS) == contract['faultInjection']['deterministicLocalIoFaultPointCount'] == 12

for prefix in ('core', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert methods == contract['testMethods']
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 33

tree = ast.parse((root / contract['corePath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == {
    'ReceiptStoreStopped', 'ConformanceStopped', 'ReceiptFaultInjector',
    'DurableReceiptStore', 'DevConformanceTransport',
    'DevTransportConformanceHarness',
}
allowed = {'__future__', 'hashlib', 'json', 'os', 'pathlib', 're', 'stat',
           'guarded_live_migration_contract_v6778', 'guarded_runtime_rules'}
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        assert all(item.name in allowed for item in node.names)
    if isinstance(node, ast.ImportFrom):
        assert node.module in allowed
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            assert node.func.id not in {'exec', 'eval', '__import__', 'open', 'print'}
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                'run', 'Popen', 'system', 'popen', 'getenv', 'putenv',
                'now', 'utcnow', 'unlink', 'remove', 'rename', 'replace',
                'write_text', 'read_text',
            }

assert contract['transportConformance'] == {
    'transportSchema': 'guarded-live-transport-v1',
    'responseSchema': 'guarded-live-transport-response-v1',
    'implementation': 'fixed-fake-only',
    'closedDispatch': True,
    'canonicalRequestAndResponseBytes': True,
    'exactOperationSetHashRequired': True,
    'approvalShapeReusedFromPredecessor': True,
    'requestCarriesPrivateResourceIdentity': False,
    'liveBackendPresent': False,
}
assert contract['durableReceiptStore'] == {
    'protocol': ['intent', 'receipt', 'completion'],
    'directoryMode': '0700',
    'fileMode': '0600',
    'canonicalJson': True,
    'exclusiveCreate': True,
    'fileAndDirectoryFsync': True,
    'symlinkAndHardlinkRejected': True,
    'exactMainAndPredecessorChain': True,
    'partialTripletBlocksFurtherExecution': True,
    'repairOrResetImplemented': False,
    'restartRecoveryTested': True,
    'localPrivateFileWritesOnly': True,
}
assert contract['reviewResult'] == {
    'environment': 'aws-dev',
    'orderedStageCount': 8,
    'closedOperationCount': 23,
    'fullReceiptChainCompletedOffline': True,
    'processRestartAtEveryStageTested': True,
    'testAndProdTargetsRejected': True,
    'deterministicIoFaultPointCount': 12,
    'currentlyLiveEnabledEnvironmentCount': 0,
}
for key in ('existingLiveAdaptersModified', 'liveTransportImplemented',
            'approvalCommandImplemented', 'devLiveEnabled', 'testLiveEnabled',
            'prodLiveEnabled', 'newLiveExecutionAuthorized'):
    assert contract[key] is False
assert contract['historicalTeardownAndScopedAuditClosed'] is True
effects = contract['effectFlags']
assert effects['localPrivateReceiptFileWrites'] is True
for key in ('cloudTransport', 'kubernetesTransport', 'terraformCommands',
            'privateEvidenceReads', 'systemClockReads', 'cloudMutation',
            'kubernetesMutation', 'secretValueRead', 'automaticRetryOrRepair'):
    assert effects[key] is False

for path in (contract_path, document_path):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.9 source/AST/privacy pins passed; dev fixed-fake transport and local durable receipts only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.9-dev-transport-conformance.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.8-live-migration-contract.sh"
echo "v0.11.9.3.6.7.7.9 passed; no live transport, command entry point or execution authorization was added."

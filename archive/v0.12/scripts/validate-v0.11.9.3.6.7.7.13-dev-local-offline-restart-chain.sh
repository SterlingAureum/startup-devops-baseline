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
contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.13-dev-local-offline-restart-chain.json'
document_path = 'docs/V0.11.9.3.6.7.7.13_DEV_LOCAL_OFFLINE_RESTART_CHAIN.md'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == 'fffce85e1a62c6f7c14e1d62a8fa8b1c048b41e7ce9007c330ae5e514546dd31', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.13'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.12'
assert contract['implementationBaselineCommit'] == 'e729e8966b3d1ab208ea47302498fb6b2416adc3'
assert contract['status'] == 'dev-local-offline-restart-chain-exercised'
assert contract['environmentProfile'] == 'aws-dev'
for prefix in ('entry', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert methods == contract['testMethods']
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 21

tree = ast.parse((root / contract['entryPath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == {'ChainExerciseStopped', 'PrivateSession'}
allowed = {
    '__future__', 'argparse', 'datetime', 'hashlib', 'json', 'os', 'pathlib',
    're', 'stat', 'subprocess', 'sys',
    'guarded_dev_command_entry_conformance_v67710',
    'guarded_dev_transport_conformance_v6779',
    'guarded_live_migration_contract_v6778', 'guarded_runtime_rules',
}
subprocess_calls = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        assert all(item.name in allowed for item in node.names)
    if isinstance(node, ast.ImportFrom):
        assert node.module in allowed
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            assert node.func.id not in {'exec', 'eval', '__import__', 'input'}
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                'Popen', 'system', 'popen', 'getenv', 'putenv', 'execve',
                'spawnv', 'unlink', 'remove', 'rename',
            }
            if node.func.attr == 'run':
                assert isinstance(node.func.value, ast.Name)
                assert node.func.value.id == 'subprocess'
                subprocess_calls.append(node)
assert len(subprocess_calls) == 1
keywords = {item.arg for item in subprocess_calls[0].keywords}
assert keywords == {'cwd', 'stdin', 'capture_output', 'timeout', 'check'}

source = (root / contract['entryPath']).read_text()
assert '[sys.executable, *argv]' in source
assert 'stdin=subprocess.DEVNULL' in source
assert 'shell=True' not in source and 'os.environ' not in source
assert 'AWS_ENDPOINT' not in source and 'DevConformanceTransport(' not in source
assert 'successful_responses(' not in source
assert "value.add_argument('command', choices=('exercise',))" in source
assert "'synthetic_receipt_chain': True" in source
assert "'live_receipt_acceptable': False" in source

assert contract['offlineChainExercise'] == {
    'commands': ['exercise'],
    'orderedPhaseCount': 8,
    'closedOperationCount': 23,
    'preflightChildProcessCount': 8,
    'executeChildProcessCount': 8,
    'independentChildProcessCount': 16,
    'durableReceiptTripletCount': 8,
    'durableReceiptFileCount': 24,
    'exactPredecessorChainRequired': True,
    'stateBeforeAfterChainRequired': True,
    'completedSessionReplayAccepted': False,
    'fixedFakeTransportOnly': True,
    'syntheticApprovalFixtures': True,
    'syntheticReceiptChain': True,
    'syntheticReceiptConvertibleToLive': False,
}
assert contract['subprocessContract'] == {
    'pythonExecutableOnly': True,
    'shellEnabled': False,
    'standardInput': 'DEVNULL',
    'perChildTimeoutSeconds': 30,
    'automaticRetryOrRepair': False,
    'arbitraryExecutableAccepted': False,
    'environmentVariableReaderImplemented': False,
    'endpointOrTransportSelectorAccepted': False,
}
assert contract['reviewResult'] == {
    'phaseCount': 8,
    'operationCount': 23,
    'preflightProcessCount': 8,
    'executeProcessCount': 8,
    'receiptTripletCount': 8,
    'receiptFileCount': 24,
    'processRestartRecoveryCovered': True,
    'stateContinuityCovered': True,
    'failureAndTimeoutStopCovered': True,
    'currentlyLiveEnabledEnvironmentCount': 0,
}
for key in ('existingLiveAdaptersModified', 'liveTransportImplemented',
            'liveExecutionCliImplemented', 'devLiveEnabled', 'testLiveEnabled',
            'prodLiveEnabled', 'newLiveExecutionAuthorized'):
    assert contract[key] is False
assert contract['historicalTeardownAndScopedAuditClosed'] is True
effects = contract['effectFlags']
for key in ('systemClockReads', 'localPrivateFixtureWrites',
            'localPrivateReceiptFileReads', 'localPrivateReceiptFileWrites',
            'localPythonSubprocesses', 'fixedFakeTransport'):
    assert effects[key] is True
for key in ('environmentVariableReads', 'cloudTransport',
            'kubernetesTransport', 'terraformCommands', 'cloudMutation',
            'kubernetesMutation', 'secretValueRead', 'automaticRetryOrRepair'):
    assert effects[key] is False

for path in (contract_path, document_path):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.13 source/AST/privacy pins passed; full dev chain remains fixed-fake only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.13-dev-local-offline-restart-chain.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.12-dev-local-offline-execute.sh"
echo "v0.11.9.3.6.7.7.13 passed; eight phases restarted locally with synthetic receipts only."

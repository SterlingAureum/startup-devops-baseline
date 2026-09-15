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
contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.12-dev-local-offline-execute.json'
document_path = 'docs/V0.11.9.3.6.7.7.12_DEV_LOCAL_OFFLINE_EXECUTE.md'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == 'e917e25625322a7e7998907df93f67fca2674ff59c5ab0f01e397e948f92c82b', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.12'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.11'
assert contract['implementationBaselineCommit'] == 'bca57aa8f9e12bc002aabea97141de12a5b4f43f'
assert contract['status'] == 'dev-local-offline-execute-implemented'
assert contract['environmentProfile'] == 'aws-dev'
for prefix in ('entry', 'test'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert methods == contract['testMethods']
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 23

tree = ast.parse((root / contract['entryPath']).read_text())
classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
assert classes == {'LocalExecuteStopped', 'TwoReadSystemUtcClock',
                   'StrictPrivateExecutionFiles'}
allowed = {
    '__future__', 'argparse', 'datetime', 'json', 'os', 'pathlib', 're',
    'stat', 'sys', 'guarded_dev_command_entry_conformance_v67710',
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
            assert node.func.id not in {'exec', 'eval', '__import__', 'input'}
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {
                'run', 'Popen', 'system', 'popen', 'getenv', 'putenv',
                'execve', 'spawnv', 'write_bytes', 'write_text', 'unlink',
                'remove', 'rename',
            }

source = (root / contract['entryPath']).read_text()
assert "entry.dispatch('execute', request, fake)" in source
assert 'DevConformanceTransport(successful_responses(args.phase))' in source
assert "add_argument('verify'" not in source
assert 'shell=True' not in source
assert '_reviewed_verify(' in source

assert contract['localOfflineExecute'] == {
    'commands': ['execute'],
    'phaseSpecificConfirmationCount': 8,
    'freshPreflightRequired': True,
    'preflightSha256Required': True,
    'preflightConvertedToInheritedReviewedVerify': True,
    'fixedFakeTransportOnly': True,
    'onePhasePerInvocation': True,
    'oneReceiptPerSuccessfulInvocation': True,
    'samePhaseReplayAccepted': False,
    'environmentVariableReaderImplemented': False,
    'arbitraryEndpointAccepted': False,
    'hostUtcReadCount': 2,
}
assert contract['receiptContract'] == {
    'store': 'v0.11.9.3.6.7.7.9-local-durable-store',
    'existingPrefixRevalidated': True,
    'intentReceiptCompletionTriplet': True,
    'exclusiveCreationAndFsyncInherited': True,
    'pendingOrUnexpectedStateBlocks': True,
    'exactPhasePredecessorRequired': True,
    'writesOnSuccessfulFixedFakeOnly': True,
}
assert contract['reviewResult'] == {
    'environment': 'aws-dev',
    'commandCount': 1,
    'orderedStageCount': 8,
    'closedOperationCount': 23,
    'actualSubprocessCovered': True,
    'strictFileScopeCovered': True,
    'freshPreflightAndCompletionClockCovered': True,
    'receiptRestartAndReplayCovered': True,
    'testAndProdApprovalTargetsRejected': True,
    'currentlyLiveEnabledEnvironmentCount': 0,
}
for key in ('existingLiveAdaptersModified', 'liveTransportImplemented',
            'liveExecutionCliImplemented', 'devLiveEnabled', 'testLiveEnabled',
            'prodLiveEnabled', 'newLiveExecutionAuthorized'):
    assert contract[key] is False
assert contract['historicalTeardownAndScopedAuditClosed'] is True
effects = contract['effectFlags']
for key in ('systemClockReads', 'localPrivateFileReads',
            'localPrivateReceiptFileReads', 'localPrivateReceiptFileWrites',
            'fixedFakeTransport'):
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
print('v0.11.9.3.6.7.7.12 source/AST/privacy pins passed; dev local fixed-fake execute only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.12-dev-local-offline-execute.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.11-dev-local-cli-preflight.sh"
echo "v0.11.9.3.6.7.7.12 passed; fixed fake and local receipt only, no live transport or authority."

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
import guarded_dev_injected_transport_protocol_v67716 as protocol
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.17-dev-restart-safe-receipt-adapter.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '0972d29ce3c12dc6769020e18b0683f11cea4f38cff2c85a0ead3813cdef63bc', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == adapter.VERSION
assert contract['predecessor'] == adapter.PREDECESSOR == protocol.VERSION
assert contract['implementationBaselineCommit'] == 'f3a85b5ffc22a927076c6a37a9338b18d110b50c'
assert contract['status'] == 'dev-restart-safe-offline-receipt-adapter-implemented'
assert digest(contract['corePath']) == contract['coreSha256']
assert digest(contract['testPath']) == contract['testSha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

summary = contract['adapterSummary']
assert summary['environment'] == adapter.ENVIRONMENT == 'aws-dev'
assert summary['designedStageCount'] == len(STAGES) == 8
assert summary['closedOperationCount'] == sum(len(STAGE_OPERATIONS[p]) for p in STAGES) == 23
assert summary['durableFileCountAfterCompleteChain'] == len(STAGES) * 3 == 24
assert summary['strictDirectoryMode'] == '0700'
assert summary['strictFileMode'] == '0600'
for key in ('exclusiveNoFollowWrites', 'fileAndDirectoryFsync',
            'attemptBeforeFixedFakeCall',
            'exactAttemptReceiptCompletionTriplet', 'restartPrefixValidation',
            'stateContinuityAcrossRestart', 'partialOrPendingTripletBlocks',
            'unknownEntryBlocks', 'fixedFakeTransportOnly'):
    assert summary[key] is True, key
for key in ('automaticRetryOrRepair', 'syntheticReceiptUsableForLive',
            'incidentOnlyPowersEnabled'):
    assert summary[key] is False, key
assert len(adapter.FAULT_POINTS) == 12

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 41

core_tree = ast.parse((root / contract['corePath']).read_text())
allowed = {'__future__', 'json', 'os', 'pathlib', 'stat',
           'guarded_dev_injected_transport_protocol_v67716',
           'guarded_dev_live_transport_design_v67715',
           'guarded_live_migration_contract_v6778', 'guarded_runtime_rules'}
for node in ast.walk(core_tree):
    if isinstance(node, ast.Import):
        assert all(item.name in allowed for item in node.names)
    if isinstance(node, ast.ImportFrom):
        assert node.module in allowed
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            assert node.func.id not in {'exec', 'eval', '__import__', 'open', 'print'}
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {'run', 'Popen', 'system', 'getenv',
                                          'now', 'utcnow', 'read_text',
                                          'write_text', 'unlink', 'remove',
                                          'rename', 'replace'}

effects = contract['effectFlags']
for key in ('filesystemReads', 'filesystemWrites',
            'privateReceiptDirectoryReads', 'privateReceiptDirectoryWrites'):
    assert effects[key] is True, key
for key in ('systemClockReads', 'environmentVariableReads', 'credentialReads',
            'subprocesses', 'cloudTransport', 'kubernetesTransport',
            'terraformCommands', 'cloudMutation', 'kubernetesMutation',
            'secretValueRead', 'automaticRetryOrRepair'):
    assert effects[key] is False, key
for key in ('existingLiveAdaptersModified', 'liveBackendImplemented',
            'liveTransportImplemented', 'liveExecutionCliImplemented',
            'durableLiveReceiptStoreImplemented', 'devLiveEnabled',
            'testLiveEnabled', 'prodLiveEnabled',
            'newLiveExecutionAuthorized'):
    assert contract[key] is False, key

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.17_DEV_RESTART_SAFE_RECEIPT_ADAPTER.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.17 source/AST/privacy pins passed; adapter remains local fixed-fake only.')
PYTHON

PYTHONDONTWRITEBYTECODE=1 \
  python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.17-dev-restart-safe-receipt-adapter.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.16-dev-injected-transport-protocol.sh"
echo "v0.11.9.3.6.7.7.17 passed; no live backend, credential reader, command or authority was added."

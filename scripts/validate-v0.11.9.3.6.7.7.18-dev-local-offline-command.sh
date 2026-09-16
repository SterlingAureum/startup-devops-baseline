#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.18-dev-local-offline-command.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

command_path = root / contract['commandPath']
spec = importlib.util.spec_from_file_location('dev_local_command_v67718', command_path)
command = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(command)

assert digest(contract_path) == '8776400e236d63c1ee07cda22422ef713d0121e54821fddadcc5f8a53876e7f3', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == command.VERSION
assert contract['predecessor'] == command.PREDECESSOR == adapter.VERSION
assert contract['implementationBaselineCommit'] == '8604d32e5bc1d093323d7bb4c990fb4a1d5d2b3e'
assert contract['status'] == 'dev-restart-safe-local-offline-command-implemented'
assert digest(contract['commandPath']) == contract['commandSha256']
assert digest(contract['testPath']) == contract['testSha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

summary = contract['commandSummary']
assert summary['environment'] == command.ENVIRONMENT == 'aws-dev'
assert summary['commandCount'] == 2
assert summary['commands'] == ['verify', 'execute']
assert summary['designedStageCount'] == len(STAGES) == 8
assert summary['closedOperationCount'] == sum(len(STAGE_OPERATIONS[p]) for p in STAGES) == 23
assert summary['verifySystemClockReadCount'] == 1
assert summary['executeSystemClockReadCount'] == 2
assert summary['strictPrivateDirectoryMode'] == '0700'
assert summary['strictPrivateFileMode'] == '0600'
for key in ('bundleAndPreflightHashBound',
            'separateVerifyAndExecuteConfirmations',
            'prefixRevalidatedBeforeExecute',
            'postconditionsNormalizedToFrozenOrder',
            'restartSafeTripletAdapterOnly', 'fixedFakeTransportOnly',
            'fullEightStageCommandChainCovered'):
    assert summary[key] is True, key
for key in ('automaticRetryOrRepair', 'syntheticReceiptUsableForLive'):
    assert summary[key] is False, key

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 38

tree = ast.parse(command_path.read_text())
allowed = {'__future__', 'argparse', 'datetime', 'json', 'os', 'pathlib',
           're', 'stat', 'sys',
           'guarded_dev_injected_transport_protocol_v67716',
           'guarded_dev_restart_safe_receipt_adapter_v67717',
           'guarded_dev_live_transport_design_v67715',
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
            assert node.func.attr not in {'run', 'Popen', 'system', 'getenv',
                                          'environ', 'unlink', 'remove',
                                          'rename', 'write_text',
                                          'write_bytes'}

effects = contract['effectFlags']
for key in ('filesystemReads', 'filesystemWrites', 'privateInputReads',
            'privateReceiptWrites', 'systemClockReads'):
    assert effects[key] is True, key
for key in ('environmentVariableReads', 'credentialReads', 'subprocesses',
            'cloudTransport', 'kubernetesTransport', 'terraformCommands',
            'cloudMutation', 'kubernetesMutation', 'secretValueRead',
            'automaticRetryOrRepair'):
    assert effects[key] is False, key
assert contract['localOfflineCommandImplemented'] is True
for key in ('existingLiveAdaptersModified', 'liveBackendImplemented',
            'liveTransportImplemented', 'liveExecutionCliImplemented',
            'durableLiveReceiptStoreImplemented', 'devLiveEnabled',
            'testLiveEnabled', 'prodLiveEnabled',
            'newLiveExecutionAuthorized'):
    assert contract[key] is False, key

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.18_DEV_LOCAL_OFFLINE_COMMAND.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.18 source/AST/privacy pins passed; commands remain local fixed-fake only.')
PYTHON

PYTHONDONTWRITEBYTECODE=1 \
  python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.18-dev-local-offline-command.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.17-dev-restart-safe-receipt-adapter.sh"
echo "v0.11.9.3.6.7.7.18 passed; no live backend, credential reader or authority was added."

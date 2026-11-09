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
import guarded_dev_live_transport_design_v67715 as design
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.16-dev-injected-transport-protocol.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '51c365ecb788f3d4bce23c76d5b11aa7bd01836ea2fd9d9bb8cf9c83c27e9060', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == protocol.VERSION
assert contract['predecessor'] == protocol.PREDECESSOR == 'v0.11.9.3.6.7.7.15'
assert contract['implementationBaselineCommit'] == 'f006cc2be6ebbdee1dd874a89f70fbd6bdaf2a95'
assert contract['status'] == 'dev-injected-transport-protocol-conformance-implemented-offline'
assert digest(contract['corePath']) == contract['coreSha256']
assert digest(contract['testPath']) == contract['testSha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

summary = contract['protocolSummary']
assert summary['environment'] == protocol.ENVIRONMENT == 'aws-dev'
assert summary['designedStageCount'] == len(STAGES) == 8
assert summary['closedOperationCount'] == sum(len(STAGE_OPERATIONS[p]) for p in STAGES) == 23
assert summary['terraformSavedPlanStageCount'] == 2
for key in ('fixedFakeTransport', 'fixedFakeJournal',
            'canonicalRequestAndResponse', 'writeAheadIntent',
            'oneIntentOneCall', 'terminalRecordAfterPostconditions',
            'exactReceiptPrefix', 'exactStateRelation'):
    assert summary[key] is True, key
for key in ('automaticRetryOrRepair',
            'historicalOrLiveReceiptAcceptedAsOfflinePrefix',
            'syntheticReceiptUsableForLive', 'durableReceiptWritten',
            'incidentOnlyPowersEnabled'):
    assert summary[key] is False, key
assert protocol.REQUEST_SCHEMA == design.REQUEST_SCHEMA
assert protocol.RESPONSE_SCHEMA == design.RESPONSE_SCHEMA
assert protocol.APPROVAL_SCHEMA == design.APPROVAL_SCHEMA
assert protocol.RECEIPT_SCHEMA == design.RECEIPT_SCHEMA
assert set(protocol.COMMON_BINDINGS) <= set(protocol.APPROVAL_FIELDS) | {'approval_sha256'}

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 50

core_tree = ast.parse((root / contract['corePath']).read_text())
allowed = {'__future__', 'decimal', 'hashlib', 'json', 're',
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
                                          'now', 'utcnow', 'open', 'read_text',
                                          'write_text', 'unlink'}

for key, value in contract['effectFlags'].items():
    assert value is False, key
for key in ('existingLiveAdaptersModified', 'liveBackendImplemented',
            'liveTransportImplemented', 'liveExecutionCliImplemented',
            'durableLiveReceiptStoreImplemented', 'devLiveEnabled',
            'testLiveEnabled', 'prodLiveEnabled',
            'newLiveExecutionAuthorized'):
    assert contract[key] is False, key

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.16_DEV_INJECTED_TRANSPORT_PROTOCOL.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.16 source/AST/privacy pins passed; protocol remains fixed-fake only.')
PYTHON

PYTHONDONTWRITEBYTECODE=1 \
  python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.16-dev-injected-transport-protocol.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.15-dev-live-transport-design.sh"
echo "v0.11.9.3.6.7.7.16 passed; no live backend, command or authority was added."

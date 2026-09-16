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
import guarded_dev_live_transport_design_v67715 as design

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.15-dev-live-transport-design.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()
canonical = lambda value: json.dumps(
    value, sort_keys=True, separators=(',', ':')).encode()

assert digest(contract_path) == '5c5ac5a670f159e2a25013a75beeea75ec7355ec13abef5e50b506604f78a21b', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.15'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.14'
assert contract['implementationBaselineCommit'] == '3be7f0248e11b1df0d427c7f61498f81063441d0'
assert contract['status'] == 'dev-versioned-live-transport-designed-offline'
assert digest(contract['corePath']) == contract['coreSha256']
assert digest(contract['testPath']) == contract['testSha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

candidate = design.expected_design()
assert hashlib.sha256(canonical(candidate)).hexdigest() == contract['canonicalDesignSha256']
gap_review = json.loads((root / contract['frozenSources'][0]['path']).read_text())
result = design.review_dev_live_transport_design(gap_review, candidate)
summary = contract['designSummary']
assert result['designedStageCount'] == summary['designedStageCount'] == 8
assert result['closedOperationCount'] == summary['closedOperationCount'] == 23
assert result['gapDesignCount'] == summary['gapDesignCount'] == 9
assert result['structuralBlockingGapDesignCount'] == summary['structuralBlockingGapDesignCount'] == 8
assert result['liveImplementedGapCount'] == summary['liveImplementedGapCount'] == 0
assert result['incidentOnlyPowerCount'] == summary['incidentOnlyPowerCount'] == 7
assert not result['incidentOnlyPowersEnabled']
assert not result['legacyDestroyWrapperCallable']
assert not result['devLiveTransportImplemented']
assert not result['devLiveCommandImplemented']
assert not result['devLiveExecutionAuthorized']
assert not result['testLiveEnabled'] and not result['prodLiveEnabled']
assert summary['transportSchema'] == design.TRANSPORT_SCHEMA
assert summary['requestSchema'] == design.REQUEST_SCHEMA
assert summary['responseSchema'] == design.RESPONSE_SCHEMA
assert summary['approvalSchema'] == design.APPROVAL_SCHEMA
assert summary['receiptSchema'] == design.RECEIPT_SCHEMA
assert sum(row['savedPlanBundleRequired'] for row in candidate['stageDesigns']) == summary['terraformSavedPlanStageCount'] == 2
assert summary['writeAheadIntentRequired']
assert summary['oneTransportCallPerIntent']
assert summary['automaticRetryOrRepair'] is False
assert summary['terminalReceiptAfterPostconditionsOnly']
assert summary['historicalOrSyntheticReceiptAccepted'] is False

test_tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(test_tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 44

core_tree = ast.parse((root / contract['corePath']).read_text())
allowed = {'__future__', 'guarded_dev_live_parity_review_v67714',
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
            assert node.func.attr not in {'run', 'Popen', 'system', 'getenv', 'now',
                                          'utcnow', 'unlink', 'write_text', 'read_text'}

for key, value in contract['effectFlags'].items():
    assert value is False, key
for key in ('existingLiveAdaptersModified', 'liveBackendImplemented',
            'liveTransportImplemented', 'liveExecutionCliImplemented',
            'devLiveEnabled', 'testLiveEnabled', 'prodLiveEnabled',
            'newLiveExecutionAuthorized'):
    assert contract[key] is False, key
assert contract['historicalTeardownAndScopedAuditClosed'] is True

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.15_DEV_LIVE_TRANSPORT_DESIGN.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.15 source/AST/privacy pins passed; dev live transport remains design-only.')
PYTHON

PYTHONDONTWRITEBYTECODE=1 \
  python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.15-dev-live-transport-design.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.14-dev-live-parity-gap-review.sh"
echo "v0.11.9.3.6.7.7.15 passed; dev transport, backend and command remain disabled."

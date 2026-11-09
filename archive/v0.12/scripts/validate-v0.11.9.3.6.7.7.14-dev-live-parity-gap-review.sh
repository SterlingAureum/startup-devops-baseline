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
import guarded_dev_live_parity_review_v67714 as review

contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.14-dev-live-parity-gap-review.json'
contract = json.loads((root / contract_path).read_text())
digest = lambda path: hashlib.sha256((root / path).read_bytes()).hexdigest()

assert digest(contract_path) == '8a96ad3a19c9182c8241520aec3367ae5959ba672e8a387ef0ed479dfa346f57', 'contract drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.14'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.13'
assert contract['implementationBaselineCommit'] == 'cd78d127968fc017364bf0775d84de0f4840cbe5'
assert contract['status'] == 'dev-live-parity-gap-reviewed'
assert digest(contract['corePath']) == contract['coreSha256']
assert digest(contract['testPath']) == contract['testSha256']
for item in contract['frozenSources']:
    assert digest(item['path']) == item['sha256'], item['path']

chain, teardown, audit = [
    json.loads((root / item['path']).read_text())
    for item in contract['frozenSources'][:3]
]
result = review.review_dev_live_parity(
    chain, teardown, audit, contract['gapManifest'])
for key, value in contract['reviewResult'].items():
    assert result[key] == value, key
assert result['status'] == 'dev-live-parity-gap-review-complete'
assert result['blockingGapIds'] == [
    row['id'] for row in contract['gapManifest']['gapRows']
    if row['blocksDevLiveTransport']]
assert result['blockingGapCount'] == 8
assert result['historicalLiveReceiptEquivalentStageCount'] == 0
assert not result['devLiveTransportReady']
assert not result['devLiveExecutionAuthorized']
assert not result['testLiveEnabled'] and not result['prodLiveEnabled']

tree = ast.parse((root / contract['testPath']).read_text())
methods = [node.name for node in ast.walk(tree)
           if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
assert len(methods) == len(set(methods)) == contract['testMethodCount'] == 39

core_tree = ast.parse((root / contract['corePath']).read_text())
allowed = {'__future__', 'guarded_live_migration_contract_v6778',
           'guarded_runtime_rules'}
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

destroy = (root / 'scripts/destroy-aws-dev.sh').read_text()
assert destroy.count('run_terraform_destroy') >= 3
assert 'if run_terraform_destroy; then' in destroy
assert 'Known dynamic dependencies converged. Review the new Terraform plan and confirm again.' in destroy
assert 'externalsecret' not in destroy.lower()

for key, value in contract['effectFlags'].items():
    assert value is False, key
for key in ('existingLiveAdaptersModified', 'liveTransportImplemented',
            'liveExecutionCliImplemented', 'devLiveEnabled', 'testLiveEnabled',
            'prodLiveEnabled', 'newLiveExecutionAuthorized'):
    assert contract[key] is False, key
assert contract['historicalTeardownAndScopedAuditClosed'] is True

for path in (contract_path,
             'docs/V0.11.9.3.6.7.7.14_DEV_LIVE_PARITY_GAP_REVIEW.md'):
    text = (root / path).read_text()
    assert '/home/sterling/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.14 source/AST/privacy pins passed; history grants no live receipt authority.')
PYTHON

PYTHONDONTWRITEBYTECODE=1 \
  python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.14-dev-live-parity-gap-review.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.13-dev-local-offline-restart-chain.sh"
echo "v0.11.9.3.6.7.7.14 passed; eight dev live-transport gaps remain fail-closed."

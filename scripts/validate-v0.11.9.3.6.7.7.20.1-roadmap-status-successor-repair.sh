#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import hashlib
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.20.1-roadmap-status-successor-repair.json'
document_path = 'docs/V0.11.9.3.6.7.7.20.1_ROADMAP_STATUS_SUCCESSOR_REPAIR.md'

def digest(path):
    return hashlib.sha256((root / path).read_bytes()).hexdigest()

def load(path):
    return json.loads((root / path).read_text())

contract = load(contract_path)
assert digest(contract_path) == '65c1a4fd7df6125f8fd464e014b5af26d5edc233d0df17afebcf36f6b4ddd719', 'repair contract drift'
assert digest(document_path) == '6a31a93cc737bc2555217396187cc4180cbfd862c947b1555842461bdb2622e5', 'repair document drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.20.1'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.20'
assert contract['implementationBaselineCommit'] == '5995e3f4427151f39dac19f0860fd3cb6e379387'
assert contract['status'] == 'roadmap-status-successor-validation-repaired'
assert contract['failureSignature'] == 'ContractError: Roadmap marker missing: Status: In Progress'

for prefix in ('repairedValidator', 'closureManifest', 'closureContract'):
    assert digest(contract[prefix + 'Path']) == contract[prefix + 'Sha256'], prefix

assert contract['acceptedLifecycleStates'] == [
    'In Progress',
    'Completed with explicit production-readiness deferrals',
]
assert contract['successorRules'] == {
    'statusReadOnlyFromV011Section': True,
    'legacyInProgressRemainsAccepted': True,
    'completedRequiresClosureManifest': True,
    'completedRequiresCheckpoint': 'v0.11.9.3.6.7.7.20',
    'completedRequiresExplicitEnvironmentDeferrals': True,
    'completedRequiresNoNewLiveAuthority': True,
    'completedRequiresAwsProdQualificationGuard': True,
    'completedRequiresProductionReadinessGuard': True,
}
assert contract['negativeLifecycleMutationCount'] == 4
assert set(contract['packageProducer'].values()) == {False}
assert contract['next'].startswith('Re-run the repository quality gates')

source = (root / contract['repairedValidatorPath']).read_text()
assert 'def validate_v011_roadmap_lifecycle(' in source
assert 'closure_manifest_path = root / "delivery/contracts/v0.11-final-evidence-manifest.json"' in source
assert 'Status: Completed with explicit production-readiness deferrals' in source
assert 'Status: In Progress' in source
assert 'newLiveExecutionAuthorized' in source
assert 'aws-prod-is-qualified' in source
assert 'v0.11-proves-full-production-readiness' in source
assert 'Unsafe v0.11 roadmap lifecycle mutation was accepted' in source

roadmap = (root / 'docs/ROADMAP.md').read_text()
start = roadmap.index('## v0.11 - Observability and SRE Baseline')
end = roadmap.index('## v0.12 - Production Readiness Capstone', start)
section = roadmap[start:end]
assert re.search(
    r'^Status: Completed with explicit production-readiness deferrals$',
    section,
    re.MULTILINE,
)

manifest = load(contract['closureManifestPath'])
assert manifest['version'] == 'v0.11'
assert manifest['closureCheckpoint'] == 'v0.11.9.3.6.7.7.20'
assert manifest['status'] == 'completed-with-explicit-environment-deferrals'
assert manifest['newLiveExecutionAuthorized'] is False
assert 'aws-prod-is-qualified' in manifest['forbiddenClaims']
assert 'v0.11-proves-full-production-readiness' in manifest['forbiddenClaims']

for path in (contract_path, document_path, contract['repairedValidatorPath']):
    text = (root / path).read_text()
    assert '/home/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None

print('v0.11.9.3.6.7.7.20.1 source, closure binding and privacy pins passed.')
PYTHON

bash "$ROOT_DIR/scripts/validate-v0.11-observability-sre-foundation.sh"
echo "v0.11.9.3.6.7.7.20.1 passed; the completed roadmap state is successor-aware and remains evidence-bounded."

#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast, hashlib, importlib.util, json, re, sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'scripts'))
spec=importlib.util.spec_from_file_location('teardown',root/'scripts/execute-v0.11.9.3.6.7.6-aws-test-teardown.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.source_checks()
assert hashlib.sha256((root/m.CONTRACT).read_bytes()).hexdigest()=='55afa438d222bceb36f364cacbf347869951d3b113bbff84182ab1a4a90a540a'
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.6'
assert c['implementationBaselineCommit']=='7349131a93f4aabf770965017758fe1cb0f74841'
assert c['runtimeStopUtc']=='2026-09-13T09:21:13Z' and c['cleanupCompleteByUtc']=='2026-09-13T10:51:13Z'
assert c['minimumRuntimeStartSeconds']==1200 and c['minimumTerraformStartSeconds']==900
assert c['runtimeProofTtlSeconds']==900 and c['savedPlanTtlSeconds']==1800
assert c['budget']['totalLimitUsd']=='36.00' and c['budget']['historicalBilledSpendUsd'] is None
raw=(json.dumps(c['reviewedInventory']['summary'],indent=2,sort_keys=True)+'\n').encode()
assert len(raw)==c['reviewedInventory']['artifact']['bytes']==1483
assert hashlib.sha256(raw).hexdigest()==c['reviewedInventory']['artifact']['sha256']
assert not any(c['privacyBoundary'].values()) and not any(c['packageProducer'].values())
assert c['machinePlanGate']['allowedActions']==[['delete'],['no-op'],['read']]
assert set(c['phases'])==set(m.PHASES)
for name in ('scripts/execute-v0.11.9.3.6.7.6-aws-test-teardown.py','scripts/test-v0.11.9.3.6.7.6-aws-test-teardown.py'):ast.parse((root/name).read_text())
for name in (m.CONTRACT,'docs/V0.11.9.3.6.7.6_GUARDED_AWS_TEST_TEARDOWN.md'):
    text=(root/name).read_text()
    assert not any(x in text for x in ('/home/sterling/','arn:aws:','secretMetadataSha256','AKIA'))
    assert re.search(r'(?<![a-zA-Z0-9])[0-9]{12}(?![a-zA-Z0-9])',text) is None
    assert re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32',text) is None
assert hashlib.sha256((root/'.gitleaksignore').read_bytes()).hexdigest()=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6 exact source, inventory, privacy and approval boundaries passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6-aws-test-teardown.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.5.2.1-aws-test-root-execution-evidence.sh"
echo "v0.11.9.3.6.7.6 passed; all validation offline."

#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast, hashlib, importlib.util, json, re, sys
from pathlib import Path
root=Path(sys.argv[1])
p='delivery/contracts/v0.11.9.3.6.7.6.6-guarded-aws-test-residual-cost-audit.json'
assert hashlib.sha256((root/p).read_bytes()).hexdigest()=='1f152a7aa8ad4f11b06a9bcd86fe94cdb69c7e5715870a134190ed706848f0ac', 'audit contract drift'
spec=importlib.util.spec_from_file_location('guarded_audit',root/'scripts/execute-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.source_checks(root)
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.6.6'
assert c['implementationBaselineCommit']=='9513c92d11b1e3ea794b997db04cf5573f8c50bf'
e=json.loads((root/c['teardownEvidencePath']).read_text())
assert hashlib.sha256((root/c['teardownEvidencePath']).read_bytes()).hexdigest()==c['teardownEvidenceSha256']
assert e['operationBoundary']['teardownComplete'] and not e['operationBoundary']['fullResidualCostAuditExecuted']
assert c['finalStateSha256']==e['finalApply']['stateAfterDigest']
assert c['privateInputsSha256']==e['privateInputsDigest'] and c['runtimeRecordSha256']==e['runtimeRecordDigest']
assert c['finalResultSha256']==e['finalApply']['redactedResultDigest']
assert c['eksCompleteSha256']==e['eniSgCleanup']['eksCompletionReceiptDigest']
assert c['maximumWindowSeconds']==14400 and c['minimumStartRemainingSeconds']==900
assert c['verifyTtlSeconds']==900 and c['preflightTtlSeconds']==3600
assert not any(c['operationBoundary'].values())
assert not c['fullAuditScope']['accountWideBillingAudit'] and not c['fullAuditScope']['untrackedUntaggedInventoryExhaustive']
assert c['privateEvidenceBoundary']['preflightParentOneAttemptMarkerRequired'] and not c['privateEvidenceBoundary']['existingAttemptsOverwritten']
assert not c['fullAuditScope']['fleetDeletedRunningAccepted'] and c['fullAuditScope']['fleetDeletedTerminatingRequiresComputeAbsence']
assert not c['fullAuditScope']['instantFleetInstancesApiInvoked']
for name in ('scripts/execute-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py','scripts/test-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py'):ast.parse((root/name).read_text())
for service,ops in m.OPS.items():
    assert all(op.startswith(('get-','list-','describe-')) for op in ops), service
assert 'get-secret-value' not in m.OPS['secretsmanager']
for name in (p,'docs/V0.11.9.3.6.7.6.6_GUARDED_AWS_TEST_RESIDUAL_COST_AUDIT.md'):
    text=(root/name).read_text()
    assert not any(s in text for s in ('/home/sterling/','arn:aws:','secretMetadataSha256','AKIA'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert hashlib.sha256((root/'.gitleaksignore').read_bytes()).hexdigest()=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.6 strict read-only/source/evidence/privacy gates passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.5-teardown-execution-evidence.sh"
echo "v0.11.9.3.6.7.6.6 passed; offline validation only; audit needs separate approval."

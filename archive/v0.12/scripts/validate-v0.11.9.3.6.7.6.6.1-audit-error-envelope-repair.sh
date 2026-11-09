#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,importlib.util,json,re,sys
from pathlib import Path
root=Path(sys.argv[1])
p='delivery/contracts/v0.11.9.3.6.7.6.6.1-aws-test-audit-error-envelope-repair.json'
assert hashlib.sha256((root/p).read_bytes()).hexdigest()=='a3fef47038277295cad9eb6e52c8e0cc371021b8de1a442c0b5dbdd4d8468bec'
spec=importlib.util.spec_from_file_location('error_repair',root/'scripts/execute-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.source_checks(root)
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.6.6.1' and c['predecessor']=='v0.11.9.3.6.7.6.6'
assert c['implementationBaselineCommit']=='decbb109a71e2f0698611ea47a4a7e21169f2331'
old=json.loads((root/'delivery/contracts/v0.11.9.3.6.7.6.6-guarded-aws-test-residual-cost-audit.json').read_text())
for key in ('finalStateSha256','teardownEvidenceSha256','privateInputsSha256','runtimeRecordSha256','finalResultSha256','eksCompleteSha256','maximumWindowSeconds','minimumStartRemainingSeconds','preflightTtlSeconds','verifyTtlSeconds','awsMaximumAttempts','phaseConfirmations','fullAuditScope','operationBoundary'):
    assert c[key]==old[key],key
assert not any(c['operationBoundary'].values())
h=c['priorStoppedPreflight']
raw=b'\nAn error occurred (NoSuchBucket) when calling the ListObjectVersions operation (reached max retries: 0): The specified bucket does not exist\n'
assert len(raw)==h['bucketCommandStderrBytes']==142
assert hashlib.sha256(raw).hexdigest()==h['bucketCommandStderrSha256']
assert m.absence_error(raw,b'','list-object-versions',('NoSuchBucket',))
assert not m.absence_error(raw.replace(b'retries: 0',b'retries: 1'),b'','list-object-versions',('NoSuchBucket',))
assert not h['fullAuditExecuted'] and not h['auditAttemptConsumed'] and not h['awsMutationExecuted']
original=(root/'scripts/execute-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py').read_text().replace('delivery/contracts/v0.11.9.3.6.7.6.6-guarded-aws-test-residual-cost-audit.json','delivery/contracts/v0.11.9.3.6.7.6.6.1-aws-test-audit-error-envelope-repair.json')
updated=(root/'scripts/execute-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py').read_text()
# Ensure the reviewed delta contains only the binding and parser replacement.
a=updated.index('def absence_error(');b=updated.index('class Runner:',a)
updated=updated[:a]+updated[b:]
a=original.index('            codes = re.findall(');b=original.index('            value = None',a)
original=original[:a]+"            require(absence_error(err.read_bytes(), out.read_bytes(), operation, absent), 'aws-error-not-absence')\n"+original[b:]
assert original==updated,'unexpected read-only executor change'
for name in ('scripts/execute-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py','scripts/test-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py'):ast.parse((root/name).read_text())
for name in (p,'docs/V0.11.9.3.6.7.6.6.1_AWS_TEST_AUDIT_ERROR_ENVELOPE_REPAIR.md'):
    text=(root/name).read_text()
    assert not any(s in text for s in ('/home/sterling/','arn:aws:','secretMetadataSha256','AKIA'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert hashlib.sha256((root/'.gitleaksignore').read_bytes()).hexdigest()=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.6.1 exact zero-retry envelope/source/history/privacy gates passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.6-guarded-residual-cost-audit.sh"
echo "v0.11.9.3.6.7.6.6.1 passed; offline repair only; fresh preflight and separate audit approval required."

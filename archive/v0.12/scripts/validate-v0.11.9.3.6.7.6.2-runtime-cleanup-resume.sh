#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,importlib.util,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'scripts'))
spec=importlib.util.spec_from_file_location('partial_resume',root/'scripts/execute-v0.11.9.3.6.7.6.2-aws-test-teardown.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.source_checks()
assert hashlib.sha256((root/m.CONTRACT).read_bytes()).hexdigest()=='e59acf63f41ee791b14f2fae8b3013aeabac20d01046afab467454b2b5bab009'
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.6.2'
assert c['implementationBaselineCommit']=='a7390ea95be2539e20f37b81a82efebf213f16cd'
assert c['runtimeStopUtc']=='2026-09-13T12:30:00Z' and c['cleanupCompleteByUtc']=='2026-09-13T14:00:00Z'
assert c['renewedSchedule']['runtimeLatestStartUtc']=='2026-09-13T12:10:00Z'
assert c['renewedSchedule']['userConfirmedCandidate'] and not c['renewedSchedule']['scheduleConfirmationAuthorizesDeletion']
assert m.projection(c)['estimated_total_usd']=='31.97' and c['budget']['totalLimitUsd']=='36.00'
assert c['budget']['historicalBilledSpendUsd'] is None and not c['historicalWindow']['approvalReused']
raw=(json.dumps(c['priorFailure']['failureResult'],indent=2,sort_keys=True)+'\n').encode()
assert len(raw)==258 and hashlib.sha256(raw).hexdigest()==c['priorFailure']['artifacts']['failure']['sha256']
err="error: unexpected -o output mode: json. We only support '-o name'\n".encode()
assert len(err)==66 and hashlib.sha256(err).hexdigest()==c['priorFailure']['artifacts']['deleteStderr']['sha256']
assert c['priorFailure']['mutationAttemptCount']==21 and c['priorFailure']['completedFreezeCount']==19
assert c['deletionOutput']['format']=='name' and not c['deletionOutput']['jsonParsingAllowed']
assert set(c['phases'])==set(m.PHASES) and not c['phases']['execute-resume']['repeatCompletedFreeze']
assert not any(c['privacyBoundary'].values()) and not any(c['packageProducer'].values())
for name in ('scripts/execute-v0.11.9.3.6.7.6.2-aws-test-teardown.py','scripts/test-v0.11.9.3.6.7.6.2-aws-test-teardown.py'):ast.parse((root/name).read_text())
for name in (m.CONTRACT,'docs/V0.11.9.3.6.7.6.2_AWS_TEST_RUNTIME_CLEANUP_RESUME.md'):
    text=(root/name).read_text()
    assert not any(x in text for x in ('/home/sterling/','arn:aws:','secretMetadataSha256','AKIA'))
    assert re.search(r'(?<![a-zA-Z0-9])[0-9]{12}(?![a-zA-Z0-9])',text) is None
    assert re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32',text) is None
assert hashlib.sha256((root/'.gitleaksignore').read_bytes()).hexdigest()=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.2 failure/partial-resume/source/time/budget/privacy boundaries passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6.2-aws-test-teardown.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.1-cleanup-window-renewal.sh"
echo "v0.11.9.3.6.7.6.2 passed; all validation offline."

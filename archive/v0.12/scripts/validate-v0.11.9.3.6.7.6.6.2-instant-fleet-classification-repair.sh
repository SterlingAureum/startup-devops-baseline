#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,importlib.util,json,re,sys
from pathlib import Path
root=Path(sys.argv[1])
contract='delivery/contracts/v0.11.9.3.6.7.6.6.2-aws-test-instant-fleet-classification-repair.json'
assert hashlib.sha256((root/contract).read_bytes()).hexdigest()=='d0b833a780e840f8d46100d356934bfc2e2c27af8d32fd7d785a4b3537b0bc18'
spec=importlib.util.spec_from_file_location('instant_repair',root/'scripts/execute-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
c=m.source_checks(root)
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.6.6.2' and c['predecessor']=='v0.11.9.3.6.7.6.6.1'
assert c['implementationBaselineCommit']=='ee31819423ae4746f06ae78755fa9292f8ab43dc'
old=json.loads((root/'delivery/contracts/v0.11.9.3.6.7.6.6.1-aws-test-audit-error-envelope-repair.json').read_text())
for key in ('finalStateSha256','teardownEvidenceSha256','privateInputsSha256','runtimeRecordSha256','finalResultSha256','eksCompleteSha256','maximumWindowSeconds','minimumStartRemainingSeconds','preflightTtlSeconds','verifyTtlSeconds','awsMaximumAttempts','phaseConfirmations','fullAuditScope','operationBoundary','errorCompatibility'):
    assert c[key]==old[key],key
assert not any(c['operationBoundary'].values())
assert m.EXEC_CONFIRM=='execute-reviewed-aws-test-residual-cost-audit-once'
h=c['priorStoppedAudit']
assert h['fullAuditExecuted'] and h['auditAttemptConsumed'] and not h['auditPassed'] and not h['awsMutationExecuted']
assert h['fleetTypeRestated']=='instant' and h['fleetStateRestated']=='active' and h['tagSweepRecordCount']==5
shared=ast.parse((root/'scripts/aws_fleet_audit_classification.py').read_text())
assert {n.names[0].name for n in ast.walk(shared) if isinstance(n,ast.Import)}=={'math','re'}
assert not any(isinstance(n,ast.ImportFrom) for n in ast.walk(shared))
updated=(root/'scripts/execute-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py').read_text()
original=(root/'scripts/execute-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py').read_text().replace('delivery/contracts/v0.11.9.3.6.7.6.6.1-aws-test-audit-error-envelope-repair.json','delivery/contracts/v0.11.9.3.6.7.6.6.2-aws-test-instant-fleet-classification-repair.json')
# Normalize exactly the reviewed binding/import/counter/Fleet-branch delta.
updated=updated.replace('import importlib.util\n','',1)
a=updated.index('_fleet_spec =');b=updated.index('STATE =',a)
updated=updated[:a]+updated[b:]
updated=updated.replace('\n        self.instant_history_fleets = 0; self.instant_history_instance_ids = set()','',1)
a=updated.index("        require(r.compute_verified, 'fleet-native-absence-proof-required')")
b=updated.index('    ec2 = re.fullmatch',a)
x=original.index('        if value is not None:',original.index('    fleet = re.fullmatch'))
y=original.index('    ec2 = re.fullmatch',x)
updated=updated[:a]+original[x:y]+updated[b:]
updated=updated.replace("\n            'accepted_instant_fleet_history_count':r.instant_history_fleets,\n            'verified_instant_fleet_instance_count':len(r.instant_history_instance_ids),",'',1)
assert updated==original,'unexpected executor change outside Fleet repair'
dev=json.loads((root/'delivery/contracts/v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.json').read_text())
assert dev['execution']['terminalOrExpiredFleetRecordCount']==8
for name in ('scripts/execute-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py','scripts/test-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py','scripts/aws_fleet_audit_classification.py'):ast.parse((root/name).read_text())
for name in (contract,'docs/V0.11.9.3.6.7.6.6.2_AWS_TEST_INSTANT_FLEET_CLASSIFICATION_REPAIR.md'):
    text=(root/name).read_text()
    assert not any(s in text for s in ('/home/sterling/','arn:aws:','secretMetadataSha256','AKIA'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert hashlib.sha256((root/'.gitleaksignore').read_bytes()).hexdigest()=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.6.2 typed instant Fleet/source/history/privacy gates passed.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.6.1-audit-error-envelope-repair.sh"
echo "v0.11.9.3.6.7.6.6.2 passed; offline Fleet repair only; fresh proofs and separate audit approval required."

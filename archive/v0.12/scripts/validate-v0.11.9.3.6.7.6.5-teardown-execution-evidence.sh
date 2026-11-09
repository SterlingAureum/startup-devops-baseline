#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import hashlib, json, re, sys
from datetime import datetime
from pathlib import Path
root = Path(sys.argv[1])
contract_path = 'delivery/contracts/v0.11.9.3.6.7.6.5-aws-test-teardown-execution-evidence.json'
raw = (root / contract_path).read_bytes()
assert hashlib.sha256(raw).hexdigest() == '684e0fe9d13005dffd08f4dbbc53709dafc6404edc776c1e783eaab473a68531', 'evidence contract drift'
c = json.loads(raw)
assert c['version'] == c['schemaVersion'] == 'v0.11.9.3.6.7.6.5'
assert c['predecessor'] == 'v0.11.9.3.6.7.6.4'
assert c['status'] == 'aws-test-teardown-execution-recorded'
assert c['targetEnvironment'] == 'aws-test' and c['awsRegion'] == 'us-east-1'
main = c['implementationBaselineCommit']
assert main == '00de317b356d9318288fbd30acaf8df0caa6ca93'
g = c['guardedImplementation']
for key in ('contract', 'executor'):
    assert hashlib.sha256((root / g[key + 'Path']).read_bytes()).hexdigest() == g[key + 'Sha256']
predecessor = json.loads((root / g['contractPath']).read_text())
assert c['privateInputsDigest'] == predecessor['inputsSha256']
assert c['runtimeRecordDigest'] == '67a642cc38bbf1198d3bab31da6814b6b79d266fa180a9a8a752827f0dc171ab'
def instant(value): return datetime.fromisoformat(value.replace('Z', '+00:00'))
for key in ('eksPlan', 'eksApply', 'eniSgCleanup', 'finalPlan', 'finalApply', 'nextDayLocalCheck'):
    assert c[key]['controlPlaneCommit'] == main
for plan, apply in (('eksPlan', 'eksApply'), ('finalPlan', 'finalApply')):
    a, p = c[apply], c[plan]
    assert instant(p['createdAtUtc']) < instant(a['startedAtUtc']) < instant(p['expiresAtUtc'])
    assert instant(a['startedAtUtc']) < instant(a['completedAtUtc'])
    assert (instant(p['expiresAtUtc']) - instant(p['createdAtUtc'])).total_seconds() == predecessor['savedPlanTtlSeconds']
assert sum(c['eksPlan']['moduleDeleteCounts'].values()) == c['eksPlan']['managedDeleteCount'] == 50
assert c['eksPlan']['moduleDeleteCounts']['module.eks'] == 19
assert c['remainingConfiguration']['configurationDeleteCount'] == 2 + 3
assert not c['remainingConfiguration']['completedRuntimeDeletionsRepeated']
a, repair, final = c['eksApply'], c['eniSgCleanup'], c['finalApply']
assert a['executorExit'] == 1 and a['stoppedAtStage'] == 'orphan-sg-interfaces'
assert a['terraformApplySucceededBeforePostcheckStop']
assert a['plannedDeletesStillInStateCount'] == a['missingExpectedRemainingCount'] == a['unexpectedRemainingCount'] == 0
assert a['remainingManagedCount'] == c['finalPlan']['managedDeleteCount'] == 40
assert a['stateAfterDigest'] == repair['stateDigest'] == c['finalPlan']['stateBeforeDigest']
assert repair['independentlyApproved'] and repair['executorExit'] == 0
assert repair['interfaceDeleteAttemptedOnce'] and repair['groupDeleteAttemptedOnce']
assert repair['capturedInterfaceAbsent'] and repair['capturedGroupAbsent'] and repair['stateUnchanged']
assert instant(repair['startedAtUtc']) < instant(repair['latestStartUtc'])
assert instant(repair['completedAtUtc']) < instant(repair['executionStopUtc'])
assert instant(a['completedAtUtc']) < instant(repair['startedAtUtc']) < instant(c['finalPlan']['createdAtUtc'])
assert final['executorExit'] == 0 and final['terraformApplyExecutedOnce'] and final['independentlyApproved']
assert final['stateResourceBlockCount'] == final['stateResourceInstanceCount'] == final['stateManagedInstanceCount'] == 0
assert final['stateBytes'] == 4536 and final['stateModeRestated'] == '0600'
assert final['stderrBytes'] == 0 and final['stderrDigest'] == hashlib.sha256(b'').hexdigest()
assert final['redactedResultDigest'] == '55feb6ca65193980b910b322236d6bc4a1e2b3ec33cba3d3a6680d56b6b7019e'
restated = (json.dumps(c['finalResultRestated'], indent=2, sort_keys=True) + '\n').encode()
assert len(restated) == final['resultBytes'] == 972
assert hashlib.sha256(restated).hexdigest() == final['redactedResultDigest']
assert c['finalResultRestated']['window_contract_sha256'] == g['contractSha256']
assert c['finalResultRestated']['terraform_state_sha256'] == final['stateAfterDigest']
assert final['stateAfterDigest'] == c['nextDayLocalCheck']['stateDigest'] == 'accd1dc4515df7abc6f2294ff675a1729e2b8cbf1fa5fe3f9a8f42759a58944e'
assert not final['residualCostAuditExecuted']
assert instant(final['completedAtUtc']) < instant(c['historicalBudget']['cleanupCompleteByUtc']) < instant(c['nextDayLocalCheck']['checkedAtUtc'])
assert c['nextDayLocalCheck']['criticalPrivateFilesDigestMatched']
assert not c['nextDayLocalCheck']['cloudObservationExecuted']
for key in ('eksApply', 'eniSgCleanup', 'finalApply'): assert not c[key]['automaticRetryPerformed']
assert not any(c['privacyBoundary'].values()) and not any(c['packageProducer'].values())
boundary = c['operationBoundary']
assert boundary['teardownComplete'] and boundary['completedTeardownMustNotBeRepeated'] and boundary['preservePrivateEvidenceAndAttemptMarkers']
assert not any(boundary[k] for k in ('fullResidualCostAuditExecuted', 'fullResidualCostAuditPassed', 'newLiveExecutionAuthorized', 'oldApprovalsReusable'))
budget = c['historicalBudget']
assert budget['totalLimitUsd'] == '36.00' and budget['estimatedTotalUsd'] == '35.20'
assert budget['historicalBilledSpendUsd'] is None
assert not budget['estimateIsBillingGuarantee'] and not budget['currentPriceQuoteVerified'] and not budget['newExecutionWindowAuthorized']
assert c['finalPlan']['backupVersionCount'] == 9 and c['finalPlan']['backupDeleteMarkerCount'] == 0
assert not c['finalPlan']['inventoryIsAtomic']
checks = c['postApplyChecks']
assert all(checks[k] for k in ('managedStateEmpty', 'eksAbsent', 'vpcAbsent', 'capturedVolumesAbsent', 'testDnsAbsent', 'albAbsent', 'backupBucketAbsent', 'credentialContainerAbsentOrDeletionTombstoneOnly'))
assert not checks['actualCredentialContainerBranchDisclosed'] and not checks['credentialRecoveryPeriodDaysClaimed'] and not checks['wholeAccountResidualCostAuditPassed']
def digests(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k.endswith(('Digest', 'Sha256')): assert re.fullmatch('[0-9a-f]{64}', v), k
            digests(v)
    elif isinstance(value, list):
        for v in value: digests(v)
digests(c)
for name in (contract_path, 'docs/V0.11.9.3.6.7.6.5_AWS_TEST_TEARDOWN_EXECUTION_EVIDENCE.md'):
    public = (root / name).read_text()
    assert not any(x in public for x in ('/home/sterling/', 'arn:aws:', 'secretMetadataSha256', 'AKIA'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', public) is None
    assert re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32', public) is None
assert hashlib.sha256((root / '.gitleaksignore').read_bytes()).hexdigest() == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.5 teardown evidence/state/receipt/clock/privacy gates passed; full residual audit pending.')
PYTHON
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.4-eks-dependency-plan-repair.sh"
echo "v0.11.9.3.6.7.6.5 passed; evidence recording offline; no live approval granted."

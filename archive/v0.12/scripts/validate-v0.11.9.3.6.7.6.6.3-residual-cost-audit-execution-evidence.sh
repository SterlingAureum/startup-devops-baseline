#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import hashlib,json,re,sys
from datetime import datetime
from pathlib import Path
root=Path(sys.argv[1]);path='delivery/contracts/v0.11.9.3.6.7.6.6.3-aws-test-residual-cost-audit-execution-evidence.json'
digest=lambda raw:hashlib.sha256(raw).hexdigest()
assert digest((root/path).read_bytes())=='90d6945c04b6ba6f308fb8de705bd5b5c730557938cfc12c9acd2f29756b8f67','execution evidence drift'
c=json.loads((root/path).read_bytes())
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.6.6.3' and c['predecessor']=='v0.11.9.3.6.7.6.6.2'
assert c['implementationBaselineCommit']=='4b4076bc8b1ae0ddd8f0dd32626f6f5fb46714d7'
assert c['status']=='aws-test-residual-cost-audit-execution-recorded'
assert c['targetEnvironment']=='aws-test' and c['awsRegion']=='us-east-1'
g=c['guardedImplementation']
for key in ('contract','executor','fleetClassifier','test'):
    assert digest((root/g[key+'Path']).read_bytes())==g[key+'Sha256'],key
old=json.loads((root/g['contractPath']).read_bytes())
chain=c['teardownChain']
assert digest((root/chain['evidencePath']).read_bytes())==chain['evidenceSha256']==old['teardownEvidenceSha256']
for key,oldkey in (('privateInputsSha256','privateInputsSha256'),('runtimeRecordSha256','runtimeRecordSha256'),('finalApplyResultSha256','finalResultSha256'),('eksCompleteSha256','eksCompleteSha256'),('finalStateSha256','finalStateSha256')):
    assert chain[key]==old[oldkey],key
assert chain['appliedCleanupCommit']==old['teardownControlPlaneCommit']
results=c['phaseResultsRestated'];metadata=c['phaseMetadata']
expected={'preflight':('2f001169d5972eb9e66fb678eb81186a6f079bd19687d1ce1d5ad7ff4e6ebe00',1340),
          'verify':('c5b59ca799da1f5363c2e9b9e756b9ead6e2095ed3858b0fbf7f51a0e6835967',1579),
          'execution':('b170807170813e77f770fc2d2f831a98582ec44f883831aff56c9321c4d77471',2161)}
for phase,value in results.items():
    raw=(json.dumps(value,sort_keys=True)+'\n').encode();meta=metadata[phase]
    assert digest(raw)==meta['resultSha256']==expected[phase][0],phase
    assert len(raw)==meta['resultBytes']==expected[phase][1],phase
    assert meta['executorExit']==0 and meta['stderrBytes']==0
    assert meta['stderrSha256']==digest(b'')
    assert meta['resultModeRestated']==meta['stderrModeRestated']=='0600'
    assert value['control_plane_commit']==c['implementationBaselineCommit'] and value['target_environment']=='aws-test'
    assert value['aws_region']=='us-east-1' and value['account_verified']
    assert value['active_rehearsal_environment_count']==0 and value['backup_bucket_absent']
    assert value['credential_container_absent_or_tombstone'] and value['credential_tombstone_present']
    assert value['terraform_state_sha256']==chain['finalStateSha256']
    assert value['terraform_state_resource_block_count']==value['terraform_state_resource_instance_count']==0
    assert value['private_inputs_sha256']==chain['privateInputsSha256']
    assert value['runtime_record_sha256']==chain['runtimeRecordSha256']
    assert value['teardown_evidence_sha256']==chain['evidenceSha256']
    assert value['raw_output_manifest_sha256']==meta['rawOutputManifestSha256']
    assert not any(value[k] for k in ('account_id_emitted','mutation_executed','terraform_command_executed','secret_value_read','automatic_retry_performed','private_resource_identity_emitted'))
p,v,e=results['preflight'],results['verify'],results['execution']
assert p['status']=='aws-test-residual-cost-audit-preflight-ready-for-separate-approval'
assert v['status']=='aws-test-residual-cost-audit-execution-inputs-verified'
assert e['status']=='aws-test-residual-cost-audit-complete'
assert not p['execution_authorized'] and not p['full_audit_executed']
assert not v['execution_authorized'] and not v['full_audit_executed']
assert e['execution_authorized'] and e['full_audit_executed'] and e['audit_passed']
assert v['immediate_preflight_matched'] and e['immediate_preflight_matched']
assert v['reviewed_preflight_sha256']==e['reviewed_preflight_sha256']==metadata['preflight']['resultSha256']
assert e['reviewed_verify_sha256']==metadata['verify']['resultSha256']
assert not e['residual_identity_found'] and not e['continuing_cost_identity_found']
instant=lambda s:datetime.fromisoformat(s.replace('Z','+00:00'))
verified=instant(v['verified_at_utc']);started=instant(metadata['execution']['commandStartedAtUtcRestated'])
observed=instant(p['observed_at_utc']);completed=instant(e['completed_at_utc'])
assert instant(metadata['preflight']['commandStartedAtUtcRestated'])<=observed<=verified<=started<completed
assert started<instant(v['verify_expires_at_utc'])
assert (instant(v['verify_expires_at_utc'])-verified).total_seconds()==old['verifyTtlSeconds']
assert (started-observed).total_seconds()<old['preflightTtlSeconds']
assert v['start_utc']==e['start_utc'] and v['end_utc']==e['end_utc']
window_start,window_end=instant(v['start_utc']),instant(v['end_utc'])
assert window_start<=verified and (window_end-window_start).total_seconds()==old['maximumWindowSeconds']
assert (window_end-started).total_seconds()>=old['minimumStartRemainingSeconds']
assert completed<=instant(metadata['execution']['wrapperCompletedAtUtcRestated'])<window_end
a=c['approval']
assert a['independentlyApproved'] and a['oneTimeReadOnlyAudit']
assert a['controlPlaneCommit']==c['implementationBaselineCommit'] and a['startUtc']==v['start_utc'] and a['endUtc']==v['end_utc']
assert a['latestStartUtc']==v['verify_expires_at_utc'] and a['stateSha256']==chain['finalStateSha256']
assert a['preflightSha256']==metadata['preflight']['resultSha256'] and a['verifySha256']==metadata['verify']['resultSha256']
assert a['scope']==e['audit_scope'] and a['correctExecutionConfirmation']==old['phaseConfirmations']['execute']=='execute-reviewed-aws-test-residual-cost-audit-once'
assert not any(value for key,value in a.items() if key.endswith('Authorized'))
h=c['attemptHistory']
assert all(h[k] for k in ('stoppedPreflightPreserved','priorLocalConfirmationFailurePreserved','stoppedConsumedFleetAuditPreserved','successUsedNewPersistentSession','successfulExecuteConsumesExclusiveMarkerByImplementation'))
assert not h['oldConsumedMarkerReused'] and not h['oldAttemptOverwritten'] and not h['successfulMarkerRawHashClaimed']
assert h['priorStoppedPreflightResultSha256']==old['priorStoppedPreflight']['redactedResultSha256']
assert h['priorStoppedFleetAuditResultSha256']==old['priorStoppedAudit']['redactedResultSha256']
assert h['priorStoppedFleetAuditManifestSha256']==old['priorStoppedAudit']['rawOutputManifestSha256']
conclusion=c['scopedConclusion']
assert conclusion['teardownAndResidualAuditStageClosed'] and conclusion['auditPassed']
assert conclusion['acceptedInstantFleetHistoryCount']==e['accepted_instant_fleet_history_count']==4
assert conclusion['verifiedInstantFleetInstanceCount']==e['verified_instant_fleet_instance_count']==4<=old['fullAuditScope']['capturedComputeCount']
assert conclusion['capturedManagedResourceCount']==e['captured_managed_resource_count']==old['fullAuditScope']['capturedManagedResourceCount']==90
assert conclusion['terminalOrExpiredFleetRecordCount']==e['terminal_or_expired_fleet_record_count']==0
assert conclusion['acceptedStaleTaggedRecordCount']==e['accepted_stale_tagged_record_count']==0
assert conclusion['allTagSweepRowsProcessedBySuccessfulImplementation'] and conclusion['credentialTombstonePresent']
for key in ('continuingCostIdentityFound','residualIdentityFound','totalTagRowCountClaimed','oldFiveRowsSameAsNewFourRecordsClaimed','historicalCapacityMetadataUsedAsLiveInstanceCount','credentialValueRead','credentialRecoveryPeriodDaysClaimed','accountWideBillingAudit','allRegionsCovered','inventoryIsAtomic','untrackedUntaggedInventoryExhaustive','historicalSpendKnown','zeroAccountWideCostGuaranteed','awsTestQualificationPassedClaimed','awsProdLiveAuthorizationGranted'):
    assert conclusion[key] is False,key
assert conclusion['actualHistoricalSpendUsd'] is None
assert not e['account_wide_billing_audit'] and not e['inventory_is_atomic'] and not e['untracked_untagged_resource_inventory_exhaustive']
state=c['stateAfter']
assert state['sha256']==chain['finalStateSha256']=='accd1dc4515df7abc6f2294ff675a1729e2b8cbf1fa5fe3f9a8f42759a58944e'
assert state['bytes']==4536 and state['modeRestated']=='0600'
assert state['resourceBlockCount']==state['resourceInstanceCount']==0 and not state['changedDuringAudit'] and not state['stateRawFileCommitted']
assert not any(c['privacyBoundary'].values()) and not any(c['packageProducer'].values())
keep=c['preservation']
assert all(keep[k] for k in ('keepAllPrivateRawOutputs','keepAllAttemptMarkers','keepStateAndInputs'))
assert not keep['existingApprovalsReusable'] and not keep['newLiveExecutionAuthorized']
def check_digests(value):
    if isinstance(value,dict):
        for key,child in value.items():
            if key.endswith('Sha256') or key=='sha256':assert isinstance(child,str) and re.fullmatch('[0-9a-f]{64}',child),key
            check_digests(child)
    elif isinstance(value,list):
        for child in value:check_digests(child)
check_digests(c)
for name in (path,'docs/V0.11.9.3.6.7.6.6.3_AWS_TEST_RESIDUAL_COST_AUDIT_EXECUTION_EVIDENCE.md'):
    public=(root/name).read_text()
    assert not any(s in public for s in ('/home/sterling/','arn:aws:','secretMetadataSha256','AKIA'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',public) is None
    assert re.search(r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}/32',public) is None
assert digest((root/'.gitleaksignore').read_bytes())=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.6.6.3 result-byte/hash/proof/scope/state/privacy gates passed; evidence only.')
PYTHON
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.6.2-instant-fleet-classification-repair.sh"
echo "v0.11.9.3.6.7.6.6.3 passed; successful scoped audit recorded offline; no new live approval."

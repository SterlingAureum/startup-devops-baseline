#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
contract_path = 'delivery/contracts/v0.11.9.3.6.7.7.20-v0.11-scope-and-evidence-closure.json'
manifest_path = 'delivery/contracts/v0.11-final-evidence-manifest.json'
document_path = 'docs/V0.11.9.3.6.7.7.20_V0.11_SCOPE_AND_EVIDENCE_CLOSURE.md'

def load(path):
    return json.loads((root / path).read_text())

def digest(path):
    return hashlib.sha256((root / path).read_bytes()).hexdigest()

contract = load(contract_path)
manifest = load(manifest_path)

assert digest(contract_path) == '343411940aab161a84caa05a4303921d73a53a4acd521f92d76fd653f3748b45', 'closure contract drift'
assert digest(manifest_path) == contract['manifestSha256'] == '0698454efe544df7d0d9784597c991c2755b5d52606789075c754775b8bb6cc8', 'manifest drift'
assert digest(document_path) == contract['documentSha256'] == '8775bb79eceb18e1cd24eb937cab7a7fe8908d0cc65c68408865f15ae81f8513', 'closure document drift'
assert contract['schemaVersion'] == contract['version'] == 'v0.11.9.3.6.7.7.20'
assert contract['predecessor'] == 'v0.11.9.3.6.7.7.19'
assert contract['implementationBaselineCommit'] == '5995e3f4427151f39dac19f0860fd3cb6e379387'
assert contract['status'] == 'v0.11-scope-and-evidence-closed-with-explicit-deferrals'
assert contract['manifestPath'] == manifest_path
assert contract['documentPath'] == document_path

expected_assertions = {
    'v011CapabilityScopeComplete': True,
    'environmentEvidenceKeptDistinct': True,
    'localQualified': True,
    'awsDevRuntimeQualified': True,
    'awsDevTeardownAndScopedAuditClosed': True,
    'awsTestHistoricalFeatureObservationQualified': True,
    'awsTestCurrentCleanRoomRootHealthy': True,
    'awsTestCurrentCleanRoomRuntimeQualified': False,
    'awsTestTeardownAndScopedAuditClosed': True,
    'awsProdLiveAccepted': False,
    'awsProdQualified': False,
    'sharedGuardedRuntimeLiveBackendImplemented': False,
    'productionReadinessClaimed': False,
    'v012HandoffRecorded': True,
}
assert contract['closureAssertions'] == expected_assertions
assert contract['validationContract'] == {
    'sourceEvidenceDigestCount': 11,
    'environmentFactCrossChecksRequired': True,
    'negativeOverclaimMutationTestsRequired': True,
    'privacyScanRequired': True,
    'predecessorReplayRequired': True,
    'cloudAccessRequired': False,
    'kubernetesAccessRequired': False,
    'terraformExecutionRequired': False,
}
assert set(contract['packageProducer'].values()) == {False}
assert contract['next'].startswith('Begin v0.12 Production Readiness Capstone')

def by_environment(value):
    rows = value['environmentEvidence']
    assert len(rows) == 4
    result = {row['environment']: row for row in rows}
    assert set(result) == {'local', 'aws-dev', 'aws-test', 'aws-prod'}
    return result

def validate_manifest(value):
    assert value['schemaVersion'] == 'v0.11-final-evidence-manifest-v1'
    assert value['version'] == 'v0.11'
    assert value['closureCheckpoint'] == 'v0.11.9.3.6.7.7.20'
    assert value['implementationBaselineCommit'] == contract['implementationBaselineCommit']
    assert value['status'] == 'completed-with-explicit-environment-deferrals'
    assert set(value['capabilityOutcome']) == {
        'metrics', 'dashboards', 'actionableAlerts', 'centralizedLogs',
        'minimalTracing', 'sliSloErrorBudgets',
        'progressiveDeliveryTelemetry', 'runbooksAndOperationalResponse',
        'guardedEnvironmentLifecycle',
    }
    environments = by_environment(value)
    assert environments['local']['acceptance'] == 'qualified-and-restored'
    assert environments['aws-dev']['acceptance'] == 'runtime-qualified-teardown-complete-and-scoped-residual-audit-passed'
    test_acceptance = environments['aws-test']['acceptance']
    assert 'historical-feature-observation-qualified' in test_acceptance
    assert 'current-clean-room-runtime-qualification-deferred' in test_acceptance
    assert 'current-clean-room-traffic-not-generated' in environments['aws-test']['claims']
    assert 'current-clean-room-runtime-qualification-not-executed' in environments['aws-test']['claims']
    assert environments['aws-prod']['acceptance'] == 'observer-implemented-and-offline-validated-live-acceptance-deferred'
    assert 'not-qualified' in environments['aws-prod']['claims']
    shared = value['sharedGuardedRuntime']
    assert shared == {
        'status': 'offline-conformance-only',
        'environmentProfileExercised': 'aws-dev',
        'orderedPhaseCount': 8,
        'closedOperationCount': 23,
        'independentChildProcessCount': 16,
        'fixedFakeTransportOnly': True,
        'syntheticReceiptsConvertibleToLive': False,
        'liveBackendImplemented': False,
        'liveExecutionAuthorized': False,
    }
    required_forbidden = {
        'aws-test-current-clean-room-runtime-qualification-passed',
        'aws-prod-live-acceptance-passed',
        'aws-prod-is-qualified',
        'shared-guarded-runtime-has-a-live-backend',
        'scoped-residual-audits-prove-zero-account-wide-cost',
        'v0.11-proves-full-production-readiness',
    }
    assert required_forbidden <= set(value['forbiddenClaims'])
    assert 'repository-wide-production-readiness-acceptance' in value['deferredToV012']
    assert len(value['sourceEvidence']) == 11
    assert len({item['path'] for item in value['sourceEvidence']}) == 11
    assert len({item['role'] for item in value['sourceEvidence']}) == 11
    assert value['privacyBoundary'] == {
        'rawPrivateEvidenceCommitted': False,
        'accountIdentifiersCommitted': False,
        'resourceIdentifiersCommitted': False,
        'secretValuesCommitted': False,
        'redactedRepositoryRecordsOnly': True,
    }
    assert value['newLiveExecutionAuthorized'] is False

validate_manifest(manifest)
for item in manifest['sourceEvidence']:
    assert digest(item['path']) == item['sha256'], item['path']

sources = {item['role']: load(item['path']) for item in manifest['sourceEvidence']}
foundation = sources['version-goal-and-security-boundary']
assert foundation['version'] == 'v0.11'
assert foundation['status'] == 'design-foundation'

local = sources['local-live-restoration-closure']
assert local['rollout']['phase'] == 'Healthy'
assert local['rollout']['abort'] is False
assert local['rollout']['desiredReplicas'] == local['rollout']['readyReplicas'] == 3
assert [item['phase'] for item in local['analysisRuns']] == ['Successful', 'Successful']
assert local['argoCD']['root']['syncStatus'] == local['argoCD']['application']['syncStatus'] == 'Synced'
assert local['argoCD']['root']['healthStatus'] == local['argoCD']['application']['healthStatus'] == 'Healthy'
assert local['idempotentRestoration']['result'] == 'passed'
assert local['idempotentRestoration']['newRevisionCreated'] is False
assert local['retainedEvidence']['retryPerformed'] is False
assert local['retainedEvidence']['promotionPerformed'] is False

dev_runtime = sources['aws-dev-live-runtime-qualification']['execution']
assert dev_runtime['status'] == 'aws-dev-runtime-qualification-complete'
assert dev_runtime['boundedRequestCount'] == 54
for key in ('trafficGenerated', 'runtimeQualified', 'requestSeriesReady',
            'availabilitySloPassed', 'latencySloPassed', 'finalRuntimeHealthy'):
    assert dev_runtime[key] is True, key
assert dev_runtime['criticalAlertsFiring'] is False
assert dev_runtime['progressiveDeliveryPromoted'] is False

dev_teardown = sources['aws-dev-live-teardown']['execution']
assert dev_teardown['status'] == 'aws-dev-teardown-execution-complete'
assert dev_teardown['terraformDestroyedResourceCount'] == 90
assert dev_teardown['postSuccessDependencyConvergencePassed'] is True
assert dev_teardown['teardownExecuted'] is True
assert dev_teardown['automaticRetryPerformed'] is False
assert dev_teardown['awsTestCreated'] is False

dev_audit = sources['aws-dev-scoped-residual-cost-audit']['execution']
assert dev_audit['status'] == 'aws-dev-residual-cost-audit-complete'
assert dev_audit['auditPassed'] is True
assert dev_audit['continuingCostIdentityFound'] is False
assert dev_audit['mutationExecuted'] is False
assert dev_audit['automaticRetryPerformed'] is False

test_history = sources['aws-test-historical-feature-observation']['historical_observation']
assert test_history['status'] == 'qualified'
assert test_history['mode'] == 'operator-observation'
assert test_history['least_privilege_verified'] is False
assert test_history['fresh_evidence_for_this_increment'] is False
assert test_history['capabilities'] == {
    'metrics': 'supported-verified',
    'dashboards': 'supported-verified',
    'alerts': 'supported-verified',
    'slo': 'supported-not-verified',
    'progressiveDeliveryTelemetry': 'supported-not-verified',
    'logs': 'not-deployed',
    'traces': 'not-deployed',
}

test_root = sources['aws-test-current-clean-room-root-deployment']['executionSummary']
assert test_root['status'] == 'aws-test-immutable-root-deployment-complete'
assert test_root['root_deployed'] is True
assert test_root['root_health'] == test_root['demo_application_health'] == 'Healthy'
assert test_root['database_ready'] is True
assert test_root['dns_alias_insync'] is True
assert test_root['credential_seeded_and_eso_verified'] is True
assert test_root['qualification_executed'] is False
assert test_root['traffic_generated'] is False
assert test_root['terraform_state_unchanged'] is True

test_teardown = sources['aws-test-current-clean-room-teardown']['operationBoundary']
assert test_teardown['teardownComplete'] is True
assert test_teardown['completedTeardownMustNotBeRepeated'] is True
assert test_teardown['newLiveExecutionAuthorized'] is False

test_audit = sources['aws-test-scoped-residual-cost-audit']['scopedConclusion']
assert test_audit['auditPassed'] is True
assert test_audit['awsTestQualificationPassedClaimed'] is False
assert test_audit['teardownAndResidualAuditStageClosed'] is True
assert test_audit['residualIdentityFound'] is False
assert test_audit['continuingCostIdentityFound'] is False
for key in ('accountWideBillingAudit', 'allRegionsCovered',
            'untrackedUntaggedInventoryExhaustive', 'zeroAccountWideCostGuaranteed'):
    assert test_audit[key] is False, key

prod = sources['aws-prod-offline-observer-boundary']
assert prod['status'] == 'implementation-and-offline-validation-only'
assert prod['live_acceptance'] == 'deferred-to-v0.11-tail'
for key in ('runtime_mutations', 'automatic_deployment', 'traffic_generation',
            'least_privilege_claimed', 'prod_qualified'):
    assert prod[key] is False, key

shared_source = sources['shared-guarded-runtime-offline-process-boundary']
assert shared_source['reviewResult']['currentlyLiveEnabledEnvironmentCount'] == 0
assert shared_source['offlineProcessChain']['fixedFakeTransportOnly'] is True
assert shared_source['offlineProcessChain']['syntheticReceiptConvertibleToLive'] is False
for key in ('liveBackendImplemented', 'liveTransportImplemented',
            'liveExecutionCliImplemented', 'devLiveEnabled', 'testLiveEnabled',
            'prodLiveEnabled', 'newLiveExecutionAuthorized'):
    assert shared_source[key] is False, key

mutations = []
def mutation(label, update):
    candidate = copy.deepcopy(manifest)
    update(candidate)
    mutations.append((label, candidate))

mutation('prod-qualified', lambda value: by_environment(value)['aws-prod']['claims'].remove('not-qualified'))
mutation('prod-live-accepted', lambda value: by_environment(value)['aws-prod'].__setitem__('acceptance', 'live-accepted'))
mutation('test-clean-room-qualified', lambda value: by_environment(value)['aws-test']['claims'].remove('current-clean-room-runtime-qualification-not-executed'))
mutation('test-traffic-generated', lambda value: by_environment(value)['aws-test']['claims'].remove('current-clean-room-traffic-not-generated'))
mutation('shared-live-backend', lambda value: value['sharedGuardedRuntime'].__setitem__('liveBackendImplemented', True))
mutation('shared-live-authority', lambda value: value['sharedGuardedRuntime'].__setitem__('liveExecutionAuthorized', True))
mutation('synthetic-live-receipts', lambda value: value['sharedGuardedRuntime'].__setitem__('syntheticReceiptsConvertibleToLive', True))
mutation('missing-prod-forbidden-claim', lambda value: value['forbiddenClaims'].remove('aws-prod-is-qualified'))
mutation('missing-production-handoff', lambda value: value['deferredToV012'].remove('repository-wide-production-readiness-acceptance'))
mutation('new-live-authority', lambda value: value.__setitem__('newLiveExecutionAuthorized', True))

for label, candidate in mutations:
    try:
        validate_manifest(candidate)
    except AssertionError:
        continue
    raise AssertionError(f'negative overclaim mutation accepted: {label}')
assert len(mutations) == 10

for path in (contract_path, manifest_path, document_path):
    text = (root / path).read_text()
    assert '/home/' not in text and '/tmp/' not in text
    assert 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])', text) is None
assert digest('.gitleaksignore') == 'a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'

print('v0.11 scope/evidence closure pins and 10 negative overclaim mutations passed; production readiness remains deferred.')
PYTHON

bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.19-dev-local-offline-process-chain.sh"
echo "v0.11.9.3.6.7.7.20 passed; closure is evidence-bounded and grants no live authority."

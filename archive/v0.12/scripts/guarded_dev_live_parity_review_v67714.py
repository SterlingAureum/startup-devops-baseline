"""Pure gap review between historical aws-dev live evidence and the new chain.

The review consumes parsed public contracts plus a versioned manifest.  It has
no filesystem, clock, environment, subprocess, cloud, Kubernetes or Terraform
IO and cannot grant live authority.
"""
from __future__ import annotations

from guarded_live_migration_contract_v6778 import STAGES
from guarded_runtime_rules import require


VERSION = 'v0.11.9.3.6.7.7.14'
CHAIN_VERSION = 'v0.11.9.3.6.7.7.13'
TEARDOWN_VERSION = 'v0.11.9.3.6.6.5.2'
AUDIT_VERSION = 'v0.11.9.3.6.6.6.1'


def expected_stage_rows() -> tuple[dict, ...]:
    historical = {
        'freeze-applications': ('aggregate-source-behavior', (
            'exact-object-identity-and-postconditions',)),
        'drain-external-secrets': ('absent', (
            'external-secret-drain',)),
        'delete-business-namespaces': ('aggregate-source-behavior', (
            'exact-object-identity-and-postconditions',)),
        'drain-runtime': ('aggregate-source-behavior', (
            'exact-object-identity-and-postconditions',)),
        'delete-node-config': ('aggregate-source-behavior', (
            'exact-object-identity-and-postconditions',)),
        'eks-delete': ('monolithic-terraform-destroy', (
            'reviewed-saved-plan-byte-binding',
            'per-stage-state-transition',
            'legacy-automatic-retry-capability',)),
        'eni-sg-cleanup': ('aggregate-convergence-result', (
            'exact-object-identity-and-postconditions',)),
        'final-delete': ('monolithic-terraform-destroy', (
            'reviewed-saved-plan-byte-binding',
            'per-stage-state-transition',
            'exact-object-identity-and-postconditions',)),
    }
    return tuple({
        'stage': stage,
        'historicalPublicCoverage': historical[stage][0],
        'offlineFixedFakeCoverage': 'complete',
        'historicalLiveReceiptEquivalent': False,
        'requiresFreshStageApproval': True,
        'requiresVersionedLiveTransport': True,
        'stageSpecificGapIds': list(historical[stage][1]),
    } for stage in STAGES)


def expected_gap_rows() -> tuple[dict, ...]:
    return (
        {'id': 'per-stage-approval-and-proof', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'per-stage-live-receipt-chain', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'per-stage-state-transition', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'exact-object-identity-and-postconditions',
         'blocksDevLiveTransport': True, 'historicalEvidenceReusable': False},
        {'id': 'external-secret-drain', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'reviewed-saved-plan-byte-binding', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'legacy-automatic-retry-capability', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'versioned-live-transport', 'blocksDevLiveTransport': True,
         'historicalEvidenceReusable': False},
        {'id': 'fresh-live-inputs-price-budget-window',
         'blocksDevLiveTransport': False, 'historicalEvidenceReusable': False},
    )


def expected_proven_controls() -> tuple[str, ...]:
    return (
        'historical-exact-main-bound',
        'reviewed-preflight-bound',
        'immediate-preflight-matched',
        'aws-dev-target-bound',
        'bounded-separate-approval-recorded',
        'successful-run-used-no-automatic-retry',
        'private-identities-not-committed',
        'post-teardown-state-empty',
        'post-teardown-continuing-cost-identity-absent',
        'aws-test-not-created',
    )


def _validate_chain(contract: dict) -> None:
    require(isinstance(contract, dict), 'chain-contract-schema')
    require(contract.get('version') == CHAIN_VERSION and
            contract.get('schemaVersion') == CHAIN_VERSION and
            contract.get('status') == 'dev-local-offline-restart-chain-exercised',
            'chain-contract-drift')
    exercise = contract.get('offlineChainExercise')
    require(isinstance(exercise, dict), 'chain-exercise-schema')
    expected = {
        'orderedPhaseCount': 8,
        'closedOperationCount': 23,
        'independentChildProcessCount': 16,
        'durableReceiptTripletCount': 8,
        'durableReceiptFileCount': 24,
        'fixedFakeTransportOnly': True,
        'syntheticApprovalFixtures': True,
        'syntheticReceiptChain': True,
        'syntheticReceiptConvertibleToLive': False,
    }
    for key, value in expected.items():
        require(exercise.get(key) == value and
                type(exercise.get(key)) is type(value), 'chain-coverage-drift')
    require(contract.get('environmentProfile') == 'aws-dev',
            'chain-environment-drift')
    for key in ('liveTransportImplemented', 'liveExecutionCliImplemented',
                'devLiveEnabled', 'testLiveEnabled', 'prodLiveEnabled',
                'newLiveExecutionAuthorized'):
        require(contract.get(key) is False, 'chain-live-boundary-drift')
    effects = contract.get('effectFlags')
    require(isinstance(effects, dict), 'chain-effect-schema')
    for key in ('cloudTransport', 'kubernetesTransport', 'terraformCommands',
                'cloudMutation', 'kubernetesMutation', 'secretValueRead',
                'automaticRetryOrRepair'):
        require(effects.get(key) is False, 'chain-live-effect-enabled')


def _validate_teardown(contract: dict) -> None:
    require(isinstance(contract, dict), 'teardown-evidence-schema')
    require(contract.get('version') == TEARDOWN_VERSION and
            contract.get('schemaVersion') == TEARDOWN_VERSION and
            contract.get('status') == 'aws-dev-teardown-execution-recorded',
            'teardown-evidence-drift')
    execution = contract.get('execution')
    require(isinstance(execution, dict), 'teardown-execution-schema')
    require(execution.get('targetEnvironment') == 'aws-dev' and
            execution.get('teardownExecuted') is True and
            execution.get('destroyExitCode') == 0 and
            execution.get('terraformDestroyedResourceCount') == 90 and
            execution.get('postSuccessDependencyConvergencePassed') is True and
            execution.get('automaticRetryPerformed') is False and
            execution.get('awsTestCreated') is False,
            'teardown-execution-drift')
    require(execution.get('immediatePreflightMatched') is True,
            'teardown-immediate-proof-drift')
    approval = contract.get('approval')
    require(isinstance(approval, dict) and
            approval.get('awsDevTeardownApproved') is True and
            approval.get('automaticRetryApproved') is False and
            approval.get('residualCostAuditApproved') is False,
            'teardown-approval-drift')
    require(contract.get('executionAuthorized') is False,
            'historical-evidence-authority-drift')


def _validate_audit(contract: dict) -> None:
    require(isinstance(contract, dict), 'audit-evidence-schema')
    require(contract.get('version') == AUDIT_VERSION and
            contract.get('schemaVersion') == AUDIT_VERSION and
            contract.get('status') == 'aws-dev-residual-cost-audit-execution-recorded',
            'audit-evidence-drift')
    preflight = contract.get('reviewedPreflight')
    execution = contract.get('execution')
    require(isinstance(preflight, dict) and isinstance(execution, dict),
            'audit-record-schema')
    require(preflight.get('terraformStateResourceCount') == 0 and
            preflight.get('backupBucketAbsent') is True and
            preflight.get('secretLiveValueAbsent') is True and
            preflight.get('accountVerified') is True,
            'audit-preflight-drift')
    require(execution.get('targetEnvironment') == 'aws-dev' and
            execution.get('auditPassed') is True and
            execution.get('continuingCostIdentityFound') is False and
            execution.get('mutationExecuted') is False and
            execution.get('automaticRetryPerformed') is False and
            execution.get('awsTestCreated') is False,
            'audit-execution-drift')
    require(contract.get('executionAuthorized') is False,
            'audit-evidence-authority-drift')


def _validate_manifest(manifest: dict) -> None:
    require(isinstance(manifest, dict), 'gap-manifest-schema')
    require(set(manifest) == {'schema', 'stageRows', 'gapRows',
                              'provenHistoricalControls',
                              'historicalSourceCapabilities'},
            'gap-manifest-keys')
    require(manifest.get('schema') == 'dev-live-parity-gap-manifest-v1',
            'gap-manifest-version')
    require(tuple(manifest.get('stageRows', ())) == expected_stage_rows(),
            'gap-stage-row-drift')
    require(tuple(manifest.get('gapRows', ())) == expected_gap_rows(),
            'gap-row-drift')
    require(tuple(manifest.get('provenHistoricalControls', ())) ==
            expected_proven_controls(), 'proven-control-drift')
    capabilities = manifest.get('historicalSourceCapabilities')
    require(capabilities == {
        'monolithicDestroyWrapper': True,
        'perStageSavedPlanBindings': False,
        'perStageReceiptChain': False,
        'perStageStateTransitions': False,
        'externalSecretDrain': False,
        'terraformFailureMayInvokeSecondDestroy': True,
        'separateResidualAuditRecorded': True,
    }, 'historical-source-capability-drift')


def review_dev_live_parity(chain: dict, teardown: dict, audit: dict,
                           manifest: dict) -> dict:
    """Return redacted aggregate gaps; never convert history to authority."""
    _validate_chain(chain)
    _validate_teardown(teardown)
    _validate_audit(audit)
    _validate_manifest(manifest)
    rows = expected_stage_rows()
    gaps = expected_gap_rows()
    require(tuple(row['stage'] for row in rows) == STAGES,
            'review-stage-order-drift')
    require(all(row['offlineFixedFakeCoverage'] == 'complete' for row in rows),
            'offline-stage-coverage-drift')
    require(not any(row['historicalLiveReceiptEquivalent'] for row in rows),
            'historical-receipt-overclaim')
    blocking = tuple(row['id'] for row in gaps if row['blocksDevLiveTransport'])
    require(len(blocking) == 8, 'blocking-gap-count-drift')
    return {
        'status': 'dev-live-parity-gap-review-complete',
        'reviewedStageCount': len(rows),
        'offlineCompleteStageCount': len(rows),
        'historicalLiveReceiptEquivalentStageCount': 0,
        'provenHistoricalControlCount': len(expected_proven_controls()),
        'blockingGapCount': len(blocking),
        'blockingGapIds': list(blocking),
        'historicalRunSucceeded': True,
        'historicalResidualAuditPassed': True,
        'historicalApprovalsReusable': False,
        'syntheticReceiptsReusableForLive': False,
        'devLiveTransportReady': False,
        'devLiveExecutionAuthorized': False,
        'testLiveEnabled': False,
        'prodLiveEnabled': False,
    }

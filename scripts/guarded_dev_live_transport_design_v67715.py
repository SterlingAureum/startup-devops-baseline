"""Pure aws-dev versioned live-transport design validation.

This module validates supplied public design data only.  It constructs no
backend, reads no private input, performs no IO and grants no live authority.
"""
from __future__ import annotations

from guarded_dev_live_parity_review_v67714 import expected_gap_rows
from guarded_live_migration_contract_v6778 import (
    INCIDENT_ONLY_POWERS,
    STAGES,
    STAGE_OPERATIONS,
)
from guarded_runtime_rules import require


VERSION = 'v0.11.9.3.6.7.7.15'
PREDECESSOR = 'v0.11.9.3.6.7.7.14'
ENVIRONMENT = 'aws-dev'
DESIGN_SCHEMA = 'guarded-dev-live-transport-design-v1'
TRANSPORT_SCHEMA = 'guarded-dev-live-transport-v1'
REQUEST_SCHEMA = 'guarded-dev-live-operation-request-v1'
RESPONSE_SCHEMA = 'guarded-dev-live-operation-response-v1'
APPROVAL_SCHEMA = 'guarded-dev-live-phase-approval-v2'
RECEIPT_SCHEMA = 'guarded-dev-live-phase-receipt-v2'

COMMON_BINDINGS = (
    'control_plane_commit',
    'phase',
    'approval_sha256',
    'reviewed_verify_sha256',
    'inputs_sha256',
    'scope_sha256',
    'operation_set_sha256',
    'proof_sha256',
    'state_before_sha256',
    'predecessor_receipt_sha256',
    'start_utc',
    'end_utc',
    'budget_limit_usd',
)

MUTATION_OPERATIONS = {
    'freeze-applications': (
        'kubernetes-freeze-exact-application',
        'kubernetes-remove-known-argo-finalizer',
        'kubernetes-delete-exact-application',
    ),
    'drain-external-secrets': (),
    'delete-business-namespaces': (
        'kubernetes-delete-reviewed-business-resources',
        'kubernetes-delete-reviewed-business-namespaces',
    ),
    'drain-runtime': (),
    'delete-node-config': (
        'kubernetes-delete-reviewed-node-configuration',
    ),
    'eks-delete': (
        'terraform-apply-reviewed-saved-plan',
    ),
    'eni-sg-cleanup': (
        'aws-delete-reviewed-captured-eni',
        'aws-delete-reviewed-captured-security-group',
    ),
    'final-delete': (
        'terraform-apply-reviewed-saved-plan',
    ),
}

POSTCONDITIONS = {
    'freeze-applications': (
        'reviewed-applications-absent',
        'active-application-operations-zero',
    ),
    'drain-external-secrets': (
        'reviewed-external-secrets-drained',
        'cleanup-permissions-retained-through-drain',
    ),
    'delete-business-namespaces': (
        'reviewed-business-resources-absent',
        'reviewed-business-namespaces-absent',
    ),
    'drain-runtime': (
        'captured-runtime-compute-absent',
        'captured-volumes-and-load-balancers-absent',
    ),
    'delete-node-config': (
        'reviewed-node-configuration-absent',
        'captured-nodeclaims-absent',
    ),
    'eks-delete': (
        'eks-and-captured-compute-absent',
        'reviewed-dependency-deletes-accounted',
        'managed-state-transition-exact',
    ),
    'eni-sg-cleanup': (
        'captured-eni-absent',
        'captured-security-group-absent',
        'terraform-state-unchanged',
    ),
    'final-delete': (
        'remaining-managed-state-empty',
        'vpc-volume-load-balancer-dns-and-backup-absent',
        'credential-container-absent-or-tombstone',
    ),
}


def _transport_flags(stage: str) -> dict:
    return {
        'kubernetes': stage in STAGES[:6],
        'aws': stage in ('drain-runtime', 'eks-delete',
                         'eni-sg-cleanup', 'final-delete'),
        'terraform': stage in ('eks-delete', 'final-delete'),
    }


def expected_stage_designs() -> tuple[dict, ...]:
    rows = []
    for stage in STAGES:
        terraform = stage in ('eks-delete', 'final-delete')
        rows.append({
            'stage': stage,
            'allowedOperationIds': list(STAGE_OPERATIONS[stage]),
            'mutationOperationIds': list(MUTATION_OPERATIONS[stage]),
            'requiredApprovalBindings': list(COMMON_BINDINGS),
            'transportKinds': _transport_flags(stage),
            'savedPlanBundleRequired': terraform,
            'savedPlanBindings': [
                'binary_plan_sha256',
                'json_plan_sha256',
                'text_plan_sha256',
                'plan_gate_sha256',
                'provider_lock_sha256',
                'terraform_version',
                'terraform_workspace',
            ] if terraform else [],
            'stateAfterRelation': 'reviewed-transition' if terraform else 'unchanged',
            'postconditions': list(POSTCONDITIONS[stage]),
            'incidentOnlyPowersAllowed': [],
            'automaticRetryAllowed': False,
            'automaticRepairAllowed': False,
            'terminalReceiptBeforePostconditionsAllowed': False,
        })
    return tuple(rows)


def expected_gap_designs() -> tuple[dict, ...]:
    clauses = {
        'per-stage-approval-and-proof': 'approval-v2-exact-stage-bindings',
        'per-stage-live-receipt-chain': 'receipt-v2-terminal-predecessor-chain',
        'per-stage-state-transition': 'receipt-v2-state-before-after',
        'exact-object-identity-and-postconditions': 'immutable-scope-and-postcondition-set',
        'external-secret-drain': 'permission-lifetime-and-read-only-drain',
        'reviewed-saved-plan-byte-binding': 'saved-plan-bundle-exact-bytes',
        'legacy-automatic-retry-capability': 'one-intent-one-call-no-retry',
        'versioned-live-transport': 'closed-dev-transport-v1-interface',
        'fresh-live-inputs-price-budget-window': 'execution-time-freshness-and-budget',
    }
    return tuple({
        'gapId': row['id'],
        'designClause': clauses[row['id']],
        'specifiedOffline': True,
        'implementedLive': False,
        'historicalEvidenceReusable': False,
    } for row in expected_gap_rows())


def expected_protocol() -> dict:
    return {
        'verificationAndExecutionSeparate': True,
        'freshVerifyRequiredForEveryStage': True,
        'approvalSchema': APPROVAL_SCHEMA,
        'requestSchema': REQUEST_SCHEMA,
        'responseSchema': RESPONSE_SCHEMA,
        'receiptSchema': RECEIPT_SCHEMA,
        'writeAheadIntentRequired': True,
        'oneTransportCallPerIntent': True,
        'terminalReceiptAfterPostconditionsOnly': True,
        'failedOrUncertainIntentBlocksProgress': True,
        'automaticRetryOrRepair': False,
        'completedPhaseReplayAccepted': False,
        'exactSameEnvironmentPredecessorRequired': True,
        'historicalOrSyntheticReceiptAccepted': False,
    }


def expected_transport() -> dict:
    return {
        'schema': TRANSPORT_SCHEMA,
        'environment': ENVIRONMENT,
        'closedOperationCount': sum(len(STAGE_OPERATIONS[s]) for s in STAGES),
        'closedDispatchRequired': True,
        'requestAndResponseCanonical': True,
        'arbitraryCommandAccepted': False,
        'endpointSelectorAccepted': False,
        'environmentFallbackAccepted': False,
        'credentialReaderImplemented': False,
        'backendImplemented': False,
        'commandEntryImplemented': False,
        'liveEnabled': False,
    }


def expected_design() -> dict:
    return {
        'schema': DESIGN_SCHEMA,
        'version': VERSION,
        'predecessor': PREDECESSOR,
        'environment': ENVIRONMENT,
        'transport': expected_transport(),
        'protocol': expected_protocol(),
        'stageDesigns': [dict(row) for row in expected_stage_designs()],
        'gapDesigns': [dict(row) for row in expected_gap_designs()],
        'incidentOnlyPowers': list(INCIDENT_ONLY_POWERS),
        'migration': {
            'firstEnvironment': ENVIRONMENT,
            'testBlockedUntilDevEvidenceReviewed': True,
            'prodDisabled': True,
            'historicalAdaptersFrozen': True,
            'legacyDestroyWrapperCallable': False,
            'syntheticReceiptConvertibleToLive': False,
        },
    }


def _validate_gap_review(contract: dict) -> None:
    require(isinstance(contract, dict), 'gap-review-schema')
    require(contract.get('version') == PREDECESSOR and
            contract.get('schemaVersion') == PREDECESSOR and
            contract.get('status') == 'dev-live-parity-gap-reviewed',
            'gap-review-drift')
    result = contract.get('reviewResult')
    require(isinstance(result, dict), 'gap-review-result-schema')
    require(result.get('blockingGapCount') == 8 and
            result.get('historicalLiveReceiptEquivalentStageCount') == 0 and
            result.get('provenHistoricalControlCount') == 10 and
            result.get('devLiveTransportReady') is False and
            result.get('devLiveExecutionAuthorized') is False,
            'gap-review-result-drift')
    manifest = contract.get('gapManifest')
    require(isinstance(manifest, dict), 'gap-review-manifest-schema')
    require(tuple(manifest.get('gapRows', ())) == expected_gap_rows(),
            'gap-review-row-drift')
    for key in ('liveTransportImplemented', 'liveExecutionCliImplemented',
                'devLiveEnabled', 'testLiveEnabled', 'prodLiveEnabled',
                'newLiveExecutionAuthorized'):
        require(contract.get(key) is False, 'predecessor-live-boundary-drift')


def _validate_design(design: dict) -> None:
    require(isinstance(design, dict) and design == expected_design(),
            'dev-live-transport-design-drift')
    require(tuple(row['stage'] for row in design['stageDesigns']) == STAGES,
            'dev-live-stage-order-drift')
    operation_ids = tuple(operation for row in design['stageDesigns']
                          for operation in row['allowedOperationIds'])
    expected_operations = tuple(operation for stage in STAGES
                                for operation in STAGE_OPERATIONS[stage])
    require(operation_ids == expected_operations and len(operation_ids) == 23,
            'dev-live-operation-set-drift')
    for row in design['stageDesigns']:
        require(set(row['mutationOperationIds']) <= set(row['allowedOperationIds']),
                'dev-live-mutation-operation-drift')
        require(not row['incidentOnlyPowersAllowed'], 'incident-power-enabled')
        require(row['automaticRetryAllowed'] is False and
                row['automaticRepairAllowed'] is False and
                row['terminalReceiptBeforePostconditionsAllowed'] is False,
                'retry-repair-or-early-receipt-enabled')
    require(not any(row['implementedLive'] for row in design['gapDesigns']),
            'live-gap-implementation-overclaim')


def review_dev_live_transport_design(gap_review: dict, design: dict) -> dict:
    """Return aggregate design coverage while preserving disabled live state."""
    _validate_gap_review(gap_review)
    _validate_design(design)
    stage_rows = expected_stage_designs()
    gap_rows = expected_gap_designs()
    return {
        'status': 'dev-versioned-live-transport-design-review-complete',
        'designedStageCount': len(stage_rows),
        'closedOperationCount': sum(len(row['allowedOperationIds'])
                                    for row in stage_rows),
        'gapDesignCount': len(gap_rows),
        'structuralBlockingGapDesignCount': sum(
            row['gapId'] != 'fresh-live-inputs-price-budget-window'
            for row in gap_rows),
        'liveImplementedGapCount': 0,
        'incidentOnlyPowerCount': len(INCIDENT_ONLY_POWERS),
        'incidentOnlyPowersEnabled': False,
        'legacyDestroyWrapperCallable': False,
        'historicalApprovalsReusable': False,
        'syntheticReceiptsReusableForLive': False,
        'devLiveTransportImplemented': False,
        'devLiveCommandImplemented': False,
        'devLiveExecutionAuthorized': False,
        'testLiveEnabled': False,
        'prodLiveEnabled': False,
    }

"""Pure review of the composed offline cleanup/destroy adapter coverage.

The review consumes already parsed public contracts and a versioned parity
manifest.  It performs no IO and deliberately distinguishes individually
simulatable phases from an executable end-to-end chain.
"""
from __future__ import annotations

from guarded_cleanup_rules import CLEANUP_STEPS
from guarded_runtime_rules import require


VERSION = 'v0.11.9.3.6.7.7.6'
ENVIRONMENTS = ('aws-dev', 'aws-test', 'aws-prod')
DESTROY_VERSION = 'v0.11.9.3.6.7.7.4'
CLEANUP_VERSION = 'v0.11.9.3.6.7.7.5'
DESTROY_PHASES = ('eks-delete', 'final-delete')
CLEANUP_PHASES = (
    'drain-external-secrets',
    'delete-business-namespaces',
    'drain-runtime',
    'delete-node-config',
    'eni-sg-cleanup',
)
COMMON_CLOCKS = {
    'maximumWindowSeconds': 28800,
    'minimumRemainingSeconds': 60,
    'proofTtlSeconds': 900,
    'observationTtlSeconds': 60,
    'recheckedAfterIntentBarrier': True,
    'postDeadlineEnforced': True,
    'monotonicScriptedUtc': True,
}


def expected_stage_rows() -> tuple[dict, ...]:
    adapters = {
        'freeze-applications': (None, None, 'unimplemented-adapter-gap', False),
        **{phase: (CLEANUP_VERSION, 'fixed-fake-cleanup',
                   'individually-simulatable', True) for phase in CLEANUP_PHASES},
        **{phase: (DESTROY_VERSION, 'fixed-fake-destroy',
                   'individually-simulatable', True) for phase in DESTROY_PHASES},
    }
    return tuple({
        'step': step,
        'adapterVersion': adapters[step][0],
        'adapterKind': adapters[step][1],
        'coverageStatus': adapters[step][2],
        'emitsConfirmedReceipt': adapters[step][3],
        'liveEnabled': False,
    } for step in CLEANUP_STEPS)


def expected_gap_rows() -> tuple[dict, ...]:
    return (
        {'id': 'freeze-applications-adapter', 'blocksLiveMigration': True,
         'incidentOnly': False, 'prodBlocking': True},
        {'id': 'live-observation-and-mutation-transports', 'blocksLiveMigration': True,
         'incidentOnly': False, 'prodBlocking': True},
        {'id': 'live-approval-command-and-receipt-handoff', 'blocksLiveMigration': True,
         'incidentOnly': False, 'prodBlocking': True},
        {'id': 'externalsecret-finalizer-exception', 'blocksLiveMigration': True,
         'incidentOnly': True, 'prodBlocking': True},
        {'id': 'namespace-pv-forced-cleanup', 'blocksLiveMigration': True,
         'incidentOnly': True, 'prodBlocking': True},
        {'id': 'backup-secret-destructive-lifecycle', 'blocksLiveMigration': True,
         'incidentOnly': True, 'prodBlocking': True},
        {'id': 'prod-fresh-scope-price-proof', 'blocksLiveMigration': False,
         'incidentOnly': False, 'prodBlocking': True},
    )


def _validate_clock(contract: dict) -> None:
    clocks = contract.get('clocks')
    require(isinstance(clocks, dict), 'clock-contract-schema')
    for key, value in COMMON_CLOCKS.items():
        require(clocks.get(key) == value and type(clocks.get(key)) is type(value),
                'clock-contract-drift')


def _validate_false_boundaries(contract: dict) -> None:
    for key in ('existingLiveAdaptersModified', 'completeAdapterMigrationImplemented',
                'newLiveExecutionAuthorized', 'historicalApprovalsReusable',
                'prodQualified'):
        require(contract.get(key) is False, 'predecessor-boundary-drift')
    require(contract.get('historicalTeardownAndScopedAuditClosed') is True,
            'historical-closure-drift')
    effects = contract.get('effectFlags')
    require(isinstance(effects, dict), 'effect-flag-schema')
    for key in ('cloudTransport', 'terraformCommands', 'systemClockReads',
                'cloudMutation', 'secretValueRead', 'automaticRetry'):
        require(effects.get(key) is False, 'live-effect-enabled')


def _validate_destroy(contract: dict) -> None:
    require(isinstance(contract, dict), 'destroy-contract-schema')
    require(contract.get('version') == DESTROY_VERSION and
            contract.get('schemaVersion') == DESTROY_VERSION,
            'destroy-version-drift')
    require(contract.get('status') == 'shared-offline-destroy-adapters-implemented',
            'destroy-status-drift')
    require(tuple(contract.get('implementedPhases', ())) == DESTROY_PHASES,
            'destroy-phase-drift')
    require(contract.get('successfulFixtureMatrixSize') == 6,
            'destroy-matrix-drift')
    profiles = contract.get('environmentProfiles')
    require(isinstance(profiles, list) and len(profiles) == len(ENVIRONMENTS),
            'destroy-profile-schema')
    require(tuple(row.get('environment') for row in profiles
                  if isinstance(row, dict)) == ENVIRONMENTS,
            'destroy-profile-drift')
    require(all(row.get('liveEnabled') is False for row in profiles),
            'destroy-profile-live-enabled')
    _validate_clock(contract)
    _validate_false_boundaries(contract)


def _validate_cleanup(contract: dict) -> None:
    require(isinstance(contract, dict), 'cleanup-contract-schema')
    require(contract.get('version') == CLEANUP_VERSION and
            contract.get('schemaVersion') == CLEANUP_VERSION and
            contract.get('predecessor') == DESTROY_VERSION,
            'cleanup-version-drift')
    require(contract.get('status') == 'shared-offline-cleanup-adapters-implemented',
            'cleanup-status-drift')
    require(tuple(contract.get('implementedPhases', ())) == CLEANUP_PHASES,
            'cleanup-phase-drift')
    require(tuple(contract.get('environmentProfiles', ())) == ENVIRONMENTS,
            'cleanup-profile-drift')
    require(contract.get('successfulFixtureMatrixSize') == 15,
            'cleanup-matrix-drift')
    require(contract.get('effectFlags', {}).get('kubernetesTransport') is False and
            contract.get('effectFlags', {}).get('kubernetesMutation') is False,
            'cleanup-live-effect-enabled')
    _validate_clock(contract)
    _validate_false_boundaries(contract)


def _validate_manifest(manifest: dict) -> None:
    require(isinstance(manifest, dict), 'parity-manifest-schema')
    require(set(manifest) == {'schema', 'environments', 'stages', 'gaps'},
            'parity-manifest-keys')
    require(manifest.get('schema') == 'offline-runtime-parity-manifest-v1',
            'parity-manifest-version')
    require(tuple(manifest.get('environments', ())) == ENVIRONMENTS,
            'parity-environment-drift')
    stages = manifest.get('stages')
    require(isinstance(stages, list) and tuple(stages) == expected_stage_rows(),
            'parity-stage-drift')
    require(tuple(row['step'] for row in stages) == CLEANUP_STEPS,
            'parity-stage-order')
    gaps = manifest.get('gaps')
    require(isinstance(gaps, list) and tuple(gaps) == expected_gap_rows(),
            'parity-gap-drift')


def review_runtime_parity(destroy_contract: dict, cleanup_contract: dict,
                          manifest: dict) -> dict:
    """Return aggregate redacted coverage facts or fail on any false claim."""
    _validate_destroy(destroy_contract)
    _validate_cleanup(cleanup_contract)
    _validate_manifest(manifest)
    stages = expected_stage_rows()
    implemented = tuple(row for row in stages
                        if row['coverageStatus'] == 'individually-simulatable')
    missing = tuple(row for row in stages
                    if row['coverageStatus'] == 'unimplemented-adapter-gap')
    require(tuple(row['step'] for row in implemented) == tuple(
        step for step in CLEANUP_STEPS if step != 'freeze-applications'),
        'implemented-stage-union-drift')
    require(tuple(row['step'] for row in missing) == ('freeze-applications',),
            'first-stage-gap-drift')
    implemented_matrix = len(implemented) * len(ENVIRONMENTS)
    complete_matrix = len(CLEANUP_STEPS) * len(ENVIRONMENTS)
    return {
        'status': 'offline-runtime-parity-review-complete',
        'environmentCount': len(ENVIRONMENTS),
        'totalStageCount': len(CLEANUP_STEPS),
        'individuallySimulatableStageCount': len(implemented),
        'unimplementedStageCount': len(missing),
        'implementedFixtureMatrixSize': implemented_matrix,
        'completeFixtureMatrixSize': complete_matrix,
        'missingFixtureMatrixSize': complete_matrix - implemented_matrix,
        'firstUnimplementedStep': missing[0]['step'],
        'syntheticPredecessorReceiptRequired': True,
        'endToEndOfflineChainExecutable': False,
        'liveMigrationReady': False,
        'prodQualified': False,
        'historicalApprovalsReusable': False,
        'historicalTeardownAndScopedAuditClosed': True,
        'migrationGapIds': [row['id'] for row in expected_gap_rows()],
    }

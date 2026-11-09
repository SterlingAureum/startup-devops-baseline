"""Pure design rules for a future versioned live runtime migration.

This module validates supplied design, approval and receipt fixtures only. It has
no file, clock, environment, subprocess, SDK, Kubernetes, cloud or Terraform IO.
Passing a review never grants live execution authority.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Mapping, Sequence

from guarded_cleanup_rules import CLEANUP_STEPS
from guarded_runtime_rules import (RuleViolation, parse_utc, require,
                                   validate_proof, validate_window)


VERSION = 'v0.11.9.3.6.7.7.8'
DESIGN_SCHEMA = 'guarded-live-migration-design-v1'
TRANSPORT_SCHEMA = 'guarded-live-transport-v1'
APPROVAL_SCHEMA = 'guarded-live-phase-approval-v1'
RECEIPT_SCHEMA = 'guarded-live-phase-receipt-v1'
ENVIRONMENTS = ('aws-dev', 'aws-test', 'aws-prod')
STAGES = tuple(CLEANUP_STEPS)

SHA256 = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')

STAGE_OPERATIONS = {
    'freeze-applications': (
        'kubernetes-observe-applications',
        'kubernetes-freeze-exact-application',
        'kubernetes-remove-known-argo-finalizer',
        'kubernetes-delete-exact-application',
    ),
    'drain-external-secrets': (
        'kubernetes-observe-external-secrets',
        'kubernetes-observe-controller-rbac',
    ),
    'delete-business-namespaces': (
        'kubernetes-observe-business-namespaces',
        'kubernetes-delete-reviewed-business-resources',
        'kubernetes-delete-reviewed-business-namespaces',
    ),
    'drain-runtime': (
        'kubernetes-observe-runtime-absence',
        'aws-observe-captured-runtime-absence',
    ),
    'delete-node-config': (
        'kubernetes-observe-node-configuration',
        'kubernetes-delete-reviewed-node-configuration',
    ),
    'eks-delete': (
        'kubernetes-observe-runtime-absence',
        'aws-observe-eks-dependency-scope',
        'terraform-show-reviewed-saved-plan',
        'terraform-apply-reviewed-saved-plan',
    ),
    'eni-sg-cleanup': (
        'aws-observe-captured-eni-sg',
        'aws-delete-reviewed-captured-eni',
        'aws-delete-reviewed-captured-security-group',
    ),
    'final-delete': (
        'aws-observe-final-scope-and-inventories',
        'terraform-show-reviewed-saved-plan',
        'terraform-apply-reviewed-saved-plan',
    ),
}

COMMON_APPROVAL_HASHES = (
    'approval_text_sha256', 'inputs_sha256', 'scope_sha256',
    'operation_set_sha256', 'proof_sha256',
)
RECEIPT_HASH_FIELDS = (
    'approval_sha256', 'inputs_sha256', 'scope_sha256',
    'operation_set_sha256', 'journal_completion_sha256',
    'raw_output_manifest_sha256', 'state_before_sha256',
    'state_after_sha256',
)
INCIDENT_ONLY_POWERS = (
    'externalsecret-finalizer-removal',
    'namespace-finalizer-force',
    'persistent-volume-finalizer-force',
    'uncaptured-resource-deletion',
    'backup-version-ad-hoc-deletion',
    'secret-force-delete-or-value-read',
    'state-edit-or-import',
)


def _sha(value: object, reason: str) -> None:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, reason)


def _commit(value: object, reason: str) -> None:
    require(isinstance(value, str) and COMMIT.fullmatch(value) is not None, reason)


def _money(value: object) -> Decimal:
    require(isinstance(value, str) and re.fullmatch(r'[0-9]+\.[0-9]{2}', value) is not None,
            'live-approval-budget-schema')
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise RuleViolation('live-approval-budget-schema') from None
    require(parsed > 0, 'live-approval-budget-positive')
    return parsed


def expected_design() -> dict:
    """Return the immutable design target; this is not a runtime configuration."""
    return {
        'schema': DESIGN_SCHEMA,
        'version': VERSION,
        'mode': 'offline-design-only',
        'stage_order': list(STAGES),
        'environment_rollout': {
            'schema_coverage': list(ENVIRONMENTS),
            'first_candidate': 'aws-dev',
            'aws-dev': 'future-separate-migration-candidate',
            'aws-test': 'blocked-until-dev-migration-evidence',
            'aws-prod': 'disabled-until-separate-qualification',
            'currently_live_enabled': [],
        },
        'transport': {
            'schema': TRANSPORT_SCHEMA,
            'dispatch': 'closed-enum-per-stage',
            'stage_operations': {step: list(STAGE_OPERATIONS[step]) for step in STAGES},
            'raw-shell': False,
            'dynamic-command-template': False,
            'endpoint-or-credential-override': False,
            'automatic-retry-or-repair': False,
            'secret-value-return': False,
            'prod-enabled': False,
        },
        'approval': {
            'schema': APPROVAL_SCHEMA,
            'commands': ['verify', 'execute'],
            'verify_can_mutate': False,
            'execute_requires_separate_human_approval': True,
            'one_phase_per_approval': True,
            'one_attempt_per_approval': True,
            'confirmation_template': 'CONFIRM_<ENV>_<PHASE>_EXECUTION',
            'binds': [
                'environment', 'phase', 'transport_version', 'control_plane_commit',
                'approval_text_sha256', 'inputs_sha256', 'scope_sha256',
                'state_sha256', 'predecessor_receipt_sha256',
                'operation_set_sha256', 'proof_sha256', 'start_utc', 'end_utc',
                'proof_created_at_utc', 'proof_expires_at_utc',
                'total_budget_limit_usd',
            ],
            'historical_approval_reusable': False,
            'synthetic_receipt_acceptable': False,
            'prod_approval_supported': False,
        },
        'receipt': {
            'schema': RECEIPT_SCHEMA,
            'storage': 'private-durable-append-only',
            'directory_mode': '0700',
            'file_mode': '0600',
            'canonical_json': True,
            'exclusive_create': True,
            'file_and_directory_fsync': True,
            'symlink_or_hardlink_rejected': True,
            'terminal_success_only': True,
            'exact_predecessor_chain': True,
            'failed_or_pending_is_terminal_stop': True,
            'public_resource_identity_emitted': False,
            'required_fields': [
                'schema', 'transport_version', 'environment', 'phase',
                'phase_index', 'status', 'control_plane_commit',
                'approval_sha256', 'inputs_sha256', 'scope_sha256',
                'operation_set_sha256', 'predecessor_receipt_sha256',
                'journal_completion_sha256', 'raw_output_manifest_sha256',
                'state_before_sha256', 'state_after_sha256', 'completed_at_utc',
                'attempt_count', 'automatic_retry_performed',
                'incident_repair_performed',
            ],
        },
        'migration': {
            'synthetic_receipt_convertible': False,
            'historical_live_receipt_reusable': False,
            'fresh_live_preflight_and_verify_required': True,
            'first_live_stage_has_no_predecessor': True,
            'later_stage_requires_exact_previous_receipt': True,
            'skip_reorder_or_cross_environment_receipt': False,
            'receipt_chain_survives_process_restart': True,
            'live_completion_inferred_from_offline_fixture': False,
        },
        'incident_boundary': {
            'normal_transport_excludes': list(INCIDENT_ONLY_POWERS),
            'requires_new_observation_design_and_approval': True,
            'cannot_resume_normal_chain_automatically': True,
        },
        'effects': {
            'repository_reads_by_validator': True,
            'cloud_transport': False,
            'kubernetes_transport': False,
            'terraform_commands': False,
            'private_evidence_reads': False,
            'system_clock_reads': False,
            'cloud_mutation': False,
            'kubernetes_mutation': False,
            'secret_value_read': False,
            'automatic_retry_or_repair': False,
            'new_live_execution_authorized': False,
        },
    }


def validate_design(value: Mapping[str, object]) -> dict:
    """Validate exact reviewed design bytes represented as data."""
    require(type(value) is dict and value == expected_design(),
            'live-migration-design-drift')
    return {
        'status': 'live-migration-design-validated-offline',
        'version': VERSION,
        'environment_count': len(ENVIRONMENTS),
        'stage_count': len(STAGES),
        'operation_count': sum(len(STAGE_OPERATIONS[step]) for step in STAGES),
        'durable_receipt_designed': True,
        'synthetic_receipt_convertible': False,
        'currently_live_enabled_environment_count': 0,
        'prod_enabled': False,
        'execution_authorized': False,
    }


def review_approval_shape(value: Mapping[str, object], *, environment: str,
                          phase: str, main: str, current_utc: str,
                          expected_predecessor_sha256: str | None) -> dict:
    """Review a future approval fixture without authorizing or executing it."""
    require(type(value) is dict and environment in ENVIRONMENTS and phase in STAGES,
            'live-approval-target')
    require(environment != 'aws-prod', 'prod-live-disabled')
    require(value.get('schema') == APPROVAL_SCHEMA
            and value.get('transport_version') == TRANSPORT_SCHEMA
            and value.get('environment') == environment
            and value.get('phase') == phase, 'live-approval-binding')
    require(value.get('mode') == 'live'
            and value.get('execution_authorized') is False
            and value.get('automatic_retry_authorized') is False
            and value.get('repair_authorized') is False,
            'live-approval-authority-flags')
    _commit(main, 'live-approval-main')
    require(value.get('control_plane_commit') == main, 'live-approval-main-drift')
    for key in COMMON_APPROVAL_HASHES:
        _sha(value.get(key), 'live-approval-hash')
    state = value.get('state_sha256')
    require(state is None or (isinstance(state, str) and SHA256.fullmatch(state)),
            'live-approval-state-hash')
    predecessor = value.get('predecessor_receipt_sha256')
    if STAGES.index(phase) == 0:
        require(expected_predecessor_sha256 is None and predecessor is None,
                'live-approval-first-predecessor')
    else:
        _sha(expected_predecessor_sha256, 'live-approval-expected-predecessor')
        require(predecessor == expected_predecessor_sha256,
                'live-approval-predecessor-drift')
    validate_window(value.get('start_utc'), value.get('end_utc'), current_utc,
                    maximum_seconds=28800, minimum_remaining_seconds=60)
    validate_proof(value.get('proof_created_at_utc'), value.get('proof_expires_at_utc'),
                   current_utc, value.get('end_utc'), ttl_seconds=900,
                   original_created=value.get('proof_created_at_utc'))
    _money(value.get('total_budget_limit_usd'))
    return {
        'status': 'future-live-approval-shape-reviewed',
        'environment': environment,
        'phase': phase,
        'design_only': True,
        'execution_authorized': False,
    }


def review_receipt_shape(value: Mapping[str, object], *, environment: str,
                         phase: str, main: str,
                         expected_predecessor_sha256: str | None) -> dict:
    """Review a future terminal receipt fixture; never persist or consume it."""
    require(type(value) is dict and environment in ENVIRONMENTS and phase in STAGES,
            'live-receipt-target')
    require(value.get('schema') == RECEIPT_SCHEMA
            and value.get('transport_version') == TRANSPORT_SCHEMA
            and value.get('environment') == environment
            and value.get('phase') == phase
            and value.get('phase_index') == STAGES.index(phase),
            'live-receipt-binding')
    _commit(main, 'live-receipt-main')
    require(value.get('control_plane_commit') == main, 'live-receipt-main-drift')
    require(value.get('status') == 'terminal-success'
            and value.get('attempt_count') == 1
            and value.get('automatic_retry_performed') is False
            and value.get('incident_repair_performed') is False,
            'live-receipt-terminal-flags')
    require('simulation_only' not in value and 'confirmed' not in value,
            'synthetic-receipt-conversion-forbidden')
    required = expected_design()['receipt']['required_fields']
    require(set(value) == set(required), 'live-receipt-field-set')
    for key in RECEIPT_HASH_FIELDS:
        _sha(value.get(key), 'live-receipt-hash')
    predecessor = value.get('predecessor_receipt_sha256')
    if STAGES.index(phase) == 0:
        require(expected_predecessor_sha256 is None and predecessor is None,
                'live-receipt-first-predecessor')
    else:
        _sha(expected_predecessor_sha256, 'live-receipt-expected-predecessor')
        require(predecessor == expected_predecessor_sha256,
                'live-receipt-predecessor-drift')
    parse_utc(value.get('completed_at_utc'))
    return {
        'status': 'future-live-receipt-shape-reviewed',
        'environment': environment,
        'phase': phase,
        'design_only': True,
        'receipt_persisted': False,
    }


def review_receipt_prefix(rows: Sequence[Mapping[str, object]], *,
                          environment: str) -> tuple[str, ...]:
    """Check exact in-environment phase order for supplied receipt metadata."""
    require(environment in ENVIRONMENTS and isinstance(rows, (tuple, list)),
            'live-receipt-prefix-target')
    require(len(rows) <= len(STAGES), 'live-receipt-prefix-length')
    phases = []
    previous = None
    for index, row in enumerate(rows):
        phase = STAGES[index]
        require(type(row) is dict and row.get('environment') == environment
                and row.get('phase') == phase and row.get('phase_index') == index
                and row.get('status') == 'terminal-success',
                'live-receipt-prefix-order')
        require(row.get('predecessor_receipt_sha256') == previous,
                'live-receipt-prefix-link')
        _sha(row.get('receipt_sha256'), 'live-receipt-prefix-hash')
        previous = row['receipt_sha256']
        phases.append(phase)
    return tuple(phases)

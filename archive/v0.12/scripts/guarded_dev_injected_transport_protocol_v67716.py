"""Pure injected aws-dev transport protocol and fixed-fake conformance core.

All clocks, approvals, responses, state hashes and postconditions are supplied
as data.  This module has no filesystem, environment, subprocess, SDK,
Kubernetes, AWS or Terraform access and creates no live or durable receipt.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from guarded_dev_live_transport_design_v67715 import (
    APPROVAL_SCHEMA,
    COMMON_BINDINGS,
    ENVIRONMENT,
    POSTCONDITIONS,
    RECEIPT_SCHEMA,
    REQUEST_SCHEMA,
    RESPONSE_SCHEMA,
    TRANSPORT_SCHEMA,
    expected_design,
    expected_stage_designs,
)
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS
from guarded_runtime_rules import RuleViolation, parse_utc, require


VERSION = 'v0.11.9.3.6.7.7.16'
PREDECESSOR = 'v0.11.9.3.6.7.7.15'
VERIFY_SCHEMA = 'guarded-dev-offline-protocol-verify-v1'
CONFORMANCE_RECEIPT_SCHEMA = 'guarded-dev-offline-protocol-receipt-v1'
JOURNAL_SCHEMA = 'guarded-dev-offline-protocol-journal-v1'
SHA256 = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')

APPROVAL_FIELDS = (
    'schema', 'mode', 'environment', 'phase', 'transport_schema',
    'control_plane_commit', 'reviewed_verify_sha256', 'inputs_sha256',
    'scope_sha256', 'operation_set_sha256', 'proof_sha256',
    'state_before_sha256', 'predecessor_receipt_sha256', 'start_utc',
    'end_utc', 'budget_limit_usd', 'execution_authorized',
    'automatic_retry_authorized', 'repair_authorized', 'simulation_only',
    'saved_plan_bundle',
)
VERIFY_FIELDS = (
    'schema', 'environment', 'phase', 'control_plane_commit',
    'inputs_sha256', 'scope_sha256', 'operation_set_sha256', 'proof_sha256',
    'state_before_sha256', 'predecessor_receipt_sha256', 'verified_at_utc',
    'verify_expires_at_utc', 'simulation_only', 'execution_authorized',
)
SAVED_PLAN_FIELDS = (
    'binary_plan_sha256', 'json_plan_sha256', 'text_plan_sha256',
    'plan_gate_sha256', 'provider_lock_sha256', 'terraform_version',
    'terraform_workspace',
)
RECEIPT_FIELDS = (
    'schema', 'live_receipt_schema_candidate', 'version', 'environment',
    'phase', 'phase_index', 'status', 'control_plane_commit',
    'approval_sha256', 'reviewed_verify_sha256', 'inputs_sha256',
    'scope_sha256', 'operation_set_sha256', 'proof_sha256',
    'predecessor_receipt_sha256', 'journal_sha256',
    'postcondition_set_sha256', 'state_before_sha256',
    'state_after_sha256', 'completed_at_utc', 'attempt_count',
    'automatic_retry_performed', 'automatic_repair_performed',
    'simulation_only', 'live_execution_authorized',
)


def canonical(value: dict | list) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def operation_set_sha256(phase: str) -> str:
    require(phase in STAGES, 'protocol-phase')
    return sha(canonical(list(STAGE_OPERATIONS[phase])))


def _hash(value: object, reason: str) -> None:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None,
            reason)


def _commit(value: object, reason: str) -> None:
    require(isinstance(value, str) and COMMIT.fullmatch(value) is not None,
            reason)


def _money(value: object) -> None:
    require(isinstance(value, str) and
            re.fullmatch(r'[0-9]+\.[0-9]{2}', value) is not None,
            'protocol-budget-schema')
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise RuleViolation('protocol-budget-schema') from None
    require(parsed > 0, 'protocol-budget-positive')


def _canonical_object(raw: bytes, reason: str) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuleViolation(reason) from None
    require(type(value) is dict and canonical(value) == raw, reason)
    return value


def _stage_design(phase: str) -> dict:
    require(phase in STAGES, 'protocol-phase')
    return dict(expected_stage_designs()[STAGES.index(phase)])


class ProtocolStopped(RuleViolation):
    """Stable redacted stop report for the injected offline protocol."""

    def __init__(self, stage: str, *, phase: str, operation: str | None,
                 intent_count: int, call_count: int):
        super().__init__('dev-injected-protocol-stopped')
        self.report = {
            'status': 'dev-injected-transport-protocol-stopped',
            'stage': stage,
            'phase': phase,
            'operation': operation,
            'intent_count': intent_count,
            'fake_call_count': call_count,
            'terminal_receipt_created': False,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'live_transport_executed': False,
            'live_execution_authorized': False,
        }


class FixedFakeJournal:
    """In-memory ordered protocol events; this is not durable storage."""

    def __init__(self):
        self.events: list[dict] = []

    def intent(self, *, phase: str, operation: str, request: bytes) -> None:
        self.events.append({
            'schema': JOURNAL_SCHEMA,
            'kind': 'intent',
            'phase': phase,
            'operation': operation,
            'request_sha256': sha(request),
            'simulation_only': True,
        })

    def response(self, *, phase: str, operation: str, raw: bytes) -> None:
        self.events.append({
            'schema': JOURNAL_SCHEMA,
            'kind': 'response',
            'phase': phase,
            'operation': operation,
            'response_sha256': sha(raw),
            'simulation_only': True,
        })

    def terminal(self, *, phase: str, receipt_sha256: str) -> None:
        self.events.append({
            'schema': JOURNAL_SCHEMA,
            'kind': 'terminal',
            'phase': phase,
            'receipt_sha256': receipt_sha256,
            'simulation_only': True,
        })


class FixedFakeTransport:
    """Closed deterministic fake; it cannot construct or reach a backend."""

    def __init__(self, *, fail_at: str = '', overrides: dict[str, bytes] | None = None):
        require(isinstance(fail_at, str) and
                (overrides is None or type(overrides) is dict),
                'fixed-fake-config')
        self.fail_at = fail_at
        self.overrides = dict(overrides or {})
        require(all(isinstance(key, str) and isinstance(value, bytes)
                    for key, value in self.overrides.items()),
                'fixed-fake-override-schema')
        self.calls: list[tuple[str, bytes]] = []

    def call(self, operation: str, request: bytes) -> bytes:
        require(isinstance(operation, str) and isinstance(request, bytes),
                'fixed-fake-call-schema')
        self.calls.append((operation, request))
        require(operation != self.fail_at, 'fixed-fake-injected-failure')
        if operation in self.overrides:
            return self.overrides[operation]
        envelope = _canonical_object(request, 'fixed-fake-request-canonical')
        return canonical({
            'schema': RESPONSE_SCHEMA,
            'environment': ENVIRONMENT,
            'phase': envelope['phase'],
            'operation': operation,
            'operation_index': envelope['operation_index'],
            'request_sha256': sha(request),
            'outcome': 'success',
            'mutation_acknowledged': envelope['mutation_expected'],
            'simulation_only': True,
            'live_effect_performed': False,
        })


def validate_receipt_prefix(receipts: tuple[dict, ...], *, main: str,
                            phase: str) -> str | None:
    """Validate only synthetic conformance receipts; never accept live history."""
    require(type(receipts) is tuple and phase in STAGES,
            'protocol-prefix-schema')
    expected_count = STAGES.index(phase)
    require(len(receipts) == expected_count, 'protocol-prefix-length')
    previous = None
    for index, receipt in enumerate(receipts):
        expected_phase = STAGES[index]
        require(type(receipt) is dict and set(receipt) == set(RECEIPT_FIELDS) and
                receipt.get('schema') == CONFORMANCE_RECEIPT_SCHEMA and
                receipt.get('live_receipt_schema_candidate') == RECEIPT_SCHEMA and
                receipt.get('version') == VERSION and
                receipt.get('environment') == ENVIRONMENT and
                receipt.get('phase') == expected_phase and
                receipt.get('phase_index') == index and
                receipt.get('control_plane_commit') == main and
                receipt.get('predecessor_receipt_sha256') == previous and
                receipt.get('status') == 'terminal-success' and
                receipt.get('simulation_only') is True and
                receipt.get('live_execution_authorized') is False and
                receipt.get('attempt_count') == 1 and
                receipt.get('automatic_retry_performed') is False and
                receipt.get('automatic_repair_performed') is False,
                'protocol-prefix-receipt')
        previous = sha(canonical(receipt))
    return previous


def validate_verify(verify: dict, *, main: str, phase: str,
                    predecessor: str | None, current_utc: str) -> None:
    require(type(verify) is dict and set(verify) == set(VERIFY_FIELDS),
            'protocol-verify-field-set')
    require(verify['schema'] == VERIFY_SCHEMA and
            verify['environment'] == ENVIRONMENT and
            verify['phase'] == phase and
            verify['control_plane_commit'] == main and
            verify['predecessor_receipt_sha256'] == predecessor and
            verify['operation_set_sha256'] == operation_set_sha256(phase) and
            verify['simulation_only'] is True and
            verify['execution_authorized'] is False,
            'protocol-verify-binding')
    for key in ('inputs_sha256', 'scope_sha256', 'operation_set_sha256',
                'proof_sha256', 'state_before_sha256'):
        _hash(verify[key], 'protocol-verify-hash')
    verified = parse_utc(verify['verified_at_utc'])
    expires = parse_utc(verify['verify_expires_at_utc'])
    current = parse_utc(current_utc)
    require(verified <= current < expires and
            0 < (expires - verified).total_seconds() <= 900,
            'protocol-verify-expired')


def validate_approval(approval: dict, *, verify: dict, main: str, phase: str,
                      predecessor: str | None, current_utc: str) -> None:
    require(type(approval) is dict and set(approval) == set(APPROVAL_FIELDS),
            'protocol-approval-field-set')
    require(approval['schema'] == APPROVAL_SCHEMA and
            approval['mode'] == 'offline-conformance' and
            approval['environment'] == ENVIRONMENT and
            approval['phase'] == phase and
            approval['transport_schema'] == TRANSPORT_SCHEMA and
            approval['control_plane_commit'] == main and
            approval['predecessor_receipt_sha256'] == predecessor and
            approval['reviewed_verify_sha256'] == sha(canonical(verify)) and
            approval['operation_set_sha256'] == operation_set_sha256(phase) and
            approval['execution_authorized'] is False and
            approval['automatic_retry_authorized'] is False and
            approval['repair_authorized'] is False and
            approval['simulation_only'] is True,
            'protocol-approval-binding')
    for key in ('reviewed_verify_sha256', 'inputs_sha256', 'scope_sha256',
                'operation_set_sha256', 'proof_sha256', 'state_before_sha256'):
        _hash(approval[key], 'protocol-approval-hash')
    for key in ('inputs_sha256', 'scope_sha256', 'operation_set_sha256',
                'proof_sha256', 'state_before_sha256'):
        require(approval[key] == verify[key], 'protocol-verify-approval-drift')
    _money(approval['budget_limit_usd'])
    start, end, current = map(parse_utc, (
        approval['start_utc'], approval['end_utc'], current_utc))
    require(start <= current and 60 <= (end - current).total_seconds() and
            0 < (end - start).total_seconds() <= 28800,
            'protocol-approval-window')
    design = _stage_design(phase)
    plan = approval['saved_plan_bundle']
    if design['savedPlanBundleRequired']:
        require(type(plan) is dict and set(plan) == set(SAVED_PLAN_FIELDS),
                'protocol-saved-plan-field-set')
        for key in SAVED_PLAN_FIELDS[:5]:
            _hash(plan[key], 'protocol-saved-plan-hash')
        require(isinstance(plan['terraform_version'], str) and
                isinstance(plan['terraform_workspace'], str) and
                bool(plan['terraform_version']) and
                plan['terraform_workspace'] == 'default',
                'protocol-saved-plan-runtime')
    else:
        require(plan is None, 'protocol-unexpected-saved-plan')


def _request(*, phase: str, operation: str, index: int, approval: dict,
             approval_sha256: str, predecessor: str | None) -> dict:
    request = {
        'schema': REQUEST_SCHEMA,
        'transport_schema': TRANSPORT_SCHEMA,
        'environment': ENVIRONMENT,
        'operation': operation,
        'operation_index': index,
        'mutation_expected': operation in _stage_design(phase)['mutationOperationIds'],
        'simulation_only': True,
        'live_execution_authorized': False,
        'control_plane_commit': approval['control_plane_commit'],
        'phase': phase,
        'approval_sha256': approval_sha256,
        'reviewed_verify_sha256': approval['reviewed_verify_sha256'],
        'inputs_sha256': approval['inputs_sha256'],
        'scope_sha256': approval['scope_sha256'],
        'operation_set_sha256': approval['operation_set_sha256'],
        'proof_sha256': approval['proof_sha256'],
        'state_before_sha256': approval['state_before_sha256'],
        'predecessor_receipt_sha256': predecessor,
        'start_utc': approval['start_utc'],
        'end_utc': approval['end_utc'],
        'budget_limit_usd': approval['budget_limit_usd'],
    }
    plan = approval['saved_plan_bundle']
    if plan is not None:
        request.update(plan)
    return request


def _validate_response(raw: bytes, *, request: dict, operation: str,
                       mutation: bool) -> None:
    value = _canonical_object(raw, 'protocol-response-canonical')
    require(value == {
        'schema': RESPONSE_SCHEMA,
        'environment': ENVIRONMENT,
        'phase': request['phase'],
        'operation': operation,
        'operation_index': request['operation_index'],
        'request_sha256': sha(canonical(request)),
        'outcome': 'success',
        'mutation_acknowledged': mutation,
        'simulation_only': True,
        'live_effect_performed': False,
    }, 'protocol-response-binding')


def run_fixed_fake_conformance(*, design: dict, main: str, phase: str,
                               receipts: tuple[dict, ...], verify: dict,
                               approval: dict, current_utc: str,
                               completed_at_utc: str, state_after_sha256: str,
                               postconditions: dict[str, bool],
                               transport: FixedFakeTransport,
                               journal: FixedFakeJournal) -> dict:
    """Run one phase through injected fakes and return a non-live receipt."""
    operation = None
    try:
        require(design == expected_design(), 'protocol-design-drift')
        _commit(main, 'protocol-main')
        require(phase in STAGES, 'protocol-phase')
        require(type(transport) is FixedFakeTransport and
                type(journal) is FixedFakeJournal,
                'protocol-fixed-injection-types')
        predecessor = validate_receipt_prefix(receipts, main=main, phase=phase)
        validate_verify(verify, main=main, phase=phase,
                        predecessor=predecessor, current_utc=current_utc)
        validate_approval(approval, verify=verify, main=main, phase=phase,
                          predecessor=predecessor, current_utc=current_utc)
        approval_hash = sha(canonical(approval))
        operations = STAGE_OPERATIONS[phase]
        mutations = set(_stage_design(phase)['mutationOperationIds'])
        for index, operation in enumerate(operations):
            request = _request(phase=phase, operation=operation, index=index,
                               approval=approval,
                               approval_sha256=approval_hash,
                               predecessor=predecessor)
            raw_request = canonical(request)
            journal.intent(phase=phase, operation=operation, request=raw_request)
            raw_response = transport.call(operation, raw_request)
            _validate_response(raw_response, request=request, operation=operation,
                               mutation=operation in mutations)
            journal.response(phase=phase, operation=operation, raw=raw_response)
        require(tuple(transport.calls[index][0] for index in range(len(operations)))
                == operations and len(transport.calls) == len(operations),
                'protocol-call-sequence')
        expected_conditions = POSTCONDITIONS[phase]
        require(type(postconditions) is dict and
                tuple(postconditions) == expected_conditions and
                all(value is True for value in postconditions.values()),
                'protocol-postconditions')
        _hash(state_after_sha256, 'protocol-state-after-hash')
        state_relation = _stage_design(phase)['stateAfterRelation']
        if state_relation == 'unchanged':
            require(state_after_sha256 == approval['state_before_sha256'],
                    'protocol-state-changed')
        else:
            require(state_after_sha256 != approval['state_before_sha256'],
                    'protocol-state-transition-missing')
        completed = parse_utc(completed_at_utc)
        require(parse_utc(current_utc) <= completed <= parse_utc(approval['end_utc']),
                'protocol-completion-clock')
        journal_before_terminal = sha(canonical(journal.events))
        receipt = {
            'schema': CONFORMANCE_RECEIPT_SCHEMA,
            'live_receipt_schema_candidate': RECEIPT_SCHEMA,
            'version': VERSION,
            'environment': ENVIRONMENT,
            'phase': phase,
            'phase_index': STAGES.index(phase),
            'status': 'terminal-success',
            'control_plane_commit': main,
            'approval_sha256': approval_hash,
            'reviewed_verify_sha256': approval['reviewed_verify_sha256'],
            'inputs_sha256': approval['inputs_sha256'],
            'scope_sha256': approval['scope_sha256'],
            'operation_set_sha256': approval['operation_set_sha256'],
            'proof_sha256': approval['proof_sha256'],
            'predecessor_receipt_sha256': predecessor,
            'journal_sha256': journal_before_terminal,
            'postcondition_set_sha256': sha(canonical(list(expected_conditions))),
            'state_before_sha256': approval['state_before_sha256'],
            'state_after_sha256': state_after_sha256,
            'completed_at_utc': completed_at_utc,
            'attempt_count': 1,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'simulation_only': True,
            'live_execution_authorized': False,
        }
        receipt_hash = sha(canonical(receipt))
        journal.terminal(phase=phase, receipt_sha256=receipt_hash)
        return {
            'status': 'dev-injected-transport-protocol-conformance-complete',
            'version': VERSION,
            'environment': ENVIRONMENT,
            'phase': phase,
            'operation_count': len(operations),
            'intent_count': len(operations),
            'fake_call_count': len(transport.calls),
            'response_count': len(operations),
            'postcondition_count': len(expected_conditions),
            'receipt': receipt,
            'receipt_sha256': receipt_hash,
            'terminal_receipt_created': True,
            'receipt_is_durable': False,
            'receipt_usable_for_live': False,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'live_transport_executed': False,
            'live_execution_authorized': False,
        }
    except ProtocolStopped:
        raise
    except (RuleViolation, KeyError, IndexError, TypeError, ValueError):
        intent_count = (sum(row.get('kind') == 'intent'
                            for row in journal.events)
                        if type(journal) is FixedFakeJournal else 0)
        call_count = (len(transport.calls)
                      if type(transport) is FixedFakeTransport else 0)
        raise ProtocolStopped(
            'protocol-conformance', phase=phase, operation=operation,
            intent_count=intent_count, call_count=call_count) from None

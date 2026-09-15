"""Dev-only offline command-entry conformance.

All clocks and private inputs are fixed in-memory test doubles. The only file
effects come from the explicitly injected v0.11.9.3.6.7.7.9 receipt store. No
CLI, environment, network, cloud, Kubernetes or Terraform backend exists here.
"""
from __future__ import annotations

import hashlib
import json
import re

from guarded_dev_transport_conformance_v6779 import (
    ConformanceStopped,
    DevConformanceTransport,
    DevTransportConformanceHarness,
    DurableReceiptStore,
    ReceiptStoreStopped,
    canonical,
    operation_set_sha256,
)
from guarded_live_migration_contract_v6778 import STAGES, review_approval_shape
from guarded_runtime_rules import RuleViolation, parse_utc, require


VERSION = 'v0.11.9.3.6.7.7.10'
ENVIRONMENT = 'aws-dev'
COMMAND_SCHEMA = 'guarded-dev-offline-command-v1'
VERIFY_SCHEMA = 'guarded-dev-offline-command-verify-v1'
PRIVATE_INPUT_NAMES = ('approval', 'evidence', 'reviewed-verify')
SHA256 = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')
CONFIRMATIONS = {
    phase: f'execute-reviewed-aws-dev-{phase}-offline-conformance'
    for phase in STAGES
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: object, reason: str) -> None:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None,
            reason)


def _commit(value: object, reason: str) -> None:
    require(isinstance(value, str) and COMMIT.fullmatch(value) is not None,
            reason)


class CommandEntryStopped(RuleViolation):
    """Stable fail-closed report that never returns private input bytes."""

    def __init__(self, stage: str, *, private_reads: int,
                 fake_transport_attempted: bool = False):
        super().__init__('dev-offline-command-entry-stopped')
        self.report = {
            'status': 'dev-offline-command-entry-stopped',
            'stage': stage,
            'private_input_read_count': private_reads,
            'fake_transport_attempted': fake_transport_attempted,
            'preserve_receipt_store': True,
            'automatic_retry_performed': False,
            'system_clock_read': False,
            'live_private_evidence_read': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'live_execution_authorized': False,
        }


class FrozenClock:
    """Exact injected UTC readings; never consults the host clock."""

    def __init__(self, readings: tuple[str, ...]):
        require(type(readings) is tuple and readings,
                'offline-clock-readings')
        for value in readings:
            require(isinstance(value, str), 'offline-clock-reading')
            parse_utc(value)
        self._readings = readings
        self._index = 0

    def now(self) -> str:
        require(self._index < len(self._readings), 'offline-clock-exhausted')
        value = self._readings[self._index]
        self._index += 1
        return value

    @property
    def read_count(self) -> int:
        return self._index


class FixedPrivateInputReader:
    """Read canonical private fixture bytes by closed logical name."""

    def __init__(self, payloads: dict[str, bytes]):
        require(type(payloads) is dict and payloads,
                'offline-private-input-map')
        require(set(payloads).issubset(PRIVATE_INPUT_NAMES),
                'offline-private-input-name')
        require(all(isinstance(value, bytes) for value in payloads.values()),
                'offline-private-input-bytes')
        self._payloads = dict(payloads)
        self.reads = []

    def read(self, name: str) -> bytes:
        require(name in PRIVATE_INPUT_NAMES and name in self._payloads,
                'offline-private-input-missing')
        self.reads.append(name)
        return self._payloads[name]


def command_request(*, command: str, phase: str, main: str,
                    approval_sha256: str, evidence_sha256: str,
                    reviewed_verify_sha256: str | None = None,
                    confirmation: str | None = None) -> dict:
    """Build one exact offline request without accepting paths or endpoints."""
    return {
        'schema': COMMAND_SCHEMA,
        'version': VERSION,
        'command': command,
        'environment': ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': main,
        'approval_input': 'approval',
        'approval_sha256': approval_sha256,
        'evidence_input': 'evidence',
        'evidence_sha256': evidence_sha256,
        'reviewed_verify_input': (
            'reviewed-verify' if command == 'execute' else None),
        'reviewed_verify_sha256': reviewed_verify_sha256,
        'confirmation': confirmation,
        'simulation_only': True,
    }


class DevOfflineCommandEntry:
    """Closed verify/execute dispatcher using injected offline dependencies."""

    def __init__(self, *, main: str, clock: FrozenClock,
                 reader: FixedPrivateInputReader, store: DurableReceiptStore):
        _commit(main, 'offline-command-main')
        require(type(clock) is FrozenClock, 'offline-command-fixed-clock')
        require(type(reader) is FixedPrivateInputReader,
                'offline-command-fixed-reader')
        require(type(store) is DurableReceiptStore,
                'offline-command-fixed-store')
        self.main = main
        self.clock = clock
        self.reader = reader
        self.store = store

    @staticmethod
    def _request(value: dict, command: str) -> None:
        require(type(value) is dict and set(value) == {
            'schema', 'version', 'command', 'environment', 'phase',
            'control_plane_commit', 'approval_input', 'approval_sha256',
            'evidence_input', 'evidence_sha256', 'reviewed_verify_input',
            'reviewed_verify_sha256', 'confirmation', 'simulation_only',
        }, 'offline-command-request-schema')
        require(value.get('schema') == COMMAND_SCHEMA
                and value.get('version') == VERSION
                and value.get('command') == command
                and value.get('environment') == ENVIRONMENT
                and value.get('phase') in STAGES
                and value.get('approval_input') == 'approval'
                and value.get('evidence_input') == 'evidence'
                and value.get('simulation_only') is True,
                'offline-command-request-binding')
        _commit(value.get('control_plane_commit'), 'offline-command-main')
        _hash(value.get('approval_sha256'), 'offline-command-approval-hash')
        _hash(value.get('evidence_sha256'), 'offline-command-evidence-hash')
        if command == 'verify':
            require(value.get('reviewed_verify_input') is None
                    and value.get('reviewed_verify_sha256') is None
                    and value.get('confirmation') is None,
                    'offline-verify-authority')
        else:
            require(value.get('reviewed_verify_input') == 'reviewed-verify',
                    'offline-execute-verify-input')
            _hash(value.get('reviewed_verify_sha256'),
                  'offline-execute-verify-hash')
            require(value.get('confirmation') == CONFIRMATIONS[value['phase']],
                    'offline-execute-confirmation')

    def _input(self, name: str, expected_sha256: str) -> dict:
        raw = self.reader.read(name)
        require(sha(raw) == expected_sha256, 'offline-private-input-drift')
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuleViolation('offline-private-input-json') from None
        require(type(value) is dict and canonical(value) == raw,
                'offline-private-input-canonical')
        return value

    def _prefix(self, phase: str) -> str | None:
        prefix = self.store.load_prefix()
        require(len(prefix) < len(STAGES) and STAGES[len(prefix)] == phase,
                'offline-command-receipt-prefix')
        return prefix[-1]['receipt_sha256'] if prefix else None

    @staticmethod
    def _evidence(value: dict) -> None:
        require(type(value) is dict and set(value) == {
            'journal_completion_sha256', 'raw_output_manifest_sha256',
            'state_after_sha256'}, 'offline-command-evidence-schema')
        for item in value.values():
            _hash(item, 'offline-command-evidence-hash')

    def _review_inputs(self, request: dict, current_utc: str) -> tuple[dict, dict, str | None]:
        phase = request['phase']
        require(request['control_plane_commit'] == self.main,
                'offline-command-main-drift')
        predecessor = self._prefix(phase)
        approval = self._input('approval', request['approval_sha256'])
        evidence = self._input('evidence', request['evidence_sha256'])
        review_approval_shape(
            approval, environment=ENVIRONMENT, phase=phase, main=self.main,
            current_utc=current_utc,
            expected_predecessor_sha256=predecessor)
        require(approval.get('operation_set_sha256') == operation_set_sha256(phase),
                'offline-command-operation-set')
        self._evidence(evidence)
        return approval, evidence, predecessor

    def verify(self, request: dict) -> dict:
        try:
            self._request(request, 'verify')
            require(set(self.reader._payloads) == {'approval', 'evidence'},
                    'offline-verify-private-input-scope')
            current = self.clock.now()
            approval, unused, predecessor = self._review_inputs(request, current)
            return {
                'schema': VERIFY_SCHEMA,
                'status': 'dev-offline-command-inputs-verified',
                'version': VERSION,
                'environment': ENVIRONMENT,
                'phase': request['phase'],
                'control_plane_commit': self.main,
                'reviewed_approval_sha256': request['approval_sha256'],
                'reviewed_evidence_sha256': request['evidence_sha256'],
                'operation_set_sha256': operation_set_sha256(request['phase']),
                'predecessor_receipt_sha256': predecessor,
                'verified_at_utc': current,
                'verify_expires_at_utc': approval['proof_expires_at_utc'],
                'end_utc': approval['end_utc'],
                'execution_authorized': False,
                'simulation_only': True,
                'system_clock_read': False,
                'live_private_evidence_read': False,
                'live_transport_executed': False,
            }
        except CommandEntryStopped:
            raise
        except (RuleViolation, ReceiptStoreStopped, TypeError, ValueError, KeyError):
            raise CommandEntryStopped(
                'verify-gate', private_reads=len(self.reader.reads)) from None

    def _review_verify(self, value: dict, request: dict,
                       current_utc: str, predecessor: str | None) -> None:
        require(type(value) is dict and set(value) == {
            'schema', 'status', 'version', 'environment', 'phase',
            'control_plane_commit', 'reviewed_approval_sha256',
            'reviewed_evidence_sha256', 'operation_set_sha256',
            'predecessor_receipt_sha256', 'verified_at_utc',
            'verify_expires_at_utc', 'end_utc', 'execution_authorized',
            'simulation_only', 'system_clock_read',
            'live_private_evidence_read', 'live_transport_executed',
        }, 'offline-reviewed-verify-schema')
        require(value.get('schema') == VERIFY_SCHEMA
                and value.get('status') == 'dev-offline-command-inputs-verified'
                and value.get('version') == VERSION
                and value.get('environment') == ENVIRONMENT
                and value.get('phase') == request['phase']
                and value.get('control_plane_commit') == self.main
                and value.get('reviewed_approval_sha256') == request['approval_sha256']
                and value.get('reviewed_evidence_sha256') == request['evidence_sha256']
                and value.get('operation_set_sha256') == operation_set_sha256(request['phase'])
                and value.get('predecessor_receipt_sha256') == predecessor
                and value.get('execution_authorized') is False
                and value.get('simulation_only') is True
                and value.get('system_clock_read') is False
                and value.get('live_private_evidence_read') is False
                and value.get('live_transport_executed') is False,
                'offline-reviewed-verify-binding')
        verified = parse_utc(value.get('verified_at_utc'))
        expiry = parse_utc(value.get('verify_expires_at_utc'))
        end = parse_utc(value.get('end_utc'))
        current = parse_utc(current_utc)
        require(verified <= current <= expiry <= end,
                'offline-reviewed-verify-clock')

    def execute(self, request: dict, transport: DevConformanceTransport) -> dict:
        attempted = False
        try:
            self._request(request, 'execute')
            require(type(transport) is DevConformanceTransport,
                    'offline-execute-fixed-transport')
            require(set(self.reader._payloads) == {
                'approval', 'evidence', 'reviewed-verify'},
                'offline-execute-private-input-scope')
            current = self.clock.now()
            approval, evidence, predecessor = self._review_inputs(request, current)
            reviewed = self._input(
                'reviewed-verify', request['reviewed_verify_sha256'])
            self._review_verify(reviewed, request, current, predecessor)
            completed = self.clock.now()
            attempted = True
            report = DevTransportConformanceHarness(
                main=self.main, store=self.store).run_phase(
                    phase=request['phase'], approval=approval,
                    current_utc=current, completed_at_utc=completed,
                    evidence=evidence, transport=transport)
            return {
                'status': 'dev-offline-command-execution-complete',
                'version': VERSION,
                'environment': ENVIRONMENT,
                'phase': request['phase'],
                'reviewed_verify_sha256': request['reviewed_verify_sha256'],
                'receipt_sha256': report['receipt_sha256'],
                'durable_receipt_appended': True,
                'fake_transport_executed': True,
                'simulation_only': True,
                'system_clock_read': False,
                'live_private_evidence_read': False,
                'kubernetes_transport_executed': False,
                'aws_transport_executed': False,
                'terraform_command_executed': False,
                'live_execution_authorized': False,
            }
        except CommandEntryStopped:
            raise
        except (RuleViolation, ReceiptStoreStopped, ConformanceStopped,
                TypeError, ValueError, KeyError):
            raise CommandEntryStopped(
                'execute-gate', private_reads=len(self.reader.reads),
                fake_transport_attempted=attempted) from None

    def dispatch(self, command: str, request: dict,
                 transport: DevConformanceTransport | None = None) -> dict:
        try:
            require(command in ('verify', 'execute')
                    and request.get('command') == command,
                    'offline-command-dispatch')
            if command == 'verify':
                require(transport is None, 'offline-verify-no-transport')
                return self.verify(request)
            require(transport is not None, 'offline-execute-transport')
            return self.execute(request, transport)
        except CommandEntryStopped:
            raise
        except (RuleViolation, AttributeError, TypeError):
            raise CommandEntryStopped(
                'dispatch-gate', private_reads=len(self.reader.reads)) from None

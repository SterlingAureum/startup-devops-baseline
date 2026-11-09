"""Dev-only offline transport conformance and durable receipt storage.

The transport is a fixed fake and cannot reach Kubernetes, AWS or Terraform.
The receipt store performs local Linux file operations only. No live execution
entry point or dynamic backend is provided.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from guarded_live_migration_contract_v6778 import (
    RECEIPT_SCHEMA,
    STAGES,
    STAGE_OPERATIONS,
    TRANSPORT_SCHEMA,
    review_approval_shape,
    review_receipt_shape,
)
from guarded_runtime_rules import RuleViolation, parse_utc, require


VERSION = 'v0.11.9.3.6.7.7.9'
ENVIRONMENT = 'aws-dev'
RESPONSE_SCHEMA = 'guarded-live-transport-response-v1'
INTENT_SCHEMA = 'guarded-live-receipt-intent-v1'
COMPLETION_SCHEMA = 'guarded-live-receipt-completion-v1'
FAULT_POINTS = (
    'after-intent-open', 'after-intent-write', 'after-intent-file-fsync',
    'after-intent-dir-fsync', 'after-receipt-open', 'after-receipt-write',
    'after-receipt-file-fsync', 'after-receipt-dir-fsync',
    'after-completion-open', 'after-completion-write',
    'after-completion-file-fsync', 'after-completion-dir-fsync',
)
SHA256 = re.compile(r'[0-9a-f]{64}')


def canonical(value: dict | list) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def operation_set_sha256(phase: str) -> str:
    require(phase in STAGES, 'conformance-phase')
    return sha(canonical(list(STAGE_OPERATIONS[phase])))


def _hash(value: object, reason: str) -> None:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, reason)


class ReceiptStoreStopped(RuleViolation):
    """Stable receipt-store failure without a private path or payload."""

    def __init__(self, stage: str):
        super().__init__('durable-receipt-store-stopped')
        self.report = {
            'status': 'offline-durable-receipt-store-stopped',
            'stage': stage,
            'preserve_receipt_store': True,
            'automatic_retry_performed': False,
            'live_execution_authorized': False,
        }


class ConformanceStopped(RuleViolation):
    """Stable transport-conformance failure without request or response bytes."""

    def __init__(self, stage: str, attempted: bool):
        super().__init__('dev-transport-conformance-stopped')
        self.report = {
            'status': 'dev-offline-transport-conformance-stopped',
            'stage': stage,
            'fake_call_attempted': attempted,
            'preserve_receipt_store': True,
            'automatic_retry_performed': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'live_execution_authorized': False,
        }


class ReceiptFaultInjector:
    """One deterministic local-IO failure point for offline tests only."""

    def __init__(self, point: str):
        require(point in FAULT_POINTS, 'receipt-fault-point')
        self.point = point
        self.triggered = False

    def check(self, point: str) -> None:
        require(point in FAULT_POINTS, 'receipt-fault-check')
        if point == self.point and not self.triggered:
            self.triggered = True
            raise OSError('injected receipt-store failure')


class DurableReceiptStore:
    """Exclusive, fsynced, append-only local receipt triplets.

    Each phase owns intent, receipt and completion files. Any partial triplet is
    pending and blocks all subsequent appends; it is never repaired here.
    """

    def __init__(self, directory: Path, *, main: str,
                 fault: ReceiptFaultInjector | None = None):
        require(isinstance(directory, Path) and directory.is_absolute(),
                'receipt-store-absolute-path')
        require(fault is None or type(fault) is ReceiptFaultInjector,
                'receipt-store-fixed-fault-type')
        self.directory = directory
        self.main = main
        self.fault = fault
        self._open_directory()

    def _open_directory(self) -> int:
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(self.directory, flags)
            value = os.fstat(descriptor)
            if (not stat.S_ISDIR(value.st_mode)
                    or stat.S_IMODE(value.st_mode) != 0o700
                    or value.st_uid != os.geteuid()):
                raise ReceiptStoreStopped('directory-scope')
            return descriptor
        except ReceiptStoreStopped:
            raise
        except (OSError, TypeError, ValueError):
            raise ReceiptStoreStopped('directory-open') from None

    @staticmethod
    def _names(index: int, phase: str) -> tuple[str, str, str]:
        prefix = f'{index:03d}.{phase}'
        return (prefix + '.intent.json', prefix + '.receipt.json',
                prefix + '.complete.json')

    @staticmethod
    def _read_regular(descriptor: int, name: str) -> bytes:
        try:
            value = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode)
                    or stat.S_IMODE(value.st_mode) != 0o600
                    or value.st_uid != os.geteuid() or value.st_nlink != 1):
                raise ReceiptStoreStopped('stored-file-scope')
            file_descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW,
                                      dir_fd=descriptor)
            try:
                chunks = []
                while True:
                    chunk = os.read(file_descriptor, 65536)
                    if not chunk:
                        return b''.join(chunks)
                    chunks.append(chunk)
            finally:
                os.close(file_descriptor)
        except ReceiptStoreStopped:
            raise
        except OSError:
            raise ReceiptStoreStopped('stored-file-read') from None

    @staticmethod
    def _json(raw: bytes, reason: str) -> dict:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ReceiptStoreStopped(reason) from None
        if type(value) is not dict or canonical(value) != raw:
            raise ReceiptStoreStopped(reason)
        return value

    def _write_file(self, descriptor: int, name: str, raw: bytes,
                    label: str) -> None:
        file_descriptor = None
        try:
            file_descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=descriptor)
            if self.fault:
                self.fault.check('after-' + label + '-open')
            offset = 0
            while offset < len(raw):
                written = os.write(file_descriptor, raw[offset:])
                if written <= 0:
                    raise OSError('short receipt-store write')
                offset += written
            if self.fault:
                self.fault.check('after-' + label + '-write')
            os.fsync(file_descriptor)
            if self.fault:
                self.fault.check('after-' + label + '-file-fsync')
        except OSError:
            raise ReceiptStoreStopped(label + '-write') from None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
        try:
            os.fsync(descriptor)
            if self.fault:
                self.fault.check('after-' + label + '-dir-fsync')
        except OSError:
            raise ReceiptStoreStopped(label + '-dir-fsync') from None

    def load_prefix(self) -> tuple[dict, ...]:
        descriptor = self._open_directory()
        try:
            allowed = set()
            rows = []
            previous = None
            gap = False
            for index, phase in enumerate(STAGES):
                names = self._names(index, phase)
                allowed.update(names)
                present = tuple(name in os.listdir(descriptor) for name in names)
                if not any(present):
                    gap = True
                    continue
                if gap:
                    raise ReceiptStoreStopped('receipt-prefix-gap')
                if present != (True, True, True):
                    raise ReceiptStoreStopped('pending-append')
                intent_raw = self._read_regular(descriptor, names[0])
                receipt_raw = self._read_regular(descriptor, names[1])
                completion_raw = self._read_regular(descriptor, names[2])
                receipt_hash = sha(receipt_raw)
                intent = self._json(intent_raw, 'intent-schema')
                receipt = self._json(receipt_raw, 'receipt-schema')
                completion = self._json(completion_raw, 'completion-schema')
                if intent != {
                    'schema': INTENT_SCHEMA,
                    'environment': ENVIRONMENT,
                    'phase': phase,
                    'receipt_sha256': receipt_hash,
                }:
                    raise ReceiptStoreStopped('intent-binding')
                if completion != {
                    'schema': COMPLETION_SCHEMA,
                    'receipt_sha256': receipt_hash,
                }:
                    raise ReceiptStoreStopped('completion-binding')
                try:
                    review_receipt_shape(
                        receipt, environment=ENVIRONMENT, phase=phase,
                        main=self.main, expected_predecessor_sha256=previous)
                except RuleViolation:
                    raise ReceiptStoreStopped('receipt-binding') from None
                rows.append({
                    'environment': ENVIRONMENT,
                    'phase': phase,
                    'phase_index': index,
                    'status': 'terminal-success',
                    'predecessor_receipt_sha256': previous,
                    'receipt_sha256': receipt_hash,
                })
                previous = receipt_hash
            actual = set(os.listdir(descriptor))
            if not actual.issubset(allowed):
                raise ReceiptStoreStopped('unexpected-store-entry')
            return tuple(rows)
        except ReceiptStoreStopped:
            raise
        except OSError:
            raise ReceiptStoreStopped('receipt-prefix-read') from None
        finally:
            os.close(descriptor)

    def append(self, receipt: dict) -> dict:
        prefix = self.load_prefix()
        index = len(prefix)
        if index >= len(STAGES):
            raise ReceiptStoreStopped('receipt-chain-complete')
        phase = STAGES[index]
        previous = prefix[-1]['receipt_sha256'] if prefix else None
        try:
            review_receipt_shape(
                receipt, environment=ENVIRONMENT, phase=phase,
                main=self.main, expected_predecessor_sha256=previous)
        except RuleViolation:
            raise ReceiptStoreStopped('new-receipt-binding') from None
        receipt_raw = canonical(receipt)
        receipt_hash = sha(receipt_raw)
        intent_raw = canonical({
            'schema': INTENT_SCHEMA,
            'environment': ENVIRONMENT,
            'phase': phase,
            'receipt_sha256': receipt_hash,
        })
        completion_raw = canonical({
            'schema': COMPLETION_SCHEMA,
            'receipt_sha256': receipt_hash,
        })
        names = self._names(index, phase)
        descriptor = self._open_directory()
        try:
            self._write_file(descriptor, names[0], intent_raw, 'intent')
            self._write_file(descriptor, names[1], receipt_raw, 'receipt')
            self._write_file(descriptor, names[2], completion_raw, 'completion')
        finally:
            os.close(descriptor)
        return {
            'status': 'offline-durable-receipt-appended',
            'environment': ENVIRONMENT,
            'phase': phase,
            'phase_index': index,
            'receipt_sha256': receipt_hash,
            'live_execution_authorized': False,
        }


class DevConformanceTransport:
    """Fixed scripted response bytes for the versioned operation interface."""

    def __init__(self, responses: dict[str, bytes], *, fail_at: str = ''):
        require(type(responses) is dict and isinstance(fail_at, str),
                'conformance-transport-schema')
        self.responses = dict(responses)
        self.fail_at = fail_at
        self.calls = []

    def call(self, operation: str, request: bytes) -> bytes:
        require(isinstance(operation, str) and isinstance(request, bytes),
                'conformance-call-schema')
        self.calls.append((operation, request))
        require(operation != self.fail_at and operation in self.responses,
                'conformance-scripted-call-failure')
        return self.responses[operation]


def successful_responses(phase: str) -> dict[str, bytes]:
    """Build exact fixed-fake success envelopes for one reviewed phase."""
    require(phase in STAGES, 'conformance-phase')
    read_only = {
        'kubernetes-observe-applications',
        'kubernetes-observe-external-secrets',
        'kubernetes-observe-controller-rbac',
        'kubernetes-observe-business-namespaces',
        'kubernetes-observe-runtime-absence',
        'aws-observe-captured-runtime-absence',
        'kubernetes-observe-node-configuration',
        'aws-observe-eks-dependency-scope',
        'terraform-show-reviewed-saved-plan',
        'aws-observe-captured-eni-sg',
        'aws-observe-final-scope-and-inventories',
    }
    return {
        operation: canonical({
            'schema': RESPONSE_SCHEMA,
            'operation': operation,
            'outcome': 'success',
            'mutation_acknowledged': operation not in read_only,
            'simulation_only': True,
        })
        for operation in STAGE_OPERATIONS[phase]
    }


class DevTransportConformanceHarness:
    """Exercise one dev phase against the fixed fake and append a real receipt."""

    def __init__(self, *, main: str, store: DurableReceiptStore):
        require(type(store) is DurableReceiptStore, 'conformance-fixed-store-type')
        self.main = main
        self.store = store

    @staticmethod
    def _response(raw: bytes, operation: str) -> dict:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ConformanceStopped('transport-response', True) from None
        expected = successful_responses_for_operation(operation)
        if type(value) is not dict or canonical(value) != raw or value != expected:
            raise ConformanceStopped('transport-response', True)
        return value

    def run_phase(self, *, phase: str, approval: dict, current_utc: str,
                  completed_at_utc: str, evidence: dict,
                  transport: DevConformanceTransport) -> dict:
        require(type(transport) is DevConformanceTransport,
                'conformance-fixed-transport-type')
        attempted = False
        try:
            prefix = self.store.load_prefix()
            require(len(prefix) < len(STAGES) and STAGES[len(prefix)] == phase,
                    'conformance-receipt-prefix')
            predecessor = prefix[-1]['receipt_sha256'] if prefix else None
            review_approval_shape(
                approval, environment=ENVIRONMENT, phase=phase, main=self.main,
                current_utc=current_utc,
                expected_predecessor_sha256=predecessor)
            require(approval.get('operation_set_sha256') == operation_set_sha256(phase),
                    'conformance-operation-set-drift')
            require(type(evidence) is dict and set(evidence) == {
                'journal_completion_sha256', 'raw_output_manifest_sha256',
                'state_after_sha256'}, 'conformance-evidence-schema')
            for value in evidence.values():
                _hash(value, 'conformance-evidence-hash')
            completed = parse_utc(completed_at_utc)
            require(parse_utc(current_utc) <= completed
                    <= parse_utc(approval['end_utc']),
                    'conformance-completion-clock')
            approval_hash = sha(canonical(approval))
            for operation in STAGE_OPERATIONS[phase]:
                request = canonical({
                    'schema': TRANSPORT_SCHEMA,
                    'environment': ENVIRONMENT,
                    'phase': phase,
                    'operation': operation,
                    'approval_sha256': approval_hash,
                    'predecessor_receipt_sha256': predecessor,
                    'simulation_only': True,
                })
                attempted = True
                self._response(transport.call(operation, request), operation)
            receipt = {
                'schema': RECEIPT_SCHEMA,
                'transport_version': TRANSPORT_SCHEMA,
                'environment': ENVIRONMENT,
                'phase': phase,
                'phase_index': STAGES.index(phase),
                'status': 'terminal-success',
                'control_plane_commit': self.main,
                'approval_sha256': approval_hash,
                'inputs_sha256': approval['inputs_sha256'],
                'scope_sha256': approval['scope_sha256'],
                'operation_set_sha256': approval['operation_set_sha256'],
                'predecessor_receipt_sha256': predecessor,
                'journal_completion_sha256': evidence['journal_completion_sha256'],
                'raw_output_manifest_sha256': evidence['raw_output_manifest_sha256'],
                'state_before_sha256': approval['state_sha256'],
                'state_after_sha256': evidence['state_after_sha256'],
                'completed_at_utc': completed_at_utc,
                'attempt_count': 1,
                'automatic_retry_performed': False,
                'incident_repair_performed': False,
            }
            appended = self.store.append(receipt)
            return {
                'status': 'dev-offline-transport-conformance-complete',
                'version': VERSION,
                'environment': ENVIRONMENT,
                'phase': phase,
                'operation_count': len(STAGE_OPERATIONS[phase]),
                'receipt_sha256': appended['receipt_sha256'],
                'durable_receipt_appended': True,
                'simulation_only': True,
                'kubernetes_transport_executed': False,
                'aws_transport_executed': False,
                'terraform_command_executed': False,
                'live_execution_authorized': False,
            }
        except (ConformanceStopped, ReceiptStoreStopped):
            raise
        except (RuleViolation, OSError, TypeError, ValueError, KeyError):
            raise ConformanceStopped('conformance-gate', attempted) from None


def successful_responses_for_operation(operation: str) -> dict:
    """Return one exact response without accepting an arbitrary operation."""
    known = {item for phase in STAGES for item in STAGE_OPERATIONS[phase]}
    require(operation in known, 'conformance-operation')
    for responses in (successful_responses(phase) for phase in STAGES):
        if operation in responses:
            return json.loads(responses[operation])
    raise RuleViolation('conformance-operation')

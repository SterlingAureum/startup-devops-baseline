"""Restart-safe offline adapter for the injected aws-dev fixed-fake protocol.

Only strict local receipt files are accessed. The composed protocol remains a
fixed fake and cannot reach Kubernetes, AWS or Terraform or grant live access.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

import guarded_dev_injected_transport_protocol_v67716 as protocol
from guarded_dev_live_transport_design_v67715 import expected_design
from guarded_live_migration_contract_v6778 import STAGES
from guarded_runtime_rules import RuleViolation, require


VERSION = 'v0.11.9.3.6.7.7.17'
PREDECESSOR = protocol.VERSION
ENVIRONMENT = protocol.ENVIRONMENT
ATTEMPT_SCHEMA = 'guarded-dev-offline-restart-attempt-v1'
COMPLETION_SCHEMA = 'guarded-dev-offline-restart-completion-v1'
FAULT_POINTS = (
    'after-attempt-open', 'after-attempt-write', 'after-attempt-file-fsync',
    'after-attempt-dir-fsync', 'after-receipt-open', 'after-receipt-write',
    'after-receipt-file-fsync', 'after-receipt-dir-fsync',
    'after-completion-open', 'after-completion-write',
    'after-completion-file-fsync', 'after-completion-dir-fsync',
)


class AdapterStopped(RuleViolation):
    """Stable local-adapter stop without a path or private payload."""

    def __init__(self, stage: str, *, phase: str | None = None,
                 attempt_created: bool = False):
        super().__init__('dev-offline-restart-adapter-stopped')
        self.report = {
            'status': 'dev-offline-restart-receipt-adapter-stopped',
            'stage': stage,
            'phase': phase,
            'attempt_created': attempt_created,
            'preserve_receipt_directory': True,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'live_transport_executed': False,
            'live_execution_authorized': False,
        }


class AdapterFaultInjector:
    """One deterministic local write failure for offline tests."""

    def __init__(self, point: str):
        require(point in FAULT_POINTS, 'adapter-fault-point')
        self.point = point
        self.triggered = False

    def check(self, point: str) -> None:
        require(point in FAULT_POINTS, 'adapter-fault-check')
        if point == self.point and not self.triggered:
            self.triggered = True
            raise OSError('injected offline adapter failure')


class RestartSafeOfflineReceiptAdapter:
    """Exclusive append-only attempt/receipt/completion triplets."""

    def __init__(self, directory: Path, *, main: str,
                 fault: AdapterFaultInjector | None = None):
        require(isinstance(directory, Path) and directory.is_absolute(),
                'adapter-directory-absolute')
        require(type(main) is str and protocol.COMMIT.fullmatch(main) is not None,
                'adapter-main')
        require(fault is None or type(fault) is AdapterFaultInjector,
                'adapter-fixed-fault-type')
        self.directory = directory
        self.main = main
        self.fault = fault
        descriptor = self._open_directory('directory-open')
        os.close(descriptor)

    @staticmethod
    def _names(index: int, phase: str) -> tuple[str, str, str]:
        prefix = f'{index:03d}.{phase}'
        return (prefix + '.attempt.json', prefix + '.receipt.json',
                prefix + '.complete.json')

    def _open_directory(self, stage: str) -> int:
        try:
            descriptor = os.open(
                self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            value = os.fstat(descriptor)
            if (not stat.S_ISDIR(value.st_mode)
                    or stat.S_IMODE(value.st_mode) != 0o700
                    or value.st_uid != os.geteuid()):
                os.close(descriptor)
                raise AdapterStopped('directory-scope')
            return descriptor
        except AdapterStopped:
            raise
        except (OSError, TypeError, ValueError):
            raise AdapterStopped(stage) from None

    @staticmethod
    def _read_regular(descriptor: int, name: str) -> bytes:
        file_descriptor = None
        try:
            value = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode)
                    or stat.S_IMODE(value.st_mode) != 0o600
                    or value.st_uid != os.geteuid() or value.st_nlink != 1):
                raise AdapterStopped('stored-file-scope')
            file_descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            chunks = []
            while True:
                chunk = os.read(file_descriptor, 65536)
                if not chunk:
                    return b''.join(chunks)
                chunks.append(chunk)
        except AdapterStopped:
            raise
        except OSError:
            raise AdapterStopped('stored-file-read') from None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

    @staticmethod
    def _object(raw: bytes, stage: str) -> dict:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AdapterStopped(stage) from None
        if type(value) is not dict or protocol.canonical(value) != raw:
            raise AdapterStopped(stage)
        return value

    def _write(self, descriptor: int, name: str, raw: bytes, label: str,
               phase: str) -> None:
        file_descriptor = None
        try:
            file_descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=descriptor)
            if self.fault:
                self.fault.check('after-' + label + '-open')
            # Keep the final byte as a local commit byte.  A fault at the
            # after-write boundary must leave an invalid partial object, not
            # a complete-looking receipt that a restart could accept before
            # its file and directory entries have been made durable.
            body, commit_byte = raw[:-1], raw[-1:]
            offset = 0
            while offset < len(body):
                written = os.write(file_descriptor, body[offset:])
                if written <= 0:
                    raise OSError('short local adapter write')
                offset += written
            if self.fault:
                self.fault.check('after-' + label + '-write')
            written = os.write(file_descriptor, commit_byte)
            if written != len(commit_byte):
                raise OSError('short local adapter commit write')
            os.fsync(file_descriptor)
            if self.fault:
                self.fault.check('after-' + label + '-file-fsync')
        except OSError:
            raise AdapterStopped(label + '-write', phase=phase,
                                 attempt_created=label != 'attempt') from None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
        try:
            os.fsync(descriptor)
            if self.fault:
                self.fault.check('after-' + label + '-dir-fsync')
        except OSError:
            raise AdapterStopped(label + '-dir-fsync', phase=phase,
                                 attempt_created=True) from None

    def load_prefix(self) -> tuple[dict, ...]:
        descriptor = self._open_directory('prefix-open')
        try:
            actual = set(os.listdir(descriptor))
            allowed = set()
            receipts = []
            previous = None
            gap = False
            for index, phase in enumerate(STAGES):
                names = self._names(index, phase)
                allowed.update(names)
                present = tuple(name in actual for name in names)
                if not any(present):
                    gap = True
                    continue
                if gap or present != (True, True, True):
                    raise AdapterStopped('pending-or-gapped-prefix', phase=phase,
                                         attempt_created=present[0])
                attempt = self._object(
                    self._read_regular(descriptor, names[0]), 'attempt-schema')
                receipt_raw = self._read_regular(descriptor, names[1])
                receipt = self._object(receipt_raw, 'receipt-schema')
                completion = self._object(
                    self._read_regular(descriptor, names[2]), 'completion-schema')
                receipt_hash = protocol.sha(receipt_raw)
                if attempt != {
                    'schema': ATTEMPT_SCHEMA,
                    'version': VERSION,
                    'environment': ENVIRONMENT,
                    'phase': phase,
                    'phase_index': index,
                    'control_plane_commit': self.main,
                    'approval_sha256': receipt.get('approval_sha256'),
                    'reviewed_verify_sha256': receipt.get('reviewed_verify_sha256'),
                    'state_before_sha256': receipt.get('state_before_sha256'),
                    'predecessor_receipt_sha256': previous,
                    'simulation_only': True,
                    'live_execution_authorized': False,
                }:
                    raise AdapterStopped('attempt-binding', phase=phase,
                                         attempt_created=True)
                if completion != {
                    'schema': COMPLETION_SCHEMA,
                    'version': VERSION,
                    'receipt_sha256': receipt_hash,
                    'simulation_only': True,
                }:
                    raise AdapterStopped('completion-binding', phase=phase,
                                         attempt_created=True)
                if (set(receipt) != set(protocol.RECEIPT_FIELDS)
                        or receipt.get('schema') != protocol.CONFORMANCE_RECEIPT_SCHEMA
                        or receipt.get('version') != protocol.VERSION
                        or receipt.get('environment') != ENVIRONMENT
                        or receipt.get('phase') != phase
                        or receipt.get('phase_index') != index
                        or receipt.get('control_plane_commit') != self.main
                        or receipt.get('predecessor_receipt_sha256') != previous
                        or receipt.get('status') != 'terminal-success'
                        or receipt.get('simulation_only') is not True
                        or receipt.get('live_execution_authorized') is not False
                        or receipt.get('attempt_count') != 1
                        or receipt.get('automatic_retry_performed') is not False
                        or receipt.get('automatic_repair_performed') is not False):
                    raise AdapterStopped('receipt-binding', phase=phase,
                                         attempt_created=True)
                receipts.append(receipt)
                previous = receipt_hash
            if not actual.issubset(allowed):
                raise AdapterStopped('unexpected-directory-entry')
            return tuple(receipts)
        except AdapterStopped:
            raise
        except OSError:
            raise AdapterStopped('prefix-read') from None
        finally:
            os.close(descriptor)

    def begin(self, *, phase: str, approval: dict, verify: dict,
              predecessor: str | None) -> None:
        prefix = self.load_prefix()
        index = len(prefix)
        require(index < len(STAGES) and STAGES[index] == phase,
                'adapter-next-phase')
        attempt = {
            'schema': ATTEMPT_SCHEMA,
            'version': VERSION,
            'environment': ENVIRONMENT,
            'phase': phase,
            'phase_index': index,
            'control_plane_commit': self.main,
            'approval_sha256': protocol.sha(protocol.canonical(approval)),
            'reviewed_verify_sha256': protocol.sha(protocol.canonical(verify)),
            'state_before_sha256': approval['state_before_sha256'],
            'predecessor_receipt_sha256': predecessor,
            'simulation_only': True,
            'live_execution_authorized': False,
        }
        descriptor = self._open_directory('attempt-open')
        try:
            self._write(descriptor, self._names(index, phase)[0],
                        protocol.canonical(attempt), 'attempt', phase)
        finally:
            os.close(descriptor)

    def complete(self, receipt: dict) -> str:
        prefix = self.load_prefix_pending()
        index = len(prefix)
        require(index < len(STAGES), 'adapter-chain-complete')
        phase = STAGES[index]
        require(type(receipt) is dict and receipt.get('phase') == phase,
                'adapter-completion-phase')
        receipt_raw = protocol.canonical(receipt)
        receipt_hash = protocol.sha(receipt_raw)
        completion = {
            'schema': COMPLETION_SCHEMA,
            'version': VERSION,
            'receipt_sha256': receipt_hash,
            'simulation_only': True,
        }
        names = self._names(index, phase)
        descriptor = self._open_directory('completion-open')
        try:
            self._write(descriptor, names[1], receipt_raw, 'receipt', phase)
            self._write(descriptor, names[2], protocol.canonical(completion),
                        'completion', phase)
        finally:
            os.close(descriptor)
        return receipt_hash

    def load_prefix_pending(self) -> tuple[dict, ...]:
        """Return completed prefix only when exactly the next attempt is pending."""
        descriptor = self._open_directory('pending-open')
        try:
            actual = set(os.listdir(descriptor))
            pending = []
            for index, phase in enumerate(STAGES):
                names = self._names(index, phase)
                present = tuple(name in actual for name in names)
                if present == (True, False, False):
                    pending.append(index)
                elif any(present) and present != (True, True, True):
                    raise AdapterStopped('invalid-pending-shape', phase=phase,
                                         attempt_created=present[0])
            require(len(pending) == 1, 'adapter-one-pending-attempt')
            pending_index = pending[0]
            completed_names = {
                name for index, phase in enumerate(STAGES[:pending_index])
                for name in self._names(index, phase)
            }
            require(all(name in actual for name in completed_names),
                    'adapter-pending-prefix-gap')
        finally:
            os.close(descriptor)
        # Temporarily validate completed files without treating the attempt as a
        # repairable prefix: parse them directly through a strict snapshot.
        snapshot = []
        descriptor = self._open_directory('pending-prefix-open')
        try:
            for index, phase in enumerate(STAGES[:pending_index]):
                raw = self._read_regular(descriptor, self._names(index, phase)[1])
                snapshot.append(self._object(raw, 'pending-receipt-schema'))
        finally:
            os.close(descriptor)
        return tuple(snapshot)


def run_restart_safe_fixed_fake_phase(*, adapter: RestartSafeOfflineReceiptAdapter,
                                      phase: str, verify: dict, approval: dict,
                                      current_utc: str, completed_at_utc: str,
                                      state_after_sha256: str,
                                      postconditions: dict[str, bool],
                                      transport: protocol.FixedFakeTransport) -> dict:
    """Run one offline fake phase after a durable exclusive attempt marker."""
    attempt_created = False
    try:
        require(type(adapter) is RestartSafeOfflineReceiptAdapter and
                type(transport) is protocol.FixedFakeTransport,
                'adapter-fixed-composition-types')
        receipts = adapter.load_prefix()
        require(len(receipts) < len(STAGES) and STAGES[len(receipts)] == phase,
                'adapter-phase-order')
        predecessor = (protocol.sha(protocol.canonical(receipts[-1]))
                       if receipts else None)
        if receipts:
            require(approval.get('state_before_sha256') ==
                    receipts[-1].get('state_after_sha256'),
                    'adapter-state-continuity')
        protocol.validate_verify(
            verify, main=adapter.main, phase=phase,
            predecessor=predecessor, current_utc=current_utc)
        protocol.validate_approval(
            approval, verify=verify, main=adapter.main, phase=phase,
            predecessor=predecessor, current_utc=current_utc)
        adapter.begin(phase=phase, approval=approval, verify=verify,
                      predecessor=predecessor)
        attempt_created = True
        result = protocol.run_fixed_fake_conformance(
            design=expected_design(), main=adapter.main, phase=phase,
            receipts=receipts, verify=verify, approval=approval,
            current_utc=current_utc, completed_at_utc=completed_at_utc,
            state_after_sha256=state_after_sha256,
            postconditions=postconditions, transport=transport,
            journal=protocol.FixedFakeJournal())
        receipt_hash = adapter.complete(result['receipt'])
        completed = adapter.load_prefix()
        require(len(completed) == len(receipts) + 1 and
                protocol.sha(protocol.canonical(completed[-1])) == receipt_hash,
                'adapter-post-write-prefix')
        return {
            'status': 'dev-offline-restart-safe-phase-complete',
            'version': VERSION,
            'environment': ENVIRONMENT,
            'phase': phase,
            'completed_phase_count': len(completed),
            'operation_count': result['operation_count'],
            'receipt_sha256': receipt_hash,
            'durable_offline_receipt_appended': True,
            'receipt_usable_for_live': False,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'live_transport_executed': False,
            'live_execution_authorized': False,
        }
    except AdapterStopped:
        raise
    except (RuleViolation, KeyError, TypeError, ValueError):
        raise AdapterStopped('phase-composition', phase=phase,
                             attempt_created=attempt_created) from None

#!/usr/bin/env python3
"""Dev-only local offline execute prototype using the fixed fake transport."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

from guarded_dev_command_entry_conformance_v67710 import (
    CONFIRMATIONS,
    ENVIRONMENT,
    VERIFY_SCHEMA,
    VERSION as ENTRY_VERSION,
    CommandEntryStopped,
    DevOfflineCommandEntry,
    FixedPrivateInputReader,
    FrozenClock,
    command_request,
    sha,
)
from guarded_dev_transport_conformance_v6779 import (
    ConformanceStopped,
    DevConformanceTransport,
    DurableReceiptStore,
    ReceiptStoreStopped,
    canonical,
    operation_set_sha256,
    successful_responses,
)
from guarded_live_migration_contract_v6778 import STAGES
from guarded_runtime_rules import RuleViolation, parse_utc, require


VERSION = 'v0.11.9.3.6.7.7.12'
PREFLIGHT_VERSION = 'v0.11.9.3.6.7.7.11'
MAX_PRIVATE_INPUT_BYTES = 1024 * 1024
COMMIT = re.compile(r'[0-9a-f]{40}')
SHA256 = re.compile(r'[0-9a-f]{64}')


class LocalExecuteStopped(RuleViolation):
    """Stable failure without private paths, bytes or resource identities."""

    def __init__(self, stage: str, *, fake_attempted: bool = False):
        super().__init__('dev-local-offline-execute-stopped')
        self.report = {
            'status': 'dev-local-offline-execute-stopped',
            'stage': stage,
            'preserve_private_inputs_and_receipts': True,
            'automatic_retry_performed': False,
            'fake_transport_attempted': fake_attempted,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
        }


class TwoReadSystemUtcClock:
    """Exactly two bounded host UTC readings for one offline execution."""

    def __init__(self):
        self.read_count = 0

    def now(self) -> str:
        require(self.read_count < 2, 'system-clock-repeat')
        self.read_count += 1
        value = datetime.now(timezone.utc).replace(microsecond=0)
        return value.isoformat().replace('+00:00', 'Z')


class StrictPrivateExecutionFiles:
    """Read approval, evidence and reviewed preflight from one strict directory."""

    def __init__(self, paths: dict[str, Path]):
        require(type(paths) is dict and set(paths) == {
            'approval', 'evidence', 'preflight'}, 'private-input-path-map')
        require(all(isinstance(path, Path) and path.is_absolute()
                    for path in paths.values()), 'private-input-absolute')
        parents = {path.parent for path in paths.values()}
        require(len(parents) == 1, 'private-input-common-parent')
        require(len({path.name for path in paths.values()}) == 3,
                'private-input-distinct-names')
        self._paths = dict(paths)

    @staticmethod
    def _directory(path: Path) -> int:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            value = os.fstat(descriptor)
            if (not stat.S_ISDIR(value.st_mode)
                    or stat.S_IMODE(value.st_mode) != 0o700
                    or value.st_uid != os.geteuid()):
                os.close(descriptor)
                raise LocalExecuteStopped('private-directory-scope')
            return descriptor
        except LocalExecuteStopped:
            raise
        except OSError:
            raise LocalExecuteStopped('private-directory-open') from None

    @staticmethod
    def _read_one(descriptor: int, name: str) -> bytes:
        file_descriptor = None
        try:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode)
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or before.st_size <= 0
                    or before.st_size > MAX_PRIVATE_INPUT_BYTES):
                raise LocalExecuteStopped('private-file-scope')
            file_descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            opened = os.fstat(file_descriptor)
            require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                    'private-file-race')
            chunks = []
            total = 0
            while True:
                chunk = os.read(file_descriptor, min(
                    65536, MAX_PRIVATE_INPUT_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                require(total <= MAX_PRIVATE_INPUT_BYTES,
                        'private-file-size-race')
            after = os.fstat(file_descriptor)
            require((after.st_dev, after.st_ino, after.st_size)
                    == (before.st_dev, before.st_ino, before.st_size),
                    'private-file-race')
            raw = b''.join(chunks)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise LocalExecuteStopped('private-file-json') from None
            require(type(value) is dict and canonical(value) == raw,
                    'private-file-canonical')
            return raw
        except LocalExecuteStopped:
            raise
        except (OSError, RuleViolation):
            raise LocalExecuteStopped('private-file-read') from None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

    def read_all(self) -> dict[str, bytes]:
        descriptor = self._directory(next(iter(self._paths.values())).parent)
        try:
            require(set(os.listdir(descriptor)) == {
                path.name for path in self._paths.values()},
                'private-directory-unexpected-entry')
            return {
                label: self._read_one(descriptor, path.name)
                for label, path in self._paths.items()
            }
        except LocalExecuteStopped:
            raise
        except (OSError, RuleViolation):
            raise LocalExecuteStopped('private-input-scope') from None
        finally:
            os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog='execute-v0.11.9.3.6.7.7.12-aws-dev-command.py')
    value.add_argument('command', choices=('execute',))
    value.add_argument('--expected-control-plane-commit', required=True)
    value.add_argument('--phase', required=True, choices=STAGES)
    value.add_argument('--approval-file', required=True, type=Path)
    value.add_argument('--expected-approval-sha256', required=True)
    value.add_argument('--evidence-file', required=True, type=Path)
    value.add_argument('--expected-evidence-sha256', required=True)
    value.add_argument('--preflight-file', required=True, type=Path)
    value.add_argument('--expected-preflight-sha256', required=True)
    value.add_argument('--receipt-directory', required=True, type=Path)
    value.add_argument('--confirm', required=True)
    return value


def _reviewed_verify(preflight: dict, approval: dict, *, phase: str,
                     main: str, approval_sha256: str,
                     evidence_sha256: str, predecessor: str | None,
                     current_utc: str) -> dict:
    require(type(preflight) is dict and set(preflight) == {
        'status', 'version', 'target_environment', 'phase',
        'control_plane_commit', 'reviewed_approval_sha256',
        'reviewed_evidence_sha256', 'operation_set_sha256',
        'predecessor_receipt_sha256', 'observed_at_utc',
        'verify_expires_at_utc', 'private_input_file_count',
        'private_path_emitted', 'system_clock_read',
        'fake_transport_executed', 'kubernetes_transport_executed',
        'aws_transport_executed', 'terraform_command_executed',
        'mutation_executed', 'execution_authorized', 'next_action',
    }, 'reviewed-preflight-schema')
    require(preflight.get('status') == 'aws-dev-local-command-preflight-complete'
            and preflight.get('version') == PREFLIGHT_VERSION
            and preflight.get('target_environment') == ENVIRONMENT
            and preflight.get('phase') == phase
            and preflight.get('control_plane_commit') == main
            and preflight.get('reviewed_approval_sha256') == approval_sha256
            and preflight.get('reviewed_evidence_sha256') == evidence_sha256
            and preflight.get('operation_set_sha256') == operation_set_sha256(phase)
            and preflight.get('predecessor_receipt_sha256') == predecessor
            and preflight.get('private_input_file_count') == 2
            and preflight.get('private_path_emitted') is False
            and preflight.get('system_clock_read') is True
            and preflight.get('fake_transport_executed') is False
            and preflight.get('kubernetes_transport_executed') is False
            and preflight.get('aws_transport_executed') is False
            and preflight.get('terraform_command_executed') is False
            and preflight.get('mutation_executed') is False
            and preflight.get('execution_authorized') is False
            and preflight.get('next_action')
            == 'review-preflight-before-separate-offline-execute-prototype',
            'reviewed-preflight-binding')
    observed = parse_utc(preflight.get('observed_at_utc'))
    expiry = parse_utc(preflight.get('verify_expires_at_utc'))
    current = parse_utc(current_utc)
    require(parse_utc(approval.get('start_utc')) <= observed
            and parse_utc(approval.get('proof_created_at_utc')) <= observed
            and preflight.get('verify_expires_at_utc')
            == approval.get('proof_expires_at_utc')
            and observed <= current <= expiry <= parse_utc(approval.get('end_utc')),
            'reviewed-preflight-clock')
    return {
        'schema': VERIFY_SCHEMA,
        'status': 'dev-offline-command-inputs-verified',
        'version': ENTRY_VERSION,
        'environment': ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': main,
        'reviewed_approval_sha256': approval_sha256,
        'reviewed_evidence_sha256': evidence_sha256,
        'operation_set_sha256': operation_set_sha256(phase),
        'predecessor_receipt_sha256': predecessor,
        'verified_at_utc': preflight['observed_at_utc'],
        'verify_expires_at_utc': preflight['verify_expires_at_utc'],
        'end_utc': approval['end_utc'],
        'execution_authorized': False,
        'simulation_only': True,
        'system_clock_read': False,
        'live_private_evidence_read': False,
        'live_transport_executed': False,
    }


def run(argv: list[str]) -> dict:
    attempted = False
    try:
        require(type(argv) is list, 'local-cli-argv')
        args = parser().parse_args(argv)
        require(args.command == 'execute' and args.phase in CONFIRMATIONS
                and args.confirm == CONFIRMATIONS[args.phase],
                'local-cli-confirmation')
        require(COMMIT.fullmatch(args.expected_control_plane_commit) is not None,
                'local-cli-main')
        hashes = (args.expected_approval_sha256,
                  args.expected_evidence_sha256,
                  args.expected_preflight_sha256)
        require(all(SHA256.fullmatch(value) is not None for value in hashes),
                'local-cli-input-hash')
        inputs = StrictPrivateExecutionFiles({
            'approval': args.approval_file,
            'evidence': args.evidence_file,
            'preflight': args.preflight_file,
        }).read_all()
        require(sha(inputs['approval']) == args.expected_approval_sha256
                and sha(inputs['evidence']) == args.expected_evidence_sha256
                and sha(inputs['preflight']) == args.expected_preflight_sha256,
                'local-cli-input-drift')
        approval = json.loads(inputs['approval'])
        preflight = json.loads(inputs['preflight'])
        store = DurableReceiptStore(
            args.receipt_directory, main=args.expected_control_plane_commit)
        prefix = store.load_prefix()
        require(len(prefix) < len(STAGES) and STAGES[len(prefix)] == args.phase,
                'local-cli-receipt-prefix')
        predecessor = prefix[-1]['receipt_sha256'] if prefix else None
        clock = TwoReadSystemUtcClock()
        current = clock.now()
        reviewed = _reviewed_verify(
            preflight, approval, phase=args.phase,
            main=args.expected_control_plane_commit,
            approval_sha256=args.expected_approval_sha256,
            evidence_sha256=args.expected_evidence_sha256,
            predecessor=predecessor, current_utc=current)
        reviewed_raw = canonical(reviewed)
        command_inputs = {
            'approval': inputs['approval'],
            'evidence': inputs['evidence'],
            'reviewed-verify': reviewed_raw,
        }
        completed = clock.now()
        request = command_request(
            command='execute', phase=args.phase,
            main=args.expected_control_plane_commit,
            approval_sha256=args.expected_approval_sha256,
            evidence_sha256=args.expected_evidence_sha256,
            reviewed_verify_sha256=sha(reviewed_raw),
            confirmation=args.confirm)
        entry = DevOfflineCommandEntry(
            main=args.expected_control_plane_commit,
            clock=FrozenClock((current, completed)),
            reader=FixedPrivateInputReader(command_inputs),
            store=store)
        fake = DevConformanceTransport(successful_responses(args.phase))
        attempted = True
        result = entry.dispatch('execute', request, fake)
        require(clock.read_count == 2 and result.get('fake_transport_executed') is True,
                'local-cli-offline-execution')
        return {
            'status': 'aws-dev-local-offline-command-execution-complete',
            'version': VERSION,
            'target_environment': ENVIRONMENT,
            'phase': args.phase,
            'control_plane_commit': args.expected_control_plane_commit,
            'reviewed_preflight_sha256': args.expected_preflight_sha256,
            'reviewed_approval_sha256': args.expected_approval_sha256,
            'reviewed_evidence_sha256': args.expected_evidence_sha256,
            'reviewed_verify_sha256': sha(reviewed_raw),
            'predecessor_receipt_sha256': predecessor,
            'receipt_sha256': result['receipt_sha256'],
            'operation_count': len(fake.calls),
            'started_at_utc': current,
            'completed_at_utc': completed,
            'system_clock_read_count': 2,
            'private_input_file_count': 3,
            'durable_receipt_appended': True,
            'fake_transport_executed': True,
            'simulation_only': True,
            'private_path_emitted': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
            'next_action': 'review-offline-receipt-before-next-phase-preflight',
        }
    except LocalExecuteStopped:
        raise
    except (RuleViolation, ReceiptStoreStopped, CommandEntryStopped,
            ConformanceStopped, OSError, TypeError, ValueError, KeyError):
        raise LocalExecuteStopped(
            'local-execution-inputs', fake_attempted=attempted) from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.write(canonical(result).decode() + '\n')
        return 0
    except (LocalExecuteStopped, SystemExit):
        sys.stderr.write(
            'STOP: aws-dev local offline execution failed; preserve private inputs and receipts.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

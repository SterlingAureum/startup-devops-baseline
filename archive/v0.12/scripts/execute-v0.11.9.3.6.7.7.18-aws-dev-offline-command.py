#!/usr/bin/env python3
"""Strict local command boundary for the restart-safe aws-dev fixed fake.

The command reads only canonical local private inputs and the host UTC clock.
It cannot read credentials or invoke subprocesses, AWS, Kubernetes or
Terraform.  Execute composes only the v0.11.9.3.6.7.7.17 adapter and exact
v0.11.9.3.6.7.7.16 fixed fake.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

import guarded_dev_injected_transport_protocol_v67716 as protocol
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter_core
from guarded_dev_live_transport_design_v67715 import (
    POSTCONDITIONS,
    expected_stage_designs,
)
from guarded_live_migration_contract_v6778 import STAGES
from guarded_runtime_rules import RuleViolation, parse_utc, require


VERSION = 'v0.11.9.3.6.7.7.18'
PREDECESSOR = adapter_core.VERSION
ENVIRONMENT = protocol.ENVIRONMENT
BUNDLE_SCHEMA = 'guarded-dev-offline-restart-command-bundle-v1'
VERIFY_CONFIRMATION = 'observe-reviewed-aws-dev-restart-safe-fixed-fake'
MAX_PRIVATE_INPUT_BYTES = 1024 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'[0-9a-f]{40}')
BUNDLE_FIELDS = (
    'schema', 'version', 'environment', 'phase', 'control_plane_commit',
    'verify', 'approval', 'state_after_sha256', 'postconditions',
    'simulation_only', 'live_execution_authorized',
)
PREFLIGHT_FIELDS = (
    'status', 'version', 'target_environment', 'phase',
    'control_plane_commit', 'reviewed_bundle_sha256',
    'receipt_prefix_count', 'predecessor_receipt_sha256',
    'state_before_sha256', 'state_after_sha256', 'operation_set_sha256',
    'observed_at_utc', 'verify_expires_at_utc', 'system_clock_read_count',
    'private_input_file_count', 'private_path_emitted',
    'fixed_fake_executed', 'receipt_written', 'automatic_retry_performed',
    'automatic_repair_performed', 'kubernetes_transport_executed',
    'aws_transport_executed', 'terraform_command_executed',
    'mutation_executed', 'live_execution_authorized', 'next_action',
)


def execute_confirmation(phase: str) -> str:
    require(phase in STAGES, 'local-command-phase')
    return 'execute-reviewed-aws-dev-restart-safe-fixed-fake-' + phase


class LocalCommandStopped(RuleViolation):
    """Redacted stop result without a path, payload or resource identity."""

    def __init__(self, stage: str, *, phase: str | None = None,
                 attempt_created: bool = False):
        super().__init__('dev-restart-safe-offline-command-stopped')
        self.report = {
            'status': 'aws-dev-restart-safe-offline-command-stopped',
            'stage': stage,
            'phase': phase,
            'attempt_created': attempt_created,
            'preserve_private_inputs_and_receipts': True,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'fixed_fake_execution_uncertain': attempt_created,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
        }


class SystemUtcClock:
    """Bounded host clock used once by verify or twice by execute."""

    def __init__(self, limit: int):
        require(type(limit) is int and limit in (1, 2), 'local-clock-limit')
        self.limit = limit
        self.read_count = 0

    def now(self) -> str:
        require(self.read_count < self.limit, 'local-clock-repeat')
        self.read_count += 1
        value = datetime.now(timezone.utc).replace(microsecond=0)
        return value.isoformat().replace('+00:00', 'Z')


class StrictCanonicalPrivateFile:
    """Read one exact canonical file from its own owned private directory."""

    def __init__(self, path: Path):
        require(isinstance(path, Path) and path.is_absolute(),
                'private-input-absolute')
        self.path = path

    def read(self) -> bytes:
        directory_descriptor = None
        file_descriptor = None
        try:
            directory_descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directory = os.fstat(directory_descriptor)
            if (not stat.S_ISDIR(directory.st_mode)
                    or stat.S_IMODE(directory.st_mode) != 0o700
                    or directory.st_uid != os.geteuid()
                    or set(os.listdir(directory_descriptor)) != {self.path.name}):
                raise LocalCommandStopped('private-directory-scope')
            before = os.stat(
                self.path.name, dir_fd=directory_descriptor,
                follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode)
                    or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or not 0 < before.st_size <= MAX_PRIVATE_INPUT_BYTES):
                raise LocalCommandStopped('private-file-scope')
            file_descriptor = os.open(
                self.path.name, os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor)
            opened = os.fstat(file_descriptor)
            require((opened.st_dev, opened.st_ino) ==
                    (before.st_dev, before.st_ino), 'private-file-race')
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
            require((after.st_dev, after.st_ino, after.st_size) ==
                    (before.st_dev, before.st_ino, before.st_size),
                    'private-file-race')
            raw = b''.join(chunks)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise LocalCommandStopped('private-file-json') from None
            require(type(value) is dict and protocol.canonical(value) == raw,
                    'private-file-canonical')
            return raw
        except LocalCommandStopped:
            raise
        except (OSError, RuleViolation, TypeError, ValueError):
            raise LocalCommandStopped('private-file-read') from None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if directory_descriptor is not None:
                os.close(directory_descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog='execute-v0.11.9.3.6.7.7.18-aws-dev-offline-command.py')
    value.add_argument('command', choices=('verify', 'execute'))
    value.add_argument('--expected-control-plane-commit', required=True)
    value.add_argument('--phase', required=True, choices=STAGES)
    value.add_argument('--bundle-file', required=True, type=Path)
    value.add_argument('--expected-bundle-sha256', required=True)
    value.add_argument('--receipt-directory', required=True, type=Path)
    value.add_argument('--preflight-file', type=Path)
    value.add_argument('--expected-preflight-sha256')
    value.add_argument('--confirm', required=True)
    return value


def _object(raw: bytes, reason: str) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuleViolation(reason) from None
    require(type(value) is dict and protocol.canonical(value) == raw, reason)
    return value


def _validate_bundle(bundle: dict, *, main: str, phase: str,
                     current_utc: str,
                     adapter: adapter_core.RestartSafeOfflineReceiptAdapter
                     ) -> tuple[tuple[dict, ...], str | None]:
    require(type(bundle) is dict and set(bundle) == set(BUNDLE_FIELDS),
            'local-bundle-field-set')
    require(bundle['schema'] == BUNDLE_SCHEMA
            and bundle['version'] == VERSION
            and bundle['environment'] == ENVIRONMENT
            and bundle['phase'] == phase
            and bundle['control_plane_commit'] == main
            and bundle['simulation_only'] is True
            and bundle['live_execution_authorized'] is False,
            'local-bundle-binding')
    receipts = adapter.load_prefix()
    require(len(receipts) < len(STAGES) and STAGES[len(receipts)] == phase,
            'local-bundle-phase-order')
    predecessor = (protocol.sha(protocol.canonical(receipts[-1]))
                   if receipts else None)
    verify = bundle['verify']
    approval = bundle['approval']
    protocol.validate_verify(
        verify, main=main, phase=phase, predecessor=predecessor,
        current_utc=current_utc)
    protocol.validate_approval(
        approval, verify=verify, main=main, phase=phase,
        predecessor=predecessor, current_utc=current_utc)
    if receipts:
        require(approval['state_before_sha256'] ==
                receipts[-1]['state_after_sha256'],
                'local-bundle-state-continuity')
    require(isinstance(bundle['state_after_sha256'], str)
            and SHA256.fullmatch(bundle['state_after_sha256']) is not None,
            'local-bundle-state-after')
    conditions = bundle['postconditions']
    require(type(conditions) is dict
            and set(conditions) == set(POSTCONDITIONS[phase])
            and all(value is True for value in conditions.values()),
            'local-bundle-postconditions')
    design = expected_stage_designs()[STAGES.index(phase)]
    if design['stateAfterRelation'] == 'unchanged':
        require(bundle['state_after_sha256'] ==
                approval['state_before_sha256'],
                'local-bundle-state-changed')
    else:
        require(bundle['state_after_sha256'] !=
                approval['state_before_sha256'],
                'local-bundle-state-transition')
    return receipts, predecessor


def _validate_preflight(preflight: dict, *, bundle: dict,
                        bundle_sha256: str, main: str, phase: str,
                        prefix_count: int, predecessor: str | None,
                        current_utc: str) -> None:
    require(type(preflight) is dict and set(preflight) == set(PREFLIGHT_FIELDS),
            'reviewed-preflight-field-set')
    require(preflight == {
        'status': 'aws-dev-restart-safe-offline-command-inputs-verified',
        'version': VERSION,
        'target_environment': ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': main,
        'reviewed_bundle_sha256': bundle_sha256,
        'receipt_prefix_count': prefix_count,
        'predecessor_receipt_sha256': predecessor,
        'state_before_sha256': bundle['approval']['state_before_sha256'],
        'state_after_sha256': bundle['state_after_sha256'],
        'operation_set_sha256': bundle['verify']['operation_set_sha256'],
        'observed_at_utc': preflight['observed_at_utc'],
        'verify_expires_at_utc': bundle['verify']['verify_expires_at_utc'],
        'system_clock_read_count': 1,
        'private_input_file_count': 1,
        'private_path_emitted': False,
        'fixed_fake_executed': False,
        'receipt_written': False,
        'automatic_retry_performed': False,
        'automatic_repair_performed': False,
        'kubernetes_transport_executed': False,
        'aws_transport_executed': False,
        'terraform_command_executed': False,
        'mutation_executed': False,
        'live_execution_authorized': False,
        'next_action': 'review-before-separate-local-fixed-fake-execute',
    }, 'reviewed-preflight-binding')
    observed = parse_utc(preflight['observed_at_utc'])
    current = parse_utc(current_utc)
    expiry = parse_utc(preflight['verify_expires_at_utc'])
    require(observed <= current < expiry, 'reviewed-preflight-expired')


def run(argv: list[str]) -> dict:
    phase = None
    attempt_created = False
    try:
        require(type(argv) is list, 'local-command-argv')
        args = parser().parse_args(argv)
        phase = args.phase
        require(COMMIT.fullmatch(args.expected_control_plane_commit) is not None,
                'local-command-main')
        require(SHA256.fullmatch(args.expected_bundle_sha256) is not None,
                'local-command-bundle-hash')
        require(isinstance(args.receipt_directory, Path)
                and args.receipt_directory.is_absolute(),
                'local-command-receipt-directory')
        if args.command == 'verify':
            require(args.confirm == VERIFY_CONFIRMATION
                    and args.preflight_file is None
                    and args.expected_preflight_sha256 is None,
                    'local-verify-command-scope')
            clock = SystemUtcClock(1)
        else:
            require(args.confirm == execute_confirmation(args.phase)
                    and isinstance(args.preflight_file, Path)
                    and args.preflight_file.is_absolute()
                    and isinstance(args.expected_preflight_sha256, str)
                    and SHA256.fullmatch(args.expected_preflight_sha256)
                    is not None,
                    'local-execute-command-scope')
            clock = SystemUtcClock(2)
        bundle_raw = StrictCanonicalPrivateFile(args.bundle_file).read()
        require(protocol.sha(bundle_raw) == args.expected_bundle_sha256,
                'local-command-bundle-drift')
        bundle = _object(bundle_raw, 'local-command-bundle-canonical')
        adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
            args.receipt_directory,
            main=args.expected_control_plane_commit)
        current = clock.now()
        receipts, predecessor = _validate_bundle(
            bundle, main=args.expected_control_plane_commit,
            phase=args.phase, current_utc=current, adapter=adapter)
        if args.command == 'verify':
            return {
                'status': 'aws-dev-restart-safe-offline-command-inputs-verified',
                'version': VERSION,
                'target_environment': ENVIRONMENT,
                'phase': args.phase,
                'control_plane_commit': args.expected_control_plane_commit,
                'reviewed_bundle_sha256': args.expected_bundle_sha256,
                'receipt_prefix_count': len(receipts),
                'predecessor_receipt_sha256': predecessor,
                'state_before_sha256': bundle['approval']['state_before_sha256'],
                'state_after_sha256': bundle['state_after_sha256'],
                'operation_set_sha256': bundle['verify']['operation_set_sha256'],
                'observed_at_utc': current,
                'verify_expires_at_utc': bundle['verify']['verify_expires_at_utc'],
                'system_clock_read_count': 1,
                'private_input_file_count': 1,
                'private_path_emitted': False,
                'fixed_fake_executed': False,
                'receipt_written': False,
                'automatic_retry_performed': False,
                'automatic_repair_performed': False,
                'kubernetes_transport_executed': False,
                'aws_transport_executed': False,
                'terraform_command_executed': False,
                'mutation_executed': False,
                'live_execution_authorized': False,
                'next_action': 'review-before-separate-local-fixed-fake-execute',
            }
        preflight_raw = StrictCanonicalPrivateFile(args.preflight_file).read()
        require(protocol.sha(preflight_raw) == args.expected_preflight_sha256,
                'local-command-preflight-drift')
        preflight = _object(
            preflight_raw, 'local-command-preflight-canonical')
        _validate_preflight(
            preflight, bundle=bundle,
            bundle_sha256=args.expected_bundle_sha256,
            main=args.expected_control_plane_commit, phase=args.phase,
            prefix_count=len(receipts), predecessor=predecessor,
            current_utc=current)
        completed = clock.now()
        attempt_created = True
        result = adapter_core.run_restart_safe_fixed_fake_phase(
            adapter=adapter, phase=args.phase, verify=bundle['verify'],
            approval=bundle['approval'], current_utc=current,
            completed_at_utc=completed,
            state_after_sha256=bundle['state_after_sha256'],
            postconditions={name: bundle['postconditions'][name]
                            for name in POSTCONDITIONS[args.phase]},
            transport=protocol.FixedFakeTransport())
        require(clock.read_count == 2, 'local-execute-clock-count')
        return {
            'status': 'aws-dev-restart-safe-offline-command-execution-complete',
            'version': VERSION,
            'target_environment': ENVIRONMENT,
            'phase': args.phase,
            'control_plane_commit': args.expected_control_plane_commit,
            'reviewed_bundle_sha256': args.expected_bundle_sha256,
            'reviewed_preflight_sha256': args.expected_preflight_sha256,
            'predecessor_receipt_sha256': predecessor,
            'receipt_sha256': result['receipt_sha256'],
            'completed_phase_count': result['completed_phase_count'],
            'operation_count': result['operation_count'],
            'started_at_utc': current,
            'completed_at_utc': completed,
            'system_clock_read_count': 2,
            'private_input_file_count': 2,
            'durable_offline_receipt_appended': True,
            'receipt_usable_for_live': False,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'private_path_emitted': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
            'next_action': 'review-offline-receipt-before-next-phase-verify',
        }
    except LocalCommandStopped:
        raise
    except adapter_core.AdapterStopped as error:
        raise LocalCommandStopped(
            'restart-safe-adapter', phase=phase,
            attempt_created=error.report.get('attempt_created', attempt_created)) \
            from None
    except (RuleViolation, OSError, KeyError, IndexError, TypeError, ValueError):
        raise LocalCommandStopped(
            'local-command-inputs', phase=phase,
            attempt_created=attempt_created) from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.write(protocol.canonical(result).decode() + '\n')
        return 0
    except (LocalCommandStopped, SystemExit):
        sys.stderr.write(
            'STOP: aws-dev restart-safe offline command failed; preserve private inputs and receipts.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

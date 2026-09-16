#!/usr/bin/env python3
"""Exercise the complete aws-dev local fixed-fake chain across processes.

This is an offline integration rehearsal. It creates synthetic private fixtures,
invokes the frozen verify and fixed-fake execute CLIs in separate child processes,
and persists only local artifacts and synthetic receipt triplets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from guarded_dev_command_entry_conformance_v67710 import CONFIRMATIONS
from guarded_dev_transport_conformance_v6779 import (
    DurableReceiptStore,
    ReceiptStoreStopped,
    canonical,
    operation_set_sha256,
)
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS
from guarded_runtime_rules import RuleViolation, require


VERSION = 'v0.11.9.3.6.7.7.13'
ENVIRONMENT = 'aws-dev'
CONFIRMATION = 'exercise-reviewed-aws-dev-eight-phase-offline-chain'
ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / 'scripts/preflight-v0.11.9.3.6.7.7.11-aws-dev-command.py'
EXECUTE = ROOT / 'scripts/execute-v0.11.9.3.6.7.7.12-aws-dev-command.py'
PREFLIGHT_SHA256 = '7da8ccfe365c8f5adc5fa5c2cf3169f4e485d799c44c45c5c0173add7e119935'
EXECUTE_SHA256 = '695e475afe1b27aa7e29fbaa28302d50b20d8c38014ce838646ab62faf63b923'
COMMIT = re.compile(r'[0-9a-f]{40}')
CHILD_TIMEOUT_SECONDS = 30


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def utc(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def fixture_hash(main: str, phase: str, label: str) -> str:
    return sha(canonical({
        'fixture': 'dev-local-offline-chain',
        'control_plane_commit': main,
        'phase': phase,
        'label': label,
    }))


class ChainExerciseStopped(RuleViolation):
    """Redacted stop that never emits private paths or fixture bytes."""

    def __init__(self, stage: str, *, child_process_count: int = 0):
        super().__init__('dev-local-offline-chain-stopped')
        self.report = {
            'status': 'dev-local-offline-chain-stopped',
            'stage': stage,
            'completed_child_process_count': child_process_count,
            'preserve_private_session_and_receipts': True,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
        }


class PrivateSession:
    """Exclusive private artifact writer below one pre-created empty directory."""

    def __init__(self, root: Path):
        require(isinstance(root, Path) and root.is_absolute(),
                'chain-session-absolute')
        try:
            value = os.lstat(root)
            require(stat.S_ISDIR(value.st_mode)
                    and stat.S_IMODE(value.st_mode) == 0o700
                    and value.st_uid == os.geteuid(), 'chain-session-scope')
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                require(os.listdir(descriptor) == [], 'chain-session-not-empty')
            finally:
                os.close(descriptor)
        except (OSError, RuleViolation):
            raise ChainExerciseStopped('private-session') from None
        self.root = root

    @staticmethod
    def directory(path: Path) -> None:
        try:
            os.mkdir(path, 0o700)
            value = os.lstat(path)
            require(stat.S_ISDIR(value.st_mode)
                    and stat.S_IMODE(value.st_mode) == 0o700
                    and value.st_uid == os.geteuid(), 'chain-directory-scope')
        except (OSError, RuleViolation):
            raise ChainExerciseStopped('private-directory-write') from None

    @staticmethod
    def file(path: Path, raw: bytes) -> None:
        descriptor = None
        parent_descriptor = None
        try:
            require(isinstance(raw, bytes), 'chain-file-bytes')
            parent_descriptor = os.open(
                path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptor = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_descriptor,
            )
            offset = 0
            while offset < len(raw):
                count = os.write(descriptor, raw[offset:])
                require(count > 0, 'chain-file-short-write')
                offset += count
            os.fsync(descriptor)
            value = os.fstat(descriptor)
            require(stat.S_ISREG(value.st_mode)
                    and stat.S_IMODE(value.st_mode) == 0o600
                    and value.st_uid == os.geteuid()
                    and value.st_nlink == 1,
                    'chain-file-scope')
            os.fsync(parent_descriptor)
        except (OSError, RuleViolation):
            raise ChainExerciseStopped('private-file-write') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if parent_descriptor is not None:
                os.close(parent_descriptor)


def approval(main: str, phase: str, predecessor: str | None,
             state_before_sha256: str, started: datetime) -> dict:
    """Build a synthetic schema-compatible fixture with all authority false."""
    return {
        'schema': 'guarded-live-phase-approval-v1',
        'transport_version': 'guarded-live-transport-v1',
        'mode': 'live',
        'environment': ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': main,
        'approval_text_sha256': fixture_hash(main, phase, 'approval-text'),
        'inputs_sha256': fixture_hash(main, phase, 'inputs'),
        'scope_sha256': fixture_hash(main, phase, 'scope'),
        'state_sha256': state_before_sha256,
        'predecessor_receipt_sha256': predecessor,
        'operation_set_sha256': operation_set_sha256(phase),
        'proof_sha256': fixture_hash(main, phase, 'proof'),
        'start_utc': utc(started),
        'end_utc': utc(started + timedelta(hours=1)),
        'proof_created_at_utc': utc(started),
        'proof_expires_at_utc': utc(started + timedelta(minutes=15)),
        'total_budget_limit_usd': '1.00',
        'execution_authorized': False,
        'automatic_retry_authorized': False,
        'repair_authorized': False,
    }


def evidence(main: str, phase: str, state_after_sha256: str) -> dict:
    return {
        'journal_completion_sha256': fixture_hash(main, phase, 'journal'),
        'raw_output_manifest_sha256': fixture_hash(main, phase, 'raw-output'),
        'state_after_sha256': state_after_sha256,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog='exercise-v0.11.9.3.6.7.7.13-dev-local-offline-chain.py')
    value.add_argument('command', choices=('exercise',))
    value.add_argument('--expected-control-plane-commit', required=True)
    value.add_argument('--private-session-directory', required=True, type=Path)
    value.add_argument('--confirm', required=True)
    return value


def _entry_hashes() -> None:
    try:
        require(sha(PREFLIGHT.read_bytes()) == PREFLIGHT_SHA256,
                'chain-preflight-byte-drift')
        require(sha(EXECUTE.read_bytes()) == EXECUTE_SHA256,
                'chain-execute-byte-drift')
    except (OSError, RuleViolation):
        raise ChainExerciseStopped('frozen-entry-bytes') from None


def _child(argv: list[str], output: Path, label: str) -> dict:
    try:
        result = subprocess.run(
            [sys.executable, *argv],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=CHILD_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ChainExerciseStopped(label + '-process') from None
    PrivateSession.file(output / (label + '.stdout'), result.stdout)
    PrivateSession.file(output / (label + '.stderr'), result.stderr)
    try:
        require(result.returncode == 0 and result.stderr == b''
                and result.stdout.endswith(b'\n')
                and result.stdout.count(b'\n') == 1,
                'chain-child-result')
        raw = result.stdout[:-1]
        value = json.loads(raw)
        require(type(value) is dict and canonical(value) == raw,
                'chain-child-canonical')
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, RuleViolation):
        raise ChainExerciseStopped(label + '-result') from None


def _copy_json(directory: Path, name: str, raw: bytes) -> Path:
    path = directory / name
    PrivateSession.file(path, raw)
    return path


def run(argv: list[str]) -> dict:
    completed_children = 0
    try:
        require(type(argv) is list, 'chain-argv')
        args = parser().parse_args(argv)
        require(args.command == 'exercise' and args.confirm == CONFIRMATION,
                'chain-confirmation')
        require(COMMIT.fullmatch(args.expected_control_plane_commit) is not None,
                'chain-main')
        _entry_hashes()
        session = PrivateSession(args.private_session_directory)
        receipts = session.root / 'receipts'
        phases = session.root / 'phases'
        session.directory(receipts)
        session.directory(phases)
        started = datetime.now(timezone.utc).replace(microsecond=0)
        predecessor = None
        state_sha256 = sha(canonical({
            'fixture': 'dev-local-offline-chain-initial-state',
            'control_plane_commit': args.expected_control_plane_commit,
        }))
        phase_reports = []
        for index, phase in enumerate(STAGES):
            phase_dir = phases / f'{index:03d}.{phase}'
            verify_inputs = phase_dir / 'verify-inputs'
            execute_inputs = phase_dir / 'execute-inputs'
            outputs = phase_dir / 'outputs'
            session.directory(phase_dir)
            session.directory(verify_inputs)
            session.directory(execute_inputs)
            session.directory(outputs)

            next_state_sha256 = fixture_hash(
                args.expected_control_plane_commit, phase, 'state-after')
            approval_raw = canonical(approval(
                args.expected_control_plane_commit, phase, predecessor,
                state_sha256, started))
            evidence_raw = canonical(evidence(
                args.expected_control_plane_commit, phase, next_state_sha256))
            approval_sha256 = sha(approval_raw)
            evidence_sha256 = sha(evidence_raw)
            verify_approval = _copy_json(
                verify_inputs, 'approval.json', approval_raw)
            verify_evidence = _copy_json(
                verify_inputs, 'evidence.json', evidence_raw)
            preflight = _child([
                str(PREFLIGHT), 'verify',
                '--expected-control-plane-commit', args.expected_control_plane_commit,
                '--phase', phase,
                '--approval-file', str(verify_approval),
                '--expected-approval-sha256', approval_sha256,
                '--evidence-file', str(verify_evidence),
                '--expected-evidence-sha256', evidence_sha256,
                '--receipt-directory', str(receipts),
                '--confirm', 'observe-reviewed-aws-dev-command-preflight',
            ], outputs, 'preflight')
            completed_children += 1
            require(preflight.get('status')
                    == 'aws-dev-local-command-preflight-complete'
                    and preflight.get('phase') == phase
                    and preflight.get('predecessor_receipt_sha256') == predecessor
                    and preflight.get('fake_transport_executed') is False,
                    'chain-preflight-binding')
            preflight_raw = canonical(preflight)

            execute_approval = _copy_json(
                execute_inputs, 'approval.json', approval_raw)
            execute_evidence = _copy_json(
                execute_inputs, 'evidence.json', evidence_raw)
            execute_preflight = _copy_json(
                execute_inputs, 'preflight.json', preflight_raw)
            executed = _child([
                str(EXECUTE), 'execute',
                '--expected-control-plane-commit', args.expected_control_plane_commit,
                '--phase', phase,
                '--approval-file', str(execute_approval),
                '--expected-approval-sha256', approval_sha256,
                '--evidence-file', str(execute_evidence),
                '--expected-evidence-sha256', evidence_sha256,
                '--preflight-file', str(execute_preflight),
                '--expected-preflight-sha256', sha(preflight_raw),
                '--receipt-directory', str(receipts),
                '--confirm', CONFIRMATIONS[phase],
            ], outputs, 'execute')
            completed_children += 1
            require(executed.get('status')
                    == 'aws-dev-local-offline-command-execution-complete'
                    and executed.get('phase') == phase
                    and executed.get('predecessor_receipt_sha256') == predecessor
                    and executed.get('durable_receipt_appended') is True
                    and executed.get('fake_transport_executed') is True
                    and executed.get('operation_count') == len(STAGE_OPERATIONS[phase]),
                    'chain-execute-binding')
            predecessor = executed.get('receipt_sha256')
            require(isinstance(predecessor, str)
                    and re.fullmatch(r'[0-9a-f]{64}', predecessor) is not None,
                    'chain-receipt-hash')
            state_sha256 = next_state_sha256
            phase_reports.append({
                'phase': phase,
                'phase_index': index,
                'preflight_status': preflight['status'],
                'execute_status': executed['status'],
                'operation_count': executed['operation_count'],
                'receipt_sha256': predecessor,
            })

        prefix = DurableReceiptStore(
            receipts, main=args.expected_control_plane_commit).load_prefix()
        require(len(prefix) == len(STAGES)
                and tuple(row['phase'] for row in prefix) == STAGES
                and predecessor == prefix[-1]['receipt_sha256']
                and len(os.listdir(receipts)) == len(STAGES) * 3,
                'chain-final-receipt-prefix')
        completed = datetime.now(timezone.utc).replace(microsecond=0)
        report = {
            'status': 'aws-dev-local-offline-restart-chain-complete',
            'version': VERSION,
            'target_environment': ENVIRONMENT,
            'control_plane_commit': args.expected_control_plane_commit,
            'phase_count': len(STAGES),
            'operation_count': sum(len(STAGE_OPERATIONS[phase]) for phase in STAGES),
            'preflight_process_count': len(STAGES),
            'execute_process_count': len(STAGES),
            'independent_child_process_count': completed_children,
            'receipt_triplet_count': len(prefix),
            'receipt_file_count': len(os.listdir(receipts)),
            'final_receipt_sha256': predecessor,
            'started_at_utc': utc(started),
            'completed_at_utc': utc(completed),
            'phase_reports': phase_reports,
            'synthetic_fixture_approvals': True,
            'synthetic_receipt_chain': True,
            'live_receipt_acceptable': False,
            'historical_approval_reusable': False,
            'fixed_fake_transport_only': True,
            'private_path_emitted': False,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
            'next_action': 'review-offline-eight-phase-chain-before-live-transport-design',
        }
        PrivateSession.file(session.root / 'summary.json', canonical(report))
        return report
    except ChainExerciseStopped:
        raise
    except (RuleViolation, ReceiptStoreStopped, OSError, TypeError,
            ValueError, KeyError):
        raise ChainExerciseStopped(
            'offline-chain', child_process_count=completed_children) from None


def main(argv: list[str] | None = None) -> int:
    try:
        report = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.write(canonical(report).decode() + '\n')
        return 0
    except (ChainExerciseStopped, SystemExit):
        sys.stderr.write(
            'STOP: aws-dev local offline chain failed; preserve the private session and receipts.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

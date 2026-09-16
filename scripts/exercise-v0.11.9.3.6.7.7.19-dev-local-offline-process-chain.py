#!/usr/bin/env python3
"""Exercise the .7.7.18 aws-dev command through sixteen fresh processes.

This is a local offline integration rehearsal. It creates synthetic canonical
private inputs, invokes only the frozen .7.7.18 verify/execute command, retains
redacted child output, and validates the restart-safe synthetic receipt chain.
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

import guarded_dev_injected_transport_protocol_v67716 as protocol
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter_core
from guarded_dev_live_transport_design_v67715 import POSTCONDITIONS
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS
from guarded_runtime_rules import RuleViolation, require


VERSION = 'v0.11.9.3.6.7.7.19'
PREDECESSOR = 'v0.11.9.3.6.7.7.18'
ENVIRONMENT = 'aws-dev'
CONFIRMATION = 'exercise-reviewed-aws-dev-restart-safe-offline-process-chain'
ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / 'scripts/execute-v0.11.9.3.6.7.7.18-aws-dev-offline-command.py'
COMMAND_SHA256 = '9a2463bdd0bad3559789e1fbc6dbf80a6544473fe86d87004affb532b9e2f589'
COMMAND_BUNDLE_SCHEMA = 'guarded-dev-offline-restart-command-bundle-v1'
VERIFY_CONFIRMATION = 'observe-reviewed-aws-dev-restart-safe-fixed-fake'
COMMIT = re.compile(r'[0-9a-f]{40}')
SHA256 = re.compile(r'[0-9a-f]{64}')
CHILD_TIMEOUT_SECONDS = 30
TERRAFORM_PHASES = ('eks-delete', 'final-delete')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
    ).encode()


def utc(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def fixture_hash(main: str, phase: str, label: str) -> str:
    return sha(canonical({
        'fixture': 'dev-local-offline-process-chain',
        'control_plane_commit': main,
        'phase': phase,
        'label': label,
    }))


def saved_plan(main: str, phase: str) -> dict:
    return {
        'binary_plan_sha256': fixture_hash(main, phase, 'binary-plan'),
        'json_plan_sha256': fixture_hash(main, phase, 'json-plan'),
        'text_plan_sha256': fixture_hash(main, phase, 'text-plan'),
        'plan_gate_sha256': fixture_hash(main, phase, 'plan-gate'),
        'provider_lock_sha256': fixture_hash(main, phase, 'provider-lock'),
        'terraform_version': '1.14.5',
        'terraform_workspace': 'default',
    }


def build_bundle(*, main: str, phase: str, predecessor: str | None,
                 state_before: str, state_after: str,
                 current: datetime) -> dict:
    verify = {
        'schema': protocol.VERIFY_SCHEMA,
        'environment': ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': main,
        'inputs_sha256': fixture_hash(main, phase, 'inputs'),
        'scope_sha256': fixture_hash(main, phase, 'scope'),
        'operation_set_sha256': protocol.operation_set_sha256(phase),
        'proof_sha256': fixture_hash(main, phase, 'proof'),
        'state_before_sha256': state_before,
        'predecessor_receipt_sha256': predecessor,
        'verified_at_utc': utc(current - timedelta(seconds=30)),
        'verify_expires_at_utc': utc(current + timedelta(minutes=10)),
        'simulation_only': True,
        'execution_authorized': False,
    }
    approval = {
        'schema': protocol.APPROVAL_SCHEMA,
        'mode': 'offline-conformance',
        'environment': ENVIRONMENT,
        'phase': phase,
        'transport_schema': protocol.TRANSPORT_SCHEMA,
        'control_plane_commit': main,
        'reviewed_verify_sha256': protocol.sha(protocol.canonical(verify)),
        'inputs_sha256': verify['inputs_sha256'],
        'scope_sha256': verify['scope_sha256'],
        'operation_set_sha256': verify['operation_set_sha256'],
        'proof_sha256': verify['proof_sha256'],
        'state_before_sha256': state_before,
        'predecessor_receipt_sha256': predecessor,
        'start_utc': utc(current - timedelta(minutes=1)),
        'end_utc': utc(current + timedelta(hours=1)),
        'budget_limit_usd': '36.00',
        'execution_authorized': False,
        'automatic_retry_authorized': False,
        'repair_authorized': False,
        'simulation_only': True,
        'saved_plan_bundle': (saved_plan(main, phase)
                              if phase in TERRAFORM_PHASES else None),
    }
    return {
        'schema': COMMAND_BUNDLE_SCHEMA,
        'version': PREDECESSOR,
        'environment': ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': main,
        'verify': verify,
        'approval': approval,
        'state_after_sha256': state_after,
        'postconditions': {name: True for name in POSTCONDITIONS[phase]},
        'simulation_only': True,
        'live_execution_authorized': False,
    }


class ProcessChainStopped(RuleViolation):
    """Redacted stop that never emits private paths or fixture content."""

    def __init__(self, stage: str, *, child_process_count: int = 0):
        super().__init__('dev-local-offline-process-chain-stopped')
        self.report = {
            'status': 'aws-dev-local-offline-process-chain-stopped',
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
    """Exclusive private artifact writer under one pre-created empty root."""

    def __init__(self, root: Path):
        require(isinstance(root, Path) and root.is_absolute(),
                'process-session-absolute')
        try:
            value = os.lstat(root)
            require(stat.S_ISDIR(value.st_mode)
                    and stat.S_IMODE(value.st_mode) == 0o700
                    and value.st_uid == os.geteuid(), 'process-session-scope')
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                require(os.listdir(descriptor) == [], 'process-session-not-empty')
            finally:
                os.close(descriptor)
        except (OSError, RuleViolation):
            raise ProcessChainStopped('private-session') from None
        self.root = root

    @staticmethod
    def directory(path: Path) -> None:
        try:
            os.mkdir(path, 0o700)
            value = os.lstat(path)
            require(stat.S_ISDIR(value.st_mode)
                    and stat.S_IMODE(value.st_mode) == 0o700
                    and value.st_uid == os.geteuid(), 'process-directory-scope')
        except (OSError, RuleViolation):
            raise ProcessChainStopped('private-directory-write') from None

    @staticmethod
    def file(path: Path, raw: bytes) -> None:
        descriptor = None
        parent_descriptor = None
        try:
            require(type(raw) is bytes, 'process-file-bytes')
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
                require(count > 0, 'process-file-short-write')
                offset += count
            os.fsync(descriptor)
            value = os.fstat(descriptor)
            require(stat.S_ISREG(value.st_mode)
                    and stat.S_IMODE(value.st_mode) == 0o600
                    and value.st_uid == os.geteuid()
                    and value.st_nlink == 1,
                    'process-file-scope')
            os.fsync(parent_descriptor)
        except (OSError, RuleViolation):
            raise ProcessChainStopped('private-file-write') from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if parent_descriptor is not None:
                os.close(parent_descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog='exercise-v0.11.9.3.6.7.7.19-dev-local-offline-process-chain.py')
    value.add_argument('command', choices=('exercise',))
    value.add_argument('--expected-control-plane-commit', required=True)
    value.add_argument('--private-session-directory', required=True, type=Path)
    value.add_argument('--confirm', required=True)
    return value


def _command_hash() -> None:
    try:
        require(sha(COMMAND.read_bytes()) == COMMAND_SHA256,
                'process-command-byte-drift')
    except (OSError, RuleViolation):
        raise ProcessChainStopped('frozen-command-bytes') from None


def _child(argv: list[str], output: Path, label: str,
           private_root: Path) -> tuple[dict, dict]:
    try:
        result = subprocess.run(
            [sys.executable, str(COMMAND), *argv],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=CHILD_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProcessChainStopped(label + '-process') from None
    PrivateSession.file(output / (label + '.stdout'), result.stdout)
    PrivateSession.file(output / (label + '.stderr'), result.stderr)
    try:
        private_path = str(private_root).encode()
        require(private_path not in result.stdout
                and private_path not in result.stderr,
                'process-private-path-output')
    except (UnicodeEncodeError, RuleViolation):
        raise ProcessChainStopped(label + '-redaction') from None
    manifest = {
        'label': label,
        'returncode': result.returncode,
        'stdout_bytes': len(result.stdout),
        'stdout_sha256': sha(result.stdout),
        'stderr_bytes': len(result.stderr),
        'stderr_sha256': sha(result.stderr),
        'private_path_emitted': False,
    }
    try:
        require(result.returncode == 0 and result.stderr == b''
                and result.stdout.endswith(b'\n')
                and result.stdout.count(b'\n') == 1,
                'process-child-result')
        raw = result.stdout[:-1]
        value = json.loads(raw)
        require(type(value) is dict and canonical(value) == raw,
                'process-child-canonical')
        return value, manifest
    except (UnicodeDecodeError, json.JSONDecodeError, RuleViolation):
        raise ProcessChainStopped(label + '-result') from None


def run(argv: list[str]) -> dict:
    completed_children = 0
    try:
        require(type(argv) is list, 'process-chain-argv')
        args = parser().parse_args(argv)
        require(args.command == 'exercise' and args.confirm == CONFIRMATION,
                'process-chain-confirmation')
        require(COMMIT.fullmatch(args.expected_control_plane_commit) is not None,
                'process-chain-main')
        _command_hash()
        session = PrivateSession(args.private_session_directory)
        receipts = session.root / 'receipts'
        phases = session.root / 'phases'
        session.directory(receipts)
        session.directory(phases)
        started = datetime.now(timezone.utc).replace(microsecond=0)
        predecessor = None
        state_sha256 = fixture_hash(
            args.expected_control_plane_commit, 'chain', 'initial-state')
        phase_reports = []
        output_manifest_hashes = []

        for index, phase in enumerate(STAGES):
            phase_dir = phases / f'{index:03d}.{phase}'
            bundle_dir = phase_dir / 'bundle-input'
            preflight_dir = phase_dir / 'preflight-input'
            outputs = phase_dir / 'outputs'
            session.directory(phase_dir)
            session.directory(bundle_dir)
            session.directory(preflight_dir)
            session.directory(outputs)

            current = datetime.now(timezone.utc).replace(microsecond=0)
            state_after = (fixture_hash(
                args.expected_control_plane_commit, phase, 'state-after')
                if phase in TERRAFORM_PHASES else state_sha256)
            bundle = build_bundle(
                main=args.expected_control_plane_commit, phase=phase,
                predecessor=predecessor, state_before=state_sha256,
                state_after=state_after, current=current)
            bundle_raw = canonical(bundle)
            bundle_path = bundle_dir / 'bundle.json'
            session.file(bundle_path, bundle_raw)
            bundle_sha256 = sha(bundle_raw)

            verified, verify_manifest = _child([
                'verify',
                '--expected-control-plane-commit',
                args.expected_control_plane_commit,
                '--phase', phase,
                '--bundle-file', str(bundle_path),
                '--expected-bundle-sha256', bundle_sha256,
                '--receipt-directory', str(receipts),
                '--confirm', VERIFY_CONFIRMATION,
            ], outputs, 'verify', session.root)
            completed_children += 1
            require(verified.get('status') ==
                    'aws-dev-restart-safe-offline-command-inputs-verified'
                    and verified.get('phase') == phase
                    and verified.get('receipt_prefix_count') == index
                    and verified.get('predecessor_receipt_sha256') == predecessor
                    and verified.get('reviewed_bundle_sha256') == bundle_sha256
                    and verified.get('fixed_fake_executed') is False
                    and verified.get('receipt_written') is False,
                    'process-verify-binding')
            preflight_raw = canonical(verified)
            preflight_path = preflight_dir / 'preflight.json'
            session.file(preflight_path, preflight_raw)
            preflight_sha256 = sha(preflight_raw)

            executed, execute_manifest = _child([
                'execute',
                '--expected-control-plane-commit',
                args.expected_control_plane_commit,
                '--phase', phase,
                '--bundle-file', str(bundle_path),
                '--expected-bundle-sha256', bundle_sha256,
                '--preflight-file', str(preflight_path),
                '--expected-preflight-sha256', preflight_sha256,
                '--receipt-directory', str(receipts),
                '--confirm',
                'execute-reviewed-aws-dev-restart-safe-fixed-fake-' + phase,
            ], outputs, 'execute', session.root)
            completed_children += 1
            require(executed.get('status') ==
                    'aws-dev-restart-safe-offline-command-execution-complete'
                    and executed.get('phase') == phase
                    and executed.get('predecessor_receipt_sha256') == predecessor
                    and executed.get('reviewed_bundle_sha256') == bundle_sha256
                    and executed.get('reviewed_preflight_sha256') ==
                    preflight_sha256
                    and executed.get('completed_phase_count') == index + 1
                    and executed.get('operation_count') ==
                    len(STAGE_OPERATIONS[phase])
                    and executed.get('durable_offline_receipt_appended') is True
                    and executed.get('receipt_usable_for_live') is False,
                    'process-execute-binding')
            receipt_sha256 = executed.get('receipt_sha256')
            require(type(receipt_sha256) is str
                    and SHA256.fullmatch(receipt_sha256) is not None,
                    'process-receipt-hash')

            output_manifest = {
                'schema': 'offline-redacted-child-output-manifest-v1',
                'version': VERSION,
                'phase': phase,
                'control_plane_commit': args.expected_control_plane_commit,
                'bundle_sha256': bundle_sha256,
                'preflight_sha256': preflight_sha256,
                'verify': verify_manifest,
                'execute': execute_manifest,
                'output_file_count': 4,
                'private_path_emitted': False,
                'resource_identity_emitted': False,
            }
            manifest_raw = canonical(output_manifest)
            session.file(outputs / 'redacted-output-manifest.json', manifest_raw)
            output_manifest_hashes.append(sha(manifest_raw))
            phase_reports.append({
                'phase': phase,
                'phase_index': index,
                'bundle_sha256': bundle_sha256,
                'preflight_sha256': preflight_sha256,
                'output_manifest_sha256': output_manifest_hashes[-1],
                'state_before_sha256': state_sha256,
                'state_after_sha256': state_after,
                'operation_count': executed['operation_count'],
                'receipt_sha256': receipt_sha256,
            })
            predecessor = receipt_sha256
            state_sha256 = state_after

        prefix = adapter_core.RestartSafeOfflineReceiptAdapter(
            receipts, main=args.expected_control_plane_commit).load_prefix()
        require(len(prefix) == len(STAGES)
                and tuple(row['phase'] for row in prefix) == STAGES
                and predecessor == protocol.sha(protocol.canonical(prefix[-1]))
                and len(os.listdir(receipts)) == len(STAGES) * 3,
                'process-final-receipt-prefix')
        completed = datetime.now(timezone.utc).replace(microsecond=0)
        report = {
            'status': 'aws-dev-local-offline-process-chain-complete',
            'version': VERSION,
            'predecessor': PREDECESSOR,
            'target_environment': ENVIRONMENT,
            'control_plane_commit': args.expected_control_plane_commit,
            'phase_count': len(STAGES),
            'operation_count': sum(
                len(STAGE_OPERATIONS[phase]) for phase in STAGES),
            'verify_process_count': len(STAGES),
            'execute_process_count': len(STAGES),
            'independent_child_process_count': completed_children,
            'receipt_triplet_count': len(prefix),
            'receipt_file_count': len(os.listdir(receipts)),
            'retained_child_output_file_count': len(STAGES) * 4,
            'redacted_output_manifest_count': len(output_manifest_hashes),
            'final_receipt_sha256': predecessor,
            'started_at_utc': utc(started),
            'completed_at_utc': utc(completed),
            'phase_reports': phase_reports,
            'synthetic_bundle_chain': True,
            'synthetic_receipt_chain': True,
            'live_receipt_acceptable': False,
            'historical_approval_reusable': False,
            'fixed_fake_transport_only': True,
            'private_path_emitted': False,
            'resource_identity_emitted': False,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'live_execution_authorized': False,
            'next_action': 'record-v0.11-scope-and-evidence-closure',
        }
        session.file(session.root / 'summary.json', canonical(report))
        return report
    except ProcessChainStopped:
        raise
    except (RuleViolation, adapter_core.AdapterStopped, OSError, TypeError,
            ValueError, KeyError, IndexError):
        raise ProcessChainStopped(
            'offline-process-chain',
            child_process_count=completed_children) from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.write(canonical(result).decode() + '\n')
        return 0
    except (ProcessChainStopped, SystemExit):
        sys.stderr.write(
            'STOP: aws-dev local offline process chain failed; preserve the private session and receipts.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

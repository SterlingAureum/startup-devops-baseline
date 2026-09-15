#!/usr/bin/env python3
"""Local aws-dev command preflight with no transport or execute command.

This prototype reads strict private local files and the host UTC clock, then
adapts them into the v0.11.9.3.6.7.7.10 offline verify entry. It cannot invoke
AWS, Kubernetes, Terraform, a fake transport operation or any mutation.
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

from guarded_dev_command_entry_conformance_v67710 import (
    CommandEntryStopped,
    DevOfflineCommandEntry,
    FixedPrivateInputReader,
    FrozenClock,
    command_request,
    sha,
)
from guarded_dev_transport_conformance_v6779 import (
    DurableReceiptStore,
    ReceiptStoreStopped,
    canonical,
)
from guarded_live_migration_contract_v6778 import STAGES
from guarded_runtime_rules import RuleViolation, require


VERSION = 'v0.11.9.3.6.7.7.11'
ENVIRONMENT = 'aws-dev'
CONFIRMATION = 'observe-reviewed-aws-dev-command-preflight'
MAX_PRIVATE_INPUT_BYTES = 1024 * 1024
COMMIT = re.compile(r'[0-9a-f]{40}')
SHA256 = re.compile(r'[0-9a-f]{64}')


class LocalPreflightStopped(RuleViolation):
    """Redacted local preflight stop without path, input or receipt bytes."""

    def __init__(self, stage: str):
        super().__init__('dev-local-command-preflight-stopped')
        self.report = {
            'status': 'dev-local-command-preflight-stopped',
            'stage': stage,
            'preserve_private_inputs_and_receipts': True,
            'automatic_retry_performed': False,
            'fake_transport_executed': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'execution_authorized': False,
        }


class SystemUtcClock:
    """One real host UTC reading, normalized to whole seconds."""

    def __init__(self):
        self._read = False

    def now(self) -> str:
        require(self._read is False, 'system-clock-repeat')
        self._read = True
        value = datetime.now(timezone.utc).replace(microsecond=0)
        return value.isoformat().replace('+00:00', 'Z')


class StrictPrivateInputFiles:
    """Read two owned canonical files through an owned 0700 parent."""

    def __init__(self, approval: Path, evidence: Path):
        require(isinstance(approval, Path) and isinstance(evidence, Path),
                'private-input-path-type')
        require(approval.is_absolute() and evidence.is_absolute(),
                'private-input-absolute')
        require(approval.parent == evidence.parent,
                'private-input-common-parent')
        self._paths = {'approval': approval, 'evidence': evidence}
        self.read_count = 0

    @staticmethod
    def _directory(path: Path) -> int:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            value = os.fstat(descriptor)
            if (not stat.S_ISDIR(value.st_mode)
                    or stat.S_IMODE(value.st_mode) != 0o700
                    or value.st_uid != os.geteuid()):
                os.close(descriptor)
                raise LocalPreflightStopped('private-directory-scope')
            return descriptor
        except LocalPreflightStopped:
            raise
        except OSError:
            raise LocalPreflightStopped('private-directory-open') from None

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
                raise LocalPreflightStopped('private-file-scope')
            file_descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
            opened = os.fstat(file_descriptor)
            require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
                    'private-file-race')
            chunks = []
            total = 0
            while True:
                chunk = os.read(file_descriptor, min(65536,
                    MAX_PRIVATE_INPUT_BYTES + 1 - total))
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
                raise LocalPreflightStopped('private-file-json') from None
            require(type(value) is dict and canonical(value) == raw,
                    'private-file-canonical')
            return raw
        except LocalPreflightStopped:
            raise
        except (OSError, RuleViolation):
            raise LocalPreflightStopped('private-file-read') from None
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)

    def read_all(self) -> dict[str, bytes]:
        descriptor = self._directory(next(iter(self._paths.values())).parent)
        try:
            require(set(os.listdir(descriptor)) == {
                path.name for path in self._paths.values()},
                'private-directory-unexpected-entry')
            require(len({path.name for path in self._paths.values()}) == 2,
                    'private-input-distinct-names')
            result = {
                label: self._read_one(descriptor, path.name)
                for label, path in self._paths.items()
            }
            self.read_count = 2
            return result
        except LocalPreflightStopped:
            raise
        except (OSError, RuleViolation):
            raise LocalPreflightStopped('private-input-scope') from None
        finally:
            os.close(descriptor)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        prog='preflight-v0.11.9.3.6.7.7.11-aws-dev-command.py')
    value.add_argument('command', choices=('verify',))
    value.add_argument('--expected-control-plane-commit', required=True)
    value.add_argument('--phase', required=True, choices=STAGES)
    value.add_argument('--approval-file', required=True, type=Path)
    value.add_argument('--expected-approval-sha256', required=True)
    value.add_argument('--evidence-file', required=True, type=Path)
    value.add_argument('--expected-evidence-sha256', required=True)
    value.add_argument('--receipt-directory', required=True, type=Path)
    value.add_argument('--confirm', required=True)
    return value


def run(argv: list[str]) -> dict:
    try:
        require(type(argv) is list, 'local-cli-argv')
        args = parser().parse_args(argv)
        require(args.command == 'verify' and args.confirm == CONFIRMATION,
                'local-cli-confirmation')
        require(COMMIT.fullmatch(args.expected_control_plane_commit) is not None,
                'local-cli-main')
        require(SHA256.fullmatch(args.expected_approval_sha256) is not None
                and SHA256.fullmatch(args.expected_evidence_sha256) is not None,
                'local-cli-input-hash')
        inputs = StrictPrivateInputFiles(
            args.approval_file, args.evidence_file).read_all()
        require(sha(inputs['approval']) == args.expected_approval_sha256
                and sha(inputs['evidence']) == args.expected_evidence_sha256,
                'local-cli-input-drift')
        now = SystemUtcClock().now()
        request = command_request(
            command='verify', phase=args.phase,
            main=args.expected_control_plane_commit,
            approval_sha256=args.expected_approval_sha256,
            evidence_sha256=args.expected_evidence_sha256)
        entry = DevOfflineCommandEntry(
            main=args.expected_control_plane_commit,
            clock=FrozenClock((now,)),
            reader=FixedPrivateInputReader(inputs),
            store=DurableReceiptStore(
                args.receipt_directory,
                main=args.expected_control_plane_commit))
        reviewed = entry.dispatch('verify', request)
        return {
            'status': 'aws-dev-local-command-preflight-complete',
            'version': VERSION,
            'target_environment': ENVIRONMENT,
            'phase': args.phase,
            'control_plane_commit': args.expected_control_plane_commit,
            'reviewed_approval_sha256': reviewed['reviewed_approval_sha256'],
            'reviewed_evidence_sha256': reviewed['reviewed_evidence_sha256'],
            'operation_set_sha256': reviewed['operation_set_sha256'],
            'predecessor_receipt_sha256': reviewed['predecessor_receipt_sha256'],
            'observed_at_utc': now,
            'verify_expires_at_utc': reviewed['verify_expires_at_utc'],
            'private_input_file_count': 2,
            'private_path_emitted': False,
            'system_clock_read': True,
            'fake_transport_executed': False,
            'kubernetes_transport_executed': False,
            'aws_transport_executed': False,
            'terraform_command_executed': False,
            'mutation_executed': False,
            'execution_authorized': False,
            'next_action': 'review-preflight-before-separate-offline-execute-prototype',
        }
    except LocalPreflightStopped:
        raise
    except (RuleViolation, ReceiptStoreStopped, CommandEntryStopped,
            OSError, TypeError, ValueError, KeyError):
        raise LocalPreflightStopped('local-inputs') from None


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(list(sys.argv[1:] if argv is None else argv))
        sys.stdout.write(canonical(result).decode() + '\n')
        return 0
    except (LocalPreflightStopped, SystemExit):
        sys.stderr.write('STOP: aws-dev local command preflight failed; preserve private inputs and receipts.\n')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

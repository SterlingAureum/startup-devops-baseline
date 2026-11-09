#!/usr/bin/env python3
"""Offline tests for the aws-dev local CLI preflight prototype."""
from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import guarded_dev_transport_conformance_v6779 as transport
from guarded_live_migration_contract_v6778 import STAGES


SCRIPT = SCRIPTS / 'preflight-v0.11.9.3.6.7.7.11-aws-dev-command.py'
SPEC = importlib.util.spec_from_file_location('dev_local_cli_v67711', SCRIPT)
cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(cli)

MAIN = 'a' * 40
STATE = 'b' * 64
NOW = '2026-09-15T00:02:00Z'


def digest(char: str) -> str:
    return char * 64


def approval(phase: str, predecessor=None, *, environment='aws-dev',
             main=MAIN) -> dict:
    return {
        'schema': 'guarded-live-phase-approval-v1',
        'transport_version': 'guarded-live-transport-v1',
        'mode': 'live',
        'environment': environment,
        'phase': phase,
        'control_plane_commit': main,
        'approval_text_sha256': digest('1'),
        'inputs_sha256': digest('2'),
        'scope_sha256': digest('3'),
        'state_sha256': STATE,
        'predecessor_receipt_sha256': predecessor,
        'operation_set_sha256': transport.operation_set_sha256(phase),
        'proof_sha256': digest('4'),
        'start_utc': '2026-09-15T00:00:00Z',
        'end_utc': '2026-09-15T01:00:00Z',
        'proof_created_at_utc': '2026-09-15T00:01:00Z',
        'proof_expires_at_utc': '2026-09-15T00:16:00Z',
        'total_budget_limit_usd': '10.00',
        'execution_authorized': False,
        'automatic_retry_authorized': False,
        'repair_authorized': False,
    }


def evidence() -> dict:
    return {
        'journal_completion_sha256': digest('5'),
        'raw_output_manifest_sha256': digest('6'),
        'state_after_sha256': STATE,
    }


class Session:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.inputs = self.root / 'inputs'
        self.receipts = self.root / 'receipts'
        self.inputs.mkdir(mode=0o700)
        self.receipts.mkdir(mode=0o700)
        self.approval = self.inputs / 'approval.json'
        self.evidence = self.inputs / 'evidence.json'
        self.write(self.approval, approval(STAGES[0]))
        self.write(self.evidence, evidence())
        return self

    def __exit__(self, *unused):
        self.temp.cleanup()

    @staticmethod
    def write(path: Path, value, *, canonical=True):
        raw = (transport.canonical(value) if canonical
               else json.dumps(value, indent=2).encode())
        path.write_bytes(raw)
        path.chmod(0o600)

    def argv(self, *, phase=STAGES[0], confirm=cli.CONFIRMATION,
             main=MAIN, approval_hash=None, evidence_hash=None,
             approval_path=None, evidence_path=None, receipt_path=None):
        approval_path = approval_path or self.approval
        evidence_path = evidence_path or self.evidence
        receipt_path = receipt_path or self.receipts
        return [
            'verify', '--expected-control-plane-commit', main,
            '--phase', phase,
            '--approval-file', str(approval_path),
            '--expected-approval-sha256', approval_hash or cli.sha(approval_path.read_bytes()),
            '--evidence-file', str(evidence_path),
            '--expected-evidence-sha256', evidence_hash or cli.sha(evidence_path.read_bytes()),
            '--receipt-directory', str(receipt_path),
            '--confirm', confirm,
        ]


class LocalCliPreflightTests(unittest.TestCase):
    def assertStopped(self, argv):
        with patch.object(cli.SystemUtcClock, 'now', return_value=NOW):
            with self.assertRaises(cli.LocalPreflightStopped):
                cli.run(argv)

    def run_ok(self, session: Session, **kwargs):
        with patch.object(cli.SystemUtcClock, 'now', return_value=NOW) as clock:
            result = cli.run(session.argv(**kwargs))
        self.assertEqual(clock.call_count, 1)
        return result

    def test_success_report_is_exact_and_writes_no_receipt(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(set(result), {
                'status', 'version', 'target_environment', 'phase',
                'control_plane_commit', 'reviewed_approval_sha256',
                'reviewed_evidence_sha256', 'operation_set_sha256',
                'predecessor_receipt_sha256', 'observed_at_utc',
                'verify_expires_at_utc', 'private_input_file_count',
                'private_path_emitted', 'system_clock_read',
                'fake_transport_executed', 'kubernetes_transport_executed',
                'aws_transport_executed', 'terraform_command_executed',
                'mutation_executed', 'execution_authorized', 'next_action'})
            self.assertEqual(result['status'],
                             'aws-dev-local-command-preflight-complete')
            self.assertEqual(result['private_input_file_count'], 2)
            self.assertTrue(result['system_clock_read'])
            self.assertFalse(any(result[key] for key in (
                'private_path_emitted', 'fake_transport_executed',
                'kubernetes_transport_executed', 'aws_transport_executed',
                'terraform_command_executed', 'mutation_executed',
                'execution_authorized')))
            self.assertEqual(list(session.receipts.iterdir()), [])

    def test_main_emits_one_canonical_json_line(self):
        with Session() as session:
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(cli.SystemUtcClock, 'now', return_value=NOW):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(cli.main(session.argv()), 0)
            raw = stdout.getvalue().encode().rstrip(b'\n')
            self.assertEqual(transport.canonical(json.loads(raw)), raw)
            self.assertEqual(stderr.getvalue(), '')

    def test_real_subprocess_reads_host_clock_and_private_files(self):
        with Session() as session:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            value = approval(STAGES[0])
            value.update({
                'start_utc': (now - timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'),
                'end_utc': (now + timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
                'proof_created_at_utc': (now - timedelta(seconds=30)).isoformat().replace('+00:00', 'Z'),
                'proof_expires_at_utc': (now + timedelta(minutes=14, seconds=30)).isoformat().replace('+00:00', 'Z'),
            })
            session.write(session.approval, value)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), *session.argv()],
                cwd=ROOT, env={'PATH': os.environ['PATH'],
                               'PYTHONDONTWRITEBYTECODE': '1'},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertTrue(result['system_clock_read'])
            self.assertEqual(completed.stderr, b'')

    def test_system_clock_is_single_use_and_utc(self):
        clock = cli.SystemUtcClock()
        value = clock.now()
        self.assertRegex(value, r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
        with self.assertRaises(Exception):
            clock.now()

    def test_parser_exposes_only_verify_command(self):
        choices = next(action.choices for action in cli.parser()._actions
                       if action.dest == 'command')
        self.assertEqual(tuple(choices), ('verify',))
        with Session() as session:
            argv = session.argv()
            argv[0] = 'execute'
            with redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(argv), 1)

    def test_missing_and_unknown_arguments_are_redacted(self):
        for argv in (['verify'], ['verify', '--unknown', 'value']):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(cli.main(argv), 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('preserve private inputs', stderr.getvalue())

    def test_confirmation_and_hash_syntax_are_required(self):
        with Session() as session:
            for argv in (
                    session.argv(confirm='wrong'),
                    session.argv(main='A' * 40),
                    session.argv(approval_hash='0' * 63),
                    session.argv(evidence_hash='z' * 64)):
                self.assertStopped(argv)

    def test_input_hash_drift_is_rejected(self):
        with Session() as session:
            self.assertStopped(session.argv(approval_hash='f' * 64))
            self.assertStopped(session.argv(evidence_hash='f' * 64))

    def test_approval_environment_main_and_phase_drift_are_rejected(self):
        mutations = (
            ('environment', 'aws-test'), ('environment', 'aws-prod'),
            ('control_plane_commit', 'c' * 40), ('phase', STAGES[1]))
        for key, value in mutations:
            with Session() as session:
                changed = approval(STAGES[0])
                changed[key] = value
                session.write(session.approval, changed)
                self.assertStopped(session.argv())

    def test_approval_authority_budget_clock_and_operation_drift_are_rejected(self):
        mutations = (
            ('execution_authorized', True),
            ('automatic_retry_authorized', True),
            ('repair_authorized', True),
            ('total_budget_limit_usd', '0.00'),
            ('proof_expires_at_utc', '2026-09-15T00:01:30Z'),
            ('operation_set_sha256', 'f' * 64))
        for key, value in mutations:
            with Session() as session:
                changed = approval(STAGES[0])
                changed[key] = value
                session.write(session.approval, changed)
                self.assertStopped(session.argv())

    def test_evidence_schema_and_hashes_are_exact(self):
        variants = []
        extra = evidence(); extra['extra'] = True; variants.append(extra)
        missing = evidence(); del missing['state_after_sha256']; variants.append(missing)
        invalid = evidence(); invalid['state_after_sha256'] = 'x'; variants.append(invalid)
        for value in variants:
            with Session() as session:
                session.write(session.evidence, value)
                self.assertStopped(session.argv())

    def test_malformed_noncanonical_empty_and_oversized_inputs_stop(self):
        variants = (b'not-json', json.dumps(approval(STAGES[0]), indent=2).encode(),
                    b'', b'{' + b' ' * (cli.MAX_PRIVATE_INPUT_BYTES + 1))
        for raw in variants:
            with Session() as session:
                session.approval.write_bytes(raw)
                session.approval.chmod(0o600)
                self.assertStopped(session.argv(
                    approval_hash=cli.sha(raw) if raw else '0' * 64))

    def test_paths_must_be_absolute_distinct_and_share_parent(self):
        with Session() as session:
            self.assertStopped(session.argv(
                approval_path=Path('approval.json'),
                approval_hash=cli.sha(session.approval.read_bytes())))
            other = session.root / 'other'; other.mkdir(mode=0o700)
            other_evidence = other / 'evidence.json'
            session.write(other_evidence, evidence())
            self.assertStopped(session.argv(evidence_path=other_evidence))
            self.assertStopped(session.argv(evidence_path=session.approval))

    def test_private_parent_mode_symlink_and_unexpected_entry_stop(self):
        with Session() as session:
            session.inputs.chmod(0o755)
            self.assertStopped(session.argv())
        with Session() as session:
            link = session.root / 'linked-inputs'; link.symlink_to(session.inputs,
                                                                   target_is_directory=True)
            self.assertStopped(session.argv(
                approval_path=link / 'approval.json',
                evidence_path=link / 'evidence.json'))
        with Session() as session:
            extra = session.inputs / 'extra'; extra.write_text('x'); extra.chmod(0o600)
            self.assertStopped(session.argv())

    def test_private_file_mode_symlink_and_hardlink_stop(self):
        with Session() as session:
            session.approval.chmod(0o644)
            self.assertStopped(session.argv())
        with Session() as session:
            session.approval.unlink()
            session.approval.symlink_to(session.evidence)
            self.assertStopped(session.argv())
        with Session() as session:
            extra = session.root / 'approval-hardlink.json'
            os.link(session.approval, extra)
            self.assertStopped(session.argv())

    def test_receipt_directory_must_be_absolute_owned_0700_and_unlinked(self):
        with Session() as session:
            session.receipts.chmod(0o755)
            self.assertStopped(session.argv())
        with Session() as session:
            self.assertStopped(session.argv(receipt_path=Path('receipts')))
        with Session() as session:
            link = session.root / 'receipt-link'
            link.symlink_to(session.receipts, target_is_directory=True)
            self.assertStopped(session.argv(receipt_path=link))

    def test_pending_and_unexpected_receipt_entries_block_verify(self):
        for name in ('000.freeze-applications.intent.json', 'unexpected'):
            with Session() as session:
                item = session.receipts / name
                item.write_bytes(transport.canonical({'pending': True}))
                item.chmod(0o600)
                self.assertStopped(session.argv())

    def test_completed_receipt_prefix_allows_exact_next_phase(self):
        with Session() as session:
            first_approval = approval(STAGES[0])
            report = transport.DevTransportConformanceHarness(
                main=MAIN,
                store=transport.DurableReceiptStore(session.receipts, main=MAIN),
            ).run_phase(
                phase=STAGES[0], approval=first_approval,
                current_utc='2026-09-15T00:02:00Z',
                completed_at_utc='2026-09-15T00:03:00Z',
                evidence=evidence(),
                transport=transport.DevConformanceTransport(
                    transport.successful_responses(STAGES[0])))
            predecessor = report['receipt_sha256']
            session.write(session.approval, approval(STAGES[1], predecessor))
            result = self.run_ok(session, phase=STAGES[1])
            self.assertEqual(result['predecessor_receipt_sha256'], predecessor)
            self.assertEqual(len(list(session.receipts.iterdir())), 3)

    def test_wrong_next_phase_or_predecessor_stops(self):
        with Session() as session:
            session.write(session.approval,
                          approval(STAGES[1], predecessor='f' * 64))
            self.assertStopped(session.argv(phase=STAGES[1]))

    def test_failure_output_does_not_disclose_paths_or_private_bytes(self):
        with Session() as session:
            secret = 'private-sensitive-marker'
            session.approval.write_text(secret)
            session.approval.chmod(0o600)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(cli.main(session.argv(
                    approval_hash=cli.sha(secret.encode()))), 1)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(secret, combined)
            self.assertNotIn(str(session.root), combined)

    def test_source_has_no_environment_network_cloud_or_command_backend(self):
        source = SCRIPT.read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or '').split('.')[0])
        self.assertTrue(imports.issubset({
            '__future__', 'argparse', 'datetime', 'json', 'os', 'pathlib',
            're', 'stat', 'sys', 'guarded_dev_command_entry_conformance_v67710',
            'guarded_dev_transport_conformance_v6779',
            'guarded_live_migration_contract_v6778', 'guarded_runtime_rules'}))
        forbidden = {'subprocess', 'socket', 'boto3', 'requests', 'urllib',
                     'kubernetes', 'terraform'}
        self.assertFalse(imports & forbidden)
        attributes = {node.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute)}
        self.assertFalse(attributes & {'getenv', 'environ', 'system', 'popen',
                                       'Popen', 'execve', 'spawnv'})
        self.assertNotIn("add_argument('execute'", source)

    def test_source_adapts_only_into_frozen_offline_verify(self):
        source = SCRIPT.read_text()
        self.assertIn("entry.dispatch('verify', request)", source)
        self.assertIn('FrozenClock((now,))', source)
        self.assertIn('FixedPrivateInputReader(inputs)', source)
        self.assertNotIn('DevConformanceTransport(', source)
        self.assertNotIn("dispatch('execute'", source)


if __name__ == '__main__':
    unittest.main(verbosity=2)

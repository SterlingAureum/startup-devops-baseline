#!/usr/bin/env python3
"""Offline tests for the dev local fixed-fake execute prototype."""
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
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS


SCRIPT = SCRIPTS / 'execute-v0.11.9.3.6.7.7.12-aws-dev-command.py'
SPEC = importlib.util.spec_from_file_location('dev_local_execute_v67712', SCRIPT)
cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(cli)

MAIN = 'a' * 40
STATE = 'b' * 64
CURRENT = datetime(2026, 9, 15, 0, 2, tzinfo=timezone.utc)
COMPLETED = datetime(2026, 9, 15, 0, 3, tzinfo=timezone.utc)


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


def preflight(phase: str, approval_raw: bytes, evidence_raw: bytes,
              predecessor=None, *, main=MAIN,
              observed='2026-09-15T00:02:00Z',
              expiry='2026-09-15T00:16:00Z') -> dict:
    return {
        'status': 'aws-dev-local-command-preflight-complete',
        'version': 'v0.11.9.3.6.7.7.11',
        'target_environment': 'aws-dev',
        'phase': phase,
        'control_plane_commit': main,
        'reviewed_approval_sha256': cli.sha(approval_raw),
        'reviewed_evidence_sha256': cli.sha(evidence_raw),
        'operation_set_sha256': transport.operation_set_sha256(phase),
        'predecessor_receipt_sha256': predecessor,
        'observed_at_utc': observed,
        'verify_expires_at_utc': expiry,
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
        self.preflight = self.inputs / 'preflight.json'
        self.configure(STAGES[0])
        return self

    def __exit__(self, *unused):
        self.temp.cleanup()

    @staticmethod
    def write(path: Path, value, *, canonical=True):
        raw = (transport.canonical(value) if canonical
               else json.dumps(value, indent=2).encode())
        path.write_bytes(raw)
        path.chmod(0o600)
        return raw

    def configure(self, phase: str, predecessor=None, *, approval_value=None,
                  evidence_value=None, preflight_value=None):
        approval_raw = self.write(
            self.approval, approval_value or approval(phase, predecessor))
        evidence_raw = self.write(self.evidence, evidence_value or evidence())
        self.write(self.preflight, preflight_value or preflight(
            phase, approval_raw, evidence_raw, predecessor))

    def argv(self, *, phase=STAGES[0], main=MAIN, confirm=None,
             approval_hash=None, evidence_hash=None, preflight_hash=None,
             approval_path=None, evidence_path=None, preflight_path=None,
             receipt_path=None):
        approval_path = approval_path or self.approval
        evidence_path = evidence_path or self.evidence
        preflight_path = preflight_path or self.preflight
        receipt_path = receipt_path or self.receipts
        return [
            'execute', '--expected-control-plane-commit', main,
            '--phase', phase,
            '--approval-file', str(approval_path),
            '--expected-approval-sha256', approval_hash or cli.sha(self.approval.read_bytes()),
            '--evidence-file', str(evidence_path),
            '--expected-evidence-sha256', evidence_hash or cli.sha(self.evidence.read_bytes()),
            '--preflight-file', str(preflight_path),
            '--expected-preflight-sha256', preflight_hash or cli.sha(self.preflight.read_bytes()),
            '--receipt-directory', str(receipt_path),
            '--confirm', confirm or cli.CONFIRMATIONS[phase],
        ]


class LocalOfflineExecuteTests(unittest.TestCase):
    def clock(self, values=(CURRENT, COMPLETED)):
        mocked = patch.object(cli, 'datetime')
        value = mocked.start()
        self.addCleanup(mocked.stop)
        value.now.side_effect = values
        return value

    def run_ok(self, session: Session, **kwargs):
        self.clock()
        return cli.run(session.argv(**kwargs))

    def assertStopped(self, session: Session, argv=None, *, clocks=(CURRENT, COMPLETED)):
        self.clock(clocks)
        with self.assertRaises(cli.LocalExecuteStopped):
            cli.run(argv or session.argv())

    def test_success_runs_exact_fixed_fake_and_appends_one_receipt(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(result['status'],
                             'aws-dev-local-offline-command-execution-complete')
            self.assertEqual(result['operation_count'], len(STAGE_OPERATIONS[STAGES[0]]))
            self.assertTrue(result['fake_transport_executed'])
            self.assertTrue(result['durable_receipt_appended'])
            self.assertEqual(len(list(session.receipts.iterdir())), 3)

    def test_success_report_effect_flags_are_fail_closed(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(result['system_clock_read_count'], 2)
            self.assertEqual(result['private_input_file_count'], 3)
            self.assertTrue(result['simulation_only'])
            self.assertFalse(any(result[key] for key in (
                'private_path_emitted', 'kubernetes_transport_executed',
                'aws_transport_executed', 'terraform_command_executed',
                'mutation_executed', 'live_execution_authorized')))

    def test_receipt_triplet_is_private_canonical_and_bound(self):
        with Session() as session:
            result = self.run_ok(session)
            for item in session.receipts.iterdir():
                self.assertEqual(item.stat().st_mode & 0o777, 0o600)
                raw = item.read_bytes()
                self.assertEqual(transport.canonical(json.loads(raw)), raw)
            rows = transport.DurableReceiptStore(
                session.receipts, main=MAIN).load_prefix()
            self.assertEqual(rows[0]['receipt_sha256'], result['receipt_sha256'])

    def test_main_emits_one_canonical_json_line(self):
        with Session() as session:
            self.clock()
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(cli.main(session.argv()), 0)
            raw = stdout.getvalue().encode().rstrip(b'\n')
            self.assertEqual(transport.canonical(json.loads(raw)), raw)
            self.assertEqual(stderr.getvalue(), '')

    def test_real_subprocess_executes_only_local_fixed_fake(self):
        with Session() as session:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            approval_value = approval(STAGES[0])
            approval_value.update({
                'start_utc': (now - timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'),
                'end_utc': (now + timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
                'proof_created_at_utc': (now - timedelta(seconds=30)).isoformat().replace('+00:00', 'Z'),
                'proof_expires_at_utc': (now + timedelta(minutes=14, seconds=30)).isoformat().replace('+00:00', 'Z'),
            })
            approval_raw = session.write(session.approval, approval_value)
            evidence_raw = session.evidence.read_bytes()
            observed = (now - timedelta(seconds=5)).isoformat().replace('+00:00', 'Z')
            session.write(session.preflight, preflight(
                STAGES[0], approval_raw, evidence_raw,
                observed=observed,
                expiry=approval_value['proof_expires_at_utc']))
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), *session.argv()],
                cwd=ROOT, env={'PATH': os.environ['PATH'],
                               'PYTHONDONTWRITEBYTECODE': '1'},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)['simulation_only'])
            self.assertEqual(completed.stderr, b'')

    def test_parser_exposes_only_execute_and_requires_all_arguments(self):
        choices = next(action.choices for action in cli.parser()._actions
                       if action.dest == 'command')
        self.assertEqual(tuple(choices), ('execute',))
        for argv in (['execute'], ['verify']):
            with redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(argv), 1)

    def test_confirmation_main_and_hash_syntax_are_exact(self):
        with Session() as session:
            for argv in (
                session.argv(confirm='wrong'),
                session.argv(main='A' * 40),
                session.argv(approval_hash='0' * 63),
                session.argv(evidence_hash='z' * 64),
                session.argv(preflight_hash='0' * 63),
            ):
                self.assertStopped(session, argv)

    def test_each_private_hash_drift_stops_without_receipt(self):
        with Session() as session:
            for key in ('approval_hash', 'evidence_hash', 'preflight_hash'):
                self.assertStopped(session, session.argv(**{key: 'f' * 64}))
            self.assertEqual(list(session.receipts.iterdir()), [])

    def test_each_preflight_binding_field_tamper_stops(self):
        fields = {
            'status': 'other', 'version': 'other',
            'target_environment': 'aws-test', 'phase': STAGES[1],
            'control_plane_commit': 'c' * 40,
            'reviewed_approval_sha256': 'f' * 64,
            'reviewed_evidence_sha256': 'f' * 64,
            'operation_set_sha256': 'f' * 64,
            'private_input_file_count': 3, 'private_path_emitted': True,
            'system_clock_read': False, 'fake_transport_executed': True,
            'kubernetes_transport_executed': True,
            'aws_transport_executed': True,
            'terraform_command_executed': True, 'mutation_executed': True,
            'execution_authorized': True, 'next_action': 'other',
        }
        for key, changed in fields.items():
            with Session() as session:
                value = json.loads(session.preflight.read_bytes())
                value[key] = changed
                session.write(session.preflight, value)
                self.assertStopped(session)

    def test_preflight_extra_missing_future_and_expired_stop(self):
        variants = []
        with Session() as base:
            original = json.loads(base.preflight.read_bytes())
        extra = deepcopy(original); extra['extra'] = True; variants.append(extra)
        missing = deepcopy(original); del missing['phase']; variants.append(missing)
        future = deepcopy(original); future['observed_at_utc'] = '2026-09-15T00:03:00Z'; variants.append(future)
        expired = deepcopy(original); expired['verify_expires_at_utc'] = '2026-09-15T00:01:59Z'; variants.append(expired)
        for value in variants:
            with Session() as session:
                session.write(session.preflight, value)
                self.assertStopped(session)

    def test_approval_environment_phase_main_authority_and_clock_drift_stop(self):
        mutations = (
            ('environment', 'aws-test'), ('phase', STAGES[1]),
            ('control_plane_commit', 'c' * 40), ('execution_authorized', True),
            ('proof_expires_at_utc', '2026-09-15T00:01:30Z'))
        for key, changed in mutations:
            with Session() as session:
                value = approval(STAGES[0]); value[key] = changed
                approval_raw = session.write(session.approval, value)
                session.write(session.preflight, preflight(
                    STAGES[0], approval_raw, session.evidence.read_bytes()))
                self.assertStopped(session)

    def test_evidence_schema_and_state_hash_drift_stop(self):
        variants = []
        extra = evidence(); extra['extra'] = True; variants.append(extra)
        missing = evidence(); del missing['state_after_sha256']; variants.append(missing)
        malformed = evidence(); malformed['state_after_sha256'] = 'x'; variants.append(malformed)
        for value in variants:
            with Session() as session:
                evidence_raw = session.write(session.evidence, value)
                session.write(session.preflight, preflight(
                    STAGES[0], session.approval.read_bytes(), evidence_raw))
                self.assertStopped(session)

    def test_noncanonical_malformed_empty_and_oversized_input_stop(self):
        variants = (b'not-json', json.dumps(approval(STAGES[0]), indent=2).encode(),
                    b'', b'{' + b' ' * (cli.MAX_PRIVATE_INPUT_BYTES + 1))
        for raw in variants:
            with Session() as session:
                session.approval.write_bytes(raw); session.approval.chmod(0o600)
                self.assertStopped(session, session.argv(
                    approval_hash=cli.sha(raw) if raw else '0' * 64))

    def test_private_paths_parent_entries_modes_and_links_are_strict(self):
        with Session() as session:
            session.inputs.chmod(0o755); self.assertStopped(session)
        with Session() as session:
            extra = session.inputs / 'extra'; extra.write_text('x'); extra.chmod(0o600)
            self.assertStopped(session)
        with Session() as session:
            session.preflight.chmod(0o644); self.assertStopped(session)
        with Session() as session:
            session.preflight.unlink(); session.preflight.symlink_to(session.evidence)
            self.assertStopped(session)
        with Session() as session:
            os.link(session.preflight, session.root / 'hardlink')
            self.assertStopped(session)

    def test_paths_must_be_absolute_distinct_and_share_parent(self):
        with Session() as session:
            self.assertStopped(session, session.argv(
                approval_path=Path('approval.json'),
                approval_hash=cli.sha(session.approval.read_bytes())))
        with Session() as session:
            other = session.root / 'other'; other.mkdir(mode=0o700)
            item = other / 'preflight.json'; item.write_bytes(session.preflight.read_bytes()); item.chmod(0o600)
            self.assertStopped(session, session.argv(preflight_path=item))
        with Session() as session:
            self.assertStopped(session, session.argv(preflight_path=session.evidence))

    def test_receipt_directory_mode_relative_symlink_and_pending_stop(self):
        with Session() as session:
            session.receipts.chmod(0o755); self.assertStopped(session)
        with Session() as session:
            self.assertStopped(session, session.argv(receipt_path=Path('receipts')))
        with Session() as session:
            link = session.root / 'link'; link.symlink_to(session.receipts, target_is_directory=True)
            self.assertStopped(session, session.argv(receipt_path=link))
        with Session() as session:
            pending = session.receipts / '000.freeze-applications.intent.json'
            pending.write_bytes(transport.canonical({'pending': True})); pending.chmod(0o600)
            self.assertStopped(session)

    def test_same_phase_cannot_repeat_after_receipt(self):
        with Session() as session:
            self.run_ok(session)
            names = sorted(item.name for item in session.receipts.iterdir())
            self.assertStopped(session)
            self.assertEqual(sorted(item.name for item in session.receipts.iterdir()), names)

    def test_completed_receipt_enables_exact_next_phase(self):
        with Session() as session:
            first = self.run_ok(session)
            session.configure(STAGES[1], first['receipt_sha256'])
            second = self.run_ok(session, phase=STAGES[1])
            self.assertEqual(second['predecessor_receipt_sha256'], first['receipt_sha256'])
            self.assertEqual(len(list(session.receipts.iterdir())), 6)

    def test_wrong_next_predecessor_or_skipped_phase_stops(self):
        with Session() as session:
            first = self.run_ok(session)
            session.configure(STAGES[1], 'f' * 64)
            self.assertStopped(session, session.argv(phase=STAGES[1]))
            session.configure(STAGES[2], first['receipt_sha256'])
            self.assertStopped(session, session.argv(phase=STAGES[2]))

    def test_late_completion_stops_and_writes_no_receipt(self):
        with Session() as session:
            late = datetime(2026, 9, 15, 1, 0, 1, tzinfo=timezone.utc)
            self.assertStopped(session, clocks=(CURRENT, late))
            self.assertEqual(list(session.receipts.iterdir()), [])

    def test_failure_output_is_redacted_and_discloses_no_private_path(self):
        with Session() as session:
            session.approval.write_text('private-sensitive-marker'); session.approval.chmod(0o600)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(cli.main(session.argv(
                    approval_hash=cli.sha(b'private-sensitive-marker'))), 1)
            combined = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn('private-sensitive-marker', combined)
            self.assertNotIn(str(session.root), combined)

    def test_source_uses_only_fixed_fake_and_no_live_backend(self):
        source = SCRIPT.read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add((node.module or '').split('.')[0])
        self.assertFalse(imports & {'subprocess', 'socket', 'boto3', 'requests',
                                    'urllib', 'kubernetes', 'terraform'})
        attributes = {node.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute)}
        self.assertFalse(attributes & {'getenv', 'environ', 'system', 'popen',
                                       'Popen', 'execve', 'spawnv'})
        self.assertIn('DevConformanceTransport(successful_responses(args.phase))', source)
        self.assertNotIn('shell=True', source)

    def test_source_dispatches_execute_only_after_reviewed_preflight(self):
        source = SCRIPT.read_text()
        self.assertIn("entry.dispatch('execute', request, fake)", source)
        self.assertIn('_reviewed_verify(', source)
        self.assertNotIn("add_argument('verify'", source)


if __name__ == '__main__':
    unittest.main(verbosity=2)

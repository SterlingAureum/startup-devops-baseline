#!/usr/bin/env python3
"""Offline integration tests for the complete dev restart chain."""
from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
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


SCRIPT = SCRIPTS / 'exercise-v0.11.9.3.6.7.7.13-dev-local-offline-chain.py'
SPEC = importlib.util.spec_from_file_location('dev_offline_chain_v67713', SCRIPT)
chain = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(chain)

MAIN = 'a' * 40


class Session:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        return self

    def __exit__(self, *unused):
        self.temp.cleanup()

    def argv(self, *, main=MAIN, confirm=chain.CONFIRMATION, root=None):
        return [
            'exercise',
            '--expected-control-plane-commit', main,
            '--private-session-directory', str(root or self.root),
            '--confirm', confirm,
        ]


class OfflineRestartChainTests(unittest.TestCase):
    def run_ok(self, session: Session):
        return chain.run(session.argv())

    @staticmethod
    def json_file(path: Path):
        raw = path.read_bytes()
        value = json.loads(raw)
        return raw, value

    def test_complete_actual_eight_phase_chain(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(result['status'],
                             'aws-dev-local-offline-restart-chain-complete')
            self.assertEqual(result['phase_count'], 8)
            self.assertEqual(result['operation_count'], 23)
            self.assertEqual(result['preflight_process_count'], 8)
            self.assertEqual(result['execute_process_count'], 8)
            self.assertEqual(result['independent_child_process_count'], 16)
            self.assertEqual(result['receipt_triplet_count'], 8)
            self.assertEqual(result['receipt_file_count'], 24)
            self.assertEqual([row['phase'] for row in result['phase_reports']],
                             list(STAGES))

    def test_summary_is_private_canonical_and_matches_return(self):
        with Session() as session:
            result = self.run_ok(session)
            summary = session.root / 'summary.json'
            raw, value = self.json_file(summary)
            self.assertEqual(raw, transport.canonical(result))
            self.assertEqual(value, result)
            self.assertEqual(stat.S_IMODE(summary.stat().st_mode), 0o600)
            self.assertEqual(summary.stat().st_nlink, 1)

    def test_main_emits_one_canonical_json_line(self):
        with Session() as session:
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(chain.main(session.argv()), 0)
            self.assertEqual(error.getvalue(), '')
            raw = output.getvalue().encode()
            self.assertEqual(raw.count(b'\n'), 1)
            self.assertEqual(transport.canonical(json.loads(raw)), raw[:-1])

    def test_each_phase_has_separate_process_inputs_and_outputs(self):
        with Session() as session:
            self.run_ok(session)
            phases = session.root / 'phases'
            self.assertEqual(len(list(phases.iterdir())), len(STAGES))
            for index, phase in enumerate(STAGES):
                root = phases / f'{index:03d}.{phase}'
                verify = root / 'verify-inputs'
                execute = root / 'execute-inputs'
                output = root / 'outputs'
                self.assertEqual({x.name for x in verify.iterdir()},
                                 {'approval.json', 'evidence.json'})
                self.assertEqual({x.name for x in execute.iterdir()},
                                 {'approval.json', 'evidence.json', 'preflight.json'})
                self.assertEqual({x.name for x in output.iterdir()}, {
                    'preflight.stdout', 'preflight.stderr',
                    'execute.stdout', 'execute.stderr'})
                self.assertEqual((output / 'preflight.stderr').read_bytes(), b'')
                self.assertEqual((output / 'execute.stderr').read_bytes(), b'')

    def test_all_artifact_directories_and_files_are_private(self):
        with Session() as session:
            self.run_ok(session)
            for current, directories, files in os.walk(session.root):
                directory = Path(current)
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                for name in files:
                    path = directory / name
                    self.assertTrue(path.is_file() and not path.is_symlink())
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(path.stat().st_nlink, 1)

    def test_receipt_prefix_reloads_after_all_process_restarts(self):
        with Session() as session:
            result = self.run_ok(session)
            first = transport.DurableReceiptStore(
                session.root / 'receipts', main=MAIN).load_prefix()
            second = transport.DurableReceiptStore(
                session.root / 'receipts', main=MAIN).load_prefix()
            self.assertEqual(first, second)
            self.assertEqual(tuple(row['phase'] for row in first), STAGES)
            self.assertEqual(first[-1]['receipt_sha256'],
                             result['final_receipt_sha256'])

    def test_predecessor_and_receipt_chain_are_exact(self):
        with Session() as session:
            result = self.run_ok(session)
            previous = None
            for index, phase in enumerate(STAGES):
                root = session.root / 'phases' / f'{index:03d}.{phase}'
                approval = json.loads(
                    (root / 'verify-inputs/approval.json').read_bytes())
                preflight = json.loads(
                    (root / 'execute-inputs/preflight.json').read_bytes())
                executed = json.loads(
                    (root / 'outputs/execute.stdout').read_bytes())
                self.assertEqual(approval['predecessor_receipt_sha256'], previous)
                self.assertEqual(preflight['predecessor_receipt_sha256'], previous)
                self.assertEqual(executed['predecessor_receipt_sha256'], previous)
                previous = result['phase_reports'][index]['receipt_sha256']

    def test_synthetic_approvals_are_bound_and_never_authorized(self):
        with Session() as session:
            self.run_ok(session)
            for index, phase in enumerate(STAGES):
                root = session.root / 'phases' / f'{index:03d}.{phase}'
                verify_raw = (root / 'verify-inputs/approval.json').read_bytes()
                execute_raw = (root / 'execute-inputs/approval.json').read_bytes()
                self.assertEqual(verify_raw, execute_raw)
                value = json.loads(verify_raw)
                self.assertEqual(value['environment'], 'aws-dev')
                self.assertEqual(value['phase'], phase)
                self.assertEqual(value['control_plane_commit'], MAIN)
                self.assertFalse(value['execution_authorized'])
                self.assertFalse(value['automatic_retry_authorized'])
                self.assertFalse(value['repair_authorized'])
                self.assertEqual(value['operation_set_sha256'],
                                 transport.operation_set_sha256(phase))

    def test_evidence_and_operation_counts_cover_exact_design(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(sum(row['operation_count']
                                 for row in result['phase_reports']), 23)
            prior_state = transport.sha(transport.canonical({
                'fixture': 'dev-local-offline-chain-initial-state',
                'control_plane_commit': MAIN,
            }))
            for index, phase in enumerate(STAGES):
                root = session.root / 'phases' / f'{index:03d}.{phase}'
                approval = json.loads(
                    (root / 'verify-inputs/approval.json').read_bytes())
                first = (root / 'verify-inputs/evidence.json').read_bytes()
                second = (root / 'execute-inputs/evidence.json').read_bytes()
                self.assertEqual(first, second)
                evidence = json.loads(first)
                self.assertEqual(set(evidence), {
                    'journal_completion_sha256',
                    'raw_output_manifest_sha256', 'state_after_sha256'})
                self.assertEqual(approval['state_sha256'], prior_state)
                prior_state = evidence['state_after_sha256']
                self.assertEqual(result['phase_reports'][index]['operation_count'],
                                 len(STAGE_OPERATIONS[phase]))

    def test_success_flags_keep_every_live_effect_false(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertTrue(result['synthetic_fixture_approvals'])
            self.assertTrue(result['synthetic_receipt_chain'])
            self.assertTrue(result['fixed_fake_transport_only'])
            for key in ('live_receipt_acceptable', 'historical_approval_reusable',
                        'private_path_emitted', 'automatic_retry_performed',
                        'automatic_repair_performed',
                        'kubernetes_transport_executed',
                        'aws_transport_executed', 'terraform_command_executed',
                        'mutation_executed', 'live_execution_authorized'):
                self.assertFalse(result[key], key)

    def test_parser_exposes_only_exercise_and_requires_arguments(self):
        parser = chain.parser()
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args([])
            with self.assertRaises(SystemExit):
                parser.parse_args(['verify'])
            with self.assertRaises(SystemExit):
                parser.parse_args(['execute'])

    def test_confirmation_and_main_are_exact(self):
        with Session() as session:
            for argv in (
                session.argv(confirm='wrong'),
                session.argv(main='a' * 39),
                session.argv(main='A' * 40),
            ):
                with self.assertRaises(chain.ChainExerciseStopped):
                    chain.run(argv)
                self.assertEqual(list(session.root.iterdir()), [])

    def test_session_must_be_absolute_owned_empty_0700_directory(self):
        with Session() as session:
            relative = Path('relative-session')
            with self.assertRaises(chain.ChainExerciseStopped):
                chain.run(session.argv(root=relative))
        with Session() as session:
            session.root.chmod(0o755)
            with self.assertRaises(chain.ChainExerciseStopped):
                chain.run(session.argv())
        with Session() as session:
            item = session.root / 'existing'
            item.write_bytes(b'x')
            with self.assertRaises(chain.ChainExerciseStopped):
                chain.run(session.argv())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'target'; target.mkdir(mode=0o700)
            link = Path(folder) / 'link'; link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(chain.ChainExerciseStopped):
                chain.run(['exercise', '--expected-control-plane-commit', MAIN,
                           '--private-session-directory', str(link.absolute()),
                           '--confirm', chain.CONFIRMATION])

    def test_existing_session_cannot_be_replayed(self):
        with Session() as session:
            self.run_ok(session)
            with patch.object(chain.subprocess, 'run') as invoked:
                with self.assertRaises(chain.ChainExerciseStopped):
                    chain.run(session.argv())
                invoked.assert_not_called()

    def test_frozen_preflight_or_execute_byte_drift_stops_before_child(self):
        for attribute in ('PREFLIGHT_SHA256', 'EXECUTE_SHA256'):
            with self.subTest(attribute=attribute), Session() as session:
                with patch.object(chain, attribute, '0' * 64), \
                     patch.object(chain.subprocess, 'run') as invoked:
                    with self.assertRaises(chain.ChainExerciseStopped):
                        chain.run(session.argv())
                    invoked.assert_not_called()

    def test_child_failure_is_preserved_without_retry(self):
        failed = subprocess.CompletedProcess(
            args=['fixture'], returncode=1, stdout=b'', stderr=b'fixture-error\n')
        with Session() as session, \
             patch.object(chain.subprocess, 'run', return_value=failed) as invoked:
            with self.assertRaises(chain.ChainExerciseStopped):
                chain.run(session.argv())
            self.assertEqual(invoked.call_count, 1)
            output = session.root / 'phases/000.freeze-applications/outputs'
            self.assertEqual((output / 'preflight.stderr').read_bytes(),
                             b'fixture-error\n')
            self.assertFalse((session.root / 'summary.json').exists())

    def test_child_timeout_stops_once_without_repair(self):
        with Session() as session, \
             patch.object(chain.subprocess, 'run',
                          side_effect=subprocess.TimeoutExpired('fixture', 30)) as invoked:
            with self.assertRaises(chain.ChainExerciseStopped) as stopped:
                chain.run(session.argv())
            self.assertEqual(invoked.call_count, 1)
            self.assertFalse(stopped.exception.report['automatic_retry_performed'])
            self.assertFalse(stopped.exception.report['automatic_repair_performed'])

    def test_preflight_or_execute_binding_drift_stops_chain(self):
        def fake_child(argv, unused_output, label):
            phase = argv[argv.index('--phase') + 1]
            if label == 'preflight':
                return {
                    'status': 'aws-dev-local-command-preflight-complete',
                    'phase': phase,
                    'predecessor_receipt_sha256': None,
                    'fake_transport_executed': False,
                }
            return {'status': 'wrong'}
        with Session() as session, patch.object(
                chain, '_child', side_effect=fake_child) as invoked:
            with self.assertRaises(chain.ChainExerciseStopped):
                chain.run(session.argv())
            self.assertEqual(invoked.call_count, 2)
            self.assertEqual(list((session.root / 'receipts').iterdir()), [])

    def test_failure_output_is_redacted(self):
        with Session() as session:
            marker = 'private-sensitive-marker'
            (session.root / marker).write_text(marker)
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(chain.main(session.argv()), 1)
            self.assertEqual(output.getvalue(), '')
            self.assertNotIn(marker, error.getvalue())
            self.assertNotIn(str(session.root), error.getvalue())
            self.assertEqual(error.getvalue(),
                'STOP: aws-dev local offline chain failed; preserve the private session and receipts.\n')

    def test_source_uses_closed_local_subprocesses_without_shell_or_environment(self):
        source = SCRIPT.read_text()
        tree = ast.parse(source)
        imports = {node.names[0].name for node in ast.walk(tree)
                   if isinstance(node, ast.Import)}
        imported_from = {node.module for node in ast.walk(tree)
                         if isinstance(node, ast.ImportFrom)}
        self.assertIn('subprocess', imports)
        self.assertFalse({'socket', 'urllib', 'requests', 'boto3', 'botocore'}
                         & (imports | imported_from))
        self.assertNotIn('os.environ', source)
        self.assertNotIn('shell=True', source)
        self.assertNotIn('AWS_ENDPOINT', source)
        self.assertNotIn('terraform ', source)
        self.assertIn('[sys.executable, *argv]', source)
        self.assertIn('stdin=subprocess.DEVNULL', source)

    def test_source_pins_predecessor_entries_and_no_live_backend(self):
        source = SCRIPT.read_text()
        self.assertIn(chain.PREFLIGHT_SHA256, source)
        self.assertIn(chain.EXECUTE_SHA256, source)
        self.assertIn("fixed_fake_transport_only': True", source)
        self.assertIn("live_receipt_acceptable': False", source)
        self.assertNotIn('DevConformanceTransport(', source)
        self.assertNotIn('successful_responses(', source)
        self.assertNotIn('kubectl', source)
        self.assertNotIn('aws ', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)

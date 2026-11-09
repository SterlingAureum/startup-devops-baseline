#!/usr/bin/env python3
"""Offline tests for the .7.7.19 fresh-process chain."""
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

import guarded_dev_injected_transport_protocol_v67716 as protocol
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter_core
from guarded_dev_live_transport_design_v67715 import POSTCONDITIONS
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/exercise-v0.11.9.3.6.7.7.19-dev-local-offline-process-chain.py'
SPEC = importlib.util.spec_from_file_location(
    'dev_local_offline_process_chain_v67719', SCRIPT)
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


class OfflineProcessChainTests(unittest.TestCase):
    @staticmethod
    def run_ok(session: Session):
        return chain.run(session.argv())

    @staticmethod
    def value(path: Path):
        raw = path.read_bytes()
        return raw, json.loads(raw)

    def test_complete_eight_phase_chain_uses_sixteen_processes(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(
                result['status'], 'aws-dev-local-offline-process-chain-complete')
            self.assertEqual(result['phase_count'], 8)
            self.assertEqual(result['operation_count'], 23)
            self.assertEqual(result['verify_process_count'], 8)
            self.assertEqual(result['execute_process_count'], 8)
            self.assertEqual(result['independent_child_process_count'], 16)
            self.assertEqual(result['receipt_triplet_count'], 8)
            self.assertEqual(result['receipt_file_count'], 24)
            self.assertEqual(result['retained_child_output_file_count'], 32)
            self.assertEqual(result['redacted_output_manifest_count'], 8)
            self.assertEqual(
                [row['phase'] for row in result['phase_reports']], list(STAGES))

    def test_summary_is_canonical_private_and_matches_return(self):
        with Session() as session:
            result = self.run_ok(session)
            path = session.root / 'summary.json'
            raw, value = self.value(path)
            self.assertEqual(raw, chain.canonical(result))
            self.assertEqual(value, result)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)

    def test_main_emits_one_canonical_json_line(self):
        with Session() as session:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(chain.main(session.argv()), 0)
            self.assertEqual(stderr.getvalue(), '')
            raw = stdout.getvalue().encode()
            self.assertEqual(raw.count(b'\n'), 1)
            self.assertEqual(chain.canonical(json.loads(raw)), raw[:-1])

    def test_each_phase_has_strict_inputs_and_retained_outputs(self):
        with Session() as session:
            self.run_ok(session)
            phases = session.root / 'phases'
            self.assertEqual(len(list(phases.iterdir())), len(STAGES))
            for index, phase in enumerate(STAGES):
                root = phases / f'{index:03d}.{phase}'
                self.assertEqual({item.name for item in root.iterdir()}, {
                    'bundle-input', 'preflight-input', 'outputs'})
                self.assertEqual(
                    {item.name for item in (root / 'bundle-input').iterdir()},
                    {'bundle.json'})
                self.assertEqual(
                    {item.name for item in (root / 'preflight-input').iterdir()},
                    {'preflight.json'})
                self.assertEqual(
                    {item.name for item in (root / 'outputs').iterdir()}, {
                        'verify.stdout', 'verify.stderr', 'execute.stdout',
                        'execute.stderr', 'redacted-output-manifest.json'})
                self.assertEqual((root / 'outputs/verify.stderr').read_bytes(), b'')
                self.assertEqual((root / 'outputs/execute.stderr').read_bytes(), b'')

    def test_all_artifact_directories_and_files_are_private(self):
        with Session() as session:
            self.run_ok(session)
            for current, unused_directories, files in os.walk(session.root):
                directory = Path(current)
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                for name in files:
                    path = directory / name
                    self.assertTrue(path.is_file() and not path.is_symlink())
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(path.stat().st_nlink, 1)

    def test_output_manifests_bind_retained_bytes(self):
        with Session() as session:
            result = self.run_ok(session)
            for row in result['phase_reports']:
                root = (session.root / 'phases' /
                        f"{row['phase_index']:03d}.{row['phase']}" / 'outputs')
                raw, manifest = self.value(root / 'redacted-output-manifest.json')
                self.assertEqual(chain.sha(raw), row['output_manifest_sha256'])
                for label in ('verify', 'execute'):
                    stdout = (root / (label + '.stdout')).read_bytes()
                    stderr = (root / (label + '.stderr')).read_bytes()
                    self.assertNotIn(str(session.root).encode(), stdout)
                    self.assertNotIn(str(session.root).encode(), stderr)
                    self.assertEqual(
                        manifest[label]['stdout_sha256'], chain.sha(stdout))
                    self.assertEqual(
                        manifest[label]['stderr_sha256'], chain.sha(stderr))
                    self.assertEqual(manifest[label]['stdout_bytes'], len(stdout))
                    self.assertEqual(manifest[label]['stderr_bytes'], len(stderr))
                    self.assertFalse(manifest[label]['private_path_emitted'])

    def test_receipt_prefix_reloads_after_every_process_restart(self):
        with Session() as session:
            result = self.run_ok(session)
            first = adapter_core.RestartSafeOfflineReceiptAdapter(
                session.root / 'receipts', main=MAIN).load_prefix()
            second = adapter_core.RestartSafeOfflineReceiptAdapter(
                session.root / 'receipts', main=MAIN).load_prefix()
            self.assertEqual(first, second)
            self.assertEqual(tuple(row['phase'] for row in first), STAGES)
            self.assertEqual(
                protocol.sha(protocol.canonical(first[-1])),
                result['final_receipt_sha256'])

    def test_bundles_bind_exact_phase_predecessor_and_no_authority(self):
        with Session() as session:
            result = self.run_ok(session)
            predecessor = None
            for row in result['phase_reports']:
                path = (session.root / 'phases' /
                        f"{row['phase_index']:03d}.{row['phase']}" /
                        'bundle-input/bundle.json')
                raw, bundle = self.value(path)
                self.assertEqual(chain.sha(raw), row['bundle_sha256'])
                self.assertEqual(bundle['version'], chain.PREDECESSOR)
                self.assertEqual(bundle['environment'], 'aws-dev')
                self.assertEqual(bundle['phase'], row['phase'])
                self.assertEqual(
                    bundle['verify']['predecessor_receipt_sha256'], predecessor)
                self.assertEqual(
                    bundle['approval']['predecessor_receipt_sha256'], predecessor)
                self.assertFalse(bundle['verify']['execution_authorized'])
                self.assertFalse(bundle['approval']['execution_authorized'])
                self.assertFalse(bundle['approval']['automatic_retry_authorized'])
                self.assertFalse(bundle['approval']['repair_authorized'])
                self.assertFalse(bundle['live_execution_authorized'])
                predecessor = row['receipt_sha256']

    def test_state_chain_and_saved_plan_boundaries_are_exact(self):
        with Session() as session:
            result = self.run_ok(session)
            previous_after = None
            for row in result['phase_reports']:
                root = (session.root / 'phases' /
                        f"{row['phase_index']:03d}.{row['phase']}")
                bundle = json.loads((root / 'bundle-input/bundle.json').read_bytes())
                before = bundle['approval']['state_before_sha256']
                after = bundle['state_after_sha256']
                if previous_after is not None:
                    self.assertEqual(before, previous_after)
                if row['phase'] in chain.TERRAFORM_PHASES:
                    self.assertNotEqual(before, after)
                    self.assertIsInstance(
                        bundle['approval']['saved_plan_bundle'], dict)
                else:
                    self.assertEqual(before, after)
                    self.assertIsNone(bundle['approval']['saved_plan_bundle'])
                self.assertEqual(
                    set(bundle['postconditions']), set(POSTCONDITIONS[row['phase']]))
                self.assertTrue(all(bundle['postconditions'].values()))
                previous_after = after

    def test_process_outputs_bind_bundle_preflight_and_receipt(self):
        with Session() as session:
            result = self.run_ok(session)
            predecessor = None
            for row in result['phase_reports']:
                root = (session.root / 'phases' /
                        f"{row['phase_index']:03d}.{row['phase']}")
                verified = json.loads((root / 'outputs/verify.stdout').read_bytes())
                executed = json.loads((root / 'outputs/execute.stdout').read_bytes())
                preflight_raw = (root / 'preflight-input/preflight.json').read_bytes()
                self.assertEqual(verified, json.loads(preflight_raw))
                self.assertEqual(chain.sha(preflight_raw), row['preflight_sha256'])
                self.assertEqual(
                    verified['reviewed_bundle_sha256'], row['bundle_sha256'])
                self.assertEqual(
                    executed['reviewed_preflight_sha256'], row['preflight_sha256'])
                self.assertEqual(
                    executed['predecessor_receipt_sha256'], predecessor)
                self.assertEqual(executed['receipt_sha256'], row['receipt_sha256'])
                predecessor = row['receipt_sha256']

    def test_operation_counts_cover_exact_closed_design(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertEqual(
                sum(row['operation_count'] for row in result['phase_reports']), 23)
            for row in result['phase_reports']:
                self.assertEqual(
                    row['operation_count'], len(STAGE_OPERATIONS[row['phase']]))

    def test_success_flags_keep_all_live_effects_false(self):
        with Session() as session:
            result = self.run_ok(session)
            self.assertTrue(result['synthetic_bundle_chain'])
            self.assertTrue(result['synthetic_receipt_chain'])
            self.assertTrue(result['fixed_fake_transport_only'])
            for key in (
                'live_receipt_acceptable', 'historical_approval_reusable',
                'private_path_emitted', 'resource_identity_emitted',
                'automatic_retry_performed', 'automatic_repair_performed',
                'kubernetes_transport_executed', 'aws_transport_executed',
                'terraform_command_executed', 'mutation_executed',
                'live_execution_authorized',
            ):
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
                with self.assertRaises(chain.ProcessChainStopped):
                    chain.run(argv)
                self.assertEqual(list(session.root.iterdir()), [])

    def test_session_must_be_absolute_owned_empty_0700_directory(self):
        with Session() as session:
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run(session.argv(root=Path('relative-session')))
        with Session() as session:
            session.root.chmod(0o755)
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run(session.argv())
        with Session() as session:
            (session.root / 'existing').write_bytes(b'x')
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run(session.argv())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'target'
            target.mkdir(mode=0o700)
            link = Path(folder) / 'link'
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run([
                    'exercise', '--expected-control-plane-commit', MAIN,
                    '--private-session-directory', str(link.absolute()),
                    '--confirm', chain.CONFIRMATION])

    def test_completed_session_cannot_be_replayed(self):
        with Session() as session:
            self.run_ok(session)
            with patch.object(chain.subprocess, 'run') as invoked:
                with self.assertRaises(chain.ProcessChainStopped):
                    chain.run(session.argv())
                invoked.assert_not_called()

    def test_frozen_command_byte_drift_stops_before_child(self):
        with Session() as session, \
             patch.object(chain, 'COMMAND_SHA256', '0' * 64), \
             patch.object(chain.subprocess, 'run') as invoked:
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run(session.argv())
            invoked.assert_not_called()

    def test_child_failure_is_retained_without_retry(self):
        failed = subprocess.CompletedProcess(
            args=['fixture'], returncode=1, stdout=b'', stderr=b'fixture-error\n')
        with Session() as session, \
             patch.object(chain.subprocess, 'run', return_value=failed) as invoked:
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run(session.argv())
            self.assertEqual(invoked.call_count, 1)
            outputs = session.root / 'phases/000.freeze-applications/outputs'
            self.assertEqual(
                (outputs / 'verify.stderr').read_bytes(), b'fixture-error\n')
            self.assertFalse((session.root / 'summary.json').exists())

    def test_child_timeout_stops_once_without_retry_or_repair(self):
        with Session() as session, \
             patch.object(
                 chain.subprocess, 'run',
                 side_effect=subprocess.TimeoutExpired('fixture', 30)) as invoked:
            with self.assertRaises(chain.ProcessChainStopped) as stopped:
                chain.run(session.argv())
            self.assertEqual(invoked.call_count, 1)
            self.assertFalse(stopped.exception.report['automatic_retry_performed'])
            self.assertFalse(stopped.exception.report['automatic_repair_performed'])

    def test_verify_or_execute_binding_drift_stops_chain(self):
        verify = {
            'status': 'wrong', 'phase': STAGES[0],
            'receipt_prefix_count': 0,
        }
        manifest = {
            'label': 'verify', 'returncode': 0, 'stdout_bytes': 0,
            'stdout_sha256': '0' * 64, 'stderr_bytes': 0,
            'stderr_sha256': '0' * 64, 'private_path_emitted': False,
        }
        with Session() as session, \
             patch.object(chain, '_child', return_value=(verify, manifest)) as invoked:
            with self.assertRaises(chain.ProcessChainStopped):
                chain.run(session.argv())
            self.assertEqual(invoked.call_count, 1)
            self.assertEqual(list((session.root / 'receipts').iterdir()), [])

    def test_failure_message_does_not_emit_private_path_or_marker(self):
        with Session() as session:
            marker = 'private-sensitive-marker'
            (session.root / marker).write_text(marker)
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(chain.main(session.argv()), 1)
            self.assertEqual(stdout.getvalue(), '')
            self.assertNotIn(marker, stderr.getvalue())
            self.assertNotIn(str(session.root), stderr.getvalue())
            self.assertEqual(stderr.getvalue(),
                'STOP: aws-dev local offline process chain failed; preserve the private session and receipts.\n')

    def test_source_uses_one_closed_python_subprocess_call(self):
        source = SCRIPT.read_text()
        tree = ast.parse(source)
        calls = []
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'run'):
                calls.append(node)
        self.assertEqual(len(calls), 1)
        self.assertIn('[sys.executable, str(COMMAND), *argv]', source)
        self.assertIn('stdin=subprocess.DEVNULL', source)
        self.assertNotIn('shell=True', source)
        self.assertNotIn('os.environ', source)
        self.assertFalse(
            {'socket', 'urllib', 'requests', 'boto3', 'botocore', 'kubernetes'}
            & imports)

    def test_source_adds_no_live_backend_or_external_command(self):
        source = SCRIPT.read_text()
        self.assertNotIn('DevLiveTransport(', source)
        self.assertNotIn('boto3', source)
        self.assertNotIn('kubectl', source)
        self.assertNotIn('terraform ', source)
        self.assertNotIn('aws ', source)
        self.assertIn("'fixed_fake_transport_only': True", source)
        self.assertIn("'live_execution_authorized': False", source)
        self.assertIn("'next_action': 'record-v0.11-scope-and-evidence-closure'", source)


if __name__ == '__main__':
    unittest.main(verbosity=2)

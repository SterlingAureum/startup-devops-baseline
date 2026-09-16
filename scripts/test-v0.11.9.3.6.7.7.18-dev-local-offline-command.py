#!/usr/bin/env python3
"""Offline tests for the restart-safe local command boundary."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import guarded_dev_injected_transport_protocol_v67716 as protocol
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter_core
from guarded_dev_live_transport_design_v67715 import POSTCONDITIONS
from guarded_live_migration_contract_v6778 import STAGES
from guarded_runtime_rules import RuleViolation


SCRIPT = Path(__file__).with_name(
    'execute-v0.11.9.3.6.7.7.18-aws-dev-offline-command.py')
SPEC = importlib.util.spec_from_file_location('dev_local_command_v67718', SCRIPT)
command = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(command)

MAIN = 'a' * 40


def digest(character: str) -> str:
    return character * 64


def utc(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def saved_plan() -> dict:
    return {
        'binary_plan_sha256': digest('1'),
        'json_plan_sha256': digest('2'),
        'text_plan_sha256': digest('3'),
        'plan_gate_sha256': digest('4'),
        'provider_lock_sha256': digest('5'),
        'terraform_version': '1.14.5',
        'terraform_workspace': 'default',
    }


def build_bundle(receipt_directory: Path, phase: str, state_before: str,
                 state_after: str, *, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
        receipt_directory, main=MAIN)
    receipts = adapter.load_prefix()
    predecessor = (protocol.sha(protocol.canonical(receipts[-1]))
                   if receipts else None)
    verify = {
        'schema': protocol.VERIFY_SCHEMA,
        'environment': protocol.ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': MAIN,
        'inputs_sha256': digest('b'),
        'scope_sha256': digest('c'),
        'operation_set_sha256': protocol.operation_set_sha256(phase),
        'proof_sha256': digest('d'),
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
        'environment': protocol.ENVIRONMENT,
        'phase': phase,
        'transport_schema': protocol.TRANSPORT_SCHEMA,
        'control_plane_commit': MAIN,
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
        'saved_plan_bundle': (saved_plan()
                              if phase in ('eks-delete', 'final-delete')
                              else None),
    }
    return {
        'schema': command.BUNDLE_SCHEMA,
        'version': command.VERSION,
        'environment': command.ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': MAIN,
        'verify': verify,
        'approval': approval,
        'state_after_sha256': state_after,
        'postconditions': {name: True for name in POSTCONDITIONS[phase]},
        'simulation_only': True,
        'live_execution_authorized': False,
    }


def private_file(parent: Path, name: str, value: dict) -> Path:
    directory = parent / (name + '-private')
    directory.mkdir(mode=0o700)
    path = directory / name
    path.write_bytes(protocol.canonical(value))
    path.chmod(0o600)
    return path


def verify_args(bundle_path: Path, bundle_hash: str, receipts: Path,
                phase: str) -> list[str]:
    return [
        'verify', '--expected-control-plane-commit', MAIN,
        '--phase', phase, '--bundle-file', str(bundle_path),
        '--expected-bundle-sha256', bundle_hash,
        '--receipt-directory', str(receipts),
        '--confirm', command.VERIFY_CONFIRMATION,
    ]


def execute_args(bundle_path: Path, bundle_hash: str, preflight_path: Path,
                 preflight_hash: str, receipts: Path, phase: str) -> list[str]:
    return [
        'execute', '--expected-control-plane-commit', MAIN,
        '--phase', phase, '--bundle-file', str(bundle_path),
        '--expected-bundle-sha256', bundle_hash,
        '--preflight-file', str(preflight_path),
        '--expected-preflight-sha256', preflight_hash,
        '--receipt-directory', str(receipts),
        '--confirm', command.execute_confirmation(phase),
    ]


class LocalOfflineCommandTests(unittest.TestCase):
    def setUp(self):
        self.owner = tempfile.TemporaryDirectory()
        self.root = Path(self.owner.name)
        self.receipts = self.root / 'receipts'
        self.receipts.mkdir(mode=0o700)

    def tearDown(self):
        self.owner.cleanup()

    def prepare(self, phase: str = STAGES[0], state_before: str | None = None,
                state_after: str | None = None):
        before = state_before or digest('1')
        after = state_after or before
        bundle = build_bundle(self.receipts, phase, before, after)
        bundle_path = private_file(self.root, 'bundle.json', bundle)
        bundle_hash = protocol.sha(protocol.canonical(bundle))
        preflight = command.run(verify_args(
            bundle_path, bundle_hash, self.receipts, phase))
        preflight_path = private_file(self.root, 'preflight.json', preflight)
        preflight_hash = protocol.sha(protocol.canonical(preflight))
        return (bundle, bundle_path, bundle_hash, preflight,
                preflight_path, preflight_hash)

    def assert_stopped(self, callable_):
        with self.assertRaises(command.LocalCommandStopped) as caught:
            callable_()
        report = caught.exception.report
        self.assertFalse(report['automatic_retry_performed'])
        self.assertFalse(report['automatic_repair_performed'])
        self.assertFalse(report['live_execution_authorized'])
        return report

    def test_verify_reads_one_file_and_writes_no_receipt(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        result = command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0]))
        self.assertEqual(result['private_input_file_count'], 1)
        self.assertFalse(result['fixed_fake_executed'])
        self.assertFalse(result['receipt_written'])
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_execute_appends_one_complete_triplet(self):
        values = self.prepare()
        result = command.run(execute_args(
            values[1], values[2], values[4], values[5],
            self.receipts, STAGES[0]))
        self.assertEqual(result['completed_phase_count'], 1)
        self.assertEqual(len(list(self.receipts.iterdir())), 3)

    def test_complete_eight_phase_chain_through_fresh_commands(self):
        state = digest('1')
        reports = []
        for phase in STAGES:
            after = (digest('2') if phase == 'eks-delete' else
                     digest('3') if phase == 'final-delete' else state)
            phase_root = self.root / ('phase-' + str(len(reports)))
            phase_root.mkdir(mode=0o700)
            bundle = build_bundle(self.receipts, phase, state, after)
            bundle_path = private_file(phase_root, 'bundle.json', bundle)
            bundle_hash = protocol.sha(protocol.canonical(bundle))
            preflight = command.run(verify_args(
                bundle_path, bundle_hash, self.receipts, phase))
            preflight_path = private_file(
                phase_root, 'preflight.json', preflight)
            preflight_hash = protocol.sha(protocol.canonical(preflight))
            reports.append(command.run(execute_args(
                bundle_path, bundle_hash, preflight_path, preflight_hash,
                self.receipts, phase)))
            state = after
        self.assertEqual([row['completed_phase_count'] for row in reports],
                         list(range(1, 9)))
        self.assertEqual(len(list(self.receipts.iterdir())), 24)

    def test_execute_report_is_explicitly_non_live(self):
        values = self.prepare()
        result = command.run(execute_args(
            values[1], values[2], values[4], values[5],
            self.receipts, STAGES[0]))
        self.assertFalse(result['receipt_usable_for_live'])
        self.assertFalse(result['aws_transport_executed'])
        self.assertFalse(result['kubernetes_transport_executed'])
        self.assertFalse(result['terraform_command_executed'])
        self.assertFalse(result['mutation_executed'])

    def test_private_paths_are_not_emitted(self):
        values = self.prepare()
        result = command.run(execute_args(
            values[1], values[2], values[4], values[5],
            self.receipts, STAGES[0]))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertFalse(result['private_path_emitted'])

    def test_verify_confirmation_is_exact(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        args = verify_args(path, protocol.sha(protocol.canonical(bundle)),
                           self.receipts, STAGES[0])
        args[-1] = 'wrong'
        self.assert_stopped(lambda: command.run(args))

    def test_execute_confirmation_is_phase_specific(self):
        values = self.prepare()
        args = execute_args(values[1], values[2], values[4], values[5],
                            self.receipts, STAGES[0])
        args[-1] = command.execute_confirmation(STAGES[1])
        self.assert_stopped(lambda: command.run(args))

    def test_verify_rejects_execute_only_arguments(self):
        values = self.prepare()
        args = verify_args(values[1], values[2], self.receipts, STAGES[0])
        args.extend(['--preflight-file', str(values[4]),
                     '--expected-preflight-sha256', values[5]])
        self.assert_stopped(lambda: command.run(args))

    def test_execute_requires_preflight(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        args = verify_args(path, protocol.sha(protocol.canonical(bundle)),
                           self.receipts, STAGES[0])
        args[0] = 'execute'
        args[-1] = command.execute_confirmation(STAGES[0])
        self.assert_stopped(lambda: command.run(args))

    def test_bundle_hash_drift_stops(self):
        values = self.prepare()
        self.assert_stopped(lambda: command.run(verify_args(
            values[1], digest('f'), self.receipts, STAGES[0])))

    def test_preflight_hash_drift_stops(self):
        values = self.prepare()
        self.assert_stopped(lambda: command.run(execute_args(
            values[1], values[2], values[4], digest('f'),
            self.receipts, STAGES[0])))

    def test_preflight_content_tamper_stops(self):
        values = self.prepare()
        changed = dict(values[3])
        changed['receipt_written'] = True
        values[4].write_bytes(protocol.canonical(changed))
        self.assert_stopped(lambda: command.run(execute_args(
            values[1], values[2], values[4],
            protocol.sha(protocol.canonical(changed)),
            self.receipts, STAGES[0])))

    def test_prefix_change_after_preflight_stops(self):
        values = self.prepare()
        adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
            self.receipts, main=MAIN)
        adapter.begin(
            phase=STAGES[0], approval=values[0]['approval'],
            verify=values[0]['verify'], predecessor=None)
        self.assert_stopped(lambda: command.run(execute_args(
            values[1], values[2], values[4], values[5],
            self.receipts, STAGES[0])))

    def test_completed_phase_replay_stops(self):
        values = self.prepare()
        args = execute_args(values[1], values[2], values[4], values[5],
                            self.receipts, STAGES[0])
        command.run(args)
        self.assert_stopped(lambda: command.run(args))

    def test_phase_skip_stops_without_attempt(self):
        bundle = build_bundle(self.receipts, STAGES[1], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        report = self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[1])))
        self.assertFalse(report['attempt_created'])

    def test_main_drift_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        bundle['control_plane_commit'] = 'b' * 40
        path = private_file(self.root, 'bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_environment_drift_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        bundle['environment'] = 'aws-test'
        path = private_file(self.root, 'bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_expired_verify_stops(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        bundle = build_bundle(
            self.receipts, STAGES[0], digest('1'), digest('1'), now=old)
        path = private_file(self.root, 'bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_false_postcondition_stops_before_attempt(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        bundle['postconditions'][next(iter(bundle['postconditions']))] = False
        path = private_file(self.root, 'bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))
        self.assertEqual(list(self.receipts.iterdir()), [])

    def test_nonterraform_state_change_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('2'))
        path = private_file(self.root, 'bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_terraform_state_must_change(self):
        for phase in STAGES[:5]:
            bundle = build_bundle(self.receipts, phase, digest('1'), digest('1'))
            root = self.root / ('prefix-' + str(STAGES.index(phase)))
            root.mkdir(mode=0o700)
            path = private_file(root, 'bundle.json', bundle)
            preflight = command.run(verify_args(
                path, protocol.sha(protocol.canonical(bundle)),
                self.receipts, phase))
            preflight_path = private_file(root, 'preflight.json', preflight)
            command.run(execute_args(
                path, protocol.sha(protocol.canonical(bundle)), preflight_path,
                protocol.sha(protocol.canonical(preflight)), self.receipts, phase))
        bundle = build_bundle(
            self.receipts, 'eks-delete', digest('1'), digest('1'))
        path = private_file(self.root, 'eks-bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, 'eks-delete')))

    def test_receipt_directory_mode_drift_stops(self):
        bundle = build_bundle(
            self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        self.receipts.chmod(0o755)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_relative_bundle_path_stops(self):
        with self.assertRaises(RuleViolation):
            command.StrictCanonicalPrivateFile(Path('bundle.json'))

    def test_private_directory_mode_drift_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        path.parent.chmod(0o755)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_private_file_mode_drift_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        path.chmod(0o644)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_private_symlink_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        target = path.parent / 'target'
        path.rename(target)
        path.symlink_to(target)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_private_hardlink_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        os.link(path, path.parent / 'other')
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_unexpected_private_sibling_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        (path.parent / 'other').write_bytes(b'x')
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_noncanonical_private_json_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        path.write_text(json.dumps(bundle, indent=2))
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(path.read_bytes()), self.receipts, STAGES[0])))

    def test_preflight_private_scope_is_independent(self):
        values = self.prepare()
        (values[4].parent / 'unexpected').write_bytes(b'x')
        self.assert_stopped(lambda: command.run(execute_args(
            values[1], values[2], values[4], values[5],
            self.receipts, STAGES[0])))

    def test_pending_receipt_blocks_verify(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
            self.receipts, main=MAIN)
        adapter.begin(phase=STAGES[0], approval=bundle['approval'],
                      verify=bundle['verify'], predecessor=None)
        path = private_file(self.root, 'bundle.json', bundle)
        self.assert_stopped(lambda: command.run(verify_args(
            path, protocol.sha(protocol.canonical(bundle)),
            self.receipts, STAGES[0])))

    def test_wrong_main_argument_stops(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        args = verify_args(path, protocol.sha(protocol.canonical(bundle)),
                           self.receipts, STAGES[0])
        args[2] = 'bad'
        self.assert_stopped(lambda: command.run(args))

    def test_cli_verify_emits_canonical_json(self):
        bundle = build_bundle(self.receipts, STAGES[0], digest('1'), digest('1'))
        path = private_file(self.root, 'bundle.json', bundle)
        result = subprocess.run(
            [sys.executable, str(SCRIPT)] + verify_args(
                path, protocol.sha(protocol.canonical(bundle)),
                self.receipts, STAGES[0]),
            capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        value = json.loads(result.stdout)
        self.assertEqual(protocol.canonical(value) + b'\n', result.stdout)

    def test_cli_execute_appends_restart_safe_triplet(self):
        values = self.prepare()
        result = subprocess.run(
            [sys.executable, str(SCRIPT)] + execute_args(
                values[1], values[2], values[4], values[5],
                self.receipts, STAGES[0]),
            capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        value = json.loads(result.stdout)
        self.assertEqual(value['completed_phase_count'], 1)
        self.assertEqual(len(list(self.receipts.iterdir())), 3)

    def test_cli_failure_is_redacted(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), 'verify'],
            capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn(str(self.root).encode(), result.stderr)
        self.assertIn(b'STOP:', result.stderr)

    def test_command_ast_has_no_backend_sdk_or_subprocess(self):
        tree = ast.parse(SCRIPT.read_text())
        forbidden = {'subprocess', 'socket', 'boto3', 'botocore', 'kubernetes'}
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {'exec', 'eval', '__import__'})
        self.assertFalse(forbidden & imports)

    def test_command_does_not_import_legacy_receipt_store(self):
        text = SCRIPT.read_text()
        self.assertNotIn('DurableReceiptStore', text)
        self.assertNotIn('guarded_dev_transport_conformance_v6779', text)

    def test_closed_confirmation_rejects_unknown_phase(self):
        with self.assertRaises(RuleViolation):
            command.execute_confirmation('unknown')


if __name__ == '__main__':
    unittest.main(verbosity=2)

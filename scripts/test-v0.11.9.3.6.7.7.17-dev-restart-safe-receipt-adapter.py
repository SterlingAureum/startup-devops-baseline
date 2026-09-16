#!/usr/bin/env python3
"""Offline tests for the restart-safe receipt adapter composition."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest

import guarded_dev_injected_transport_protocol_v67716 as protocol
import guarded_dev_restart_safe_receipt_adapter_v67717 as adapter_core
from guarded_dev_live_transport_design_v67715 import POSTCONDITIONS
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS
from guarded_runtime_rules import RuleViolation


MAIN = 'a' * 40
NOW = '2026-09-16T01:00:00Z'
END = '2026-09-16T03:00:00Z'


def digest(character: str) -> str:
    return character * 64


def plan_bundle() -> dict:
    return {
        'binary_plan_sha256': digest('1'),
        'json_plan_sha256': digest('2'),
        'text_plan_sha256': digest('3'),
        'plan_gate_sha256': digest('4'),
        'provider_lock_sha256': digest('5'),
        'terraform_version': '1.14.5',
        'terraform_workspace': 'default',
    }


def inputs(adapter: adapter_core.RestartSafeOfflineReceiptAdapter, phase: str,
           state_before: str):
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
        'verified_at_utc': '2026-09-16T00:55:00Z',
        'verify_expires_at_utc': '2026-09-16T01:10:00Z',
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
        'start_utc': '2026-09-16T00:50:00Z',
        'end_utc': END,
        'budget_limit_usd': '36.00',
        'execution_authorized': False,
        'automatic_retry_authorized': False,
        'repair_authorized': False,
        'simulation_only': True,
        'saved_plan_bundle': (plan_bundle()
                              if phase in ('eks-delete', 'final-delete')
                              else None),
    }
    conditions = {name: True for name in POSTCONDITIONS[phase]}
    return verify, approval, conditions


def make_session():
    owner = tempfile.TemporaryDirectory()
    path = Path(owner.name) / 'receipts'
    path.mkdir(mode=0o700)
    return owner, path


def run_phase(path: Path, phase: str, state_before: str, state_after: str,
              *, fault=None, transport=None, verify_update=None,
              approval_update=None, conditions_update=None):
    adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
        path, main=MAIN, fault=fault)
    verify, approval, conditions = inputs(adapter, phase, state_before)
    if verify_update:
        verify_update(verify)
        approval['reviewed_verify_sha256'] = protocol.sha(protocol.canonical(verify))
    if approval_update:
        approval_update(approval)
    if conditions_update:
        conditions_update(conditions)
    return adapter_core.run_restart_safe_fixed_fake_phase(
        adapter=adapter, phase=phase, verify=verify, approval=approval,
        current_utc=NOW, completed_at_utc='2026-09-16T01:01:00Z',
        state_after_sha256=state_after, postconditions=conditions,
        transport=transport or protocol.FixedFakeTransport())


def complete_chain(path: Path):
    reports = []
    state = digest('1')
    for phase in STAGES:
        state_after = state
        if phase == 'eks-delete':
            state_after = digest('2')
        if phase == 'final-delete':
            state_after = digest('3')
        reports.append(run_phase(path, phase, state, state_after))
        state = state_after
    return reports


class RestartSafeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.owner, self.path = make_session()

    def tearDown(self):
        self.owner.cleanup()

    def assert_stopped(self, callable_):
        with self.assertRaises(adapter_core.AdapterStopped) as caught:
            callable_()
        self.assertFalse(caught.exception.report['automatic_retry_performed'])
        self.assertFalse(caught.exception.report['automatic_repair_performed'])
        self.assertFalse(caught.exception.report['live_execution_authorized'])
        return caught.exception.report

    def test_complete_eight_phase_restart_chain(self):
        reports = complete_chain(self.path)
        self.assertEqual([row['completed_phase_count'] for row in reports],
                         list(range(1, 9)))

    def test_each_phase_uses_a_new_adapter_instance(self):
        state = digest('1')
        for index, phase in enumerate(STAGES):
            adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
                self.path, main=MAIN)
            self.assertEqual(len(adapter.load_prefix()), index)
            state_after = (digest('2') if phase == 'eks-delete' else
                           digest('3') if phase == 'final-delete' else state)
            run_phase(self.path, phase, state, state_after)
            state = state_after

    def test_complete_chain_has_twenty_four_private_files(self):
        complete_chain(self.path)
        entries = list(self.path.iterdir())
        self.assertEqual(len(entries), 24)
        self.assertTrue(all((item.stat().st_mode & 0o777) == 0o600
                            for item in entries))

    def test_exact_twenty_three_fake_calls_across_chain(self):
        total = 0
        state = digest('1')
        for phase in STAGES:
            transport = protocol.FixedFakeTransport()
            state_after = (digest('2') if phase == 'eks-delete' else
                           digest('3') if phase == 'final-delete' else state)
            run_phase(self.path, phase, state, state_after, transport=transport)
            total += len(transport.calls)
            state = state_after
        self.assertEqual(total, 23)

    def test_receipt_prefix_survives_reopen(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        reopened = adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN)
        self.assertEqual(len(reopened.load_prefix()), 1)

    def test_attempt_is_written_before_first_fake_call(self):
        operation = STAGE_OPERATIONS[STAGES[0]][0]
        transport = protocol.FixedFakeTransport(fail_at=operation)
        report = self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'),
            transport=transport))
        self.assertTrue(report['attempt_created'])
        self.assertTrue((self.path / adapter_core.RestartSafeOfflineReceiptAdapter._names(
            0, STAGES[0])[0]).exists())

    def test_fake_failure_leaves_pending_attempt_and_blocks_restart(self):
        transport = protocol.FixedFakeTransport(
            fail_at=STAGE_OPERATIONS[STAGES[0]][1])
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'),
            transport=transport))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_failed_fake_is_not_retried(self):
        transport = protocol.FixedFakeTransport(
            fail_at=STAGE_OPERATIONS[STAGES[0]][1])
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'),
            transport=transport))
        self.assertEqual(len(transport.calls), 2)

    def test_completed_phase_cannot_replay(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1')))

    def test_phase_skip_is_rejected_before_attempt(self):
        report = self.assert_stopped(lambda: run_phase(
            self.path, STAGES[1], digest('1'), digest('1')))
        self.assertFalse(report['attempt_created'])
        self.assertEqual(list(self.path.iterdir()), [])

    def test_state_continuity_required_after_restart(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[1], digest('f'), digest('f')))

    def test_prevalidation_failure_writes_no_attempt(self):
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'),
            approval_update=lambda row: row.update(execution_authorized=True)))
        self.assertEqual(list(self.path.iterdir()), [])

    def test_verify_expiry_writes_no_attempt(self):
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'),
            verify_update=lambda row: row.update(verify_expires_at_utc=NOW)))
        self.assertEqual(list(self.path.iterdir()), [])

    def test_false_postcondition_preserves_pending_attempt(self):
        report = self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'),
            conditions_update=lambda row: row.update({next(iter(row)): False})))
        self.assertTrue(report['attempt_created'])

    def test_nonterraform_state_change_preserves_pending_attempt(self):
        report = self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('f')))
        self.assertTrue(report['attempt_created'])

    def test_directory_must_be_absolute(self):
        with self.assertRaises(RuleViolation):
            adapter_core.RestartSafeOfflineReceiptAdapter(
                Path('relative'), main=MAIN)

    def test_directory_must_be_mode_0700(self):
        self.path.chmod(0o755)
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN))

    def test_symlink_directory_rejected(self):
        link = Path(self.owner.name) / 'link'
        link.symlink_to(self.path, target_is_directory=True)
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            link, main=MAIN))

    def test_wrong_main_rejected(self):
        with self.assertRaises(RuleViolation):
            adapter_core.RestartSafeOfflineReceiptAdapter(
                self.path, main='bad')

    def test_custom_fault_subclass_rejected(self):
        class Other(adapter_core.AdapterFaultInjector):
            pass
        with self.assertRaises(RuleViolation):
            adapter_core.RestartSafeOfflineReceiptAdapter(
                self.path, main=MAIN,
                fault=Other(adapter_core.FAULT_POINTS[0]))

    def test_custom_adapter_subclass_rejected(self):
        class Other(adapter_core.RestartSafeOfflineReceiptAdapter):
            pass
        value = Other(self.path, main=MAIN)
        self.assert_stopped(lambda: adapter_core.run_restart_safe_fixed_fake_phase(
            adapter=value, phase=STAGES[0], verify={}, approval={},
            current_utc=NOW, completed_at_utc=NOW,
            state_after_sha256=digest('1'), postconditions={},
            transport=protocol.FixedFakeTransport()))

    def test_custom_transport_subclass_rejected(self):
        class Other(protocol.FixedFakeTransport):
            pass
        adapter = adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN)
        verify, approval, conditions = inputs(adapter, STAGES[0], digest('1'))
        with self.assertRaises(RuleViolation):
            adapter_core.run_restart_safe_fixed_fake_phase(
                adapter=adapter, phase=STAGES[0], verify=verify,
                approval=approval, current_utc=NOW,
                completed_at_utc=NOW, state_after_sha256=digest('1'),
                postconditions=conditions, transport=Other())

    def test_unknown_directory_entry_rejected(self):
        (self.path / 'unexpected').write_bytes(b'x')
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_stored_file_mode_drift_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        name = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])[1]
        (self.path / name).chmod(0o644)
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_stored_symlink_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        names = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])
        target = self.path / names[1]
        target.unlink()
        target.symlink_to(self.path / names[0])
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_stored_hardlink_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        names = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])
        os.link(self.path / names[1], self.path / 'hardlink')
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_attempt_tamper_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        name = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])[0]
        value = json.loads((self.path / name).read_bytes())
        value['phase'] = STAGES[1]
        (self.path / name).write_bytes(protocol.canonical(value))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_receipt_tamper_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        name = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])[1]
        value = json.loads((self.path / name).read_bytes())
        value['automatic_retry_performed'] = True
        (self.path / name).write_bytes(protocol.canonical(value))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_completion_tamper_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        name = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])[2]
        value = json.loads((self.path / name).read_bytes())
        value['receipt_sha256'] = digest('f')
        (self.path / name).write_bytes(protocol.canonical(value))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_noncanonical_receipt_rejected(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        name = adapter_core.RestartSafeOfflineReceiptAdapter._names(0, STAGES[0])[1]
        value = json.loads((self.path / name).read_bytes())
        (self.path / name).write_bytes(json.dumps(value, indent=2).encode())
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_main_drift_rejects_existing_prefix(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main='b' * 40).load_prefix())

    def test_receipt_schema_cannot_be_upgraded_to_live(self):
        run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        receipt = adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix()[0]
        self.assertEqual(receipt['schema'], protocol.CONFORMANCE_RECEIPT_SCHEMA)
        self.assertTrue(receipt['simulation_only'])
        self.assertFalse(receipt['live_execution_authorized'])

    def test_attempt_open_fault_blocks_session(self):
        fault = adapter_core.AdapterFaultInjector('after-attempt-open')
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'), fault=fault))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_attempt_fsync_fault_blocks_session(self):
        fault = adapter_core.AdapterFaultInjector('after-attempt-file-fsync')
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'), fault=fault))
        self.assertTrue(fault.triggered)

    def test_receipt_write_fault_blocks_session(self):
        fault = adapter_core.AdapterFaultInjector('after-receipt-write')
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'), fault=fault))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_completion_write_fault_blocks_session(self):
        fault = adapter_core.AdapterFaultInjector('after-completion-write')
        self.assert_stopped(lambda: run_phase(
            self.path, STAGES[0], digest('1'), digest('1'), fault=fault))
        self.assert_stopped(lambda: adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix())

    def test_fault_points_are_closed(self):
        with self.assertRaises(RuleViolation):
            adapter_core.AdapterFaultInjector('unknown')

    def test_success_report_has_fail_closed_flags(self):
        report = run_phase(self.path, STAGES[0], digest('1'), digest('1'))
        self.assertTrue(report['durable_offline_receipt_appended'])
        self.assertFalse(report['receipt_usable_for_live'])
        self.assertFalse(report['automatic_retry_performed'])
        self.assertFalse(report['live_transport_executed'])
        self.assertFalse(report['live_execution_authorized'])

    def test_terraform_transition_persists_across_restart(self):
        state = digest('1')
        for phase in STAGES[:6]:
            state_after = digest('2') if phase == 'eks-delete' else state
            run_phase(self.path, phase, state, state_after)
            state = state_after
        prefix = adapter_core.RestartSafeOfflineReceiptAdapter(
            self.path, main=MAIN).load_prefix()
        self.assertEqual(prefix[-1]['state_after_sha256'], digest('2'))

    def test_no_live_receipt_or_backend_name_in_file_names(self):
        complete_chain(self.path)
        for item in self.path.iterdir():
            self.assertNotIn('live', item.name)
            self.assertNotIn('backend', item.name)

    def test_core_ast_has_no_cloud_sdk_subprocess_or_command_entry(self):
        tree = ast.parse(Path(adapter_core.__file__).read_text())
        forbidden = {'subprocess', 'socket', 'boto3', 'botocore', 'kubernetes'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(forbidden & {item.name for item in node.names})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {'exec', 'eval', '__import__'})


if __name__ == '__main__':
    unittest.main(verbosity=2)

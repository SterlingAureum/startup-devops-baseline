#!/usr/bin/env python3
"""Offline tests for dev transport conformance and durable receipts."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import guarded_dev_transport_conformance_v6779 as core
from guarded_live_migration_contract_v6778 import STAGES, STAGE_OPERATIONS


MAIN = 'a' * 40
STATE = 'b' * 64


def digest(char: str) -> str:
    return char * 64


def make_approval(phase, predecessor=None, environment='aws-dev'):
    return {
        'schema': 'guarded-live-phase-approval-v1',
        'transport_version': 'guarded-live-transport-v1',
        'mode': 'live',
        'environment': environment,
        'phase': phase,
        'control_plane_commit': MAIN,
        'approval_text_sha256': digest('1'),
        'inputs_sha256': digest('2'),
        'scope_sha256': digest('3'),
        'state_sha256': STATE,
        'predecessor_receipt_sha256': predecessor,
        'operation_set_sha256': core.operation_set_sha256(phase),
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


def evidence():
    return {
        'journal_completion_sha256': digest('5'),
        'raw_output_manifest_sha256': digest('6'),
        'state_after_sha256': STATE,
    }


class StoreDirectory:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.path.chmod(0o700)
        return self.path

    def __exit__(self, *unused):
        self.temp.cleanup()


def run_phase(directory, phase, predecessor=None, *, responses=None,
              fail_at='', fault=None):
    store = core.DurableReceiptStore(directory, main=MAIN, fault=fault)
    harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
    transport = core.DevConformanceTransport(
        responses if responses is not None else core.successful_responses(phase),
        fail_at=fail_at)
    report = harness.run_phase(
        phase=phase, approval=make_approval(phase, predecessor),
        current_utc='2026-09-15T00:02:00Z',
        completed_at_utc='2026-09-15T00:03:00Z',
        evidence=evidence(), transport=transport)
    return report, transport


class DevConformanceTests(unittest.TestCase):
    def assertStopped(self, function, *args, **kwargs):
        with self.assertRaises((core.RuleViolation, core.ReceiptStoreStopped,
                                core.ConformanceStopped)):
            function(*args, **kwargs)

    def test_empty_private_store_loads(self):
        with StoreDirectory() as directory:
            store = core.DurableReceiptStore(directory, main=MAIN)
            self.assertEqual(store.load_prefix(), ())

    def test_store_requires_absolute_owned_0700_directory(self):
        with StoreDirectory() as directory:
            directory.chmod(0o755)
            self.assertStopped(core.DurableReceiptStore, directory, main=MAIN)
        self.assertStopped(core.DurableReceiptStore, Path('relative'), main=MAIN)

    def test_store_rejects_symlink_directory(self):
        with StoreDirectory() as parent:
            real = parent / 'real'
            real.mkdir(mode=0o700)
            link = parent / 'link'
            link.symlink_to(real, target_is_directory=True)
            self.assertStopped(core.DurableReceiptStore, link, main=MAIN)

    def test_operation_sets_cover_exact_design(self):
        self.assertEqual(tuple(STAGE_OPERATIONS), STAGES)
        self.assertEqual(sum(len(value) for value in STAGE_OPERATIONS.values()), 23)
        for phase in STAGES:
            self.assertEqual(len(core.operation_set_sha256(phase)), 64)

    def test_first_dev_phase_appends_durable_receipt(self):
        with StoreDirectory() as directory:
            report, transport = run_phase(directory, STAGES[0])
            self.assertEqual(report['status'],
                             'dev-offline-transport-conformance-complete')
            self.assertTrue(report['durable_receipt_appended'])
            self.assertFalse(report['live_execution_authorized'])
            self.assertEqual([row[0] for row in transport.calls],
                             list(STAGE_OPERATIONS[STAGES[0]]))

    def test_receipt_triplet_names_modes_and_canonical_bytes(self):
        with StoreDirectory() as directory:
            run_phase(directory, STAGES[0])
            names = sorted(item.name for item in directory.iterdir())
            self.assertEqual(names, sorted(core.DurableReceiptStore._names(0, STAGES[0])))
            for path in directory.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                value = json.loads(path.read_bytes())
                self.assertEqual(path.read_bytes(), core.canonical(value))

    def test_restart_recovers_completed_receipt(self):
        with StoreDirectory() as directory:
            first, unused = run_phase(directory, STAGES[0])
            reopened = core.DurableReceiptStore(directory, main=MAIN)
            rows = reopened.load_prefix()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['receipt_sha256'], first['receipt_sha256'])

    def test_eight_stage_restart_chain_completes(self):
        with StoreDirectory() as directory:
            predecessor = None
            total_calls = 0
            for phase in STAGES:
                report, transport = run_phase(directory, phase, predecessor)
                predecessor = report['receipt_sha256']
                total_calls += len(transport.calls)
            rows = core.DurableReceiptStore(directory, main=MAIN).load_prefix()
            self.assertEqual(tuple(row['phase'] for row in rows), STAGES)
            self.assertEqual(len(rows), 8)
            self.assertEqual(total_calls, 23)

    def test_full_chain_rejects_another_append(self):
        with StoreDirectory() as directory:
            predecessor = None
            for phase in STAGES:
                report, unused = run_phase(directory, phase, predecessor)
                predecessor = report['receipt_sha256']
            store = core.DurableReceiptStore(directory, main=MAIN)
            self.assertStopped(store.append, {})

    def test_receipt_predecessor_is_null_then_exact_hash(self):
        with StoreDirectory() as directory:
            first, unused = run_phase(directory, STAGES[0])
            second, unused = run_phase(directory, STAGES[1], first['receipt_sha256'])
            rows = core.DurableReceiptStore(directory, main=MAIN).load_prefix()
            self.assertIsNone(rows[0]['predecessor_receipt_sha256'])
            self.assertEqual(rows[1]['predecessor_receipt_sha256'],
                             first['receipt_sha256'])
            self.assertEqual(rows[1]['receipt_sha256'], second['receipt_sha256'])

    def test_wrong_phase_or_predecessor_stops_before_transport(self):
        with StoreDirectory() as directory:
            store = core.DurableReceiptStore(directory, main=MAIN)
            harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
            for phase, predecessor in ((STAGES[1], None),
                                       (STAGES[0], digest('9'))):
                transport = core.DevConformanceTransport(
                    core.successful_responses(phase))
                self.assertStopped(
                    harness.run_phase, phase=phase,
                    approval=make_approval(phase, predecessor),
                    current_utc='2026-09-15T00:02:00Z',
                    completed_at_utc='2026-09-15T00:03:00Z',
                    evidence=evidence(), transport=transport)
                self.assertEqual(transport.calls, [])

    def test_test_and_prod_approval_targets_are_rejected(self):
        with StoreDirectory() as directory:
            for environment in ('aws-test', 'aws-prod'):
                store = core.DurableReceiptStore(directory, main=MAIN)
                harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
                transport = core.DevConformanceTransport(
                    core.successful_responses(STAGES[0]))
                self.assertStopped(
                    harness.run_phase, phase=STAGES[0],
                    approval=make_approval(STAGES[0], environment=environment),
                    current_utc='2026-09-15T00:02:00Z',
                    completed_at_utc='2026-09-15T00:03:00Z',
                    evidence=evidence(), transport=transport)
                self.assertEqual(transport.calls, [])

    def test_transport_and_store_subclasses_are_rejected(self):
        class OtherTransport(core.DevConformanceTransport):
            pass

        class OtherStore(core.DurableReceiptStore):
            pass

        with StoreDirectory() as directory:
            other_store = OtherStore(directory, main=MAIN)
            self.assertStopped(core.DevTransportConformanceHarness,
                               main=MAIN, store=other_store)
            store = core.DurableReceiptStore(directory, main=MAIN)
            harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
            transport = OtherTransport(core.successful_responses(STAGES[0]))
            self.assertStopped(
                harness.run_phase, phase=STAGES[0],
                approval=make_approval(STAGES[0]),
                current_utc='2026-09-15T00:02:00Z',
                completed_at_utc='2026-09-15T00:03:00Z',
                evidence=evidence(), transport=transport)

    def test_transport_failure_creates_no_receipt_files(self):
        with StoreDirectory() as directory:
            phase = STAGES[0]
            store = core.DurableReceiptStore(directory, main=MAIN)
            harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
            transport = core.DevConformanceTransport(
                core.successful_responses(phase),
                fail_at=STAGE_OPERATIONS[phase][1])
            self.assertStopped(
                harness.run_phase, phase=phase, approval=make_approval(phase),
                current_utc='2026-09-15T00:02:00Z',
                completed_at_utc='2026-09-15T00:03:00Z',
                evidence=evidence(), transport=transport)
            self.assertEqual(list(directory.iterdir()), [])

    def test_missing_malformed_or_wrong_response_stops(self):
        phase = STAGES[0]
        variants = ({}, {**core.successful_responses(phase),
                         STAGE_OPERATIONS[phase][0]: b'not-json'})
        wrong = core.successful_responses(phase)
        value = json.loads(wrong[STAGE_OPERATIONS[phase][0]])
        value['mutation_acknowledged'] = True
        wrong[STAGE_OPERATIONS[phase][0]] = core.canonical(value)
        for responses in (*variants, wrong):
            with StoreDirectory() as directory:
                self.assertStopped(run_phase, directory, phase,
                                   responses=responses)
                self.assertEqual(list(directory.iterdir()), [])

    def test_request_envelope_is_redacted_and_exact(self):
        with StoreDirectory() as directory:
            unused, transport = run_phase(directory, STAGES[0])
            for operation, raw in transport.calls:
                value = json.loads(raw)
                self.assertEqual(value['operation'], operation)
                self.assertEqual(value['environment'], 'aws-dev')
                self.assertTrue(value['simulation_only'])
                self.assertEqual(set(value), {
                    'schema', 'environment', 'phase', 'operation',
                    'approval_sha256', 'predecessor_receipt_sha256',
                    'simulation_only'})

    def test_operation_set_approval_drift_stops_before_call(self):
        with StoreDirectory() as directory:
            phase = STAGES[0]
            value = make_approval(phase)
            value['operation_set_sha256'] = digest('f')
            store = core.DurableReceiptStore(directory, main=MAIN)
            harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
            transport = core.DevConformanceTransport(core.successful_responses(phase))
            self.assertStopped(
                harness.run_phase, phase=phase, approval=value,
                current_utc='2026-09-15T00:02:00Z',
                completed_at_utc='2026-09-15T00:03:00Z',
                evidence=evidence(), transport=transport)
            self.assertEqual(transport.calls, [])

    def test_approval_clock_main_and_authority_drift_stop_before_call(self):
        changes = (
            ('control_plane_commit', 'c' * 40),
            ('execution_authorized', True),
            ('repair_authorized', True),
            ('proof_expires_at_utc', '2026-09-15T00:17:00Z'),
        )
        for key, changed in changes:
            with StoreDirectory() as directory:
                phase = STAGES[0]
                value = make_approval(phase)
                value[key] = changed
                store = core.DurableReceiptStore(directory, main=MAIN)
                harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
                transport = core.DevConformanceTransport(
                    core.successful_responses(phase))
                self.assertStopped(
                    harness.run_phase, phase=phase, approval=value,
                    current_utc='2026-09-15T00:02:00Z',
                    completed_at_utc='2026-09-15T00:03:00Z',
                    evidence=evidence(), transport=transport)
                self.assertEqual(transport.calls, [])

    def test_completion_clock_and_evidence_schema_are_exact(self):
        variants = (
            ('2026-09-14T23:59:59Z', evidence()),
            ('2026-09-15T01:00:01Z', evidence()),
            ('2026-09-15T00:03:00Z', {'state_after_sha256': STATE}),
            ('2026-09-15T00:03:00Z', {**evidence(),
                                      'state_after_sha256': 'bad'}),
        )
        for completed, values in variants:
            with StoreDirectory() as directory:
                phase = STAGES[0]
                store = core.DurableReceiptStore(directory, main=MAIN)
                harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
                transport = core.DevConformanceTransport(
                    core.successful_responses(phase))
                self.assertStopped(
                    harness.run_phase, phase=phase,
                    approval=make_approval(phase),
                    current_utc='2026-09-15T00:02:00Z',
                    completed_at_utc=completed, evidence=values,
                    transport=transport)

    def test_each_precompletion_fault_leaves_store_blocked(self):
        blocked_points = [point for point in core.FAULT_POINTS
                          if not point.startswith('after-completion-')]
        for point in blocked_points:
            with StoreDirectory() as directory:
                fault = core.ReceiptFaultInjector(point)
                self.assertStopped(run_phase, directory, STAGES[0], fault=fault)
                self.assertTrue(fault.triggered)
                self.assertStopped(
                    core.DurableReceiptStore(directory, main=MAIN).load_prefix)

    def test_completion_open_failure_leaves_pending_store(self):
        with StoreDirectory() as directory:
            fault = core.ReceiptFaultInjector('after-completion-open')
            self.assertStopped(run_phase, directory, STAGES[0], fault=fault)
            self.assertStopped(
                core.DurableReceiptStore(directory, main=MAIN).load_prefix)

    def test_complete_marker_bytes_allow_restart_recovery(self):
        for point in ('after-completion-write', 'after-completion-file-fsync',
                      'after-completion-dir-fsync'):
            with StoreDirectory() as directory:
                fault = core.ReceiptFaultInjector(point)
                self.assertStopped(run_phase, directory, STAGES[0], fault=fault)
                rows = core.DurableReceiptStore(directory, main=MAIN).load_prefix()
                self.assertEqual(len(rows), 1)

    def test_pending_store_blocks_transport_before_repeat(self):
        with StoreDirectory() as directory:
            fault = core.ReceiptFaultInjector('after-receipt-write')
            self.assertStopped(run_phase, directory, STAGES[0], fault=fault)
            transport = core.DevConformanceTransport(
                core.successful_responses(STAGES[0]))
            store = core.DurableReceiptStore(directory, main=MAIN)
            harness = core.DevTransportConformanceHarness(main=MAIN, store=store)
            self.assertStopped(
                harness.run_phase, phase=STAGES[0],
                approval=make_approval(STAGES[0]),
                current_utc='2026-09-15T00:02:00Z',
                completed_at_utc='2026-09-15T00:03:00Z',
                evidence=evidence(), transport=transport)
            self.assertEqual(transport.calls, [])

    def test_unexpected_entry_and_prefix_gap_are_rejected(self):
        with StoreDirectory() as directory:
            (directory / 'foreign').write_text('x')
            (directory / 'foreign').chmod(0o600)
            self.assertStopped(
                core.DurableReceiptStore(directory, main=MAIN).load_prefix)
        with StoreDirectory() as directory:
            names = core.DurableReceiptStore._names(1, STAGES[1])
            for name in names:
                (directory / name).write_text('{}')
                (directory / name).chmod(0o600)
            self.assertStopped(
                core.DurableReceiptStore(directory, main=MAIN).load_prefix)

    def test_stored_file_mode_symlink_and_hardlink_are_rejected(self):
        mutations = ('mode', 'symlink', 'hardlink')
        for mutation in mutations:
            with StoreDirectory() as directory:
                run_phase(directory, STAGES[0])
                receipt_name = core.DurableReceiptStore._names(0, STAGES[0])[1]
                target = directory / receipt_name
                if mutation == 'mode':
                    target.chmod(0o644)
                elif mutation == 'symlink':
                    saved = directory / 'saved'
                    target.rename(saved)
                    target.symlink_to(saved)
                else:
                    os.link(target, directory / 'second-link')
                self.assertStopped(
                    core.DurableReceiptStore(directory, main=MAIN).load_prefix)

    def test_intent_receipt_and_completion_tamper_are_rejected(self):
        for offset in range(3):
            with StoreDirectory() as directory:
                run_phase(directory, STAGES[0])
                path = directory / core.DurableReceiptStore._names(0, STAGES[0])[offset]
                value = json.loads(path.read_text())
                value['tampered'] = True
                path.write_bytes(core.canonical(value))
                self.assertStopped(
                    core.DurableReceiptStore(directory, main=MAIN).load_prefix)

    def test_noncanonical_receipt_bytes_are_rejected(self):
        with StoreDirectory() as directory:
            run_phase(directory, STAGES[0])
            path = directory / core.DurableReceiptStore._names(0, STAGES[0])[1]
            value = json.loads(path.read_text())
            path.write_text(json.dumps(value, indent=2))
            self.assertStopped(
                core.DurableReceiptStore(directory, main=MAIN).load_prefix)

    def test_main_drift_rejects_existing_receipt(self):
        with StoreDirectory() as directory:
            run_phase(directory, STAGES[0])
            self.assertStopped(
                core.DurableReceiptStore(directory, main='c' * 40).load_prefix)

    def test_receipt_fault_injector_type_and_point_are_closed(self):
        self.assertStopped(core.ReceiptFaultInjector, 'unknown')
        with StoreDirectory() as directory:
            self.assertStopped(core.DurableReceiptStore, directory, main=MAIN,
                               fault=object())

    def test_response_builder_rejects_unknown_operation(self):
        self.assertStopped(core.successful_responses_for_operation, 'unknown')
        self.assertStopped(core.successful_responses, 'unknown')

    def test_public_failure_reports_contain_no_private_bytes(self):
        store_error = core.ReceiptStoreStopped('receipt-write').report
        transport_error = core.ConformanceStopped('transport-response', True).report
        raw = json.dumps([store_error, transport_error], sort_keys=True)
        self.assertNotIn('/tmp/', raw)
        self.assertNotIn('/home/', raw)
        self.assertNotIn(MAIN, raw)
        self.assertFalse(store_error['live_execution_authorized'])
        self.assertFalse(transport_error['live_execution_authorized'])

    def test_no_live_transport_or_secret_value_effect_claims(self):
        with StoreDirectory() as directory:
            report, unused = run_phase(directory, STAGES[0])
            self.assertTrue(report['simulation_only'])
            self.assertFalse(report['kubernetes_transport_executed'])
            self.assertFalse(report['aws_transport_executed'])
            self.assertFalse(report['terraform_command_executed'])

    def test_core_ast_has_no_subprocess_network_sdk_or_cli(self):
        path = ROOT / 'scripts' / 'guarded_dev_transport_conformance_v6779.py'
        tree = ast.parse(path.read_text())
        forbidden_modules = {'subprocess', 'socket', 'boto3', 'botocore',
                             'requests', 'urllib', 'http', 'shlex'}
        forbidden_calls = {'exec', 'eval', '__import__', 'print'}
        forbidden_attributes = {'run', 'Popen', 'system', 'getenv', 'putenv'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(item.name.split('.')[0] not in forbidden_modules
                                    for item in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or '').split('.')[0], forbidden_modules)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden_calls)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, forbidden_attributes)


if __name__ == '__main__':
    unittest.main(verbosity=2)

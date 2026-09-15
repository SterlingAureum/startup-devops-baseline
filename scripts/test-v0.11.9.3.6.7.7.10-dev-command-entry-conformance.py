#!/usr/bin/env python3
"""Offline tests for the dev command-entry conformance layer."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import guarded_dev_command_entry_conformance_v67710 as core
import guarded_dev_transport_conformance_v6779 as transport_core
from guarded_live_migration_contract_v6778 import STAGES


MAIN = 'a' * 40
STATE = 'b' * 64


def digest(char: str) -> str:
    return char * 64


def approval(phase: str, predecessor=None, *, environment='aws-dev') -> dict:
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
        'operation_set_sha256': transport_core.operation_set_sha256(phase),
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


def payloads(phase: str, predecessor=None, reviewed=None,
             approval_value=None, evidence_value=None):
    approval_raw = core.canonical(
        approval_value if approval_value is not None
        else approval(phase, predecessor))
    evidence_raw = core.canonical(
        evidence_value if evidence_value is not None else evidence())
    values = {'approval': approval_raw, 'evidence': evidence_raw}
    if reviewed is not None:
        values['reviewed-verify'] = core.canonical(reviewed)
    return values


def request(command: str, phase: str, values: dict, *, reviewed=None,
            confirmation=None, main=MAIN):
    return core.command_request(
        command=command, phase=phase, main=main,
        approval_sha256=core.sha(values['approval']),
        evidence_sha256=core.sha(values['evidence']),
        reviewed_verify_sha256=(
            core.sha(values['reviewed-verify']) if reviewed is not None else None),
        confirmation=(confirmation if confirmation is not None else
                      (core.CONFIRMATIONS[phase] if command == 'execute' else None)))


class StoreDirectory:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.path.chmod(0o700)
        return self.path

    def __exit__(self, *unused):
        self.temp.cleanup()


def entry(directory: Path, readings: tuple[str, ...], values: dict,
          *, main=MAIN):
    clock = core.FrozenClock(readings)
    reader = core.FixedPrivateInputReader(values)
    store = transport_core.DurableReceiptStore(directory, main=main)
    return core.DevOfflineCommandEntry(
        main=main, clock=clock, reader=reader, store=store), clock, reader


def run_verify(directory: Path, phase: str, predecessor=None,
               *, values=None, now='2026-09-15T00:02:00Z'):
    values = values or payloads(phase, predecessor)
    command, clock, reader = entry(directory, (now,), values)
    req = request('verify', phase, values)
    return command.dispatch('verify', req), clock, reader, values


def run_execute(directory: Path, phase: str, predecessor, reviewed: dict,
                *, values=None, current='2026-09-15T00:03:00Z',
                completed='2026-09-15T00:04:00Z', transport=None):
    values = values or payloads(phase, predecessor, reviewed)
    command, clock, reader = entry(directory, (current, completed), values)
    req = request('execute', phase, values, reviewed=reviewed)
    fake = transport or transport_core.DevConformanceTransport(
        transport_core.successful_responses(phase))
    return command.dispatch('execute', req, fake), clock, reader, values, fake


class CommandEntryTests(unittest.TestCase):
    def assertStopped(self, function, *args, **kwargs):
        with self.assertRaises(core.CommandEntryStopped):
            function(*args, **kwargs)

    def test_verify_request_schema_is_exact_and_redacted(self):
        values = payloads(STAGES[0])
        value = request('verify', STAGES[0], values)
        self.assertEqual(set(value), {
            'schema', 'version', 'command', 'environment', 'phase',
            'control_plane_commit', 'approval_input', 'approval_sha256',
            'evidence_input', 'evidence_sha256', 'reviewed_verify_input',
            'reviewed_verify_sha256', 'confirmation', 'simulation_only'})
        self.assertIsNone(value['confirmation'])
        self.assertNotIn('/', json.dumps(value))

    def test_verify_success_reads_two_inputs_and_writes_no_receipt(self):
        with StoreDirectory() as directory:
            report, clock, reader, unused = run_verify(directory, STAGES[0])
            self.assertEqual(report['status'],
                             'dev-offline-command-inputs-verified')
            self.assertEqual(reader.reads, ['approval', 'evidence'])
            self.assertEqual(clock.read_count, 1)
            self.assertEqual(list(directory.iterdir()), [])

    def test_verify_report_schema_and_effect_flags_are_exact(self):
        with StoreDirectory() as directory:
            report, unused, unused, unused = run_verify(directory, STAGES[0])
            self.assertEqual(set(report), {
                'schema', 'status', 'version', 'environment', 'phase',
                'control_plane_commit', 'reviewed_approval_sha256',
                'reviewed_evidence_sha256', 'operation_set_sha256',
                'predecessor_receipt_sha256', 'verified_at_utc',
                'verify_expires_at_utc', 'end_utc', 'execution_authorized',
                'simulation_only', 'system_clock_read',
                'live_private_evidence_read', 'live_transport_executed'})
            self.assertFalse(report['execution_authorized'])
            self.assertFalse(report['system_clock_read'])
            self.assertFalse(report['live_private_evidence_read'])

    def test_execute_requires_separate_reviewed_verify_and_confirmation(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            report, clock, reader, unused, fake = run_execute(
                directory, STAGES[0], None, reviewed)
            self.assertEqual(report['status'],
                             'dev-offline-command-execution-complete')
            self.assertEqual(reader.reads,
                             ['approval', 'evidence', 'reviewed-verify'])
            self.assertEqual(clock.read_count, 2)
            self.assertTrue(fake.calls)

    def test_execute_appends_one_durable_receipt_triplet(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            report, unused, unused, unused, unused = run_execute(
                directory, STAGES[0], None, reviewed)
            rows = transport_core.DurableReceiptStore(
                directory, main=MAIN).load_prefix()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['receipt_sha256'], report['receipt_sha256'])
            self.assertEqual(len(list(directory.iterdir())), 3)

    def test_complete_eight_stage_command_chain(self):
        with StoreDirectory() as directory:
            predecessor = None
            calls = 0
            for phase in STAGES:
                reviewed, unused, unused, unused = run_verify(
                    directory, phase, predecessor)
                report, unused, unused, unused, fake = run_execute(
                    directory, phase, predecessor, reviewed)
                predecessor = report['receipt_sha256']
                calls += len(fake.calls)
            rows = transport_core.DurableReceiptStore(
                directory, main=MAIN).load_prefix()
            self.assertEqual(tuple(row['phase'] for row in rows), STAGES)
            self.assertEqual(len(rows), 8)
            self.assertEqual(calls, 23)

    def test_each_stage_uses_fresh_clock_reader_and_store_instance(self):
        with StoreDirectory() as directory:
            predecessor = None
            for index, phase in enumerate(STAGES):
                reviewed, verify_clock, verify_reader, unused = run_verify(
                    directory, phase, predecessor)
                report, execute_clock, execute_reader, unused, unused = run_execute(
                    directory, phase, predecessor, reviewed)
                self.assertEqual(verify_clock.read_count, 1)
                self.assertEqual(execute_clock.read_count, 2)
                self.assertEqual(len(verify_reader.reads), 2)
                self.assertEqual(len(execute_reader.reads), 3)
                self.assertEqual(report['phase'], STAGES[index])
                predecessor = report['receipt_sha256']

    def test_first_and_later_predecessors_are_exact(self):
        with StoreDirectory() as directory:
            first, unused, unused, unused = run_verify(directory, STAGES[0])
            self.assertIsNone(first['predecessor_receipt_sha256'])
            executed, unused, unused, unused, unused = run_execute(
                directory, STAGES[0], None, first)
            second, unused, unused, unused = run_verify(
                directory, STAGES[1], executed['receipt_sha256'])
            self.assertEqual(second['predecessor_receipt_sha256'],
                             executed['receipt_sha256'])

    def test_unknown_and_mismatched_commands_stop(self):
        with StoreDirectory() as directory:
            values = payloads(STAGES[0])
            command, unused, unused = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            req = request('verify', STAGES[0], values)
            self.assertStopped(command.dispatch, 'unknown', req)
            self.assertStopped(command.dispatch, 'execute', req)

    def test_verify_rejects_transport_argument(self):
        with StoreDirectory() as directory:
            values = payloads(STAGES[0])
            command, unused, unused = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            fake = transport_core.DevConformanceTransport(
                transport_core.successful_responses(STAGES[0]))
            self.assertStopped(command.dispatch, 'verify',
                               request('verify', STAGES[0], values), fake)
            self.assertEqual(fake.calls, [])

    def test_request_extra_missing_and_version_drift_stop(self):
        changes = ('extra', 'missing', 'version')
        for change in changes:
            with StoreDirectory() as directory:
                values = payloads(STAGES[0])
                req = request('verify', STAGES[0], values)
                if change == 'extra':
                    req['extra'] = True
                elif change == 'missing':
                    del req['simulation_only']
                else:
                    req['version'] = 'v0.11.9.3.6.7.7.9'
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify', req)

    def test_request_environment_main_phase_and_simulation_drift_stop(self):
        changes = {
            'environment': 'aws-test',
            'control_plane_commit': 'c' * 40,
            'phase': 'unknown',
            'simulation_only': False,
        }
        for key, changed in changes.items():
            with StoreDirectory() as directory:
                values = payloads(STAGES[0])
                req = request('verify', STAGES[0], values)
                req[key] = changed
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify', req)

    def test_test_and_prod_approval_targets_stop(self):
        for environment in ('aws-test', 'aws-prod'):
            with StoreDirectory() as directory:
                values = payloads(
                    STAGES[0], approval_value=approval(
                        STAGES[0], environment=environment))
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify',
                                   request('verify', STAGES[0], values))

    def test_approval_and_evidence_hash_drift_stop(self):
        for key in ('approval_sha256', 'evidence_sha256'):
            with StoreDirectory() as directory:
                values = payloads(STAGES[0])
                req = request('verify', STAGES[0], values)
                req[key] = digest('f')
                command, unused, reader = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify', req)
                self.assertLessEqual(len(reader.reads), 2)

    def test_malformed_and_noncanonical_private_inputs_stop(self):
        variants = (b'not-json', json.dumps(approval(STAGES[0]), indent=2).encode())
        for raw in variants:
            with StoreDirectory() as directory:
                values = payloads(STAGES[0])
                values['approval'] = raw
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify',
                                   request('verify', STAGES[0], values))

    def test_private_input_names_missing_and_extra_are_rejected(self):
        self.assertRaises(core.RuleViolation,
                          core.FixedPrivateInputReader, {'path': b'{}'})
        with StoreDirectory() as directory:
            values = payloads(STAGES[0])
            values['reviewed-verify'] = b'{}'
            command, unused, unused = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            self.assertStopped(command.dispatch, 'verify',
                               request('verify', STAGES[0], values))

    def test_frozen_clock_returns_exact_readings_without_host_clock(self):
        clock = core.FrozenClock(('2026-09-15T00:02:00Z',
                                  '2026-09-15T00:03:00Z'))
        self.assertEqual(clock.now(), '2026-09-15T00:02:00Z')
        self.assertEqual(clock.now(), '2026-09-15T00:03:00Z')
        with self.assertRaises(core.RuleViolation):
            clock.now()

    def test_clock_schema_and_exhaustion_stop_command(self):
        with self.assertRaises(core.RuleViolation):
            core.FrozenClock(())
        with StoreDirectory() as directory:
            values = payloads(STAGES[0])
            command, unused, unused = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            reviewed = command.dispatch(
                'verify', request('verify', STAGES[0], values))
            execute_values = payloads(STAGES[0], reviewed=reviewed)
            execute, unused, unused = entry(
                directory, ('2026-09-15T00:03:00Z',), execute_values)
            req = request('execute', STAGES[0], execute_values,
                          reviewed=reviewed)
            fake = transport_core.DevConformanceTransport(
                transport_core.successful_responses(STAGES[0]))
            self.assertStopped(execute.dispatch, 'execute', req, fake)
            self.assertEqual(fake.calls, [])

    def test_dependency_subclasses_are_rejected(self):
        class OtherClock(core.FrozenClock):
            pass
        class OtherReader(core.FixedPrivateInputReader):
            pass
        class OtherStore(transport_core.DurableReceiptStore):
            pass
        with StoreDirectory() as directory:
            values = payloads(STAGES[0])
            normal_clock = core.FrozenClock(('2026-09-15T00:02:00Z',))
            normal_reader = core.FixedPrivateInputReader(values)
            normal_store = transport_core.DurableReceiptStore(directory, main=MAIN)
            with self.assertRaises(core.RuleViolation):
                core.DevOfflineCommandEntry(
                    main=MAIN,
                    clock=OtherClock(('2026-09-15T00:02:00Z',)),
                    reader=normal_reader, store=normal_store)
            with self.assertRaises(core.RuleViolation):
                core.DevOfflineCommandEntry(
                    main=MAIN, clock=normal_clock,
                    reader=OtherReader(values), store=normal_store)
            with self.assertRaises(core.RuleViolation):
                core.DevOfflineCommandEntry(
                    main=MAIN, clock=normal_clock,
                    reader=normal_reader,
                    store=OtherStore(directory, main=MAIN))

    def test_approval_main_authority_clock_and_budget_drift_stop(self):
        variants = (
            ('control_plane_commit', 'c' * 40),
            ('execution_authorized', True),
            ('automatic_retry_authorized', True),
            ('repair_authorized', True),
            ('proof_expires_at_utc', '2026-09-15T00:17:00Z'),
            ('total_budget_limit_usd', '0.00'),
        )
        for key, changed in variants:
            with StoreDirectory() as directory:
                value = approval(STAGES[0])
                value[key] = changed
                values = payloads(STAGES[0], approval_value=value)
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify',
                                   request('verify', STAGES[0], values))

    def test_operation_set_drift_stops_verify(self):
        with StoreDirectory() as directory:
            value = approval(STAGES[0])
            value['operation_set_sha256'] = digest('f')
            values = payloads(STAGES[0], approval_value=value)
            command, unused, unused = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            self.assertStopped(command.dispatch, 'verify',
                               request('verify', STAGES[0], values))

    def test_evidence_schema_and_hashes_are_exact(self):
        variants = ({'state_after_sha256': STATE},
                    {**evidence(), 'extra': digest('7')},
                    {**evidence(), 'state_after_sha256': 'bad'})
        for value in variants:
            with StoreDirectory() as directory:
                values = payloads(STAGES[0], evidence_value=value)
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:02:00Z',), values)
                self.assertStopped(command.dispatch, 'verify',
                                   request('verify', STAGES[0], values))

    def test_wrong_or_missing_confirmation_stops_before_transport(self):
        for confirmation in ('', 'execute-reviewed-aws-test-freeze-applications'):
            with StoreDirectory() as directory:
                reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
                values = payloads(STAGES[0], reviewed=reviewed)
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:03:00Z',
                                '2026-09-15T00:04:00Z'), values)
                req = request('execute', STAGES[0], values,
                              reviewed=reviewed, confirmation=confirmation)
                fake = transport_core.DevConformanceTransport(
                    transport_core.successful_responses(STAGES[0]))
                self.assertStopped(command.dispatch, 'execute', req, fake)
                self.assertEqual(fake.calls, [])

    def test_reviewed_verify_hash_tamper_stops(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            values = payloads(STAGES[0], reviewed=reviewed)
            req = request('execute', STAGES[0], values, reviewed=reviewed)
            req['reviewed_verify_sha256'] = digest('f')
            command, unused, unused = entry(
                directory, ('2026-09-15T00:03:00Z',
                            '2026-09-15T00:04:00Z'), values)
            fake = transport_core.DevConformanceTransport(
                transport_core.successful_responses(STAGES[0]))
            self.assertStopped(command.dispatch, 'execute', req, fake)
            self.assertEqual(fake.calls, [])

    def test_each_reviewed_verify_field_tamper_stops(self):
        changes = {
            'phase': STAGES[1],
            'control_plane_commit': 'c' * 40,
            'reviewed_evidence_sha256': digest('f'),
            'operation_set_sha256': digest('f'),
            'execution_authorized': True,
            'live_transport_executed': True,
        }
        for key, changed in changes.items():
            with StoreDirectory() as directory:
                reviewed, unused, unused, unused = run_verify(
                    directory, STAGES[0])
                altered = deepcopy(reviewed)
                altered[key] = changed
                values = payloads(STAGES[0], reviewed=altered)
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:03:00Z',
                                '2026-09-15T00:04:00Z'), values)
                req = request('execute', STAGES[0], values, reviewed=altered)
                fake = transport_core.DevConformanceTransport(
                    transport_core.successful_responses(STAGES[0]))
                self.assertStopped(command.dispatch, 'execute', req, fake)
                self.assertEqual(fake.calls, [])

    def test_expired_or_future_reviewed_verify_stops(self):
        cases = ('2026-09-15T00:17:00Z', '2026-09-15T00:00:30Z')
        for current in cases:
            with StoreDirectory() as directory:
                reviewed, unused, unused, unused = run_verify(
                    directory, STAGES[0])
                values = payloads(STAGES[0], reviewed=reviewed)
                command, unused, unused = entry(
                    directory, (current, '2026-09-15T00:18:00Z'), values)
                req = request('execute', STAGES[0], values, reviewed=reviewed)
                fake = transport_core.DevConformanceTransport(
                    transport_core.successful_responses(STAGES[0]))
                self.assertStopped(command.dispatch, 'execute', req, fake)
                self.assertEqual(fake.calls, [])

    def test_execute_rereads_approval_and_evidence_bytes(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, original = run_verify(directory, STAGES[0])
            changed = dict(original)
            changed['evidence'] = core.canonical({
                **evidence(), 'state_after_sha256': digest('9')})
            changed['reviewed-verify'] = core.canonical(reviewed)
            command, unused, unused = entry(
                directory, ('2026-09-15T00:03:00Z',
                            '2026-09-15T00:04:00Z'), changed)
            req = request('execute', STAGES[0], changed, reviewed=reviewed)
            fake = transport_core.DevConformanceTransport(
                transport_core.successful_responses(STAGES[0]))
            self.assertStopped(command.dispatch, 'execute', req, fake)
            self.assertEqual(fake.calls, [])

    def test_prefix_change_after_verify_stops_execute(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            transport_core.DevTransportConformanceHarness(
                main=MAIN,
                store=transport_core.DurableReceiptStore(
                    directory, main=MAIN)).run_phase(
                        phase=STAGES[0], approval=approval(STAGES[0]),
                        current_utc='2026-09-15T00:03:00Z',
                        completed_at_utc='2026-09-15T00:04:00Z',
                        evidence=evidence(),
                        transport=transport_core.DevConformanceTransport(
                            transport_core.successful_responses(STAGES[0])))
            values = payloads(STAGES[0], reviewed=reviewed)
            command, unused, unused = entry(
                directory, ('2026-09-15T00:05:00Z',
                            '2026-09-15T00:06:00Z'), values)
            fake = transport_core.DevConformanceTransport(
                transport_core.successful_responses(STAGES[0]))
            self.assertStopped(command.dispatch, 'execute',
                               request('execute', STAGES[0], values,
                                       reviewed=reviewed), fake)
            self.assertEqual(fake.calls, [])

    def test_transport_type_failure_and_response_failure_stop(self):
        class OtherTransport(transport_core.DevConformanceTransport):
            pass
        for kind in ('subclass', 'failure'):
            with StoreDirectory() as directory:
                reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
                values = payloads(STAGES[0], reviewed=reviewed)
                command, unused, unused = entry(
                    directory, ('2026-09-15T00:03:00Z',
                                '2026-09-15T00:04:00Z'), values)
                fake = (OtherTransport(
                    transport_core.successful_responses(STAGES[0]))
                        if kind == 'subclass' else
                        transport_core.DevConformanceTransport(
                            transport_core.successful_responses(STAGES[0]),
                            fail_at='kubernetes-observe-applications'))
                self.assertStopped(command.dispatch, 'execute',
                                   request('execute', STAGES[0], values,
                                           reviewed=reviewed), fake)
                self.assertEqual(list(directory.iterdir()), [])

    def test_completion_outside_approval_window_stops_without_receipt(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            values = payloads(STAGES[0], reviewed=reviewed)
            command, unused, unused = entry(
                directory, ('2026-09-15T00:03:00Z',
                            '2026-09-15T01:00:01Z'), values)
            fake = transport_core.DevConformanceTransport(
                transport_core.successful_responses(STAGES[0]))
            self.assertStopped(command.dispatch, 'execute',
                               request('execute', STAGES[0], values,
                                       reviewed=reviewed), fake)
            self.assertEqual(list(directory.iterdir()), [])

    def test_pending_receipt_store_blocks_verify_before_private_reads(self):
        with StoreDirectory() as directory:
            (directory / '000.freeze-applications.intent.json').write_bytes(b'{}')
            (directory / '000.freeze-applications.intent.json').chmod(0o600)
            values = payloads(STAGES[0])
            command, unused, reader = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            self.assertStopped(command.dispatch, 'verify',
                               request('verify', STAGES[0], values))
            self.assertEqual(reader.reads, [])

    def test_completed_receipt_recovers_for_next_command(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            first, unused, unused, unused, unused = run_execute(
                directory, STAGES[0], None, reviewed)
            second, unused, unused, unused = run_verify(
                directory, STAGES[1], first['receipt_sha256'])
            self.assertEqual(second['phase'], STAGES[1])

    def test_public_failure_report_contains_no_private_bytes(self):
        report = core.CommandEntryStopped(
            'verify-gate', private_reads=2).report
        raw = json.dumps(report, sort_keys=True)
        self.assertNotIn('/home/', raw)
        self.assertNotIn('/tmp/', raw)
        self.assertNotIn(MAIN, raw)
        self.assertFalse(report['live_execution_authorized'])
        self.assertFalse(report['automatic_retry_performed'])

    def test_success_reports_never_claim_live_effects(self):
        with StoreDirectory() as directory:
            reviewed, unused, unused, unused = run_verify(directory, STAGES[0])
            report, unused, unused, unused, unused = run_execute(
                directory, STAGES[0], None, reviewed)
            for key in ('system_clock_read', 'live_private_evidence_read',
                        'kubernetes_transport_executed',
                        'aws_transport_executed',
                        'terraform_command_executed',
                        'live_execution_authorized'):
                self.assertFalse(report[key])

    def test_confirmation_set_is_exactly_eight_dev_values(self):
        self.assertEqual(tuple(core.CONFIRMATIONS), STAGES)
        self.assertEqual(len(set(core.CONFIRMATIONS.values())), 8)
        self.assertTrue(all(value.startswith('execute-reviewed-aws-dev-')
                            for value in core.CONFIRMATIONS.values()))

    def test_command_builder_rejects_no_live_target_but_request_gate_does(self):
        values = payloads(STAGES[0])
        req = request('verify', STAGES[0], values)
        req['environment'] = 'aws-prod'
        with StoreDirectory() as directory:
            command, unused, unused = entry(
                directory, ('2026-09-15T00:02:00Z',), values)
            self.assertStopped(command.dispatch, 'verify', req)

    def test_core_ast_has_no_cli_environment_clock_file_or_network_reader(self):
        path = ROOT / 'scripts' / 'guarded_dev_command_entry_conformance_v67710.py'
        tree = ast.parse(path.read_text())
        forbidden_modules = {
            'argparse', 'os', 'pathlib', 'subprocess', 'socket', 'boto3',
            'botocore', 'requests', 'urllib', 'http', 'shlex', 'time',
            'datetime',
        }
        forbidden_calls = {'exec', 'eval', '__import__', 'open', 'print'}
        forbidden_attributes = {
            'run', 'Popen', 'system', 'getenv', 'putenv', 'environ',
            'now', 'utcnow', 'read_text', 'read_bytes', 'write_text',
            'write_bytes',
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(item.name.split('.')[0] not in forbidden_modules
                                    for item in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or '').split('.')[0],
                                 forbidden_modules)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden_calls)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'now':
                    self.assertIsInstance(node.func.value, ast.Attribute)
                    self.assertEqual(node.func.value.attr, 'clock')
                else:
                    self.assertNotIn(node.func.attr, forbidden_attributes)


if __name__ == '__main__':
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Offline tests for the injected dev transport protocol and fixed fake."""
from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path

import guarded_dev_injected_transport_protocol_v67716 as core
from guarded_dev_live_transport_design_v67715 import (
    COMMON_BINDINGS,
    POSTCONDITIONS,
    expected_design,
)
from guarded_live_migration_contract_v6778 import (
    INCIDENT_ONLY_POWERS,
    STAGES,
    STAGE_OPERATIONS,
)
from guarded_runtime_rules import RuleViolation


MAIN = 'a' * 40
NOW = '2026-09-16T01:00:00Z'
END = '2026-09-16T03:00:00Z'
STATE = '1' * 64


def digest(character: str) -> str:
    return character * 64


def prefix_for(phase: str) -> tuple[dict, ...]:
    rows = []
    previous = None
    for index, prior in enumerate(STAGES[:STAGES.index(phase)]):
        row = {
            'schema': core.CONFORMANCE_RECEIPT_SCHEMA,
            'live_receipt_schema_candidate': core.RECEIPT_SCHEMA,
            'version': core.VERSION,
            'environment': core.ENVIRONMENT,
            'phase': prior,
            'phase_index': index,
            'status': 'terminal-success',
            'control_plane_commit': MAIN,
            'approval_sha256': digest('2'),
            'reviewed_verify_sha256': digest('3'),
            'inputs_sha256': digest('4'),
            'scope_sha256': digest('5'),
            'operation_set_sha256': core.operation_set_sha256(prior),
            'proof_sha256': digest('6'),
            'predecessor_receipt_sha256': previous,
            'journal_sha256': digest('7'),
            'postcondition_set_sha256': core.sha(
                core.canonical(list(POSTCONDITIONS[prior]))),
            'state_before_sha256': digest('8'),
            'state_after_sha256': digest('9'),
            'completed_at_utc': NOW,
            'attempt_count': 1,
            'automatic_retry_performed': False,
            'automatic_repair_performed': False,
            'simulation_only': True,
            'live_execution_authorized': False,
        }
        rows.append(row)
        previous = core.sha(core.canonical(row))
    return tuple(rows)


def verify_for(phase: str, predecessor: str | None, state: str = STATE) -> dict:
    return {
        'schema': core.VERIFY_SCHEMA,
        'environment': core.ENVIRONMENT,
        'phase': phase,
        'control_plane_commit': MAIN,
        'inputs_sha256': digest('b'),
        'scope_sha256': digest('c'),
        'operation_set_sha256': core.operation_set_sha256(phase),
        'proof_sha256': digest('d'),
        'state_before_sha256': state,
        'predecessor_receipt_sha256': predecessor,
        'verified_at_utc': '2026-09-16T00:55:00Z',
        'verify_expires_at_utc': '2026-09-16T01:10:00Z',
        'simulation_only': True,
        'execution_authorized': False,
    }


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


def approval_for(phase: str, verify: dict, predecessor: str | None) -> dict:
    terraform = phase in ('eks-delete', 'final-delete')
    return {
        'schema': core.APPROVAL_SCHEMA,
        'mode': 'offline-conformance',
        'environment': core.ENVIRONMENT,
        'phase': phase,
        'transport_schema': core.TRANSPORT_SCHEMA,
        'control_plane_commit': MAIN,
        'reviewed_verify_sha256': core.sha(core.canonical(verify)),
        'inputs_sha256': verify['inputs_sha256'],
        'scope_sha256': verify['scope_sha256'],
        'operation_set_sha256': verify['operation_set_sha256'],
        'proof_sha256': verify['proof_sha256'],
        'state_before_sha256': verify['state_before_sha256'],
        'predecessor_receipt_sha256': predecessor,
        'start_utc': '2026-09-16T00:50:00Z',
        'end_utc': END,
        'budget_limit_usd': '36.00',
        'execution_authorized': False,
        'automatic_retry_authorized': False,
        'repair_authorized': False,
        'simulation_only': True,
        'saved_plan_bundle': plan_bundle() if terraform else None,
    }


def fixtures(phase: str = STAGES[0]):
    receipts = prefix_for(phase)
    predecessor = (core.sha(core.canonical(receipts[-1]))
                   if receipts else None)
    verify = verify_for(phase, predecessor)
    approval = approval_for(phase, verify, predecessor)
    conditions = {name: True for name in POSTCONDITIONS[phase]}
    state_after = digest('e') if phase in ('eks-delete', 'final-delete') else STATE
    return receipts, verify, approval, conditions, state_after


def run(phase: str = STAGES[0], **updates):
    receipts, verify, approval, conditions, state_after = fixtures(phase)
    values = {
        'design': expected_design(),
        'main': MAIN,
        'phase': phase,
        'receipts': receipts,
        'verify': verify,
        'approval': approval,
        'current_utc': NOW,
        'completed_at_utc': '2026-09-16T01:01:00Z',
        'state_after_sha256': state_after,
        'postconditions': conditions,
        'transport': core.FixedFakeTransport(),
        'journal': core.FixedFakeJournal(),
    }
    values.update(updates)
    return core.run_fixed_fake_conformance(**values), values


class InjectedProtocolTests(unittest.TestCase):
    def assert_stopped(self, callable_):
        with self.assertRaises(core.ProtocolStopped) as caught:
            callable_()
        self.assertFalse(caught.exception.report['terminal_receipt_created'])
        self.assertFalse(caught.exception.report['automatic_retry_performed'])
        self.assertFalse(caught.exception.report['live_execution_authorized'])
        return caught.exception.report

    def test_all_eight_stages_complete_against_fixed_fake(self):
        for phase in STAGES:
            report, _ = run(phase)
            self.assertEqual(report['phase'], phase)
            self.assertEqual(report['operation_count'], len(STAGE_OPERATIONS[phase]))
            self.assertTrue(report['terminal_receipt_created'])

    def test_exact_twenty_three_operations_are_exercised(self):
        self.assertEqual(sum(run(stage)[0]['fake_call_count'] for stage in STAGES), 23)

    def test_request_binds_every_common_design_field(self):
        _, values = run()
        request = core._canonical_object(values['transport'].calls[0][1], 'test')
        self.assertTrue(set(COMMON_BINDINGS).issubset(request))

    def test_request_and_response_are_canonical(self):
        _, values = run()
        operation, raw = values['transport'].calls[0]
        self.assertEqual(core.canonical(core._canonical_object(raw, 'test')), raw)
        response = values['journal'].events[1]
        self.assertEqual(response['operation'], operation)

    def test_operation_order_is_exact_for_every_stage(self):
        for phase in STAGES:
            _, values = run(phase)
            self.assertEqual(tuple(call[0] for call in values['transport'].calls),
                             STAGE_OPERATIONS[phase])

    def test_one_intent_precedes_each_one_call(self):
        report, values = run('freeze-applications')
        kinds = [row['kind'] for row in values['journal'].events]
        self.assertEqual(kinds, ['intent', 'response'] * 4 + ['terminal'])
        self.assertEqual(report['intent_count'], report['fake_call_count'])

    def test_terminal_record_follows_all_responses(self):
        _, values = run('final-delete')
        self.assertEqual(values['journal'].events[-1]['kind'], 'terminal')
        self.assertFalse(any(row['kind'] == 'terminal'
                             for row in values['journal'].events[:-1]))

    def test_receipt_is_explicitly_non_durable_and_non_live(self):
        report, _ = run()
        self.assertFalse(report['receipt_is_durable'])
        self.assertFalse(report['receipt_usable_for_live'])
        self.assertTrue(report['receipt']['simulation_only'])
        self.assertFalse(report['receipt']['live_execution_authorized'])

    def test_receipt_field_set_is_closed(self):
        report, _ = run()
        self.assertEqual(set(report['receipt']), set(core.RECEIPT_FIELDS))

    def test_receipt_hash_matches_canonical_bytes(self):
        report, _ = run()
        self.assertEqual(report['receipt_sha256'],
                         core.sha(core.canonical(report['receipt'])))

    def test_external_secret_drain_has_no_mutation(self):
        _, values = run('drain-external-secrets')
        for _, raw in values['transport'].calls:
            self.assertFalse(core._canonical_object(raw, 'test')['mutation_expected'])

    def test_only_two_stages_carry_saved_plan_bindings(self):
        for phase in STAGES:
            _, values = run(phase)
            request = core._canonical_object(values['transport'].calls[0][1], 'test')
            self.assertEqual('binary_plan_sha256' in request,
                             phase in ('eks-delete', 'final-delete'))

    def test_nonterraform_state_must_be_unchanged(self):
        for phase in STAGES:
            if phase not in ('eks-delete', 'final-delete'):
                self.assert_stopped(lambda phase=phase: run(
                    phase, state_after_sha256=digest('f')))

    def test_terraform_state_requires_a_transition(self):
        for phase in ('eks-delete', 'final-delete'):
            self.assert_stopped(lambda phase=phase: run(
                phase, state_after_sha256=STATE))

    def test_missing_saved_plan_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures('eks-delete')
        approval['saved_plan_bundle'] = None
        self.assert_stopped(lambda: run('eks-delete', approval=approval))

    def test_saved_plan_hash_drift_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures('final-delete')
        approval['saved_plan_bundle']['binary_plan_sha256'] = 'bad'
        self.assert_stopped(lambda: run('final-delete', approval=approval))

    def test_saved_plan_workspace_drift_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures('eks-delete')
        approval['saved_plan_bundle']['terraform_workspace'] = 'other'
        self.assert_stopped(lambda: run('eks-delete', approval=approval))

    def test_unexpected_saved_plan_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['saved_plan_bundle'] = plan_bundle()
        self.assert_stopped(lambda: run(approval=approval))

    def test_postcondition_omission_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        conditions.pop(next(iter(conditions)))
        self.assert_stopped(lambda: run(postconditions=conditions))

    def test_false_postcondition_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        conditions[next(iter(conditions))] = False
        self.assert_stopped(lambda: run(postconditions=conditions))

    def test_postcondition_reorder_rejected(self):
        phase = 'final-delete'
        conditions = {name: True for name in reversed(POSTCONDITIONS[phase])}
        self.assert_stopped(lambda: run(phase, postconditions=conditions))

    def test_fixed_fake_failure_stops_without_retry(self):
        operation = STAGE_OPERATIONS['freeze-applications'][1]
        transport = core.FixedFakeTransport(fail_at=operation)
        report = self.assert_stopped(lambda: run(transport=transport))
        self.assertEqual(report['fake_call_count'], 2)
        self.assertEqual(len(transport.calls), 2)

    def test_malformed_response_stops_after_one_call(self):
        operation = STAGE_OPERATIONS[STAGES[0]][0]
        transport = core.FixedFakeTransport(overrides={operation: b'{}'})
        report = self.assert_stopped(lambda: run(transport=transport))
        self.assertEqual(report['fake_call_count'], 1)

    def test_live_effect_response_rejected(self):
        operation = STAGE_OPERATIONS[STAGES[0]][0]
        override = core.canonical({'live_effect_performed': True})
        self.assert_stopped(lambda: run(
            transport=core.FixedFakeTransport(overrides={operation: override})))

    def test_mutation_acknowledgement_drift_rejected(self):
        operation = STAGE_OPERATIONS[STAGES[0]][0]
        transport = core.FixedFakeTransport(overrides={operation: core.canonical({
            'schema': core.RESPONSE_SCHEMA,
            'environment': core.ENVIRONMENT,
            'phase': STAGES[0], 'operation': operation, 'operation_index': 0,
            'request_sha256': digest('f'), 'outcome': 'success',
            'mutation_acknowledged': True, 'simulation_only': True,
            'live_effect_performed': False,
        })})
        self.assert_stopped(lambda: run(transport=transport))

    def test_custom_transport_subclass_rejected(self):
        class Other(core.FixedFakeTransport):
            pass
        self.assert_stopped(lambda: run(transport=Other()))

    def test_custom_journal_subclass_rejected(self):
        class Other(core.FixedFakeJournal):
            pass
        self.assert_stopped(lambda: run(journal=Other()))

    def test_arbitrary_override_is_never_dispatched(self):
        transport = core.FixedFakeTransport(overrides={'arbitrary': b'{}'})
        run(transport=transport)
        self.assertNotIn('arbitrary', [call[0] for call in transport.calls])

    def test_incident_only_powers_never_enter_requests(self):
        for phase in STAGES:
            _, values = run(phase)
            raw = b''.join(item[1] for item in values['transport'].calls)
            for power in INCIDENT_ONLY_POWERS:
                self.assertNotIn(power.encode(), raw)

    def test_design_drift_rejected(self):
        design = expected_design()
        design['transport']['liveEnabled'] = True
        self.assert_stopped(lambda: run(design=design))

    def test_wrong_main_rejected(self):
        self.assert_stopped(lambda: run(main='bad'))

    def test_wrong_phase_rejected(self):
        values = run()[1]
        values['phase'] = 'unknown'
        self.assert_stopped(lambda: core.run_fixed_fake_conformance(**values))

    def test_verify_field_omission_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        verify.pop('proof_sha256')
        self.assert_stopped(lambda: run(verify=verify))

    def test_verify_expiry_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        verify['verify_expires_at_utc'] = NOW
        approval['reviewed_verify_sha256'] = core.sha(core.canonical(verify))
        self.assert_stopped(lambda: run(verify=verify, approval=approval))

    def test_verify_ttl_extension_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        verify['verify_expires_at_utc'] = '2026-09-16T01:11:00Z'
        approval['reviewed_verify_sha256'] = core.sha(core.canonical(verify))
        self.assert_stopped(lambda: run(verify=verify, approval=approval))

    def test_reviewed_verify_hash_drift_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['reviewed_verify_sha256'] = digest('f')
        self.assert_stopped(lambda: run(approval=approval))

    def test_verify_approval_binding_drift_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['scope_sha256'] = digest('f')
        self.assert_stopped(lambda: run(approval=approval))

    def test_approval_field_expansion_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['extra'] = False
        self.assert_stopped(lambda: run(approval=approval))

    def test_approval_live_authority_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['execution_authorized'] = True
        self.assert_stopped(lambda: run(approval=approval))

    def test_approval_retry_or_repair_rejected(self):
        for key in ('automatic_retry_authorized', 'repair_authorized'):
            receipts, verify, approval, conditions, state_after = fixtures()
            approval[key] = True
            self.assert_stopped(lambda approval=approval: run(approval=approval))

    def test_approval_budget_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['budget_limit_usd'] = '0.00'
        self.assert_stopped(lambda: run(approval=approval))

    def test_approval_window_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures()
        approval['end_utc'] = NOW
        self.assert_stopped(lambda: run(approval=approval))

    def test_predecessor_drift_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures(STAGES[1])
        verify['predecessor_receipt_sha256'] = digest('f')
        approval = approval_for(STAGES[1], verify, digest('f'))
        self.assert_stopped(lambda: run(STAGES[1], verify=verify, approval=approval))

    def test_live_receipt_schema_cannot_seed_prefix(self):
        receipts, verify, approval, conditions, state_after = fixtures(STAGES[1])
        rows = list(receipts)
        rows[0]['schema'] = core.RECEIPT_SCHEMA
        self.assert_stopped(lambda: run(STAGES[1], receipts=tuple(rows)))

    def test_cross_environment_receipt_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures(STAGES[1])
        rows = list(receipts)
        rows[0]['environment'] = 'aws-test'
        self.assert_stopped(lambda: run(STAGES[1], receipts=tuple(rows)))

    def test_receipt_retry_or_live_flag_rejected(self):
        for key in ('automatic_retry_performed', 'live_execution_authorized'):
            receipts, verify, approval, conditions, state_after = fixtures(STAGES[1])
            rows = list(receipts)
            rows[0][key] = True
            self.assert_stopped(lambda rows=rows: run(STAGES[1], receipts=tuple(rows)))

    def test_receipt_extra_field_rejected(self):
        receipts, verify, approval, conditions, state_after = fixtures(STAGES[1])
        rows = list(receipts)
        rows[0]['extra'] = 'not-accepted'
        self.assert_stopped(lambda: run(STAGES[1], receipts=tuple(rows)))

    def test_completion_after_window_rejected(self):
        self.assert_stopped(lambda: run(completed_at_utc='2026-09-16T03:00:01Z'))

    def test_report_keeps_all_live_effects_false(self):
        report, _ = run()
        self.assertFalse(report['live_transport_executed'])
        self.assertFalse(report['live_execution_authorized'])
        self.assertFalse(report['automatic_retry_performed'])
        self.assertFalse(report['automatic_repair_performed'])

    def test_core_ast_has_no_io_environment_clock_or_backend_import(self):
        path = Path(core.__file__)
        tree = ast.parse(path.read_text())
        forbidden_modules = {'os', 'pathlib', 'subprocess', 'socket', 'time',
                             'datetime', 'boto3', 'botocore', 'kubernetes'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(forbidden_modules & {item.name for item in node.names})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn(node.module, forbidden_modules)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {'open', 'exec', 'eval', '__import__'})


if __name__ == '__main__':
    unittest.main(verbosity=2)

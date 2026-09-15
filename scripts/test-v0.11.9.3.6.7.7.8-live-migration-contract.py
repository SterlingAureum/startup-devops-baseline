#!/usr/bin/env python3
"""Offline tests for the v0.11.9.3.6.7.7.8 migration design."""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import guarded_live_migration_contract_v6778 as design


MAIN = 'a' * 40


def digest(char: str) -> str:
    return char * 64


def approval(environment='aws-dev', phase='freeze-applications', predecessor=None):
    return {
        'schema': design.APPROVAL_SCHEMA,
        'transport_version': design.TRANSPORT_SCHEMA,
        'mode': 'live',
        'environment': environment,
        'phase': phase,
        'control_plane_commit': MAIN,
        'approval_text_sha256': digest('1'),
        'inputs_sha256': digest('2'),
        'scope_sha256': digest('3'),
        'state_sha256': digest('4'),
        'predecessor_receipt_sha256': predecessor,
        'operation_set_sha256': digest('5'),
        'proof_sha256': digest('6'),
        'start_utc': '2026-09-15T00:00:00Z',
        'end_utc': '2026-09-15T01:00:00Z',
        'proof_created_at_utc': '2026-09-15T00:01:00Z',
        'proof_expires_at_utc': '2026-09-15T00:16:00Z',
        'total_budget_limit_usd': '10.00',
        'execution_authorized': False,
        'automatic_retry_authorized': False,
        'repair_authorized': False,
    }


def receipt(environment='aws-dev', phase='freeze-applications', predecessor=None):
    return {
        'schema': design.RECEIPT_SCHEMA,
        'transport_version': design.TRANSPORT_SCHEMA,
        'environment': environment,
        'phase': phase,
        'phase_index': design.STAGES.index(phase),
        'status': 'terminal-success',
        'control_plane_commit': MAIN,
        'approval_sha256': digest('1'),
        'inputs_sha256': digest('2'),
        'scope_sha256': digest('3'),
        'operation_set_sha256': digest('4'),
        'predecessor_receipt_sha256': predecessor,
        'journal_completion_sha256': digest('5'),
        'raw_output_manifest_sha256': digest('6'),
        'state_before_sha256': digest('7'),
        'state_after_sha256': digest('8'),
        'completed_at_utc': '2026-09-15T00:10:00Z',
        'attempt_count': 1,
        'automatic_retry_performed': False,
        'incident_repair_performed': False,
    }


def prefix(environment='aws-dev', count=8):
    rows = []
    previous = None
    for index, phase in enumerate(design.STAGES[:count]):
        current = f'{index + 1:x}' * 64
        rows.append({
            'environment': environment,
            'phase': phase,
            'phase_index': index,
            'status': 'terminal-success',
            'predecessor_receipt_sha256': previous,
            'receipt_sha256': current,
        })
        previous = current
    return rows


class LiveMigrationDesignTests(unittest.TestCase):
    def assertViolation(self, function, *args, **kwargs):
        with self.assertRaises(design.RuleViolation):
            function(*args, **kwargs)

    def test_exact_design_validates(self):
        report = design.validate_design(design.expected_design())
        self.assertEqual(report['status'], 'live-migration-design-validated-offline')
        self.assertFalse(report['execution_authorized'])

    def test_stage_order_is_exact_eight_stage_chain(self):
        self.assertEqual(design.STAGES, (
            'freeze-applications', 'drain-external-secrets',
            'delete-business-namespaces', 'drain-runtime', 'delete-node-config',
            'eks-delete', 'eni-sg-cleanup', 'final-delete'))

    def test_environment_schema_order_is_dev_test_prod(self):
        self.assertEqual(design.ENVIRONMENTS, ('aws-dev', 'aws-test', 'aws-prod'))
        self.assertEqual(design.expected_design()['environment_rollout']['schema_coverage'],
                         list(design.ENVIRONMENTS))

    def test_no_environment_is_live_enabled_by_design(self):
        rollout = design.expected_design()['environment_rollout']
        self.assertEqual(rollout['currently_live_enabled'], [])
        self.assertEqual(rollout['aws-dev'], 'future-separate-migration-candidate')

    def test_test_waits_for_dev_migration_evidence(self):
        self.assertEqual(design.expected_design()['environment_rollout']['aws-test'],
                         'blocked-until-dev-migration-evidence')

    def test_prod_remains_disabled_and_separately_qualified(self):
        value = design.expected_design()
        self.assertEqual(value['environment_rollout']['aws-prod'],
                         'disabled-until-separate-qualification')
        self.assertFalse(value['transport']['prod-enabled'])
        self.assertFalse(value['approval']['prod_approval_supported'])

    def test_transport_schema_and_closed_dispatch_are_exact(self):
        transport = design.expected_design()['transport']
        self.assertEqual(transport['schema'], 'guarded-live-transport-v1')
        self.assertEqual(transport['dispatch'], 'closed-enum-per-stage')
        self.assertEqual(set(transport['stage_operations']), set(design.STAGES))

    def test_each_stage_operation_set_is_nonempty_and_unique(self):
        for operations in design.STAGE_OPERATIONS.values():
            self.assertTrue(operations)
            self.assertEqual(len(operations), len(set(operations)))

    def test_raw_shell_dynamic_commands_and_overrides_are_forbidden(self):
        transport = design.expected_design()['transport']
        for key in ('raw-shell', 'dynamic-command-template',
                    'endpoint-or-credential-override'):
            self.assertFalse(transport[key])

    def test_saved_plan_apply_exists_only_in_destroy_stages(self):
        stages = [stage for stage, operations in design.STAGE_OPERATIONS.items()
                  if 'terraform-apply-reviewed-saved-plan' in operations]
        self.assertEqual(stages, ['eks-delete', 'final-delete'])

    def test_transport_has_no_replan_operation(self):
        operations = [item for values in design.STAGE_OPERATIONS.values()
                      for item in values]
        self.assertFalse(any('plan-create' in item or 'replan' in item
                             for item in operations))

    def test_normal_transport_excludes_incident_only_powers(self):
        value = design.expected_design()
        operations = {item for values in design.STAGE_OPERATIONS.values()
                      for item in values}
        self.assertTrue(set(design.INCIDENT_ONLY_POWERS).isdisjoint(operations))
        self.assertEqual(value['incident_boundary']['normal_transport_excludes'],
                         list(design.INCIDENT_ONLY_POWERS))

    def test_secret_value_return_retry_and_repair_are_forbidden(self):
        transport = design.expected_design()['transport']
        self.assertFalse(transport['secret-value-return'])
        self.assertFalse(transport['automatic-retry-or-repair'])

    def test_verify_and_execute_are_distinct_commands(self):
        approval_contract = design.expected_design()['approval']
        self.assertEqual(approval_contract['commands'], ['verify', 'execute'])
        self.assertFalse(approval_contract['verify_can_mutate'])
        self.assertTrue(approval_contract['execute_requires_separate_human_approval'])

    def test_approval_is_one_phase_and_one_attempt(self):
        approval_contract = design.expected_design()['approval']
        self.assertTrue(approval_contract['one_phase_per_approval'])
        self.assertTrue(approval_contract['one_attempt_per_approval'])

    def test_approval_binds_identity_scope_clock_budget_and_predecessor(self):
        binds = set(design.expected_design()['approval']['binds'])
        self.assertTrue({
            'environment', 'phase', 'transport_version', 'control_plane_commit',
            'inputs_sha256', 'scope_sha256', 'state_sha256',
            'predecessor_receipt_sha256', 'operation_set_sha256',
            'proof_sha256', 'start_utc', 'end_utc',
            'proof_expires_at_utc', 'total_budget_limit_usd',
        }.issubset(binds))

    def test_historical_approval_and_synthetic_receipt_are_not_accepted(self):
        approval_contract = design.expected_design()['approval']
        self.assertFalse(approval_contract['historical_approval_reusable'])
        self.assertFalse(approval_contract['synthetic_receipt_acceptable'])

    def test_receipt_storage_is_private_atomic_and_durable(self):
        contract = design.expected_design()['receipt']
        self.assertEqual(contract['storage'], 'private-durable-append-only')
        self.assertEqual((contract['directory_mode'], contract['file_mode']),
                         ('0700', '0600'))
        for key in ('canonical_json', 'exclusive_create', 'file_and_directory_fsync',
                    'symlink_or_hardlink_rejected'):
            self.assertTrue(contract[key])

    def test_receipt_requires_terminal_success_and_exact_predecessor(self):
        contract = design.expected_design()['receipt']
        self.assertTrue(contract['terminal_success_only'])
        self.assertTrue(contract['exact_predecessor_chain'])
        self.assertTrue(contract['failed_or_pending_is_terminal_stop'])

    def test_receipt_field_set_binds_state_journal_and_raw_manifest(self):
        fields = set(design.expected_design()['receipt']['required_fields'])
        self.assertTrue({'state_before_sha256', 'state_after_sha256',
                         'journal_completion_sha256', 'raw_output_manifest_sha256',
                         'predecessor_receipt_sha256'}.issubset(fields))

    def test_synthetic_receipts_cannot_be_converted_to_live(self):
        migration = design.expected_design()['migration']
        self.assertFalse(migration['synthetic_receipt_convertible'])
        self.assertFalse(migration['live_completion_inferred_from_offline_fixture'])
        self.assertTrue(migration['fresh_live_preflight_and_verify_required'])

    def test_live_chain_starts_fresh_and_survives_restart(self):
        migration = design.expected_design()['migration']
        self.assertTrue(migration['first_live_stage_has_no_predecessor'])
        self.assertTrue(migration['later_stage_requires_exact_previous_receipt'])
        self.assertTrue(migration['receipt_chain_survives_process_restart'])

    def test_any_design_drift_is_rejected(self):
        value = design.expected_design()
        value['transport']['raw-shell'] = True
        self.assertViolation(design.validate_design, value)

    def test_valid_dev_first_stage_approval_shape_is_reviewed_only(self):
        report = design.review_approval_shape(
            approval(), environment='aws-dev', phase='freeze-applications',
            main=MAIN, current_utc='2026-09-15T00:02:00Z',
            expected_predecessor_sha256=None)
        self.assertTrue(report['design_only'])
        self.assertFalse(report['execution_authorized'])

    def test_valid_test_later_stage_requires_exact_predecessor(self):
        predecessor = digest('9')
        report = design.review_approval_shape(
            approval('aws-test', 'drain-runtime', predecessor),
            environment='aws-test', phase='drain-runtime', main=MAIN,
            current_utc='2026-09-15T00:02:00Z',
            expected_predecessor_sha256=predecessor)
        self.assertEqual(report['phase'], 'drain-runtime')

    def test_prod_approval_shape_is_rejected(self):
        self.assertViolation(
            design.review_approval_shape,
            approval('aws-prod'), environment='aws-prod',
            phase='freeze-applications', main=MAIN,
            current_utc='2026-09-15T00:02:00Z',
            expected_predecessor_sha256=None)

    def test_approval_main_and_target_drift_are_rejected(self):
        value = approval()
        value['control_plane_commit'] = 'b' * 40
        self.assertViolation(
            design.review_approval_shape, value, environment='aws-dev',
            phase='freeze-applications', main=MAIN,
            current_utc='2026-09-15T00:02:00Z',
            expected_predecessor_sha256=None)

    def test_first_and_later_approval_predecessor_rules_are_strict(self):
        first = approval(predecessor=digest('9'))
        self.assertViolation(
            design.review_approval_shape, first, environment='aws-dev',
            phase='freeze-applications', main=MAIN,
            current_utc='2026-09-15T00:02:00Z',
            expected_predecessor_sha256=None)
        later = approval(phase='drain-runtime', predecessor=digest('8'))
        self.assertViolation(
            design.review_approval_shape, later, environment='aws-dev',
            phase='drain-runtime', main=MAIN,
            current_utc='2026-09-15T00:02:00Z',
            expected_predecessor_sha256=digest('9'))

    def test_expired_window_or_proof_is_rejected(self):
        self.assertViolation(
            design.review_approval_shape, approval(), environment='aws-dev',
            phase='freeze-applications', main=MAIN,
            current_utc='2026-09-15T00:17:00Z',
            expected_predecessor_sha256=None)

    def test_budget_schema_and_positive_value_are_required(self):
        for bad in ('10', '0.00', '-1.00', 10):
            value = approval()
            value['total_budget_limit_usd'] = bad
            self.assertViolation(
                design.review_approval_shape, value, environment='aws-dev',
                phase='freeze-applications', main=MAIN,
                current_utc='2026-09-15T00:02:00Z',
                expected_predecessor_sha256=None)

    def test_approval_authority_flags_cannot_be_pregranted(self):
        for key in ('execution_authorized', 'automatic_retry_authorized',
                    'repair_authorized'):
            value = approval()
            value[key] = True
            self.assertViolation(
                design.review_approval_shape, value, environment='aws-dev',
                phase='freeze-applications', main=MAIN,
                current_utc='2026-09-15T00:02:00Z',
                expected_predecessor_sha256=None)

    def test_valid_terminal_receipt_shape_is_reviewed_not_persisted(self):
        report = design.review_receipt_shape(
            receipt(), environment='aws-dev', phase='freeze-applications',
            main=MAIN, expected_predecessor_sha256=None)
        self.assertTrue(report['design_only'])
        self.assertFalse(report['receipt_persisted'])

    def test_synthetic_fields_are_rejected_from_live_receipt(self):
        for key, value in (('simulation_only', True), ('confirmed', True)):
            row = receipt()
            row[key] = value
            self.assertViolation(
                design.review_receipt_shape, row, environment='aws-dev',
                phase='freeze-applications', main=MAIN,
                expected_predecessor_sha256=None)

    def test_failed_pending_retry_or_repair_receipt_is_rejected(self):
        for key, value in (('status', 'failed'), ('status', 'pending'),
                           ('attempt_count', 2),
                           ('automatic_retry_performed', True),
                           ('incident_repair_performed', True)):
            row = receipt()
            row[key] = value
            self.assertViolation(
                design.review_receipt_shape, row, environment='aws-dev',
                phase='freeze-applications', main=MAIN,
                expected_predecessor_sha256=None)

    def test_receipt_field_hash_main_and_predecessor_drift_rejected(self):
        changes = (
            ('scope_sha256', 'bad'),
            ('control_plane_commit', 'b' * 40),
            ('predecessor_receipt_sha256', digest('9')),
        )
        for key, value in changes:
            row = receipt()
            row[key] = value
            self.assertViolation(
                design.review_receipt_shape, row, environment='aws-dev',
                phase='freeze-applications', main=MAIN,
                expected_predecessor_sha256=None)

    def test_complete_receipt_prefix_has_exact_eight_links(self):
        rows = prefix()
        self.assertEqual(design.review_receipt_prefix(rows, environment='aws-dev'),
                         design.STAGES)

    def test_receipt_prefix_reorder_cross_environment_and_link_drift_rejected(self):
        variants = []
        reordered = prefix(count=3)
        reordered[1]['phase'] = 'drain-runtime'
        variants.append(reordered)
        crossed = prefix(count=3)
        crossed[2]['environment'] = 'aws-test'
        variants.append(crossed)
        unlinked = prefix(count=3)
        unlinked[2]['predecessor_receipt_sha256'] = digest('f')
        variants.append(unlinked)
        for rows in variants:
            self.assertViolation(design.review_receipt_prefix, rows,
                                 environment='aws-dev')

    def test_core_ast_has_no_io_or_execution_primitives(self):
        tree = ast.parse((ROOT / 'scripts' /
                          'guarded_live_migration_contract_v6778.py').read_text())
        forbidden_modules = {'os', 'subprocess', 'socket', 'boto3', 'botocore',
                             'requests', 'urllib', 'pathlib', 'time', 'datetime'}
        forbidden_calls = {'open', 'exec', 'eval', '__import__', 'print'}
        forbidden_attributes = {'run', 'Popen', 'system', 'getenv', 'now',
                                'utcnow', 'write_text', 'read_text', 'unlink'}
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

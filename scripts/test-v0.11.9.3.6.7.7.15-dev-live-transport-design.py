#!/usr/bin/env python3
from __future__ import annotations

import ast
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import guarded_dev_live_transport_design_v67715 as design
from guarded_runtime_rules import RuleViolation


GAP_REVIEW = ROOT / 'delivery/contracts/v0.11.9.3.6.7.7.14-dev-live-parity-gap-review.json'


def predecessor() -> dict:
    return json.loads(GAP_REVIEW.read_text())


class DevLiveTransportDesignTests(unittest.TestCase):
    def result(self, reviewed=None, candidate=None):
        return design.review_dev_live_transport_design(
            predecessor() if reviewed is None else reviewed,
            design.expected_design() if candidate is None else candidate,
        )

    def rejected(self, reviewed=None, candidate=None):
        with self.assertRaises(RuleViolation):
            self.result(reviewed, candidate)

    def test_report_covers_eight_stages_and_twenty_three_operations(self):
        result = self.result()
        self.assertEqual(result['designedStageCount'], 8)
        self.assertEqual(result['closedOperationCount'], 23)

    def test_all_nine_gaps_have_offline_design_clauses(self):
        result = self.result()
        self.assertEqual(result['gapDesignCount'], 9)
        self.assertEqual(result['structuralBlockingGapDesignCount'], 8)

    def test_no_gap_is_claimed_live_implemented(self):
        self.assertEqual(self.result()['liveImplementedGapCount'], 0)

    def test_dev_test_and_prod_remain_disabled(self):
        result = self.result()
        self.assertFalse(result['devLiveTransportImplemented'])
        self.assertFalse(result['devLiveCommandImplemented'])
        self.assertFalse(result['devLiveExecutionAuthorized'])
        self.assertFalse(result['testLiveEnabled'])
        self.assertFalse(result['prodLiveEnabled'])

    def test_stage_order_and_phase_operation_pairs_are_exact(self):
        rows = design.expected_stage_designs()
        self.assertEqual(tuple(row['stage'] for row in rows), design.STAGES)
        pairs = [(row['stage'], operation) for row in rows
                 for operation in row['allowedOperationIds']]
        self.assertEqual(len(pairs), 23)
        self.assertEqual(pairs, [(stage, operation) for stage in design.STAGES
                                 for operation in design.STAGE_OPERATIONS[stage]])

    def test_mutations_are_subsets_of_each_closed_operation_set(self):
        for row in design.expected_stage_designs():
            self.assertLessEqual(set(row['mutationOperationIds']),
                                 set(row['allowedOperationIds']))

    def test_every_stage_requires_exact_common_bindings(self):
        for row in design.expected_stage_designs():
            self.assertEqual(tuple(row['requiredApprovalBindings']),
                             design.COMMON_BINDINGS)

    def test_only_terraform_stages_require_saved_plan_bundle(self):
        rows = {row['stage']: row for row in design.expected_stage_designs()}
        required = {stage for stage, row in rows.items()
                    if row['savedPlanBundleRequired']}
        self.assertEqual(required, {'eks-delete', 'final-delete'})
        self.assertTrue(rows['eks-delete']['savedPlanBindings'])
        self.assertTrue(rows['final-delete']['savedPlanBindings'])

    def test_nonterraform_stages_require_unchanged_state(self):
        for row in design.expected_stage_designs():
            expected = ('reviewed-transition' if row['transportKinds']['terraform']
                        else 'unchanged')
            self.assertEqual(row['stateAfterRelation'], expected)

    def test_external_secret_drain_is_read_only_and_keeps_permissions(self):
        row = next(row for row in design.expected_stage_designs()
                   if row['stage'] == 'drain-external-secrets')
        self.assertEqual(row['mutationOperationIds'], [])
        self.assertIn('cleanup-permissions-retained-through-drain',
                      row['postconditions'])

    def test_protocol_is_one_intent_one_call_without_retry(self):
        protocol = design.expected_protocol()
        self.assertTrue(protocol['writeAheadIntentRequired'])
        self.assertTrue(protocol['oneTransportCallPerIntent'])
        self.assertFalse(protocol['automaticRetryOrRepair'])
        self.assertTrue(protocol['failedOrUncertainIntentBlocksProgress'])

    def test_terminal_receipt_follows_postconditions(self):
        protocol = design.expected_protocol()
        self.assertTrue(protocol['terminalReceiptAfterPostconditionsOnly'])
        for row in design.expected_stage_designs():
            self.assertFalse(row['terminalReceiptBeforePostconditionsAllowed'])

    def test_historical_and_synthetic_receipts_are_rejected(self):
        self.assertFalse(design.expected_protocol()['historicalOrSyntheticReceiptAccepted'])
        result = self.result()
        self.assertFalse(result['historicalApprovalsReusable'])
        self.assertFalse(result['syntheticReceiptsReusableForLive'])

    def test_incident_only_powers_are_enumerated_but_never_enabled(self):
        result = self.result()
        self.assertEqual(result['incidentOnlyPowerCount'], len(design.INCIDENT_ONLY_POWERS))
        self.assertFalse(result['incidentOnlyPowersEnabled'])
        self.assertTrue(all(not row['incidentOnlyPowersAllowed']
                            for row in design.expected_stage_designs()))

    def test_legacy_destroy_wrapper_is_not_callable(self):
        candidate = design.expected_design()
        self.assertFalse(candidate['migration']['legacyDestroyWrapperCallable'])
        self.assertFalse(self.result()['legacyDestroyWrapperCallable'])

    def test_transport_interface_is_closed_but_unimplemented(self):
        transport = design.expected_transport()
        self.assertEqual(transport['closedOperationCount'], 23)
        self.assertTrue(transport['closedDispatchRequired'])
        self.assertFalse(transport['backendImplemented'])
        self.assertFalse(transport['commandEntryImplemented'])
        self.assertFalse(transport['liveEnabled'])

    def test_predecessor_version_drift_rejected(self):
        reviewed = predecessor(); reviewed['version'] = 'drift'
        self.rejected(reviewed)

    def test_predecessor_status_drift_rejected(self):
        reviewed = predecessor(); reviewed['status'] = 'complete'
        self.rejected(reviewed)

    def test_predecessor_gap_count_drift_rejected(self):
        reviewed = predecessor(); reviewed['reviewResult']['blockingGapCount'] = 7
        self.rejected(reviewed)

    def test_predecessor_receipt_overclaim_rejected(self):
        reviewed = predecessor()
        reviewed['reviewResult']['historicalLiveReceiptEquivalentStageCount'] = 1
        self.rejected(reviewed)

    def test_predecessor_ready_claim_rejected(self):
        reviewed = predecessor(); reviewed['reviewResult']['devLiveTransportReady'] = True
        self.rejected(reviewed)

    def test_predecessor_live_flag_rejected(self):
        reviewed = predecessor(); reviewed['devLiveEnabled'] = True
        self.rejected(reviewed)

    def test_predecessor_gap_row_drift_rejected(self):
        reviewed = predecessor(); reviewed['gapManifest']['gapRows'].pop()
        self.rejected(reviewed)

    def test_design_extra_key_rejected(self):
        candidate = design.expected_design(); candidate['authorized'] = False
        self.rejected(candidate=candidate)

    def test_environment_expansion_rejected(self):
        candidate = design.expected_design(); candidate['environment'] = 'aws-test'
        self.rejected(candidate=candidate)

    def test_backend_implementation_claim_rejected(self):
        candidate = design.expected_design()
        candidate['transport']['backendImplemented'] = True
        self.rejected(candidate=candidate)

    def test_command_entry_claim_rejected(self):
        candidate = design.expected_design()
        candidate['transport']['commandEntryImplemented'] = True
        self.rejected(candidate=candidate)

    def test_arbitrary_command_or_endpoint_selector_rejected(self):
        for key in ('arbitraryCommandAccepted', 'endpointSelectorAccepted'):
            candidate = design.expected_design(); candidate['transport'][key] = True
            self.rejected(candidate=candidate)

    def test_environment_fallback_and_credential_reader_rejected(self):
        for key in ('environmentFallbackAccepted', 'credentialReaderImplemented'):
            candidate = design.expected_design(); candidate['transport'][key] = True
            self.rejected(candidate=candidate)

    def test_stage_reorder_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][0], candidate['stageDesigns'][1] = (
            candidate['stageDesigns'][1], candidate['stageDesigns'][0])
        self.rejected(candidate=candidate)

    def test_operation_expansion_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][0]['allowedOperationIds'].append('shell-command')
        self.rejected(candidate=candidate)

    def test_mutation_operation_expansion_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][1]['mutationOperationIds'].append(
            'kubernetes-observe-external-secrets')
        self.rejected(candidate=candidate)

    def test_approval_binding_omission_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][0]['requiredApprovalBindings'].pop()
        self.rejected(candidate=candidate)

    def test_saved_plan_binding_drift_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][5]['savedPlanBindings'].pop()
        self.rejected(candidate=candidate)

    def test_state_relation_drift_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][5]['stateAfterRelation'] = 'unchanged'
        self.rejected(candidate=candidate)

    def test_postcondition_omission_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][7]['postconditions'].pop()
        self.rejected(candidate=candidate)

    def test_incident_power_enable_rejected(self):
        candidate = design.expected_design()
        candidate['stageDesigns'][0]['incidentOnlyPowersAllowed'].append(
            design.INCIDENT_ONLY_POWERS[0])
        self.rejected(candidate=candidate)

    def test_retry_repair_and_early_receipt_rejected(self):
        for key in ('automaticRetryAllowed', 'automaticRepairAllowed',
                    'terminalReceiptBeforePostconditionsAllowed'):
            candidate = design.expected_design(); candidate['stageDesigns'][0][key] = True
            self.rejected(candidate=candidate)

    def test_gap_live_implementation_overclaim_rejected(self):
        candidate = design.expected_design(); candidate['gapDesigns'][0]['implementedLive'] = True
        self.rejected(candidate=candidate)

    def test_gap_omission_and_clause_drift_rejected(self):
        candidate = design.expected_design(); candidate['gapDesigns'].pop()
        self.rejected(candidate=candidate)
        candidate = design.expected_design(); candidate['gapDesigns'][0]['designClause'] = 'other'
        self.rejected(candidate=candidate)

    def test_protocol_intent_call_and_receipt_drift_rejected(self):
        for key, value in (
            ('writeAheadIntentRequired', False),
            ('oneTransportCallPerIntent', False),
            ('terminalReceiptAfterPostconditionsOnly', False),
            ('historicalOrSyntheticReceiptAccepted', True),
        ):
            candidate = design.expected_design(); candidate['protocol'][key] = value
            self.rejected(candidate=candidate)

    def test_migration_prod_legacy_and_synthetic_enable_rejected(self):
        cases = (
            ('prodDisabled', False),
            ('legacyDestroyWrapperCallable', True),
            ('syntheticReceiptConvertibleToLive', True),
        )
        for key, value in cases:
            candidate = design.expected_design(); candidate['migration'][key] = value
            self.rejected(candidate=candidate)

    def test_review_does_not_mutate_inputs(self):
        reviewed = predecessor(); candidate = design.expected_design()
        before = copy.deepcopy((reviewed, candidate))
        design.review_dev_live_transport_design(reviewed, candidate)
        self.assertEqual((reviewed, candidate), before)

    def test_core_ast_has_no_io_clock_environment_or_backend_import(self):
        tree = ast.parse(
            (ROOT / 'scripts/guarded_dev_live_transport_design_v67715.py').read_text())
        forbidden = {'boto3', 'botocore', 'subprocess', 'socket', 'urllib', 'requests',
                     'os', 'pathlib', 'datetime', 'time'}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertFalse(imported & forbidden)


if __name__ == '__main__':
    unittest.main(verbosity=2)

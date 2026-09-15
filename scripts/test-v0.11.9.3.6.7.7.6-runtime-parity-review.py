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

import guarded_runtime_parity_v6776 as parity
from guarded_runtime_rules import RuleViolation


DESTROY_PATH = ROOT / 'delivery/contracts/v0.11.9.3.6.7.7.4-shared-offline-destroy-adapters.json'
CLEANUP_PATH = ROOT / 'delivery/contracts/v0.11.9.3.6.7.7.5-shared-offline-cleanup-adapters.json'


def contracts() -> tuple[dict, dict]:
    return json.loads(DESTROY_PATH.read_text()), json.loads(CLEANUP_PATH.read_text())


def manifest() -> dict:
    return {
        'schema': 'offline-runtime-parity-manifest-v1',
        'environments': list(parity.ENVIRONMENTS),
        'stages': [dict(row) for row in parity.expected_stage_rows()],
        'gaps': [dict(row) for row in parity.expected_gap_rows()],
    }


class RuntimeParityReviewTests(unittest.TestCase):
    def review(self, destroy=None, cleanup=None, reviewed=None):
        original_destroy, original_cleanup = contracts()
        return parity.review_runtime_parity(
            original_destroy if destroy is None else destroy,
            original_cleanup if cleanup is None else cleanup,
            manifest() if reviewed is None else reviewed,
        )

    def rejected(self, destroy=None, cleanup=None, reviewed=None):
        with self.assertRaises(RuleViolation):
            self.review(destroy, cleanup, reviewed)

    def test_complete_report_counts_seven_of_eight_and_twenty_one_of_twenty_four(self):
        report = self.review()
        self.assertEqual(report['totalStageCount'], 8)
        self.assertEqual(report['individuallySimulatableStageCount'], 7)
        self.assertEqual(report['implementedFixtureMatrixSize'], 21)
        self.assertEqual(report['completeFixtureMatrixSize'], 24)
        self.assertEqual(report['missingFixtureMatrixSize'], 3)

    def test_three_environment_profiles_are_exact(self):
        report = self.review()
        self.assertEqual(report['environmentCount'], 3)

    def test_freeze_is_the_only_first_stage_gap(self):
        report = self.review()
        self.assertEqual(report['firstUnimplementedStep'], 'freeze-applications')
        self.assertEqual(report['unimplementedStageCount'], 1)

    def test_synthetic_receipt_does_not_claim_end_to_end_chain(self):
        report = self.review()
        self.assertTrue(report['syntheticPredecessorReceiptRequired'])
        self.assertFalse(report['endToEndOfflineChainExecutable'])

    def test_live_prod_and_historical_approval_boundaries_remain_false(self):
        report = self.review()
        self.assertFalse(report['liveMigrationReady'])
        self.assertFalse(report['prodQualified'])
        self.assertFalse(report['historicalApprovalsReusable'])
        self.assertTrue(report['historicalTeardownAndScopedAuditClosed'])

    def test_stage_order_is_exact_cleanup_order(self):
        self.assertEqual(tuple(row['step'] for row in parity.expected_stage_rows()),
                         parity.CLEANUP_STEPS)

    def test_each_implemented_stage_has_three_fixture_profiles(self):
        rows = parity.expected_stage_rows()
        pairs = {(environment, row['step']) for environment in parity.ENVIRONMENTS
                 for row in rows if row['coverageStatus'] == 'individually-simulatable'}
        self.assertEqual(len(pairs), 21)

    def test_missing_freeze_has_three_environment_cells(self):
        rows = parity.expected_stage_rows()
        pairs = {(environment, row['step']) for environment in parity.ENVIRONMENTS
                 for row in rows if row['coverageStatus'] == 'unimplemented-adapter-gap'}
        self.assertEqual(pairs, {(environment, 'freeze-applications')
                                for environment in parity.ENVIRONMENTS})

    def test_destroy_version_drift_rejected(self):
        destroy, cleanup = contracts(); destroy['version'] = 'drift'
        self.rejected(destroy, cleanup)

    def test_destroy_status_drift_rejected(self):
        destroy, cleanup = contracts(); destroy['status'] = 'complete'
        self.rejected(destroy, cleanup)

    def test_destroy_phase_reorder_rejected(self):
        destroy, cleanup = contracts(); destroy['implementedPhases'].reverse()
        self.rejected(destroy, cleanup)

    def test_destroy_matrix_claim_drift_rejected(self):
        destroy, cleanup = contracts(); destroy['successfulFixtureMatrixSize'] = 7
        self.rejected(destroy, cleanup)

    def test_destroy_environment_reorder_rejected(self):
        destroy, cleanup = contracts(); destroy['environmentProfiles'].reverse()
        self.rejected(destroy, cleanup)

    def test_destroy_profile_live_enable_rejected(self):
        destroy, cleanup = contracts(); destroy['environmentProfiles'][0]['liveEnabled'] = True
        self.rejected(destroy, cleanup)

    def test_cleanup_predecessor_drift_rejected(self):
        destroy, cleanup = contracts(); cleanup['predecessor'] = 'other'
        self.rejected(destroy, cleanup)

    def test_cleanup_phase_omission_rejected(self):
        destroy, cleanup = contracts(); cleanup['implementedPhases'].pop()
        self.rejected(destroy, cleanup)

    def test_cleanup_matrix_claim_drift_rejected(self):
        destroy, cleanup = contracts(); cleanup['successfulFixtureMatrixSize'] = 18
        self.rejected(destroy, cleanup)

    def test_cleanup_environment_expansion_rejected(self):
        destroy, cleanup = contracts(); cleanup['environmentProfiles'].append('other')
        self.rejected(destroy, cleanup)

    def test_common_clock_drift_rejected(self):
        destroy, cleanup = contracts(); cleanup['clocks']['proofTtlSeconds'] = 901
        self.rejected(destroy, cleanup)

    def test_live_effect_enable_rejected(self):
        destroy, cleanup = contracts(); destroy['effectFlags']['cloudTransport'] = True
        self.rejected(destroy, cleanup)

    def test_kubernetes_effect_enable_rejected(self):
        destroy, cleanup = contracts(); cleanup['effectFlags']['kubernetesMutation'] = True
        self.rejected(destroy, cleanup)

    def test_historical_closure_reversal_rejected(self):
        destroy, cleanup = contracts(); cleanup['historicalTeardownAndScopedAuditClosed'] = False
        self.rejected(destroy, cleanup)

    def test_historical_approval_reuse_rejected(self):
        destroy, cleanup = contracts(); destroy['historicalApprovalsReusable'] = True
        self.rejected(destroy, cleanup)

    def test_manifest_extra_key_rejected(self):
        reviewed = manifest(); reviewed['authorized'] = False
        self.rejected(reviewed=reviewed)

    def test_manifest_environment_drift_rejected(self):
        reviewed = manifest(); reviewed['environments'][2] = 'aws-stage'
        self.rejected(reviewed=reviewed)

    def test_manifest_stage_omission_rejected(self):
        reviewed = manifest(); reviewed['stages'].pop()
        self.rejected(reviewed=reviewed)

    def test_manifest_stage_reorder_rejected(self):
        reviewed = manifest(); reviewed['stages'][0], reviewed['stages'][1] = reviewed['stages'][1], reviewed['stages'][0]
        self.rejected(reviewed=reviewed)

    def test_freeze_cannot_be_claimed_implemented(self):
        reviewed = manifest(); reviewed['stages'][0]['coverageStatus'] = 'individually-simulatable'
        self.rejected(reviewed=reviewed)

    def test_implemented_stage_cannot_change_adapter_version(self):
        reviewed = manifest(); reviewed['stages'][1]['adapterVersion'] = parity.DESTROY_VERSION
        self.rejected(reviewed=reviewed)

    def test_any_live_stage_enable_rejected(self):
        reviewed = manifest(); reviewed['stages'][-1]['liveEnabled'] = True
        self.rejected(reviewed=reviewed)

    def test_gap_omission_rejected(self):
        reviewed = manifest(); reviewed['gaps'].pop()
        self.rejected(reviewed=reviewed)

    def test_incident_gap_cannot_be_generalized_silently(self):
        reviewed = manifest(); reviewed['gaps'][3]['incidentOnly'] = False
        self.rejected(reviewed=reviewed)

    def test_prod_scope_gap_is_explicit(self):
        report = self.review()
        self.assertIn('prod-fresh-scope-price-proof', report['migrationGapIds'])

    def test_finalizer_namespace_pv_and_destructive_lifecycle_gaps_are_explicit(self):
        gap_ids = set(self.review()['migrationGapIds'])
        self.assertTrue({'externalsecret-finalizer-exception',
                         'namespace-pv-forced-cleanup',
                         'backup-secret-destructive-lifecycle'} <= gap_ids)

    def test_core_ast_contains_no_io_network_subprocess_or_environment_import(self):
        tree = ast.parse((ROOT / 'scripts/guarded_runtime_parity_v6776.py').read_text())
        forbidden = {'boto3', 'botocore', 'subprocess', 'socket', 'urllib', 'requests',
                     'os', 'pathlib', 'datetime', 'time'}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertFalse(imported & forbidden)

    def test_review_does_not_mutate_inputs(self):
        destroy, cleanup = contracts(); reviewed = manifest()
        before = copy.deepcopy((destroy, cleanup, reviewed))
        parity.review_runtime_parity(destroy, cleanup, reviewed)
        self.assertEqual((destroy, cleanup, reviewed), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)

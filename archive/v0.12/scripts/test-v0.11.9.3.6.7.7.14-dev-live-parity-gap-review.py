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

import guarded_dev_live_parity_review_v67714 as review
from guarded_runtime_rules import RuleViolation


CHAIN = ROOT / 'delivery/contracts/v0.11.9.3.6.7.7.13-dev-local-offline-restart-chain.json'
TEARDOWN = ROOT / 'delivery/contracts/v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.json'
AUDIT = ROOT / 'delivery/contracts/v0.11.9.3.6.6.6.1-aws-dev-residual-cost-audit-execution-evidence.json'


def contracts() -> tuple[dict, dict, dict]:
    return tuple(json.loads(path.read_text()) for path in (CHAIN, TEARDOWN, AUDIT))


def manifest() -> dict:
    return {
        'schema': 'dev-live-parity-gap-manifest-v1',
        'stageRows': [dict(row) for row in review.expected_stage_rows()],
        'gapRows': [dict(row) for row in review.expected_gap_rows()],
        'provenHistoricalControls': list(review.expected_proven_controls()),
        'historicalSourceCapabilities': {
            'monolithicDestroyWrapper': True,
            'perStageSavedPlanBindings': False,
            'perStageReceiptChain': False,
            'perStageStateTransitions': False,
            'externalSecretDrain': False,
            'terraformFailureMayInvokeSecondDestroy': True,
            'separateResidualAuditRecorded': True,
        },
    }


class DevLiveParityGapReviewTests(unittest.TestCase):
    def result(self, chain=None, teardown=None, audit=None, reviewed=None):
        original = contracts()
        return review.review_dev_live_parity(
            original[0] if chain is None else chain,
            original[1] if teardown is None else teardown,
            original[2] if audit is None else audit,
            manifest() if reviewed is None else reviewed,
        )

    def rejected(self, chain=None, teardown=None, audit=None, reviewed=None):
        with self.assertRaises(RuleViolation):
            self.result(chain, teardown, audit, reviewed)

    def test_report_keeps_all_eight_stages_offline_complete(self):
        result = self.result()
        self.assertEqual(result['reviewedStageCount'], 8)
        self.assertEqual(result['offlineCompleteStageCount'], 8)

    def test_no_historical_stage_has_equivalent_live_receipt(self):
        self.assertEqual(self.result()['historicalLiveReceiptEquivalentStageCount'], 0)

    def test_ten_historical_controls_are_proven_without_authority(self):
        result = self.result()
        self.assertEqual(result['provenHistoricalControlCount'], 10)
        self.assertFalse(result['devLiveExecutionAuthorized'])

    def test_exact_eight_blocking_gaps_are_reported(self):
        result = self.result()
        self.assertEqual(result['blockingGapCount'], 8)
        self.assertEqual(result['blockingGapIds'], [
            row['id'] for row in review.expected_gap_rows()
            if row['blocksDevLiveTransport']])

    def test_history_and_synthetic_receipts_are_not_reusable(self):
        result = self.result()
        self.assertFalse(result['historicalApprovalsReusable'])
        self.assertFalse(result['syntheticReceiptsReusableForLive'])

    def test_dev_test_and_prod_live_boundaries_remain_closed(self):
        result = self.result()
        self.assertFalse(result['devLiveTransportReady'])
        self.assertFalse(result['testLiveEnabled'])
        self.assertFalse(result['prodLiveEnabled'])

    def test_stage_order_is_exact(self):
        self.assertEqual(tuple(row['stage'] for row in review.expected_stage_rows()),
                         review.STAGES)

    def test_external_secret_drain_is_explicitly_absent_in_history(self):
        row = next(row for row in review.expected_stage_rows()
                   if row['stage'] == 'drain-external-secrets')
        self.assertEqual(row['historicalPublicCoverage'], 'absent')
        self.assertIn('external-secret-drain', row['stageSpecificGapIds'])

    def test_terraform_stages_are_historically_monolithic(self):
        rows = {row['stage']: row for row in review.expected_stage_rows()}
        self.assertEqual(rows['eks-delete']['historicalPublicCoverage'],
                         'monolithic-terraform-destroy')
        self.assertEqual(rows['final-delete']['historicalPublicCoverage'],
                         'monolithic-terraform-destroy')

    def test_legacy_retry_capability_is_not_hidden(self):
        row = next(row for row in review.expected_stage_rows()
                   if row['stage'] == 'eks-delete')
        self.assertIn('legacy-automatic-retry-capability', row['stageSpecificGapIds'])

    def test_fresh_budget_gap_does_not_claim_current_authority(self):
        row = review.expected_gap_rows()[-1]
        self.assertEqual(row['id'], 'fresh-live-inputs-price-budget-window')
        self.assertFalse(row['blocksDevLiveTransport'])
        self.assertFalse(row['historicalEvidenceReusable'])

    def test_chain_version_drift_rejected(self):
        chain, teardown, audit = contracts(); chain['version'] = 'drift'
        self.rejected(chain, teardown, audit)

    def test_chain_status_drift_rejected(self):
        chain, teardown, audit = contracts(); chain['status'] = 'complete'
        self.rejected(chain, teardown, audit)

    def test_chain_stage_count_drift_rejected(self):
        chain, teardown, audit = contracts()
        chain['offlineChainExercise']['orderedPhaseCount'] = 7
        self.rejected(chain, teardown, audit)

    def test_chain_operation_count_drift_rejected(self):
        chain, teardown, audit = contracts()
        chain['offlineChainExercise']['closedOperationCount'] = 24
        self.rejected(chain, teardown, audit)

    def test_chain_fixed_fake_boundary_drift_rejected(self):
        chain, teardown, audit = contracts()
        chain['offlineChainExercise']['fixedFakeTransportOnly'] = False
        self.rejected(chain, teardown, audit)

    def test_chain_live_enable_rejected(self):
        chain, teardown, audit = contracts(); chain['devLiveEnabled'] = True
        self.rejected(chain, teardown, audit)

    def test_chain_cloud_effect_rejected(self):
        chain, teardown, audit = contracts()
        chain['effectFlags']['cloudTransport'] = True
        self.rejected(chain, teardown, audit)

    def test_teardown_version_drift_rejected(self):
        chain, teardown, audit = contracts(); teardown['version'] = 'drift'
        self.rejected(chain, teardown, audit)

    def test_teardown_resource_count_drift_rejected(self):
        chain, teardown, audit = contracts()
        teardown['execution']['terraformDestroyedResourceCount'] = 89
        self.rejected(chain, teardown, audit)

    def test_historical_retry_outcome_drift_rejected(self):
        chain, teardown, audit = contracts()
        teardown['execution']['automaticRetryPerformed'] = True
        self.rejected(chain, teardown, audit)

    def test_historical_retry_approval_drift_rejected(self):
        chain, teardown, audit = contracts()
        teardown['approval']['automaticRetryApproved'] = True
        self.rejected(chain, teardown, audit)

    def test_historical_evidence_cannot_authorize_execution(self):
        chain, teardown, audit = contracts(); teardown['executionAuthorized'] = True
        self.rejected(chain, teardown, audit)

    def test_audit_version_drift_rejected(self):
        chain, teardown, audit = contracts(); audit['version'] = 'drift'
        self.rejected(chain, teardown, audit)

    def test_nonempty_final_state_rejected(self):
        chain, teardown, audit = contracts()
        audit['reviewedPreflight']['terraformStateResourceCount'] = 1
        self.rejected(chain, teardown, audit)

    def test_failed_residual_audit_rejected(self):
        chain, teardown, audit = contracts(); audit['execution']['auditPassed'] = False
        self.rejected(chain, teardown, audit)

    def test_continuing_cost_identity_rejected(self):
        chain, teardown, audit = contracts()
        audit['execution']['continuingCostIdentityFound'] = True
        self.rejected(chain, teardown, audit)

    def test_audit_mutation_claim_rejected(self):
        chain, teardown, audit = contracts()
        audit['execution']['mutationExecuted'] = True
        self.rejected(chain, teardown, audit)

    def test_manifest_extra_key_rejected(self):
        reviewed = manifest(); reviewed['authorized'] = False
        self.rejected(reviewed=reviewed)

    def test_manifest_stage_reorder_rejected(self):
        reviewed = manifest()
        reviewed['stageRows'][0], reviewed['stageRows'][1] = (
            reviewed['stageRows'][1], reviewed['stageRows'][0])
        self.rejected(reviewed=reviewed)

    def test_manifest_offline_coverage_overclaim_rejected(self):
        reviewed = manifest(); reviewed['stageRows'][0]['offlineFixedFakeCoverage'] = 'live'
        self.rejected(reviewed=reviewed)

    def test_manifest_historical_receipt_overclaim_rejected(self):
        reviewed = manifest()
        reviewed['stageRows'][0]['historicalLiveReceiptEquivalent'] = True
        self.rejected(reviewed=reviewed)

    def test_manifest_gap_omission_rejected(self):
        reviewed = manifest(); reviewed['gapRows'].pop()
        self.rejected(reviewed=reviewed)

    def test_manifest_blocking_gap_downgrade_rejected(self):
        reviewed = manifest(); reviewed['gapRows'][0]['blocksDevLiveTransport'] = False
        self.rejected(reviewed=reviewed)

    def test_manifest_proven_control_omission_rejected(self):
        reviewed = manifest(); reviewed['provenHistoricalControls'].pop()
        self.rejected(reviewed=reviewed)

    def test_manifest_historical_capability_drift_rejected(self):
        reviewed = manifest()
        reviewed['historicalSourceCapabilities']['perStageReceiptChain'] = True
        self.rejected(reviewed=reviewed)

    def test_review_does_not_mutate_inputs(self):
        chain, teardown, audit = contracts(); reviewed = manifest()
        before = copy.deepcopy((chain, teardown, audit, reviewed))
        review.review_dev_live_parity(chain, teardown, audit, reviewed)
        self.assertEqual((chain, teardown, audit, reviewed), before)

    def test_core_ast_has_no_io_clock_environment_or_transport(self):
        tree = ast.parse((ROOT / 'scripts/guarded_dev_live_parity_review_v67714.py').read_text())
        forbidden = {'boto3', 'botocore', 'subprocess', 'socket', 'urllib', 'requests',
                     'os', 'pathlib', 'datetime', 'time'}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertFalse(imported & forbidden)

    def test_legacy_source_contains_second_destroy_path_but_new_review_does_not_execute_it(self):
        source = (ROOT / 'scripts/destroy-aws-dev.sh').read_text()
        self.assertGreaterEqual(source.count('run_terraform_destroy'), 3)
        tree = ast.parse(
            (ROOT / 'scripts/guarded_dev_live_parity_review_v67714.py').read_text())
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute)}
        self.assertFalse(calls & {'run', 'Popen', 'system'})


if __name__ == '__main__':
    unittest.main(verbosity=2)

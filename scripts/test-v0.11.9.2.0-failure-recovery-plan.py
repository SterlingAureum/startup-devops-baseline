#!/usr/bin/env python3
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'failure_recovery', ROOT / 'scripts/check-v0.11.9.2.0-failure-recovery-plan.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def plan():
    image_id = 'containerd://sha256:' + 'b' * 64
    return {
        'schema_version': 'v0.11.9.2.0-plan-v1', 'environment': 'local',
        'branch': M.BRANCH, 'source_commit': 'a' * 40, 'context': 'kind-demo',
        'review_reference': 'ticket-92', 'operator': 'tester', 'recovery_owner': 'owner',
        'evidence_directory': '/tmp/private-failure-recovery',
        'baseline': {'application_version': 'healthy-1', 'release_id': 'release-1',
                     'rollout_uid': 'rollout-uid-1', 'image_reference': 'demo:test',
                     'runtime_image_id': image_id, 'fault_mode': 'disabled'},
        'candidate': {'application_version': 'reject-2', 'image_reference': 'demo:test',
                      'runtime_image_id': image_id, 'fault_mode': 'availability-503'},
        'fault': {'mechanism': 'candidate-version-header-availability',
                  'service': 'demo-api-canary', 'route': '/version',
                  'header_name': 'X-Rehearsal-Fault', 'response_status': 503,
                  'max_requests': 80, 'max_seconds': 180, 'cleanup_max_seconds': 300},
        'expected_rejection': {'metric': 'canary-availability-error-budget-burn-rate',
                               'analysis_phase': 'Failed', 'provider_error_accepted': False,
                               'no_data_accepted': False},
        'recovery': {'method': 'gitops-known-good-baseline-restore',
                     'manual_authorization_required': True, 'max_seconds': 600},
        'whole_rehearsal_max_seconds': 1800,
    }


class Tests(unittest.TestCase):
    def test_positive_is_offline_and_non_authorizing(self):
        result = M.validate(plan())
        self.assertEqual(result['status'], 'failure_recovery_plan_validated_offline')
        self.assertFalse(result['runtime_qualified'])
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['fault_implemented'])

    def test_top_level_and_target_rejections(self):
        mutations = [
            lambda p: p.update(execute=True), lambda p: p.pop('operator'),
            lambda p: p.update(environment='aws-dev'), lambda p: p.update(branch='main'),
            lambda p: p.update(source_commit='short'), lambda p: p.update(context='minikube'),
            lambda p: p.update(evidence_directory='relative'),
            lambda p: p.update(evidence_directory='/REPLACE_PRIVATE'),
            lambda p: p['fault'].update(service='demo-api-stable'),
            lambda p: p['fault'].update(route='/missing'), lambda p: p['fault'].update(response_status=200),
        ]
        for mutate in mutations:
            value = plan()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                M.validate(value)

    def test_identity_and_isolation_rejections(self):
        mutations = [
            lambda p: p['candidate'].update(application_version=p['baseline']['application_version']),
            lambda p: p['candidate'].update(image_reference='demo:other'),
            lambda p: p['candidate'].update(image_reference='not tagged'),
            lambda p: p['candidate'].update(application_version='bad version'),
            lambda p: p['candidate'].update(runtime_image_id='containerd://sha256:' + 'c' * 64),
            lambda p: p['baseline'].update(fault_mode='availability-503'),
            lambda p: p['candidate'].update(fault_mode='disabled'),
            lambda p: p['baseline'].update(runtime_image_id='sha256:bad'),
        ]
        for mutate in mutations:
            value = plan()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                M.validate(value)

    def test_bounds_and_false_failure_rejections(self):
        mutations = [
            lambda p: p['fault'].update(max_requests=81),
            lambda p: p['fault'].update(max_seconds=True),
            lambda p: p['fault'].update(cleanup_max_seconds=301),
            lambda p: p['expected_rejection'].update(provider_error_accepted=True),
            lambda p: p['expected_rejection'].update(no_data_accepted=True),
            lambda p: p['recovery'].update(manual_authorization_required=False),
            lambda p: p['recovery'].update(max_seconds=601),
            lambda p: p.update(whole_rehearsal_max_seconds=1801),
        ]
        for mutate in mutations:
            value = plan()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                M.validate(value)

    def test_unedited_template_is_rejected_by_cli(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/check-v0.11.9.2.0-failure-recovery-plan.py'),
             '--plan', str(ROOT / 'delivery/examples/v0.11.9.2.0-local-failure-recovery-plan.json')],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('No execution is authorized', result.stderr)

    def test_contract_boundaries(self):
        contract = json.loads((ROOT / 'delivery/contracts/v0.11.9.2.0-local-failure-recovery-design.json').read_text())
        self.assertFalse(contract['execution_authorized'])
        self.assertFalse(contract['fault_implemented'])
        self.assertFalse(contract['automatic_promote'])
        self.assertFalse(contract['automatic_retry'])
        self.assertFalse(contract['automatic_abort'])
        self.assertFalse(contract['automatic_rollback'])
        self.assertEqual(contract['failure_target']['metric'],
                         'canary-availability-error-budget-burn-rate')


if __name__ == '__main__':
    unittest.main()

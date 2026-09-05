#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'local_failure_recovery', ROOT / 'scripts/local-failure-recovery-rehearsal.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

SHA = 'a' * 40
IMAGE_ID = 'containerd://sha256:' + 'b' * 64
TOKEN = 'fixed-private-token'
DIGEST = hashlib.sha256(TOKEN.encode()).hexdigest()


def pod(uid, version, release, pod_hash, mode='disabled', digest=''):
    return {'metadata': {'uid': uid, 'labels': {'app': 'demo', 'rollouts-pod-template-hash': pod_hash},
                         'annotations': {M.BASE.ANN + 'application-version': version,
                                         M.BASE.ANN + 'release-id': release}},
            'spec': {'containers': [{'name': 'demo-api', 'image': 'demo:test', 'env': [
                {'name': 'REHEARSAL_FAULT_MODE', 'value': mode},
                {'name': 'REHEARSAL_FAULT_TOKEN_SHA256', 'value': digest}]}]},
            'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                       'containerStatuses': [{'name': 'demo-api', 'ready': True, 'imageID': IMAGE_ID}]}}


def fixture(candidate=False, aborted=False, restored=False):
    version = 'healthy-1' if not candidate or restored else 'reject-2'
    release = 'baseline-release' if not candidate or restored else 'candidate-release'
    status = {'phase': 'Healthy' if not candidate or restored else 'Degraded',
              'currentPodHash': 'hash1' if not candidate or restored else 'hash2',
              'stableRS': 'hash1', 'readyReplicas': 1 if not candidate or restored else 2,
              'availableReplicas': 1 if not candidate or restored else 2}
    if aborted:
        status['abort'] = True
    rollout = {'metadata': {'uid': 'rollout-uid', 'annotations': {
                   M.BASE.ANN + 'application-version': version, M.BASE.ANN + 'release-id': release}},
               'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'demo'}},
                        'template': {'spec': {'containers': [{'name': 'demo-api', 'image': 'demo:test',
                          'imagePullPolicy': 'Never', 'env': [
                            {'name': 'REHEARSAL_FAULT_MODE',
                             'value': 'availability-503' if candidate and not restored else 'disabled'},
                            {'name': 'REHEARSAL_FAULT_TOKEN_SHA256',
                             'value': DIGEST if candidate and not restored else ''}]}]}}},
               'status': status}
    pods = [pod('stable-pod', 'healthy-1', 'baseline-release', 'hash1')]
    if candidate and not restored:
        pods.append(pod('candidate-pod', 'reject-2', 'candidate-release', 'hash2',
                        'availability-503', DIGEST))
    analysis = {'metadata': {'uid': 'failed-analysis', 'creationTimestamp': '2099-01-01T00:00:00Z'},
                'spec': {'args': [{'name': 'expected-release-id', 'value': 'candidate-release'}]},
                'status': {'phase': 'Failed', 'metricResults': [
                    {'name': 'canary-availability-error-budget-burn-rate', 'phase': 'Failed',
                     'measurements': [{'value': '100'}]}]}}
    return {'rollout': rollout, 'pods': {'items': pods},
            'stable_service': {'spec': {'selector': {'rollouts-pod-template-hash': 'hash1'}}},
            'stable_endpoints': {'subsets': [{'addresses': [{'targetRef': {'uid': 'stable-pod'}}]}]},
            'analyses': {'items': [analysis] if candidate or restored else []},
            'analysis_template': {'spec': {'metrics': []}}, 'applications': []}


def plan(bundle):
    return {'schema_version': 'v0.11.9.2.0-plan-v1', 'environment': 'local',
            'branch': M.PLAN.BRANCH, 'source_commit': SHA, 'context': 'kind-demo',
            'review_reference': 'review-92', 'operator': 'tester', 'recovery_owner': 'owner',
            'evidence_directory': str(bundle),
            'baseline': {'application_version': 'healthy-1', 'release_id': 'baseline-release',
                         'rollout_uid': 'rollout-uid', 'image_reference': 'demo:test',
                         'runtime_image_id': IMAGE_ID, 'fault_mode': 'disabled'},
            'candidate': {'application_version': 'reject-2', 'image_reference': 'demo:test',
                          'runtime_image_id': IMAGE_ID, 'fault_mode': 'availability-503'},
            'fault': {'mechanism': 'candidate-version-header-availability',
                      'service': 'demo-api-canary', 'route': '/version',
                      'header_name': 'X-Rehearsal-Fault', 'response_status': 503,
                      'max_requests': 80, 'max_seconds': 180, 'cleanup_max_seconds': 300},
            'expected_rejection': {'metric': 'canary-availability-error-budget-burn-rate',
                                   'analysis_phase': 'Failed', 'provider_error_accepted': False,
                                   'no_data_accepted': False},
            'recovery': {'method': 'gitops-known-good-baseline-restore',
                         'manual_authorization_required': True, 'max_seconds': 600},
            'whole_rehearsal_max_seconds': 1800}


class Tests(unittest.TestCase):
    def test_fault_isolation(self):
        value = fixture(candidate=True)
        M.assert_fault_isolation(value, plan('/tmp/evidence'), DIGEST, True)
        value['pods']['items'][0]['spec']['containers'][0]['env'][0]['value'] = 'availability-503'
        with self.assertRaisesRegex(ValueError, 'Stable Pod'):
            M.assert_fault_isolation(value, plan('/tmp/evidence'), DIGEST, True)

    def test_failed_analysis_requires_exact_measured_metric(self):
        value = fixture(candidate=True)
        state = {'candidate_release_id': 'candidate-release', 'old_analysis_uids': []}
        self.assertEqual(M.failed_analysis(value, state), 'failed-analysis')
        for mutation in ('phase', 'measurement', 'provider'):
            changed = copy.deepcopy(value)
            result = changed['analyses']['items'][0]['status']['metricResults'][0]
            if mutation == 'phase':
                changed['analyses']['items'][0]['status']['phase'] = 'Error'
            elif mutation == 'measurement':
                result['measurements'] = []
            else:
                result['phase'] = 'Error'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                M.failed_analysis(changed, state)

    def test_phase_confirmations_are_distinct(self):
        self.assertEqual(set(M.PHASES), set(M.CONFIRM))
        self.assertEqual(len(set(M.CONFIRM.values())), 5)
        self.assertEqual(M.CONFIRM['traffic'], 'generate-reviewed-candidate-fault-traffic')
        self.assertEqual(M.CONFIRM['restore'], 'restore-reviewed-local-baseline')

    def test_complete_mocked_phase_sequence(self):
        baseline = fixture()
        candidate = fixture(candidate=True)
        aborted = fixture(candidate=True, aborted=True)
        restored = fixture(candidate=True, restored=True)
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / 'bundle'
            source = Path(tmp) / 'plan.json'
            source.write_text(json.dumps(plan(bundle)))
            args = Namespace(phase='prepare', bundle=str(bundle), plan=str(source),
                             review=None, confirm='observe-local')
            with patch.object(M.BASE, 'isolated', return_value=({}, 'cluster-uid', 'https://127.0.0.1:6443')), \
                    patch.object(M.BASE, 'git_identity', return_value=SHA), \
                    patch.object(M.BASE, 'snapshot') as snapshot, \
                    patch.object(M.BASE, 'bounded_command') as command, \
                    patch.object(M, 'wait_arm', return_value=candidate), \
                    patch.object(M.secrets, 'token_urlsafe', return_value=TOKEN):
                snapshot.return_value = baseline
                M.execute(args)
                args.plan = None
                args.phase, args.confirm = 'arm', 'deploy-reviewed-local-fault-candidate'
                M.execute(args)
                args.phase, args.confirm = 'traffic', 'generate-reviewed-candidate-fault-traffic'
                snapshot.side_effect = [candidate, candidate]
                M.execute(args)
                snapshot.side_effect = None
                snapshot.return_value = candidate
                args.phase, args.confirm, args.review = 'rejection-review', 'observe-local', 'review-92'
                M.execute(args)
                snapshot.return_value = aborted
                args.phase, args.review = 'abort-check', None
                M.execute(args)
                args.phase, args.confirm, args.review = 'recovery-approval', 'approve-reviewed-local-recovery', 'review-92'
                M.execute(args)
                args.phase, args.confirm, args.review = 'restore', 'restore-reviewed-local-baseline', None
                snapshot.side_effect = [aborted, restored]
                M.execute(args)
                snapshot.side_effect = None
                snapshot.return_value = restored
                args.phase, args.confirm = 'final', 'observe-local'
                M.execute(args)
                self.assertEqual(command.call_count, 3)
            self.assertTrue(json.loads((bundle / 'final.passed.json').read_text())['runtime_qualified'])
            self.assertEqual((bundle / 'fault-token.private').stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, 'already passed'):
                with patch.object(M.BASE, 'isolated', return_value=({}, 'cluster-uid', 'https://127.0.0.1:6443')), \
                        patch.object(M.BASE, 'git_identity', return_value=SHA):
                    M.execute(args)


if __name__ == '__main__':
    unittest.main()

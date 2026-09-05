#!/usr/bin/env python3
import importlib.util
import json
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'prepare_failure_recovery_plan',
    ROOT / 'scripts/prepare-local-failure-recovery-live-plan.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

SHA = 'a' * 40
IMAGE_ID = 'containerd://sha256:' + 'b' * 64


def fixture():
    rollout = {'metadata': {'uid': 'rollout-uid', 'annotations': {
                   M.BASE.ANN + 'application-version': 'healthy-1',
                   M.BASE.ANN + 'release-id': 'baseline-release'}},
               'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': 'demo'}},
                        'strategy': {'canary': {'steps': [
                            {'setWeight': 20}, {'pause': {'duration': '1m'}},
                            {'analysis': {'templates': [{'templateName': 'demo-api-canary-health'}]}},
                            {'setWeight': 50}, {'pause': {}},
                            {'analysis': {'templates': [{'templateName': 'demo-api-canary-health'}]}},
                            {'setWeight': 100}]}},
                        'template': {'spec': {'containers': [{'name': 'demo-api',
                          'image': 'demo:test', 'imagePullPolicy': 'Never', 'env': [
                            {'name': 'REHEARSAL_FAULT_MODE', 'value': 'disabled'},
                            {'name': 'REHEARSAL_FAULT_TOKEN_SHA256', 'value': ''}]}]}}},
               'status': {'phase': 'Healthy', 'currentPodHash': 'hash1', 'stableRS': 'hash1',
                          'readyReplicas': 1, 'availableReplicas': 1}}
    pod = {'metadata': {'uid': 'pod-uid', 'labels': {'app': 'demo',
            'rollouts-pod-template-hash': 'hash1'}, 'annotations': {
            M.BASE.ANN + 'application-version': 'healthy-1',
            M.BASE.ANN + 'release-id': 'baseline-release'}},
           'spec': {'containers': [{'name': 'demo-api', 'image': 'demo:test', 'env': [
               {'name': 'REHEARSAL_FAULT_MODE', 'value': 'disabled'},
               {'name': 'REHEARSAL_FAULT_TOKEN_SHA256', 'value': ''}]}]},
           'status': {'conditions': [{'type': 'Ready', 'status': 'True'}],
                      'containerStatuses': [{'name': 'demo-api', 'ready': True,
                                            'imageID': IMAGE_ID}]}}
    metrics = [{'name': name} for name in M.BASE.METRICS]
    return {'rollout': rollout, 'pods': {'items': [pod]}, 'analyses': {'items': []},
            'stable_service': {'spec': {'selector': {'rollouts-pod-template-hash': 'hash1'}}},
            'stable_endpoints': {'subsets': [{'addresses': [{'targetRef': {'uid': 'pod-uid'}}]}]},
            'analysis_template': {'spec': {'metrics': metrics}}, 'applications': []}


class Tests(unittest.TestCase):
    def args(self, directory):
        return Namespace(context='kind-demo', candidate_version='reject-2', review='review-92',
                         operator='tester', recovery_owner='owner',
                         plan=str(Path(directory) / 'plan.json'),
                         bundle=str(Path(directory) / 'bundle'), max_requests=80,
                         analysis_wait_seconds=180, confirm='observe-and-write-local-plan')

    def test_builds_exact_private_plan_from_healthy_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp)
            with patch.object(M.BASE, 'isolated', return_value=({}, 'uid', 'https://127.0.0.1')), \
                    patch.object(M.BASE, 'git_identity', return_value=SHA), \
                    patch.object(M.BASE, 'snapshot', return_value=fixture()):
                M.create(args)
            plan = json.loads(Path(args.plan).read_text())
            self.assertEqual(plan['source_commit'], SHA)
            self.assertEqual(plan['baseline']['runtime_image_id'], IMAGE_ID)
            self.assertEqual(plan['candidate']['runtime_image_id'], IMAGE_ID)
            self.assertEqual(Path(args.plan).stat().st_mode & 0o777, 0o600)
            self.assertFalse(Path(args.bundle).exists())

    def test_rejects_existing_bundle_before_runtime_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp)
            Path(args.bundle).mkdir()
            with self.assertRaisesRegex(ValueError, 'bundle already exists'):
                M.create(args)


if __name__ == '__main__':
    unittest.main()

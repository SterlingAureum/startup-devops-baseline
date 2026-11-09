#!/usr/bin/env python3
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rehearsal', ROOT / 'scripts/local-release-rehearsal.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture():
    return {'analysis_template': {'spec': {'metrics': [{'name': k} for k in m.METRICS]}},
            'rollout': {'metadata': {'uid': 'r1', 'annotations': {m.ANN + 'application-version': 'v2', m.ANN + 'release-id': 'release2'}},
                       'spec': {'strategy': {'canary': {'steps': [{'setWeight': 20}, {'pause': {'duration': '60s'}}, {'analysis': {'templates': [{'templateName': 'demo-api-canary-health'}]}}, {'setWeight': 50}, {'pause': {}}, {'analysis': {'templates': [{'templateName': 'demo-api-canary-health'}]}}, {'setWeight': 100}]}},
                                'replicas': 1, 'selector': {'matchLabels': {'app': 'demo'}},
                                'template': {'spec': {'containers': [{'name': 'demo-api', 'image': 'demo:test', 'imagePullPolicy': 'Never'}]}}},
                       'status': {'phase': 'Healthy', 'currentPodHash': 'hash2', 'stableRS': 'hash2', 'readyReplicas': 1, 'availableReplicas': 1}},
            'pods': {'items': [{'metadata': {'uid': 'p1', 'labels': {'app': 'demo', 'rollouts-pod-template-hash': 'hash2'}, 'annotations': {m.ANN + 'application-version': 'v2'}},
                                'spec': {'containers': [{'name': 'demo-api', 'image': 'demo:test'}]},
                                'status': {'containerStatuses': [{'name': 'demo-api', 'ready': True, 'imageID': 'containerd://sha256:abc'}]}}]},
            'stable_service': {'spec': {'selector': {'rollouts-pod-template-hash': 'hash2'}}},
            'stable_endpoints': {'subsets': [{'addresses': [{'targetRef': {'uid': 'p1'}}]}]},
            'analyses': {'items': [{'metadata': {'uid': 'a' + str(n), 'creationTimestamp': '2026-09-03T01:00:00Z', 'ownerReferences': [{'kind': 'Rollout', 'uid': 'r1'}]},
                                    'spec': {'args': [{'name': 'expected-release-id', 'value': 'release2'}]},
                                    'status': {'phase': 'Successful', 'metricResults': [{'name': k, 'phase': 'Successful'} for k in sorted(m.METRICS)]}} for n in (1, 2)]}}


class Tests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()
        self.plan = {'rollout_uid': 'r1', 'baseline_release_id': 'release1', 'old_analysis_uids': [], 'started_at': '2026-09-03T00:00:00+00:00'}

    def test_positive(self):
        m.gate_profile(self.data)
        m.healthy(self.data['rollout'])
        m.stable_ready(self.data)
        self.assertEqual(m.image_identity(self.data, 'v2')['reference'], 'demo:test')
        self.assertEqual(m.fresh_analyses(self.data, self.plan, 2), ['a1', 'a2'])

    def test_missing_gate_profile(self):
        self.data['analysis_template']['spec']['metrics'].pop()
        with self.assertRaises(ValueError):
            m.gate_profile(self.data)

    def test_health_and_endpoints(self):
        for key, value in [('phase', 'Paused'), ('stableRS', 'old'), ('readyReplicas', 0), ('abort', True)]:
            data = copy.deepcopy(self.data)
            data['rollout']['status'][key] = value
            with self.assertRaises(ValueError):
                m.healthy(data['rollout'])
        self.data['stable_endpoints']['subsets'] = []
        with self.assertRaises(ValueError):
            m.stable_ready(self.data)

    def test_image_and_version(self):
        with self.assertRaises(ValueError):
            m.image_identity(self.data, 'old')
        self.data['pods']['items'][0]['status']['containerStatuses'][0]['ready'] = False
        with self.assertRaises(ValueError):
            m.image_identity(self.data, 'v2')

    def test_stale_duplicate_owner_failed_metric(self):
        mutations = [lambda d: d['analyses']['items'].pop(),
                     lambda d: d['analyses']['items'][1]['metadata'].update(uid='a1'),
                     lambda d: d['analyses']['items'][0]['metadata'].update(creationTimestamp='2020-01-01T00:00:00Z'),
                     lambda d: d['analyses']['items'][0]['metadata'].update(ownerReferences=[]),
                     lambda d: d['analyses']['items'][0]['status'].update(phase='Error'),
                     lambda d: d['analyses']['items'][0]['status']['metricResults'].pop(),
                     lambda d: d['rollout']['metadata'].update(uid='recreated')]
        for mutate in mutations:
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.assertRaises(ValueError):
                m.fresh_analyses(data, self.plan, 2)
        self.plan['old_analysis_uids'] = ['a1']
        with self.assertRaises(ValueError):
            m.fresh_analyses(self.data, self.plan, 2)

    def test_context_rejected_before_io(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'run') as run:
            with self.assertRaises(ValueError):
                m.isolated('arn:aws:eks:prod', Path(tmp))
            run.assert_not_called()

    def test_remote_api_rejected(self):
        config = {'clusters': [{'cluster': {'server': 'https://remote.example:6443'}}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(m.shutil, 'which', return_value='/usr/bin/tool'), patch.object(m, 'run', return_value=json.dumps(config)):
            with self.assertRaises(ValueError):
                m.isolated('kind-demo', Path(tmp))

    def test_git_guards(self):
        for outputs in (['dirty'], ['', 'main'], ['', m.BRANCH, 'a' * 40, 'b' * 40 + '\trefs/heads/x']):
            with patch.object(m, 'run', side_effect=outputs), self.assertRaises(ValueError):
                m.git_identity()

    def test_command_failure_and_group_cleanup(self):
        with patch.object(m.subprocess, 'Popen') as popen, patch.object(m.os, 'killpg') as kill:
            popen.return_value.stdout = io.StringIO('visible output\n')
            popen.return_value.wait.return_value = 1
            retained = io.StringIO()
            with patch('builtins.print') as output, self.assertRaises(ValueError):
                m.bounded_command(['false'], {}, retained)
            self.assertEqual(retained.getvalue(), 'visible output\n')
            output.assert_any_call('visible output\n', end='', flush=True)
            self.assertEqual(kill.call_count, 2)

    def test_bundle_input_diagnostic(self):
        with self.assertRaisesRegex(ValueError, 'do not enter REHEARSAL_DIR'):
            m.bundle_path('REHEARSAL_DIR=/tmp/local-release-rehearsal.ABC123/run')
        self.assertEqual(m.bundle_path('/tmp/local-release-rehearsal.ABC123/run'),
                         Path('/tmp/local-release-rehearsal.ABC123/run'))

    def test_transient_release_pod_readiness_converges(self):
        waiting = copy.deepcopy(self.data)
        waiting['pods']['items'][0]['status']['containerStatuses'][0]['ready'] = False
        expected = m.image_identity(self.data, 'v2')
        with patch.object(m, 'snapshot', side_effect=[waiting, self.data]), \
                patch.object(m.time, 'sleep'), patch('builtins.print'):
            observed, identity = m.wait_snapshot_identity({}, 'v2', expected, timeout=1, poll=0)
        self.assertIs(observed, self.data)
        self.assertEqual(identity, expected)

    def test_exclusive_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'evidence.json'
            m.write(path, {'one': 1})
            with self.assertRaises(FileExistsError):
                m.write(path, {'two': 2})

    def test_complete_mocked_phase_sequence(self):
        baseline = fixture()
        candidate = fixture()
        baseline['rollout']['metadata']['annotations'][m.ANN + 'application-version'] = 'v1'
        baseline['rollout']['metadata']['annotations'][m.ANN + 'release-id'] = 'release1'
        baseline['pods']['items'][0]['metadata']['annotations'][m.ANN + 'application-version'] = 'v1'
        baseline['analyses']['items'] = []
        candidate['applications'] = [{'spec': {'source': {'repoURL': m.REPO, 'targetRevision': 'a' * 40}},
                                      'status': {'sync': {'revision': 'a' * 40, 'status': 'Synced'}}}] * 2
        for a in candidate['analyses']['items']:
            a['metadata']['creationTimestamp'] = '2099-01-01T00:00:00Z'
        with tempfile.TemporaryDirectory() as tmp, patch.object(m, 'isolated', return_value=({}, 'cluster1', 'https://127.0.0.1:6443')), patch.object(m, 'git_identity', return_value='a' * 40), patch.object(m, 'bounded_command') as command, patch.object(m, 'snapshot') as snapshot:
            args = Namespace(bundle=Path(tmp) / 'bundle', phase='prepare', context='kind-demo', version='v2', review='ticket-1', recovery_owner='tester', confirm='observe-local')
            snapshot.return_value = baseline
            m.execute(args)
            args.phase, args.confirm = 'deploy', 'deploy-reviewed-local'
            snapshot.side_effect = [baseline, candidate]
            m.execute(args)
            snapshot.side_effect = None
            snapshot.return_value = candidate
            for phase in ('first-analysis', 'human-review', 'second-analysis', 'final'):
                args.phase = phase
                args.confirm = 'generate-local-traffic' if 'analysis' in phase else 'observe-local'
                m.execute(args)
            self.assertTrue(json.loads((args.bundle / 'final.passed.json').read_text())['runtime_qualified'])
            self.assertEqual(command.call_count, 5)
            with self.assertRaises(ValueError):
                m.execute(args)


if __name__ == '__main__':
    unittest.main()

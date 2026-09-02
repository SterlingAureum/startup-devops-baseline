#!/usr/bin/env python3
"""Offline safety tests; all AWS/Kubernetes calls are mocked."""
import copy
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
import aws_test_feature_common as c


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, c.ROOT / 'scripts' / path)
    item = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(item)
    return item


prepare = module('prepare', 'prepare-aws-test-feature.py')
observe = module('observe', 'check-aws-test-observability-qualification.py')
ACCOUNT = '123456789012'
SHA = 'a' * 40
IMAGE = 'example/demo@sha256:' + 'b' * 64


def plan_document():
    variables = {'environment': 'test', 'project_name': 'startup-devops-baseline', 'aws_region': c.REGION,
                 'eks_node_min_size': 4, 'eks_node_desired_size': 4, 'eks_node_max_size': 4,
                 'eks_public_access_cidrs': ['8.8.8.8/32']}
    return {'variables': {k: {'value': v} for k, v in variables.items()}, 'resource_changes': [
        {'type': 'aws_eks_cluster', 'change': {'actions': ['create'], 'after': {'name': c.CLUSTER, 'tags_all': {'Environment': 'test'}}}}]}


def rollout():
    return {'metadata': {'generation': 1, 'annotations': {'platform.startup.dev/application-version': 'v-test'}},
            'spec': {'replicas': 2, 'template': {'spec': {'containers': [{'name': 'demo-api', 'image': IMAGE}]}}},
            'status': {'phase': 'Healthy', 'observedGeneration': 1, 'replicas': 2, 'updatedReplicas': 2,
                       'readyReplicas': 2, 'availableReplicas': 2, 'stableRS': 'abc', 'currentPodHash': 'abc'}}


class Guards(unittest.TestCase):
    def test_environment_drops_target_injection(self):
        with patch.dict(os.environ, {'TF_VAR_environment': 'prod', 'TF_CLI_ARGS': '-destroy',
                                    'CLUSTER_NAME': 'dev', 'KUBECONFIG': '/wrong', 'AWS_ENDPOINT_URL': 'http://wrong'}):
            env = c.environment()
        self.assertEqual(env['CLUSTER_NAME'], c.CLUSTER)
        for key in ('TF_VAR_environment', 'TF_CLI_ARGS', 'KUBECONFIG', 'AWS_ENDPOINT_URL'):
            self.assertNotIn(key, env)

    def test_preflight_positive_and_each_mismatch(self):
        good = [c.BRANCH, '', SHA, SHA + '\trefs/heads/' + c.BRANCH]
        with patch.object(c, 'git', side_effect=good), patch.object(c, 'aws', return_value=ACCOUNT):
            c.preflight(ACCOUNT, SHA)
        for i, wrong in enumerate(('main', ' M script.py', 'b' * 40, 'c' * 40)):
            values = good.copy()
            values[i] = wrong
            with self.subTest(i=i), patch.object(c, 'git', side_effect=values), patch.object(c, 'aws', return_value=ACCOUNT):
                with self.assertRaises(RuntimeError):
                    c.preflight(ACCOUNT, SHA)
        with patch.object(c, 'git', side_effect=good), patch.object(c, 'aws', return_value='999999999999'):
            with self.assertRaises(RuntimeError):
                c.preflight(ACCOUNT, SHA)

    def test_discovery_is_fail_closed(self):
        for error in ('AccessDeniedException', 'EndpointConnectionError', 'expired token'):
            with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=error)):
                with self.assertRaises(RuntimeError):
                    c.discover(ACCOUNT)
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr='ResourceNotFoundException')):
            self.assertIsNone(c.discover(ACCOUNT))

    def test_rbac_denial_is_not_an_api_failure(self):
        for rc, text, expected in ((0, 'yes\n', True), (1, 'no\n', False)):
            with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=rc, stdout=text)):
                self.assertEqual(c.can_i({}, 'get', 'pods'), expected)
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='')):
            with self.assertRaises(RuntimeError):
                c.can_i({}, 'get', 'pods')

    def test_plan_scope_and_negative_changes(self):
        prepare.check_plan(plan_document(), ACCOUNT, '8.8.8.8/32')
        mutations = [
            lambda p: p['variables']['environment'].update(value='prod'),
            lambda p: p['variables']['eks_node_desired_size'].update(value=2),
            lambda p: p['resource_changes'][0]['change'].update(actions=['delete', 'create']),
            lambda p: p['resource_changes'][0]['change']['after'].update(name='startup-devops-baseline-dev'),
            lambda p: p['resource_changes'][0]['change']['after'].update(arn='arn:aws:eks:us-east-1:999999999999:cluster/test'),
            lambda p: p['resource_changes'][0]['change']['after'].update(tags_all={'Environment': 'prod'}),
        ]
        for mutation in mutations:
            p = plan_document()
            mutation(p)
            with self.assertRaises(RuntimeError):
                prepare.check_plan(p, ACCOUNT, '8.8.8.8/32')

    def test_apply_and_bootstrap_require_confirmation(self):
        with patch.object(prepare, 'tf') as tf:
            with self.assertRaises(RuntimeError):
                prepare.apply(SimpleNamespace(confirm='no'))
            with self.assertRaises(RuntimeError):
                prepare.bootstrap(SimpleNamespace(confirm='no'))
            tf.assert_not_called()

    def test_expired_or_modified_plan_never_applies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            plan = path / 'review.tfplan'
            plan.write_bytes(b'test plan')
            record = {'account': ACCOUNT, 'sha': SHA, 'region': c.REGION, 'cluster': c.CLUSTER,
                      'created_at': 0, 'plan_sha256': prepare.digest(plan), 'profile_sha256': prepare.digest(c.PROFILE)}
            for stale in (True, False):
                if not stale:
                    record.update(created_at=prepare.time.time(), plan_sha256='tampered')
                (path / 'review.json').write_text(json.dumps(record))
                with patch.object(prepare, 'tf') as tf:
                    with self.assertRaises(RuntimeError):
                        prepare.apply(SimpleNamespace(confirm='apply-reviewed-aws-test', bundle=directory, account=ACCOUNT, sha=SHA))
                    tf.assert_not_called()

    def test_secret_create_only_no_dev_read(self):
        responses = [json.dumps({'kind': 'Namespace'}), '', 'created']
        with patch.object(c, 'kube', side_effect=responses) as kube:
            prepare.secret({})
        calls = kube.call_args_list
        self.assertEqual(calls[-1].args[1:4], ('create', '-f', '-'))
        self.assertFalse(any('observability-metrics-grafana' in str(call) for call in calls))
        existing = {'data': {'admin-user': 'YWRtaW4=', 'admin-password': 'bG9jYWw='}}
        with patch.object(c, 'kube', side_effect=['{}', json.dumps(existing)]) as kube:
            prepare.secret({})
        self.assertEqual(kube.call_count, 2)

    def test_rollout_negative_cases(self):
        observe.check_rollout(rollout(), 'v-test', IMAGE)
        text_generation = rollout()
        text_generation['status']['observedGeneration'] = '1'
        observe.check_rollout(text_generation, 'v-test', IMAGE)
        mutations = [lambda r: r['status'].update(phase='Paused'),
                     lambda r: r['status'].update(observedGeneration=0),
                     lambda r: r['status'].update(readyReplicas=1),
                     lambda r: r['status'].update(stableRS='old'),
                     lambda r: r['spec']['template']['spec']['containers'][0].update(image='wrong')]
        for mutation in mutations:
            r = rollout()
            mutation(r)
            with self.assertRaises(RuntimeError):
                observe.check_rollout(r, 'v-test', IMAGE)

    def test_source_inventory_is_independent(self):
        source_test = module('source_test', 'test-aws-test-qualification-prerequisites.py')
        contract = json.loads(c.CONTRACT.read_text())
        self.assertEqual(source_test.source_external_charts(), contract['external_charts'])
        self.assertEqual(c.release()[1].split('@')[1][:7], 'sha256:')

    def test_waiting_evidence_is_test_and_not_qualified(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'evidence.json'
            argv = ['observe', '--account', ACCOUNT, '--sha', SHA, '--application-version', 'v-test', '--output', str(output)]
            with patch.object(sys, 'argv', argv), patch.object(c, 'preflight'), patch.object(c, 'run'), patch.object(c, 'discover', return_value=None):
                self.assertEqual(observe.main(), 2)
            evidence = json.loads(output.read_text())
            self.assertEqual(evidence['environment'], 'aws-test')
            self.assertEqual(evidence['status'], 'waiting-runtime')
            self.assertFalse(any(x['status'] == 'supported-verified' for x in evidence['capabilities'].values()))

    def test_bootstrap_orders_secret_before_root_and_reuses_test_only_helpers(self):
        events = []
        def run(args, **kwargs):
            events.append(Path(args[1]).name)
            env = kwargs['env']
            self.assertEqual(env['CLUSTER_NAME'], c.CLUSTER)
            self.assertEqual(env['DEMO_APPLICATION'], 'demo-api-aws-test')
            self.assertEqual(env['TARGET_REVISION'], c.BRANCH)
            root = c.yaml.safe_load(Path(env['SOURCE_FILE']).read_text())
            self.assertEqual(root['spec']['source']['path'], c.OVERLAY)
            self.assertEqual(root['metadata']['name'], 'startup-devops-aws-test-root')
            self.assertIn('automated', root['spec']['syncPolicy'])
            self.assertTrue(root['spec']['ignoreDifferences'])
        args = SimpleNamespace(confirm='bootstrap-reviewed-aws-test', argocd_version='v3.0.0', account=ACCOUNT, sha=SHA)
        with patch.object(prepare, 'initialize'), patch.object(prepare, 'tf', side_effect=[c.CLUSTER, 'test']), \
             patch.object(c, 'kube_env', return_value={'CLUSTER_NAME': c.CLUSTER}), \
             patch.object(c, 'wait_capacity', side_effect=lambda env: events.append('nodes')), \
             patch.object(c, 'kube', return_value=''), \
             patch.object(prepare, 'secret', side_effect=lambda env: events.append('secret')), \
             patch.object(c, 'run', side_effect=run), patch.object(c, 'preflight'):
            prepare.bootstrap(args)
        self.assertEqual(events, ['nodes', 'secret', 'bootstrap-eks-argocd.sh', 'deploy-aws-dev-root-app.sh'])

    def test_application_revision_and_chart_inventory(self):
        contract = json.loads(c.CONTRACT.read_text())
        apps = []
        for name in contract['same_repository_applications'] + ['startup-devops-aws-test-root']:
            apps.append({'metadata': {'name': name}, 'spec': {'source': {'repoURL': c.REPO,
                         'targetRevision': c.BRANCH, 'path': c.OVERLAY}},
                         'status': {'sync': {'status': 'Synced', 'revision': SHA}, 'health': {'status': 'Healthy'}}})
        for chart, version in contract['external_charts'].items():
            apps.append({'metadata': {'name': chart}, 'spec': {'source': {'repoURL': 'https://charts.example.invalid', 'chart': chart, 'targetRevision': version}},
                         'status': {'sync': {'status': 'Synced', 'revision': version}, 'health': {'status': 'Healthy'}}})
        expected = {a['metadata']['name']: copy.deepcopy(a['spec']['source']) for a in apps}
        observe.check_applications(apps, SHA, expected)
        for mutation in (lambda x: x[0]['status']['sync'].update(revision='b' * 40),
                         lambda x: x[0]['spec']['source'].update(targetRevision='main'),
                         lambda x: x[0]['spec']['source'].update(path='clusters/aws/overlays/dev'),
                         lambda x: x[-1]['spec']['source'].update(repoURL='https://wrong.invalid'),
                         lambda x: x[-1]['spec']['source'].update(targetRevision='latest')):
            copy_apps = copy.deepcopy(apps)
            mutation(copy_apps)
            with self.assertRaises(RuntimeError):
                observe.check_applications(copy_apps, SHA, expected)

    def test_static_boundary_contract(self):
        contract = json.loads((c.ROOT / 'delivery/contracts/v0.11.8.2.1-aws-test-feature-qualification.json').read_text())
        self.assertFalse(contract['automatic_promotion'])
        self.assertFalse(contract['prod_in_scope'])
        self.assertEqual(contract['cluster'], c.CLUSTER)
        for name in ('apply-aws-test.sh', 'bootstrap-aws-test.sh'):
            self.assertIn('!= "main"', (c.ROOT / 'scripts' / name).read_text())
        for env in ('test', 'prod'):
            root = c.yaml.safe_load((c.ROOT / f'clusters/aws/overlays/{env}/root-app.yaml').read_text())
            self.assertEqual(root['spec']['source']['targetRevision'], 'main')

    def test_complete_observation_pass_and_unready_failure(self):
        contract = json.loads(c.CONTRACT.read_text())
        apps = []
        for name in contract['same_repository_applications'] + ['startup-devops-aws-test-root']:
            apps.append({'kind': 'Application', 'metadata': {'name': name}, 'spec': {'source': {
                'repoURL': c.REPO, 'targetRevision': c.BRANCH, 'path': c.OVERLAY}},
                'status': {'sync': {'status': 'Synced', 'revision': SHA}, 'health': {'status': 'Healthy'}}})
        for chart, version in contract['external_charts'].items():
            apps.append({'kind': 'Application', 'metadata': {'name': chart}, 'spec': {'source': {
                'repoURL': 'https://charts.example.invalid', 'chart': chart, 'targetRevision': version}},
                'status': {'sync': {'status': 'Synced', 'revision': version}, 'health': {'status': 'Healthy'}}})
        rendered = c.yaml.safe_dump_all(apps)
        names = ('capacity', 'data', 'delivery', 'platform', 'service', 'slo')
        rules = ('demo_api:slo_availability:ratio30d', 'demo_api:slo_latency:ratio30d',
                 'demo_api:slo_availability_burn_rate:ratio1h', 'demo_api:slo_latency_burn_rate:ratio1h',
                 'DemoApiAvailabilityErrorBudgetFastBurn', 'DemoApiLatencyErrorBudgetFastBurn', 'PrometheusTargetDown')
        @contextmanager
        def forward(*args):
            yield 'http://127.0.0.1:12345'
        for healthy in (True, False):
            current = rollout()
            if not healthy:
                current['status']['phase'] = 'Paused'
            def get(env, *args):
                if 'applications' in args:
                    return {'items': apps}
                if 'rollout' in args:
                    return current
                if 'configmaps' in args:
                    return {'items': [{'metadata': {'name': f'observability-dashboard-{x}-overview'}} for x in names]}
                if 'startup-apps' in args and 'pods' in args:
                    return {'items': [{'metadata': {'name': f'demo-{i}'},
                        'spec': {'containers': [{'name': 'demo-api', 'image': IMAGE}]},
                        'status': {'phase': 'Running', 'conditions': [{'type': 'Ready', 'status': 'True'}]}} for i in range(2)]}
                return {'items': []}
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'evidence.json'
                argv = ['observe', '--account', ACCOUNT, '--sha', SHA, '--application-version', 'v-test',
                        '--operator-observation', '--output', str(output)]
                with patch.object(sys, 'argv', argv), patch.object(c, 'preflight'), \
                     patch.object(c, 'discover', return_value={'status': 'ACTIVE'}), \
                     patch.object(c, 'kube_env', return_value={}), patch.object(c, 'can_i', return_value=True), \
                     patch.object(c, 'release', return_value=('v-test', IMAGE)), \
                     patch.object(c, 'run', return_value=rendered), patch.object(c, 'get', side_effect=get), \
                     patch.object(c, 'kube', return_value='deployment/monitoring'), \
                     patch.object(c, 'load_capacity', return_value=SimpleNamespace(runtime_ready=lambda *x: True)), \
                     patch.object(observe, 'forward', side_effect=forward), \
                     patch.object(observe, 'api', side_effect=[{'activeTargets': [{'labels': {'job': 'demo-api'}, 'health': 'up'}]},
                         {'groups': [{'rules': [{'name': x} for x in rules]}]}, {'result': []}]):
                    self.assertEqual(observe.main(), 0 if healthy else 1)
                evidence = json.loads(output.read_text())
                self.assertEqual(evidence['status'], 'qualified' if healthy else 'failed')
                if healthy:
                    self.assertIn(IMAGE, [x.get('observedValue') for x in evidence['checks']])
                    self.assertEqual(evidence['capabilities']['slo']['status'], 'supported-not-verified')


if __name__ == '__main__':
    unittest.main(verbosity=2)

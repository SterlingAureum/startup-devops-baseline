#!/usr/bin/env python3
"""Offline prod approval/identity/observation tests; all live I/O mocked."""
import copy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import shutil
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
import aws_test_feature_common as c


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


p = load('prod', 'check-aws-prod-observability-qualification.py')
f = load('test_fixtures', 'test-aws-test-feature.py')
ACCOUNT, SHA, IMAGE = f.ACCOUNT, f.SHA, f.IMAGE
ACTOR = f'arn:aws:iam::{ACCOUNT}:role/reviewed-prod-observer'


def approval():
    now = datetime.now(timezone.utc)
    return {'approved': True, 'environment': 'aws-prod', 'account': ACCOUNT, 'region': 'us-east-1',
            'cluster': p.CLUSTER, 'sha': SHA, 'application_version': 'v-test', 'image': IMAGE,
            'action': 'observe', 'mode': 'operator-observation', 'actor_arn': ACTOR,
            'reference': 'CHANGE-123', 'issued_at': (now - timedelta(minutes=1)).isoformat(),
            'expires_at': (now + timedelta(minutes=20)).isoformat()}


def arguments(directory):
    return SimpleNamespace(confirm='approved-prod-read-only', operator_observation=True,
                           approval=Path(directory) / 'approval.json', account=ACCOUNT, sha=SHA,
                           application_version='v-test', output=Path(directory) / 'evidence.json')


def applications():
    contract = json.loads(p.CONTRACT.read_text())
    expected = {}
    for name in contract['same_repository_applications'] + [p.ROOT_APP]:
        expected[name] = {'metadata': {'name': name}, 'spec': {'project': 'default',
            'source': {'repoURL': c.REPO, 'targetRevision': 'main', 'path': p.OVERLAY},
            'destination': {'server': 'https://kubernetes.default.svc', 'namespace': 'argocd'}}}
    for name, chart in contract['external_applications'].items():
        expected[name] = {'metadata': {'name': name}, 'spec': {'project': 'default',
            'source': {'repoURL': 'https://charts.example.invalid', 'chart': chart['chart'], 'targetRevision': chart['version']},
            'destination': {'server': 'https://kubernetes.default.svc', 'namespace': 'observability'}}}
    actual = copy.deepcopy(list(expected.values()))
    for app in actual:
        source = app['spec']['source']
        app['status'] = {'sync': {'status': 'Synced', 'revision': source['targetRevision'] if 'chart' in source else SHA},
                         'health': {'status': 'Healthy'}}
    return expected, actual


class ProdGuards(unittest.TestCase):
    def test_real_source_inventory(self):
        contract = json.loads(p.CONTRACT.read_text())
        folder = c.ROOT / 'clusters/aws/base/platform'
        kustomization = c.yaml.safe_load((folder / 'kustomization.yaml').read_text())
        apps = []
        for path in kustomization['resources']:
            apps.extend(x for x in c.yaml.safe_load_all((folder / path).read_text()) if x and x.get('kind') == 'Application')
        charts = {x['metadata']['name'].replace('-aws-dev', '-aws-prod'):
                  {'chart': x['spec']['source']['chart'], 'version': x['spec']['source']['targetRevision']}
                  for x in apps if 'chart' in x['spec']['source']}
        self.assertEqual(charts, contract['external_applications'])
        own = sorted(x['metadata']['name'].replace('-aws-dev', '-aws-prod') for x in apps if 'chart' not in x['spec']['source'])
        self.assertEqual(own, sorted(contract['same_repository_applications']))
        root = c.yaml.safe_load((c.ROOT / p.OVERLAY / 'root-app.yaml').read_text())
        self.assertEqual(root['spec']['source']['targetRevision'], 'main')
        self.assertEqual(root['spec']['source']['path'], p.OVERLAY)

    def test_real_prod_render_when_available(self):
        if not (shutil.which('kustomize') or shutil.which('kubectl')):
            self.skipTest('Real prod rendering needs kustomize or kubectl; run locally.')
        expected = p.expected_applications(p.environment(), {'resourcesVpcConfig': {'vpcId': 'vpc-offline-fixture'}})
        actual = copy.deepcopy(list(expected.values()))
        for app in actual:
            source = app['spec']['source']
            app['status'] = {'sync': {'status': 'Synced', 'revision': source['targetRevision'] if 'chart' in source else SHA},
                             'health': {'status': 'Healthy'}}
        p.check_applications(actual, expected, SHA)

    def test_approval_scope_expiry_and_no_io(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c.subprocess, 'run') as run:
            args = arguments(directory)
            args.approval.write_text(json.dumps(approval()))
            p.approve(args, IMAGE)
            for key, value in {'approved': False, 'environment': 'aws-test', 'account': '999999999999',
                               'region': 'us-west-2', 'cluster': 'test', 'sha': 'b'*40,
                               'application_version': 'old', 'image': 'wrong', 'action': 'apply',
                               'mode': 'bounded', 'reference': '', 'actor_arn': 'wrong',
                               'issued_at': '2099-01-01T00:00:00Z',
                               'expires_at': '2000-01-01T00:00:00Z'}.items():
                value_doc = approval()
                value_doc[key] = value
                args.approval.write_text(json.dumps(value_doc))
                with self.subTest(key=key), self.assertRaises((RuntimeError, ValueError)):
                    p.approve(args, IMAGE)
            run.assert_not_called()

    def test_main_missing_approval_never_calls_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['prod', '--account', ACCOUNT, '--sha', SHA, '--application-version', 'v-test',
                    '--output', str(Path(directory) / 'evidence.json'), '--operator-observation',
                    '--confirm', 'approved-prod-read-only']
            with patch.object(sys, 'argv', argv), patch.object(p, 'release', return_value=('v-test', IMAGE)), \
                 patch.object(c.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'approval record'):
                    p.main()
                run.assert_not_called()
                self.assertFalse((Path(directory) / 'evidence.json').exists())

    def test_approval_ttl_and_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            args = arguments(directory)
            value = approval()
            value['expires_at'] = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            args.approval.write_text(json.dumps(value))
            with self.assertRaisesRegex(RuntimeError, 'one hour'):
                p.approve(args, IMAGE)
            args.approval.write_text(json.dumps(approval()))
            args.confirm = ''
            with self.assertRaises(RuntimeError):
                p.approve(args, IMAGE)

    def test_main_branch_and_actor_guards(self):
        args = SimpleNamespace(account=ACCOUNT, sha=SHA)
        for branch in ('main', c.BRANCH):
            with patch.object(c, 'git', side_effect=[branch, '', SHA, SHA+' refs/heads/main']), \
                 patch.object(p, 'aws', return_value=json.dumps({'Account': ACCOUNT, 'Arn': ACTOR})) as aws:
                if branch == 'main':
                    p.preflight(args, approval())
                else:
                    with self.assertRaises(RuntimeError):
                        p.preflight(args, approval())
                    aws.assert_not_called()
        with patch.object(c, 'git', side_effect=['main', '', SHA, SHA+' refs/heads/main']), \
             patch.object(p, 'aws', return_value=json.dumps({'Account': ACCOUNT, 'Arn': 'wrong'})), self.assertRaises(RuntimeError):
            p.preflight(args, approval())

    def test_discovery_errors_and_wrong_cluster(self):
        args = SimpleNamespace(account=ACCOUNT)
        for error in ('AccessDeniedException', 'network timeout', 'ResourceNotFoundException elsewhere'):
            with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=error)), self.assertRaises(RuntimeError):
                p.discover(args)
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=1,
             stderr='An error occurred (ResourceNotFoundException) when calling the DescribeCluster operation: absent')):
            self.assertIsNone(p.discover(args))
        with patch.object(c.subprocess, 'run', return_value=SimpleNamespace(returncode=0,
             stdout=json.dumps({'cluster': {'name': 'test', 'arn': 'wrong', 'status': 'ACTIVE'}}))), self.assertRaises(RuntimeError):
            p.discover(args)

    def test_temporary_kubeconfig_checks_context_and_endpoint(self):
        args = SimpleNamespace(account=ACCOUNT)
        cluster = {'arn': f'arn:aws:eks:us-east-1:{ACCOUNT}:cluster/{p.CLUSTER}', 'endpoint': 'https://prod.example.invalid'}
        for wrong in (None, 'context', 'endpoint'):
            config = {'current-context': cluster['arn'], 'clusters': [{'cluster': {'server': cluster['endpoint']}}]}
            if wrong == 'context':
                config['current-context'] = 'dev'
            if wrong == 'endpoint':
                config['clusters'][0]['cluster']['server'] = 'https://dev.example.invalid'
            with tempfile.TemporaryDirectory() as directory, patch.object(c, 'run', side_effect=['', json.dumps(config)]) as run:
                if wrong:
                    with self.assertRaises(RuntimeError):
                        p.kube_env(args, cluster, directory)
                else:
                    env = p.kube_env(args, cluster, directory)
                    self.assertEqual(env['KUBECONFIG'], str(Path(directory) / 'kubeconfig'))
                    self.assertEqual(env['CLUSTER_NAME'], p.CLUSTER)
                    self.assertEqual(env['AWS_ENVIRONMENT'], 'aws-prod')
                self.assertEqual(run.call_args_list[0].args[0][3:6], ['eks', 'update-kubeconfig', '--name'])

    def test_application_source_and_revision_mutations(self):
        expected, actual = applications()
        p.check_applications(actual, expected, SHA)
        for mutate in (lambda x: x[0]['spec']['source'].update(targetRevision=c.BRANCH),
                       lambda x: x[0]['spec']['source'].update(path='clusters/aws/overlays/test'),
                       lambda x: x[0]['spec']['destination'].update(namespace='wrong'),
                       lambda x: x[0]['status']['sync'].update(revision='b'*40),
                       lambda x: x[-1]['spec']['source'].update(targetRevision='latest'),
                       lambda x: x.append(copy.deepcopy(x[0])), lambda x: x.pop()):
            bad = copy.deepcopy(actual)
            mutate(bad)
            with self.assertRaises(RuntimeError):
                p.check_applications(bad, expected, SHA)

    def test_cross_environment_targets(self):
        targets = f.demo_targets()
        pods = [{'metadata': {'name': f'demo-{i}'}} for i in range(2)]
        with self.assertRaises(RuntimeError):
            p.shared.check_demo_targets(targets, f.rollout(), pods, 'v-test', IMAGE, environment='aws-prod')
        for t in targets:
            t['labels']['deployment_environment_name'] = 'aws-prod'
        p.shared.check_demo_targets(targets, f.rollout(), pods, 'v-test', IMAGE, environment='aws-prod')

    def test_main_waiting_and_failure_evidence(self):
        for missing in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                args = arguments(directory)
                args.approval.write_text(json.dumps(approval()))
                argv = ['prod', '--account', ACCOUNT, '--sha', SHA, '--application-version', 'v-test',
                        '--approval', str(args.approval), '--confirm', args.confirm, '--operator-observation', '--output', str(args.output)]
                with patch.object(sys, 'argv', argv), patch.object(p, 'release', return_value=('v-test', IMAGE)), \
                     patch.object(c, 'run'), patch.object(p, 'preflight'), \
                     patch.object(p, 'discover', return_value=None) as discover:
                    if not missing:
                        discover.side_effect = RuntimeError('AccessDenied')
                    self.assertEqual(p.main(), 2 if missing else 1)
                evidence = json.loads(args.output.read_text())
                self.assertEqual(evidence['status'], 'waiting-runtime' if missing else 'failed')
                self.assertEqual(evidence['environment'], 'aws-prod')
                self.assertTrue(evidence['approval']['approved'])
                self.assertFalse(any(x['status'] == 'supported-verified' for x in evidence['capabilities'].values()))

    def test_complete_observation(self):
        expected, actual = applications()
        targets = f.demo_targets(('demo-api-stable', 'demo-api-canary'))
        for t in targets:
            t['labels']['deployment_environment_name'] = 'aws-prod'
        rollout = f.rollout()
        rollout['spec']['strategy'] = {'canary': {'stableService': 'demo-api-stable', 'canaryService': 'demo-api-canary'}}
        def get(env, *args):
            if 'applications' in args:
                return {'items': actual}
            if 'rollout' in args:
                return rollout
            if 'configmaps' in args:
                return {'items': [{'metadata': {'name': f'observability-dashboard-{x}-overview'}}
                                  for x in ('capacity', 'data', 'delivery', 'platform', 'service', 'slo')]}
            if 'startup-apps' in args and 'pods' in args:
                return {'items': [{'metadata': {'name': f'demo-{i}'},
                                  'spec': {'containers': [{'name': 'demo-api', 'image': IMAGE}]},
                                  'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}} for i in range(2)]}
            return {'items': []}
        @contextmanager
        def forward(*args):
            yield 'http://127.0.0.1:12345'
        rules = ('demo_api:slo_availability:ratio30d', 'demo_api:slo_latency:ratio30d',
                 'demo_api:slo_availability_burn_rate:ratio1h', 'demo_api:slo_latency_burn_rate:ratio1h',
                 'DemoApiAvailabilityErrorBudgetFastBurn', 'DemoApiLatencyErrorBudgetFastBurn', 'PrometheusTargetDown')
        checks, capabilities = [], {key: {'status': 'supported-not-verified', 'evidenceCheckIds': []}
                                     for key in ('metrics','dashboards','alerts','logs','traces','slo','progressiveDeliveryTelemetry')}
        with patch.object(c, 'can_i', return_value=True), patch.object(p, 'expected_applications', return_value=expected), \
             patch.object(c, 'get', side_effect=get), patch.object(c, 'kube', return_value='deployment/monitoring'), \
             patch.object(c, 'load_capacity', return_value=SimpleNamespace(runtime_ready=lambda *x: True)), \
             patch.object(p.shared, 'forward', side_effect=forward), \
             patch.object(p.shared, 'api', side_effect=[{'activeTargets': targets}, {'groups': [{'rules': [{'name': n} for n in rules]}]}]):
            p.observe(SimpleNamespace(sha=SHA, application_version='v-test'), {}, {}, IMAGE, checks, capabilities)
        self.assertEqual(capabilities['metrics']['status'], 'supported-verified')
        self.assertEqual(capabilities['slo']['status'], 'supported-not-verified')
        self.assertTrue(all(x['outcome'] == 'passed' for x in checks))

    def test_main_success_and_approval_change_never_passes(self):
        for changed in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                args = arguments(directory)
                args.approval.write_text(json.dumps(approval()))
                argv = ['prod', '--account', ACCOUNT, '--sha', SHA, '--application-version', 'v-test',
                        '--approval', str(args.approval), '--confirm', args.confirm, '--operator-observation', '--output', str(args.output)]
                def observe(args, env, cluster, image, checks, capabilities):
                    checks.append({'id': 'prometheus.target', 'outcome': 'passed', 'observedValue': 'up', 'diagnostic': None})
                    capabilities['metrics'] = {'status': 'supported-verified', 'evidenceCheckIds': ['prometheus.target']}
                    if changed:
                        value = approval()
                        value['reference'] = 'CHANGED'
                        args.approval.write_text(json.dumps(value))
                with patch.object(sys, 'argv', argv), patch.object(p, 'release', return_value=('v-test', IMAGE)), \
                     patch.object(c, 'run'), patch.object(p, 'preflight'), patch.object(p, 'discover', return_value={}), \
                     patch.object(p, 'kube_env', return_value={}), patch.object(p, 'observe', side_effect=observe):
                    self.assertEqual(p.main(), 1 if changed else 0)
                self.assertEqual(json.loads(args.output.read_text())['status'], 'failed' if changed else 'qualified')


if __name__ == '__main__':
    unittest.main(verbosity=2)

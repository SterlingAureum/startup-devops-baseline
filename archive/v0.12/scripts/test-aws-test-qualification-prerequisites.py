#!/usr/bin/env python3
"""Static contracts and positive/negative rendered-document fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preview', ROOT / 'scripts/check-aws-test-qualification-preview.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
C = json.loads(checker.CONTRACT.read_text())


def source_external_charts():
    inventory = {}
    for path in sorted((ROOT / 'clusters/aws/base/platform').glob('*.yaml')):
        for item in yaml.safe_load_all(path.read_text()):
            if not item or item.get('kind') != 'Application':
                continue
            source = item.get('spec', {}).get('source', {})
            chart = source.get('chart')
            if not chart:
                continue
            if chart in inventory:
                raise AssertionError(f'duplicate external Chart in source manifests: {chart}')
            inventory[chart] = source.get('targetRevision')
    return inventory


def fixture():
    docs = []
    for name in C['same_repository_applications']:
        docs.append({'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
                     'metadata': {'name': name, 'namespace': 'argocd'},
                     'spec': {'source': {'repoURL': C['repository'], 'targetRevision': 'main'}}})
    for chart, version in C['external_charts'].items():
        names = {
            'kube-prometheus-stack': 'monitoring-aws-test',
            'plugin-barman-cloud': 'barman-cloud-plugin',
        }
        name = names.get(chart, chart)
        docs.append({'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
                     'metadata': {'name': name, 'namespace': 'argocd'},
                     'spec': {'source': {'repoURL': 'https://charts.example.invalid', 'chart': chart,
                     'targetRevision': version, 'helm': {'valuesObject': {'grafana': {}}}}}})
    preview = copy.deepcopy(docs)
    for item in preview:
        source = item['spec']['source']
        if source['repoURL'] == C['repository']:
            source['targetRevision'] = C['qualification_revision']
        if item['metadata']['name'] == 'monitoring-aws-test':
            source['helm']['valuesObject']['grafana']['admin'] = {
                'existingSecret': 'observability-grafana-admin', 'userKey': 'admin-user', 'passwordKey': 'admin-password'}
    return docs, preview


class Contracts(unittest.TestCase):
    def test_static_boundaries(self):
        self.assertEqual(C['version'], 'v0.11.8.2.0')
        self.assertEqual(C['predecessor'], 'v0.11.8.1.5')
        self.assertFalse(C['live_execution_enabled'])
        self.assertFalse(C['prod_in_scope'])
        self.assertFalse(C['release']['promote'])
        self.assertFalse(C['release']['copy_dev_evidence'])
        self.assertTrue(C['grafana']['independent_credentials'])
        self.assertFalse(C['capacity']['automatic_loading'])
        self.assertTrue(C['capacity']['requires_reviewed_plan'])
        self.assertEqual(C['qualification_revision'], 'feature/v0.11-observability-sre-baseline')
        self.assertEqual(source_external_charts(), C['external_charts'])
        barman = yaml.safe_load((ROOT / 'clusters/aws/base/platform/barman-cloud-plugin.yaml').read_text())
        self.assertEqual(barman['metadata']['name'], 'barman-cloud-plugin')
        self.assertEqual(barman['spec']['source']['chart'], 'plugin-barman-cloud')
        for env in ('test', 'prod'):
            root = yaml.safe_load((ROOT / f'clusters/aws/overlays/{env}/root-app.yaml').read_text())
            self.assertEqual(root['spec']['source']['targetRevision'], 'main')
        for name in ('apply-aws-test.sh', 'bootstrap-aws-test.sh'):
            script = (ROOT / 'scripts' / name).read_text()
            self.assertIn('branch --show-current', script)
            self.assertIn('!= "main"', script)
            self.assertIn('status --porcelain', script)
            self.assertIn('CONFIRM_AWS_TEST_', script)
        preview = ROOT / C['qualification_overlay']
        root = yaml.safe_load((preview / 'root-app.yaml').read_text())
        self.assertNotIn('syncPolicy', root['spec'])
        self.assertEqual(root['metadata']['name'], C['root_application'])
        self.assertEqual(root['spec']['source'], {'repoURL': C['repository'],
            'targetRevision': C['qualification_revision'], 'path': C['qualification_overlay']})
        overlay = yaml.safe_load((preview / 'kustomization.yaml').read_text())
        self.assertEqual(overlay['resources'], ['../test'])
        self.assertEqual(len(overlay['patches']), 2)
        revision, grafana = overlay['patches']
        self.assertEqual(set(revision['target']['name'][2:-2].split('|')), set(C['same_repository_applications']))
        self.assertEqual(yaml.safe_load(revision['patch']), [{'op': 'replace',
            'path': '/spec/source/targetRevision', 'value': C['qualification_revision']}])
        self.assertEqual(grafana['target']['name'], 'monitoring-aws-test')
        self.assertEqual(yaml.safe_load(grafana['patch']), [{'op': 'add',
            'path': '/spec/source/helm/valuesObject/grafana/admin', 'value': {
            'existingSecret': C['grafana']['secret'], 'userKey': C['grafana']['user_key'],
            'passwordKey': C['grafana']['password_key']}}])
        profile = ROOT / C['capacity']['profile']
        self.assertFalse(profile.name.endswith('.auto.tfvars'))
        values = dict(re.findall(r'^(eks_node_\w+_size)\s*=\s*(\d+)\s*$', profile.read_text(), re.M))
        self.assertEqual(values, {'eks_node_min_size': '4', 'eks_node_desired_size': '4', 'eks_node_max_size': '4'})
        self.assertEqual([C['capacity'][key] for key in ('min', 'desired', 'max')], [4, 4, 4])

    def test_positive(self):
        checker.validate(*fixture(), C)

    def test_negative_documents(self):
        mutations = {
            'old feature revision': lambda s, p: p[0]['spec']['source'].update(targetRevision='main'),
            'stable changed': lambda s, p: s[0]['spec']['source'].update(targetRevision='feature/other'),
            'missing resource': lambda s, p: p.pop(),
            'duplicate resource': lambda s, p: p.append(copy.deepcopy(p[0])),
            'unrelated mutation': lambda s, p: p[0]['spec'].update(project='other'),
            'chart unpinned': lambda s, p: p[-1]['spec']['source'].update(targetRevision='latest'),
            'credentials omitted': lambda s, p: p[-1]['spec']['source']['helm']['valuesObject']['grafana'].clear(),
            'wrong credential': lambda s, p: p[-1]['spec']['source']['helm']['valuesObject']['grafana']['admin'].update(existingSecret='dev-copy'),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                stable, preview = fixture()
                mutate(stable, preview)
                with self.assertRaises(ValueError):
                    checker.validate(stable, preview, C)

    def test_legacy_application_name_cannot_replace_chart_identity(self):
        stable, preview = fixture()
        legacy = copy.deepcopy(C)
        legacy['external_charts']['barman-cloud-plugin'] = legacy['external_charts'].pop('plugin-barman-cloud')
        self.assertNotEqual(source_external_charts(), legacy['external_charts'])
        with self.assertRaisesRegex(ValueError, r'application=barman-cloud-plugin, chart=plugin-barman-cloud'):
            checker.validate(stable, preview, legacy)


if __name__ == '__main__':
    unittest.main(verbosity=2)

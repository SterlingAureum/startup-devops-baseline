#!/usr/bin/env python3
"""Offline regression for single and ALB stable/canary Service topology."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('fixtures', Path(__file__).with_name('test-aws-test-feature.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


class Targets(unittest.TestCase):
    def setUp(self):
        self.rollout = f.rollout()
        self.rollout['spec']['strategy'] = {'canary': {
            'stableService': 'demo-api-stable', 'canaryService': 'demo-api-canary'}}
        self.pods = [{'metadata': {'name': f'demo-{i}'}} for i in range(2)]
        self.targets = f.demo_targets(('demo-api-stable', 'demo-api-canary'))

    def check(self, targets, rollout=None):
        f.observe.check_demo_targets(targets, rollout or self.rollout, self.pods, 'v-test', f.IMAGE)

    def test_positive_topologies(self):
        self.check(self.targets)
        self.check(self.targets[:2])  # Empty canary discovery is valid after convergence.
        self.check(f.demo_targets(), f.rollout())
        self.check(self.targets + [{'labels': {'job': 'node-exporter'}, 'health': 'down'}])

    def test_identity_mutations(self):
        for key, value in {'namespace': 'other', 'service_name': 'other',
                           'deployment_environment_name': 'aws-dev', 'service_version': 'old',
                           'container_image_digest': 'sha256:wrong', 'endpoint': 'wrong',
                           'job': 'demo-api', 'service': 'unknown', 'pod': 'old-pod'}.items():
            targets = copy.deepcopy(self.targets)
            targets[0]['labels'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                self.check(targets)
        targets = copy.deepcopy(self.targets)
        targets[0]['scrapePool'] = 'wrong'
        with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
            self.check(targets)

    def test_missing_down_and_partial_targets(self):
        for targets in ([], self.targets[1:], self.targets[2:]):
            with self.subTest(targets=targets), self.assertRaises(RuntimeError):
                self.check(targets)
        targets = copy.deepcopy(self.targets)
        targets[-1].update(health='down', lastError='context deadline exceeded')
        with self.assertRaisesRegex(RuntimeError, 'context deadline exceeded'):
            self.check(targets)

    def test_source_service_monitor_job_contract(self):
        import yaml
        source = (f.c.ROOT / 'apps/demo-api/helm/templates/servicemonitor.yaml').read_text()
        # Parse the real relabeling list without rendering unrelated Helm fields.
        relabels = yaml.safe_load(source.split('      relabelings:\n', 1)[1].split('{{- end }}', 1)[0])
        mapping = {r['targetLabel']: r['sourceLabels'] for r in relabels}
        self.assertEqual(mapping['job'], ['__meta_kubernetes_service_name'])
        self.assertIn('deployment_environment_name', mapping)
        self.assertIn('container_image_digest', mapping)


if __name__ == '__main__':
    unittest.main(verbosity=2)

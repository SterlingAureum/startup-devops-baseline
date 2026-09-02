#!/usr/bin/env python3
"""Offline variable/review regression tests. No cloud commands are executed."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.dont_write_bytecode = True
import aws_test_feature_common as c
import importlib.util

spec = importlib.util.spec_from_file_location('feature_tests', Path(__file__).with_name('test-aws-test-feature.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
p = fixtures.prepare
ACCOUNT, SHA = fixtures.ACCOUNT, fixtures.SHA
ROLE = f'arn:aws:iam::{ACCOUNT}:role/startup-devops-baseline-test-github-runtime-read-role'


def enabled_plan():
    doc = fixtures.plan_document()
    doc['variables'].update(enable_github_actions_runtime_identity={'value': True},
                            github_actions_runtime_role_arn={'value': ROLE},
                            additional_tags={'value': {'Owner': 'fixture-owner'}})
    doc['resource_changes'].append({'type': 'aws_eks_access_entry',
        'address': 'module.github_actions_runtime_identity[0].aws_eks_access_entry.runtime',
        'change': {'actions': ['create'], 'after': {'principal_arn': ROLE,
            'cluster_name': c.CLUSTER, 'kubernetes_groups': ['demo-api-runtime-qualification']}}})
    return doc


class VariableGuards(unittest.TestCase):
    def test_fingerprints_and_forbidden_inputs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c, 'TF', Path(directory)):
            local = c.TF / 'terraform.tfvars'
            self.assertEqual(p.variable_inputs(), {'terraform.tfvars': None})
            local.write_text('additional_tags = { Owner = "fixture-owner" }\n')
            before = p.variable_inputs()
            self.assertEqual(before['terraform.tfvars'], p.digest(local))
            local.write_text('additional_tags = { Owner = "changed" }\n')
            self.assertNotEqual(before, p.variable_inputs())
            for name in ('terraform.tfvars.json', 'capacity.auto.tfvars', 'capacity.auto.tfvars.json'):
                extra = c.TF / name
                extra.write_text('{}')
                with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'additional variable'):
                    p.variable_inputs()
                extra.unlink()
            local.unlink()
            local.symlink_to(c.TF / 'missing')
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                p.variable_inputs()

    def test_role_and_entry_boundaries(self):
        self.assertIsNone(p.check_plan(fixtures.plan_document(), ACCOUNT, '8.8.8.8/32'))
        self.assertEqual(p.check_plan(enabled_plan(), ACCOUNT, '8.8.8.8/32'), ROLE)
        mutations = [
            lambda d: d['variables']['github_actions_runtime_role_arn'].update(value=None),
            lambda d: d['variables']['github_actions_runtime_role_arn'].update(value=ROLE.replace(ACCOUNT, '999999999999')),
            lambda d: d['variables']['github_actions_runtime_role_arn'].update(value=ROLE.replace('-test-', '-dev-')),
            lambda d: d['variables']['enable_github_actions_runtime_identity'].update(value='true'),
            lambda d: d['variables']['enable_github_actions_runtime_identity'].update(value=False),
            lambda d: d['resource_changes'].pop(),
            lambda d: d['resource_changes'][1]['change']['after'].update(cluster_name='dev'),
            lambda d: d['resource_changes'][1]['change']['after'].update(principal_arn='wrong'),
            lambda d: d['resource_changes'][1]['change']['after'].update(kubernetes_groups=['system:masters']),
        ]
        for i, mutation in enumerate(mutations):
            doc = enabled_plan()
            mutation(doc)
            with self.subTest(i=i), self.assertRaises(RuntimeError):
                p.check_plan(doc, ACCOUNT, '8.8.8.8/32')

    def test_read_only_role_lookup(self):
        with patch.object(c, 'aws', return_value=ROLE) as aws:
            p.check_role_exists(None)
            aws.assert_not_called()
            p.check_role_exists(ROLE)
            self.assertEqual(aws.call_args.args[:2], ('iam', 'get-role'))
        for result in ('wrong', ''):
            with patch.object(c, 'aws', return_value=result), self.assertRaises(RuntimeError):
                p.check_role_exists(ROLE)
        with patch.object(c, 'aws', side_effect=RuntimeError('AccessDenied')), self.assertRaises(RuntimeError):
            p.check_role_exists(ROLE)

    def test_missing_bundle_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(p, 'tf') as tf:
            with self.assertRaisesRegex(RuntimeError, 'Incomplete plan bundle'):
                p.apply(SimpleNamespace(confirm='apply-reviewed-aws-test', bundle=directory))
            tf.assert_not_called()

    def test_plan_preserves_file_and_apply_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tfroot = root / 'terraform'
            tfroot.mkdir()
            local = tfroot / 'terraform.tfvars'
            original = f'additional_tags = {{ Owner = "fixture-owner" }}\nenable_github_actions_runtime_identity = true\ngithub_actions_runtime_role_arn = "{ROLE}"\n'
            local.write_text(original)
            bundle = root / 'bundle'
            def fake_tf(*args, **kwargs):
                if args[0] == 'plan':
                    self.assertIn(f'-var-file={c.PROFILE}', args)
                    (bundle / 'review.tfplan').write_bytes(b'offline plan fixture')
                if args[:2] == ('show', '-json'):
                    return json.dumps(enabled_plan())
                return ''
            with patch.object(c, 'TF', tfroot), patch.object(p, 'initialize'), \
                 patch.object(c, 'discover', return_value=None), patch.object(c, 'aws', return_value=ROLE), \
                 patch.object(p, 'tf', side_effect=fake_tf):
                p.plan(SimpleNamespace(management_ip='8.8.8.8', mode='create', bundle=str(bundle), account=ACCOUNT, sha=SHA))
            self.assertEqual(local.read_text(), original)
            record = json.loads((bundle / 'review.json').read_text())
            self.assertEqual(record['variable_inputs'], {'terraform.tfvars': p.digest(local)})
            args = SimpleNamespace(confirm='apply-reviewed-aws-test', bundle=str(bundle), account=ACCOUNT, sha=SHA)
            for change in ('modified', 'removed', 'added', 'legacy'):
                current = copy.deepcopy(record)
                local.write_text(original)
                if change == 'modified':
                    local.write_text(original + '# changed\n')
                elif change == 'removed':
                    local.unlink()
                elif change == 'added':
                    current['variable_inputs'] = {'terraform.tfvars': None}
                else:
                    current.pop('variable_inputs')
                (bundle / 'review.json').write_text(json.dumps(current))
                with self.subTest(change=change), patch.object(c, 'TF', tfroot), patch.object(p, 'tf') as tf:
                    with self.assertRaisesRegex(RuntimeError, 'generate a new plan'):
                        p.apply(args)
                    tf.assert_not_called()
            local.write_text(original)
            (bundle / 'review.json').write_text(json.dumps(record))
            ready = {'resourcesVpcConfig': {'publicAccessCidrs': ['8.8.8.8/32']}}
            with patch.object(c, 'TF', tfroot), patch.object(p, 'initialize'), \
                 patch.object(c, 'discover', side_effect=[None, ready]), patch.object(c, 'aws', return_value=ROLE), \
                 patch.object(p, 'tf', side_effect=fake_tf) as tf:
                p.apply(args)
                self.assertEqual(sum(call.args[0] == 'apply' for call in tf.call_args_list), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)

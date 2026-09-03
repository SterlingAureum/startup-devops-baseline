#!/usr/bin/env python3
"""Metadata-only rebuild preflight and refusal regression; no cloud calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('fixtures', Path(__file__).with_name('test-aws-test-feature.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
p, c = f.prepare, f.c
NAME = 'startup-devops-baseline-test/demo-api/postgresql'
SECRET = {'Name': NAME, 'ARN': f'arn:aws:secretsmanager:us-east-1:{f.ACCOUNT}:secret:{NAME}-Ab1234'}


class SecretPreflight(unittest.TestCase):
    def test_closure_is_historical_and_bounded(self):
        contract = json.loads((c.ROOT / 'delivery/contracts/v0.11.8.2.2-test-closure-and-rebuild.json').read_text())
        history = contract['historical_observation']
        self.assertEqual(history['repository_commit'], '456e1eb85ba63dc94c6e1f04b4498a4c0a87669b')
        self.assertEqual(history['mode'], 'operator-observation')
        self.assertFalse(history['least_privilege_verified'])
        self.assertFalse(history['fresh_evidence_for_this_increment'])
        self.assertEqual(history['capabilities']['slo'], 'supported-not-verified')
        self.assertEqual(history['capabilities']['traces'], 'not-deployed')
        self.assertFalse(contract['preflight']['automatic_delete_restore_import'])
        self.assertFalse(contract['prod_in_scope'])

    def invoke(self, value=None, error=''):
        proc = SimpleNamespace(returncode=1 if error else 0, stdout=json.dumps(value), stderr=error)
        return patch.object(c.subprocess, 'run', return_value=proc)

    def test_absent_and_active_are_read_only(self):
        with self.invoke(error='An error occurred (ResourceNotFoundException) when calling the DescribeSecret operation: missing') as run:
            p.check_test_secret(f.ACCOUNT)
            self.assertEqual(run.call_args.args[0], ['aws', '--region', 'us-east-1', 'secretsmanager',
                             'describe-secret', '--secret-id', NAME, '--output', 'json'])
        with self.invoke(SECRET):
            p.check_test_secret(f.ACCOUNT)
            p.check_test_secret(f.ACCOUNT, {'resource_changes': []})

    def test_pending_and_foreign_identity_refused(self):
        for value in ({**SECRET, 'DeletedDate': '2026-09-02T16:06:49Z'},
                      {**SECRET, 'Name': 'dev'},
                      {**SECRET, 'ARN': SECRET['ARN'].replace(f.ACCOUNT, '999999999999')},
                      {**SECRET, 'ARN': SECRET['ARN'].replace('us-east-1', 'us-west-2')}):
            with self.subTest(value=value), self.invoke(value), self.assertRaises(RuntimeError):
                p.check_test_secret(f.ACCOUNT)

    def test_lookup_errors_never_mean_absent(self):
        for error in ('AccessDeniedException', 'ExpiredTokenException', 'connection error',
                      'ResourceNotFoundException in an unrelated message'):
            with self.subTest(error=error), self.invoke(error=error), self.assertRaisesRegex(RuntimeError, 'not confirmed absent'):
                p.check_test_secret(f.ACCOUNT)
        with self.invoke(None), self.assertRaises(RuntimeError):
            p.check_test_secret(f.ACCOUNT)

    def test_existing_unmanaged_collision_refused(self):
        doc = {'resource_changes': [{'address': 'module.external_secrets.aws_secretsmanager_secret.this',
                                    'change': {'actions': ['create']}}]}
        with self.invoke(SECRET), self.assertRaisesRegex(RuntimeError, 'already exists'):
            p.check_test_secret(f.ACCOUNT, doc)

    def test_plan_stops_before_terraform_or_bundle(self):
        with patch.object(p, 'variable_inputs', return_value={}), patch.object(p, 'initialize') as initialize, \
             patch.object(p, 'tf') as tf, self.invoke({**SECRET, 'DeletedDate': 'pending'}):
            with self.assertRaisesRegex(RuntimeError, 'scheduled for deletion'):
                p.plan(SimpleNamespace(account=f.ACCOUNT, management_ip='8.8.8.8'))
            initialize.assert_not_called()
            tf.assert_not_called()

    def test_apply_rechecks_pending_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            output = bundle / 'review.tfplan'
            output.write_bytes(b'fixture')
            record = {'account': f.ACCOUNT, 'sha': f.SHA, 'region': c.REGION, 'cluster': c.CLUSTER,
                      'created_at': time.time(), 'plan_sha256': p.digest(output),
                      'profile_sha256': p.digest(c.PROFILE), 'variable_inputs': {}, 'cidr': '8.8.8.8/32'}
            (bundle / 'review.json').write_text(json.dumps(record))
            with patch.object(p, 'variable_inputs', return_value={}), patch.object(p, 'initialize'), \
                 patch.object(p, 'tf', return_value=json.dumps(f.plan_document())) as tf, \
                 self.invoke({**SECRET, 'DeletedDate': 'pending'}):
                with self.assertRaisesRegex(RuntimeError, 'scheduled for deletion'):
                    p.apply(SimpleNamespace(confirm='apply-reviewed-aws-test', bundle=directory,
                                            account=f.ACCOUNT, sha=f.SHA))
                self.assertEqual([call.args[0] for call in tf.call_args_list], ['show'])


if __name__ == '__main__':
    unittest.main(verbosity=2)

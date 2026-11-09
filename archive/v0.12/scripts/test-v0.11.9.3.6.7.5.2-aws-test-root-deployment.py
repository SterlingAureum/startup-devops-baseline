#!/usr/bin/env python3
"""Offline behavior tests; cloud/cluster commands are replaced by fixtures."""
import base64
import copy
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
import uuid
from unittest.mock import patch

import aws_test_immutable_root as h
spec = importlib.util.spec_from_file_location('executor', h.ROOT / 'scripts/execute-v0.11.9.3.6.7.5.2-aws-test-root-deployment.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
C = h.p.load(h.ROOT / h.CONTRACT)
COMMIT = 'a' * 40
# Public documentation account and synthetic identities; no production values.
OUTPUTS = {'vpc_id': 'vpc-abcdef', 'cnpg_backup_bucket_name': 'example-test-backup',
           'cnpg_backup_role_arn': 'arn:aws:iam::123456789012:role/example-backup',
           'external_secrets_role_arn': 'arn:aws:iam::123456789012:role/example-eso',
           'external_secrets_secret_arn': 'arn:aws:secretsmanager:us-east-1:123456789012:secret:example',
           'external_secrets_secret_name': 'startup-devops-baseline-test/demo-api/postgresql'}
AT = datetime(2026, 9, 13, 6, 51, 13, tzinfo=timezone.utc)


class FakeRunner:
    """Successful reconciliation with controllable cloud ownership failures."""
    def __init__(self, bundle):
        self.kube = ['fixture-kubectl']
        self.bundle = bundle
        self.calls = []
        self.version_exists = False
        self.foreign_alb = False
        self.mismatch = False
        self.record = None
        self.uri = 'postgresql://app:fixture-password@postgresql-baseline-rw.data-platform.svc.cluster.local/app'
        self.apps = [{'metadata': {'name': x['name']}, 'spec': {'source': x['source'], 'destination': x['destination']},
                      'status': {'sync': {'status': 'Synced', 'revision': COMMIT}, 'health': {'status': 'Healthy'}}}
                     for x in h.p.load(bundle / 'application-source-map.json')]
    def check_time_and_state(self):
        return 1000
    def apply(self, label, objects):
        self.calls.append((label, True))
        return objects
    def wait(self, label, read, condition):
        value = read()
        if not condition(value):
            raise ValueError('fixture-not-ready')
        return value
    def get(self, label, kind, name, namespace=None, optional=False):
        self.calls.append((label, False))
        if kind == 'application':
            if name == h.p.APP:
                return {'spec': h.p.load(self.bundle / 'root-application.json')['spec'],
                        'status': {'sync': {'status': 'Synced', 'revision': COMMIT}, 'health': {'status': 'Healthy'}}}
            return next(x for x in self.apps if x['metadata']['name'] == name)
        if kind == 'applications.argoproj.io':
            return {'items': self.apps}
        if kind == 'clusters.postgresql.cnpg.io':
            return {'status': {'readyInstances': 3, 'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        if kind == 'externalsecret':
            return {'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        if kind == 'secret':
            key = 'fqdn-uri' if name == 'postgresql-baseline-app' else 'DATABASE_URL'
            uri = self.uri + ('wrong' if self.mismatch and key == 'DATABASE_URL' else '')
            return {'data': {key: base64.b64encode(uri.encode()).decode()}}
        if kind == 'ingress':
            return {'status': {'loadBalancer': {'ingress': [{'hostname': 'example.elb.amazonaws.com'}]}}}
        if kind == 'nodepools':
            return {'items': [x for x in h.p.load(self.bundle / 'rendered-root-resources.json')['items'] if x['kind'] == 'NodePool']}
        if kind == 'nodes':
            return {'items': []}
        if kind == 'serviceaccount':
            key = 'external_secrets_role_arn' if name == 'external-secrets' else 'cnpg_backup_role_arn'
            return {'metadata': {'annotations': {'eks.amazonaws.com/role-arn': OUTPUTS[key]}}}
        if kind == 'objectstores.barmancloud.cnpg.io':
            return {'spec': {'configuration': {'destinationPath': 's3://example-test-backup/postgresql-baseline'}}}
        raise AssertionError((label, kind, name))
    def call(self, label, command, payload=None, mutation=False, optional=False):
        self.calls.append((label, mutation))
        if label == 'metadata-before-seed':
            return {'ARN': OUTPUTS['external_secrets_secret_arn'], 'Name': OUTPUTS['external_secrets_secret_name'],
                    'VersionIdsToStages': {'existing': ['AWSCURRENT']} if self.version_exists else {}}
        if label == 'initial-credential-version':
            self.credential = json.loads(payload)
            assert self.uri not in ' '.join(command)
            return {}
        if label == 'credential-readback':
            return {'SecretString': json.dumps(self.credential)}
        if label == 'external-secret-refresh':
            return {}
        if label == 'application-alb':
            return {'LoadBalancers': [{'DNSName': 'example.elb.amazonaws.com', 'VpcId': 'vpc-foreign' if self.foreign_alb else OUTPUTS['vpc_id'],
                    'Type': 'application', 'Scheme': 'internet-facing', 'State': {'Code': 'active'},
                    'LoadBalancerArn': 'fixture-alb', 'CanonicalHostedZoneId': 'EXAMPLE'}]}
        if label == 'alb-owner-tags':
            return {'TagDescriptions': [{'Tags': [{'Key': 'elbv2.k8s.aws/cluster', 'Value': h.p.CLUSTER},
                                                  {'Key': 'ingress.k8s.aws/stack', 'Value': 'startup-apps/demo-api'}]}]}
        if label in ('dns-record-inventory', 'alias-final'):
            return {'ResourceRecordSets': [self.record] if self.record else []}
        if label == 'test-alias-upsert':
            self.record = json.loads(payload)['Changes'][0]['ResourceRecordSet']
            assert self.record['AliasTarget']['DNSName'].endswith('.')
            return {'ChangeInfo': {'Id': 'fixture-change'}}
        if label == 'dns-change-status':
            return {'ChangeInfo': {'Status': 'INSYNC'}}
        raise AssertionError(label)


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.umask(0o077)
        # Local test artifacts, never AWS calls. Allow this test directory only.
        cls.temp = tempfile.TemporaryDirectory()
        cls.bundle = Path(cls.temp.name)
        if shutil.which('kubectl'):
            h.render_bundle(C, COMMIT, OUTPUTS, cls.bundle)
            cls.render_available = True
        else:
            cls.render_available = False
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def runner(self):
        if not self.render_available:
            self.skipTest('kubectl absent: real local rendering required by prepare, not mocked')
        return FakeRunner(self.bundle)
    def deploy(self, runner):
        with patch.object(h.p, 'exact_main'):
            return e.deploy(runner, self.bundle, C, COMMIT, OUTPUTS, 'EXAMPLE', 'a' * 36)
    def test_actual_nested_render_and_all_git_children_pinned(self):
        r = self.runner()
        git = [x for x in r.apps if x['spec']['source']['repoURL'] == h.p.REPO]
        self.assertEqual(len(git), 9)
        self.assertTrue(all(x['spec']['source']['targetRevision'] == COMMIT for x in git))
        self.assertEqual(len(h.p.load(self.bundle / 'rendered-root-resources.json')['items']), 23)
        pg = h.p.load(self.bundle / 'rendered-postgresql-resources.json')['items']
        cluster = next(x for x in pg if x['kind'] == 'Cluster')
        self.assertEqual(cluster['spec']['serviceAccountTemplate']['metadata']['annotations']['eks.amazonaws.com/role-arn'], OUTPUTS['cnpg_backup_role_arn'])
    def test_complete_reconciliation_seed_dns_and_postchecks(self):
        r = self.runner()
        result = self.deploy(r)
        self.assertEqual(result['status'], 'aws-test-immutable-root-deployment-complete')
        for label in ('initial-credential-version', 'external-secret-refresh', 'test-alias-upsert'):
            self.assertEqual(r.calls.count((label, True)), 1)
        self.assertFalse(result['traffic_generated'])
        self.assertFalse(result['automatic_teardown_executed'])
    def test_existing_version_stops_without_secret_overwrite(self):
        r = self.runner(); r.version_exists = True
        with self.assertRaises(ValueError):
            self.deploy(r)
        self.assertNotIn(('initial-credential-version', True), r.calls)
    def test_eso_mismatch_stops_before_dns(self):
        r = self.runner(); r.mismatch = True
        with self.assertRaises(ValueError):
            self.deploy(r)
        self.assertNotIn(('test-alias-upsert', True), r.calls)
    def test_foreign_alb_stops_before_dns(self):
        r = self.runner(); r.foreign_alb = True
        with self.assertRaises(ValueError):
            self.deploy(r)
        self.assertNotIn(('test-alias-upsert', True), r.calls)
    def test_existing_dns_is_not_overwritten(self):
        r = self.runner(); r.record = {'Name': 'demo.test.aureumstack.com.', 'Type': 'AAAA'}
        with self.assertRaises(ValueError):
            self.deploy(r)
        self.assertNotIn(('test-alias-upsert', True), r.calls)
    def test_postcheck_child_revision_drift_rejected(self):
        r = self.runner()
        r.apps[0]['spec']['source']['targetRevision'] = 'main'
        with self.assertRaises(ValueError):
            self.deploy(r)
    def test_budget_includes_previous_day_and_cleanup(self):
        model = h.budget(C, AT)
        self.assertEqual(model['estimated_total_usd'], '27.50')
        self.assertEqual(model['mutation_stop_utc'], '2026-09-13T09:21:13Z')
        self.assertIsNone(model['historical_billed_spend_usd'])
        self.assertFalse(model['estimate_is_billing_guarantee'])
    def test_budget_cannot_fit_20_expectation(self):
        c = copy.deepcopy(C); c['budget']['totalLimitUsd'] = '20.00'
        with self.assertRaises(ValueError):
            h.budget(c, AT)
    def test_elapsed_deadline_not_extended(self):
        for at in (AT + timedelta(hours=3), AT + timedelta(days=1)):
            with self.assertRaises(ValueError):
                h.budget(C, at)
    def test_all_three_confirmations_required(self):
        h.assert_confirmations({}, False)
        h.assert_confirmations(h.CONFIRMATIONS, True)
        for key in h.CONFIRMATIONS:
            env = dict(h.CONFIRMATIONS); env.pop(key)
            with self.assertRaises(ValueError):
                h.assert_confirmations(env, True)
        with self.assertRaises(ValueError):
            h.assert_confirmations(h.CONFIRMATIONS, False)
    def test_old_confirmation_and_endpoint_rejected(self):
        for key in ('CONFIRM_AWS_TEST_APPLY', 'AWS_ENDPOINT_URL'):
            with self.assertRaises(ValueError):
                h.assert_confirmations({**h.CONFIRMATIONS, key: 'value'}, True)
    def test_wrong_state_arn_account_rejected(self):
        with self.assertRaises(ValueError):
            h.validate_outputs(OUTPUTS, '999999999999')
    def test_bad_database_host_rejected(self):
        raw = base64.b64encode(b'postgresql://app:fixture@external.example/app').decode()
        with self.assertRaises(ValueError):
            e.secret_uri({'data': {'fqdn-uri': raw}}, 'fqdn-uri')
    def test_one_time_marker_uses_exclusive_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'one-time-execution-attempt.json'
            h.p.write(marker, {'outcome_not_yet_known': True})
            with self.assertRaises(FileExistsError):
                h.p.write(marker, {})
    def test_deadline_stops_before_command(self):
        r = e.Runner(self.bundle, {'kubeconfig_path': 'fixture'}, AT, 'fixture')
        with patch.object(h, 'now', return_value=AT), patch.object(e.subprocess, 'Popen') as process:
            with self.assertRaises(ValueError):
                r.call('forbidden-command', ['fixture'])
            process.assert_not_called()
    def test_state_drift_stops_before_command(self):
        r = e.Runner(self.bundle, {'kubeconfig_path': 'fixture'}, AT + timedelta(hours=1), 'old')
        with patch.object(h, 'now', return_value=AT), patch.object(h.p, 'digest', return_value='changed'), patch.object(e.subprocess, 'Popen') as process:
            with self.assertRaises(ValueError):
                r.call('forbidden-command', ['fixture'])
            process.assert_not_called()
    def test_process_failure_records_attempt_and_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            r = e.Runner(Path(directory), {'kubeconfig_path': 'fixture'}, AT + timedelta(hours=1), 'same')
            process = unittest.mock.Mock(returncode=1)
            with patch.object(r, 'check_time_and_state', return_value=100), patch.object(e.subprocess, 'Popen', return_value=process) as popen:
                with self.assertRaises(ValueError):
                    r.call('test-mutation', ['fixture'], mutation=True)
            self.assertTrue(r.mutation_attempted)
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(len((Path(directory) / 'mutation-attempts.jsonl').read_text().splitlines()), 1)
    def test_timeout_terminates_process_group_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            r = e.Runner(Path(directory), {'kubeconfig_path': 'fixture'}, AT + timedelta(hours=1), 'same')
            process = unittest.mock.Mock(pid=42)
            process.communicate.side_effect = subprocess.TimeoutExpired('fixture', 1)
            with patch.object(r, 'check_time_and_state', return_value=100), patch.object(e.subprocess, 'Popen', return_value=process) as popen, patch.object(e.os, 'killpg') as kill:
                with self.assertRaises(subprocess.TimeoutExpired):
                    r.call('test-timeout', ['fixture'])
            self.assertEqual(popen.call_count, 1)
            kill.assert_called_once_with(42, e.signal.SIGTERM)
    def test_verify_binding_ttl_flags_and_token(self):
        proof = {"status": "aws-test-immutable-root-deployment-inputs-verified", "control_plane_commit": COMMIT,
                 "verified_at_utc": AT.strftime("%Y-%m-%dT%H:%M:%SZ"), "private_plan_sha256": "plan",
                 "attempt_token": str(uuid.uuid4()), "root_deployment_authorized": False,
                 "credential_transfer_authorized": False, "dns_write_authorized": False, "mutation_executed": False}
        args = SimpleNamespace(verify_result=Path('/fixture/proof'), expected_verify_sha256='hash',
                               expected_main=COMMIT, bundle=Path('/fixture/bundle'))
        def digest(path):
            return 'hash' if path == args.verify_result else 'plan'
        with patch.object(h, 'read_private', return_value=proof), patch.object(h.p, 'digest', side_effect=digest), patch.object(h, 'now', return_value=AT):
            self.assertEqual(e.validate_verify(args, C), proof)
            for field, value in (("control_plane_commit", "b" * 40), ("private_plan_sha256", "changed"),
                                 ("attempt_token", "invalid"), ("credential_transfer_authorized", True),
                                 ("verified_at_utc", "2026-09-13T06:00:00Z")):
                changed = dict(proof); changed[field] = value
                with patch.object(h, 'read_private', return_value=changed), self.assertRaises(ValueError):
                    e.validate_verify(args, C)
            args.expected_verify_sha256 = 'wrong'
            with self.assertRaises(ValueError):
                e.validate_verify(args, C)
    def test_private_render_tamper_and_human_review_gate(self):
        self.runner()
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            for name in ('root-application.json', 'rendered-root-resources.json', 'rendered-postgresql-resources.json', 'application-source-map.json'):
                shutil.copyfile(self.bundle / name, bundle / name)
                (bundle / name).chmod(0o600)
            inputs = bundle / 'inputs.json'; h.p.write(inputs, {})
            plan = {'expected_main': COMMIT, 'inputs_sha256': h.p.digest(inputs),
                    'contract_sha256': h.p.digest(h.ROOT / h.CONTRACT), 'created_at_utc': AT.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'human_manifest_reviewed': False, 'human_cost_scope_reviewed': True,
                    'cleanup_complete_by_utc': C['budget']['cleanupCompleteByUtc'], 'total_budget_limit_usd': '36.00'}
            for filename, key in (('root-application.json', 'root_manifest_sha256'), ('rendered-root-resources.json', 'render_sha256'),
                                  ('rendered-postgresql-resources.json', 'postgresql_render_sha256'), ('application-source-map.json', 'source_map_sha256')):
                plan[key] = h.p.digest(bundle / filename)
            h.p.write(bundle / 'private-root-plan.json', plan)
            with patch.object(h.p, 'persistent'), patch.object(h, 'now', return_value=AT):
                with self.assertRaises(ValueError):
                    h.validate_bundle(bundle, inputs, COMMIT, C)
                plan['human_manifest_reviewed'] = True
                (bundle / 'private-root-plan.json').write_text(json.dumps(plan))
                h.validate_bundle(bundle, inputs, COMMIT, C)
                (bundle / 'rendered-postgresql-resources.json').write_text('{}')
                with self.assertRaises(ValueError):
                    h.validate_bundle(bundle, inputs, COMMIT, C)

    def test_inventory_get_has_no_empty_resource_name(self):
        r = e.Runner(self.bundle, {'kubeconfig_path': 'fixture'}, AT, 'same')
        with patch.object(r, 'call', return_value={}) as call:
            r.get('inventory', 'nodes', '')
        self.assertNotIn('', call.call_args.args[1])


if __name__ == '__main__':
    unittest.main(verbosity=2)

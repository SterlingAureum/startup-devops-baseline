#!/usr/bin/env python3
"""Behavioral offline tests for the read-only cleanup boundary."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import aws_test_immutable_root as h
spec = importlib.util.spec_from_file_location('observer', h.ROOT / 'scripts/observe-v0.11.9.3.6.7.5.2.1-aws-test-cleanup.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c = h.p.load(h.ROOT / m.CONTRACT)


class CleanupObserverTests(unittest.TestCase):
    def observer(self):
        return m.Observer(Path('/fixture'), {'kubeconfig_path': '/fixture/kubeconfig'}, h.now(), 'fixture')
    def test_read_only_allowlist(self):
        runner = self.observer()
        with patch.object(m.e.Runner, 'call', return_value={}) as call:
            for service, action in sorted(m.ALLOWED_AWS):
                runner.call('read', m.AWS + [service, action])
            runner.get('read', 'pv', '')
            runner.call('config', runner.kube + ['config', 'view', '--minify', '-o', 'json'])
        self.assertEqual(call.call_count, len(m.ALLOWED_AWS) + 2)
    def test_mutations_secret_values_and_terraform_cannot_launch(self):
        runner = self.observer()
        forbidden=[m.AWS+['secretsmanager','get-secret-value'],m.AWS+['secretsmanager','delete-secret'],
                   m.AWS+['s3api','delete-objects'],m.AWS+['route53','change-resource-record-sets'],
                   runner.kube+['patch','application'],runner.kube+['delete','nodepool'],
                   ['terraform','destroy'],['bash','scripts/destroy-aws-test.sh']]
        with patch.object(m.e.Runner, 'call') as call:
            for command in forbidden:
                with self.assertRaises(ValueError):runner.call('forbidden',command)
            with self.assertRaises(ValueError):runner.call('forbidden',m.AWS+['sts','get-caller-identity'],mutation=True)
            with self.assertRaises(ValueError):runner.call('forbidden',m.AWS+['sts','get-caller-identity'],payload=b'body')
            call.assert_not_called()
    def test_cleanup_reserve_and_bounded_observation(self):
        at=datetime(2026,9,13,8,5,tzinfo=timezone.utc)
        self.assertEqual((m.deadline(c,at)-at).total_seconds(),600)
        at=datetime(2026,9,13,9,20,tzinfo=timezone.utc)
        self.assertEqual((m.deadline(c,at)-at).total_seconds(),73)
        for at in (datetime(2026,9,13,9,22,tzinfo=timezone.utc),datetime(2026,9,14,tzinfo=timezone.utc)):
            with self.assertRaises(ValueError):m.deadline(c,at)
    def apps(self):
        deployed=c['implementationBaselineCommit']
        source={'repoURL':h.p.REPO,'targetRevision':deployed}
        child={'metadata':{'name':'fixture-child'},'spec':{'source':source,'destination':{'namespace':'fixture'}},
               'status':{'health':{'status':'Healthy'},'operationState':{'phase':'Running'}}}
        root={'spec':{'source':source}}
        apps=[{'metadata':{'name':h.p.APP},**root},child]
        mapping=[{'name':'fixture-child',**child['spec']}]
        return apps,root,mapping,deployed
    def test_deployed_revision_remains_original_when_main_advances(self):
        args=self.apps();result=m.app_inventory(*args)
        self.assertEqual(result['application_count'],2)
        self.assertEqual(result['active_application_operation_count'],1)
        # Running sync is reported; observation does not terminate it.
    def test_unrelated_application_inventory_rejected(self):
        apps,root,mapping,deployed=self.apps()
        apps.append({'metadata':{'name':'unrelated'}})
        with self.assertRaises(ValueError):m.app_inventory(apps,root,mapping,deployed)
    def test_child_drift_rejected(self):
        apps,root,mapping,deployed=copy.deepcopy(self.apps())
        apps[1]['spec']['source']['targetRevision']='main'
        with self.assertRaises(ValueError):m.app_inventory(apps,root,mapping,deployed)
    def test_deployment_proof_cannot_be_replaced(self):
        with patch.object(h,'read_private',return_value=c['executionSummary']),patch.object(h.p,'digest',return_value=c['artifacts']['executionResult']['sha256']):
            m.deployment_proof(Path('/fixture'),c)
        with patch.object(h,'read_private',return_value=c['executionSummary']),patch.object(h.p,'digest',return_value='wrong'):
            with self.assertRaises(ValueError):m.deployment_proof(Path('/fixture'),c)
    def test_complete_observation_with_private_fixtures(self):
        apps,root,mapping,deployed=self.apps()
        account='123456789012'
        outputs={'vpc_id':'vpc-abcdef','cnpg_backup_bucket_name':'example-test-backup',
          'cnpg_backup_role_arn':'arn:aws:iam::123456789012:role/example-backup',
          'external_secrets_role_arn':'arn:aws:iam::123456789012:role/example-eso',
          'external_secrets_secret_arn':'arn:aws:secretsmanager:us-east-1:123456789012:secret:example',
          'external_secrets_secret_name':'startup-devops-baseline-test/demo-api/postgresql'}
        state={'outputs':{key:{'value':value} for key,value in outputs.items()}}
        inputs={'aws_account_id':account,'management_cidr':'fixture-cidr','kubeconfig_path':'/fixture/kubeconfig'}
        responses={
          'identity':{'Account':account},'clusters':{'clusters':[h.p.CLUSTER]},
          'cluster':{'cluster':{'status':'ACTIVE','endpoint':'fixture-endpoint','resourcesVpcConfig':
            {'vpcId':outputs['vpc_id'],'endpointPublicAccess':True,'endpointPrivateAccess':True,'publicAccessCidrs':['fixture-cidr']}}},
          'kubeconfig':{},'api-namespace':{},'applications':{'items':apps},
          'persistent-claims':{'items':[]},'vpc-compute':{'Reservations':[]},
          'load-balancers':{'LoadBalancers':[{'VpcId':outputs['vpc_id'],'Type':'application','Scheme':'internet-facing',
            'LoadBalancerArn':'fixture-alb','DNSName':'fixture.elb.amazonaws.com','CanonicalHostedZoneId':'FIXTURE'}]},
          'load-balancer-tags':{'TagDescriptions':[{'Tags':[{'Key':'elbv2.k8s.aws/cluster','Value':h.p.CLUSTER},
            {'Key':'ingress.k8s.aws/stack','Value':'startup-apps/demo-api'}]}]},
          'zones':{'HostedZones':[{'Name':'aureumstack.com.','Config':{'PrivateZone':False},'Id':'FIXTURE'}]},
          'dns-records':{'ResourceRecordSets':[{'Name':'demo.test.aureumstack.com.','Type':'A',
             'AliasTarget':{'DNSName':'dualstack.fixture.elb.amazonaws.com.','HostedZoneId':'FIXTURE'}}]},
          'credential-metadata':{'ARN':outputs['external_secrets_secret_arn'],'VersionIdsToStages':{'fixture':['AWSCURRENT']}},
          'backup-versions':{'Versions':[{'Size':10},{'Size':20}],'DeleteMarkers':[{}]}}
        for label in ('nodes','nodepools','nodeclaims','nodeclasses','persistent-volumes','database'):responses[label]={'items':[]}
        class FixtureObserver(m.Observer):
            def call(self,label,command,payload=None,mutation=False,optional=False):
                if mutation or payload is not None:raise AssertionError('fixture-mutation')
                return responses[label]
            def check_time_and_state(self):return 100
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(inputs=Path('/fixture/inputs'),expected_main='b'*40,bundle=Path('/fixture/bundle'),
                                 deployment_result=Path('/fixture/result'),output_directory=Path(directory)/'inventory')
            with patch.object(m,'source_checks',return_value=c),patch.object(h,'assert_confirmations'),patch.object(h.p,'exact_main'), \
                 patch.object(h.p,'local_inputs',return_value=(None,inputs,state)),patch.object(h,'read_private'), \
                 patch.object(m,'deployment_proof'),patch.object(m,'reviewed_bundle',return_value=(root,mapping)), \
                 patch.object(m,'deadline',return_value=h.now()),patch.object(h,'new_directory',side_effect=lambda path:path.mkdir(mode=0o700)), \
                 patch.object(h.p,'digest',return_value='fixture-state'),patch.object(h.p,'kube_auth'),patch.object(m,'Observer',FixtureObserver):
                result=m.observe(args)
            self.assertEqual(result['backup_recorded_version_bytes'],30)
            self.assertEqual(result['backup_delete_marker_count'],1)
            self.assertFalse(result['volume_inventory_exhaustive'])
            self.assertFalse(result['teardown_authorized'])
            self.assertFalse(result['credential_value_read'])
            self.assertEqual((args.output_directory/'summary.json').stat().st_mode & 0o777,0o600)

    def test_exact_reported_execution_bytes(self):
        raw=(json.dumps(c['executionSummary'],indent=2,sort_keys=True)+'\n').encode()
        import hashlib
        self.assertEqual(len(raw),821)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),c['artifacts']['executionResult']['sha256'])


if __name__=='__main__':unittest.main(verbosity=2)

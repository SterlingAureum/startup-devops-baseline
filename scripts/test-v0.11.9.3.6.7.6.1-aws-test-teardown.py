#!/usr/bin/env python3
"""Offline behavioral gates for explicit staged deletion."""
import copy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
import aws_test_immutable_root as h
spec=importlib.util.spec_from_file_location('teardown',h.ROOT/'scripts/execute-v0.11.9.3.6.7.6.1-aws-test-teardown.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture_state():
    return {'resources':[{'mode':'managed','module':'module.eks','type':'aws_eks_cluster','name':'this','instances':[{'attributes':{'id':'fixture-cluster'}}]},
        {'mode':'managed','module':'module.eks','type':'aws_eks_node_group','name':'this','instances':[{'attributes':{'id':'fixture-nodegroup'}}]},
        {'mode':'managed','module':'module.vpc','type':'aws_vpc','name':'this','instances':[{'attributes':{'id':'fixture-vpc'}}]}]}


def fixture_plan():
    return {'resource_changes':[{'mode':'managed','address':address,'type':address.split('.')[-2],
        'change':{'actions':['delete'],'before':value,'after':None}} for address,value in m.addresses(fixture_state()).items()]}


class TeardownTests(unittest.TestCase):
    def test_indexed_state_addresses(self):
        value=fixture_state();value['resources'][0]['instances'][0]['index_key']='fixture-key'
        self.assertIn('module.eks.aws_eks_cluster.this["fixture-key"]',m.addresses(value))
    def test_full_delete_plan(self):
        gate=m.plan_gate(fixture_plan(),fixture_state(),'final');self.assertEqual(gate['managed_delete_count'],3)
    def test_eks_target_plan_must_preserve_vpc(self):
        with self.assertRaises(ValueError):m.plan_gate(fixture_plan(),fixture_state(),'eks')
        plan=fixture_plan();plan['resource_changes']=plan['resource_changes'][:2]
        self.assertEqual(m.plan_gate(plan,fixture_state(),'eks')['managed_delete_count'],2)
    def test_final_incomplete_plan_rejected(self):
        plan=fixture_plan();plan['resource_changes']=plan['resource_changes'][:2]
        with self.assertRaises(ValueError):m.plan_gate(plan,fixture_state(),'final')
    def test_updates_creates_and_replacements_rejected(self):
        for action in (['update'],['create'],['delete','create'],['create','delete']):
            plan=fixture_plan();plan['resource_changes'][0]['change']['actions']=action
            with self.assertRaises(ValueError):m.plan_gate(plan,fixture_state(),'final')
    def test_unknown_resource_and_before_id_rejected(self):
        for key,value in (('address','module.prod.aws_vpc.this'),('change',{'actions':['delete'],'before':{'id':'different'},'after':None})):
            plan=fixture_plan();plan['resource_changes'][0][key]=value
            with self.assertRaises(ValueError):m.plan_gate(plan,fixture_state(),'final')
    def test_verified_remote_absence_accounted_separately(self):
        plan=fixture_plan();missing=plan['resource_changes'].pop()
        plan['resource_drift']=[missing]
        self.assertEqual(m.plan_gate(plan,fixture_state(),'final')['reviewed_remote_absence_count'],1)
    def test_sg_ownership_and_reference_gate(self):
        record={'cluster_sg':'fixture-sg','outputs':{'vpc_id':'fixture-vpc'},'account':'fixture-owner'}
        group={'GroupId':'fixture-sg','VpcId':'fixture-vpc','OwnerId':'fixture-owner','GroupName':'eks-cluster-sg-'+h.p.CLUSTER+'-fixture',
            'Description':'EKS created security group','IpPermissions':[{'UserIdGroupPairs':[{'GroupId':'fixture-sg'}]}]}
        self.assertTrue(m.sg_safe([group],[],record))
        self.assertFalse(m.sg_safe([],[],record))
        with self.assertRaises(ValueError):m.sg_safe([group],[{}],record)
        other={'GroupId':'other','IpPermissions':[{'UserIdGroupPairs':[{'GroupId':'fixture-sg'}]}]}
        with self.assertRaises(ValueError):m.sg_safe([group,other],[],record)
        group['OwnerId']='foreign'
        with self.assertRaises(ValueError):m.sg_safe([group],[],record)
    def test_each_phase_requires_only_its_own_confirmation(self):
        for phase,expected in m.PHASES.items():
            env={expected[0]:expected[1]} if expected else {}
            m.confirmations(phase,env)
            if expected:
                with self.assertRaises(ValueError):m.confirmations(phase,{})
            with self.assertRaises(ValueError):m.confirmations(phase,{**env,'CONFIRM_AWS_TEST_APPLY':'value'})
            with self.assertRaises(ValueError):m.confirmations(phase,{**env,'TF_CLI_ARGS_apply':'value'})
    def test_no_delete_call_after_deadline(self):
        runner=m.Runner(Path('/fixture'),{'kubeconfig_path':'fixture'},h.now()-timedelta(seconds=1),'fixture')
        with patch.object(m.subprocess,'Popen') as process:
            with self.assertRaises(ValueError):runner.invoke('forbidden',['fixture'],True)
            process.assert_not_called()
    def test_failed_mutation_is_journaled_once_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=m.Runner(Path(directory),{'kubeconfig_path':'fixture'},h.now()+timedelta(minutes=1),'fixture')
            process=Mock(returncode=1)
            with patch.object(runner,'check_time_and_state',return_value=100),patch.object(m.subprocess,'Popen',return_value=process) as popen:
                with self.assertRaises(ValueError):runner.invoke('fixture-delete',['fixture'],True)
            self.assertEqual(popen.call_count,1)
            self.assertTrue(runner.mutation_attempted)
            self.assertEqual(len((Path(directory)/'mutation-attempts.jsonl').read_text().splitlines()),1)
    def test_timeout_stops_process_group_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=m.Runner(Path(directory),{'kubeconfig_path':'fixture'},h.now()+timedelta(minutes=1),'fixture')
            process=Mock(pid=42);process.wait.side_effect=[subprocess.TimeoutExpired('fixture',1),0,0]
            with patch.object(runner,'check_time_and_state',return_value=100),patch.object(m.subprocess,'Popen',return_value=process) as popen,patch.object(m.os,'killpg') as kill:
                with self.assertRaises(subprocess.TimeoutExpired):runner.invoke('fixture-delete',['fixture'],True)
            self.assertEqual(popen.call_count,1);kill.assert_called_once_with(42,m.signal.SIGTERM)
    def test_data_absence_code_is_narrow(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=m.Runner(Path(directory),{'kubeconfig_path':'fixture'},h.now()+timedelta(minutes=1),'fixture')
            def launch(cmd,**kwargs):kwargs['stderr'].write(b'An error occurred (AccessDenied)');kwargs['stderr'].flush();return Mock(returncode=1)
            with patch.object(runner,'check_time_and_state',return_value=100),patch.object(m.subprocess,'Popen',side_effect=launch):
                with self.assertRaises(ValueError):runner.invoke('bucket-read',['fixture'],absent_code='NoSuchBucket')
    def test_app_only_orphan_cascade(self):
        runner=m.Runner(Path('/fixture'),{'kubeconfig_path':'fixture'},h.now(),'fixture')
        with patch.object(runner,'invoke',return_value={}) as invoke:
            runner.delete('app','application','fixture');self.assertIn('--cascade=orphan',invoke.call_args.args[1])
            runner.delete('pool','nodepool','fixture');self.assertIn('--cascade=background',invoke.call_args.args[1])
    def test_runtime_freezes_root_first_and_keeps_controllers(self):
        record={'apps':['child',h.p.APP],'alias':{},'zone':'fixture','pvs':[], 'new_instance_ids':['fixture'], 'outputs':{'vpc_id':'fixture'}}
        class FixtureRunner:
            kube=['fixture-kubectl']
            def __init__(self):self.calls=[]
            def get(self,label,*args):
                if label.startswith(('freeze-check','orphan-check')):return {'spec':{},'metadata':{'finalizers':list(m.FINALIZERS)},'status':{}}
                return {'items':[]}
            def invoke(self,label,command,*args,**kwargs):
                self.calls.append((label,command))
                if label=='delete-test-alias':return {'ChangeInfo':{'Id':'fixture'}}
                if label=='dns-change':return {'ChangeInfo':{'Status':'INSYNC'}}
                if label=='alb-removal-read':return {'LoadBalancers':[]}
                if label=='new-node-read':return {'Reservations':[]}
                return {}
            def delete(self,label,kind,name,namespace=None):self.calls.append((label,[kind,name]))
            def absent(self,*args):pass
            def wait(self,label,read,condition):
                value=read()
                if not condition(value):raise AssertionError(label)
                return value
        record['app_specs']={name:{} for name in record['apps']}
        runner=FixtureRunner();m.runtime_cleanup(runner,record)
        self.assertEqual(runner.calls[0][0],'freeze-'+h.p.APP)
        namespace_deletes=[cmd[1] for label,cmd in runner.calls if label.startswith('remove-namespace')]
        self.assertEqual(namespace_deletes,['startup-apps','data-platform','observability'])
        self.assertNotIn('kube-system',namespace_deletes);self.assertNotIn('cnpg-system',namespace_deletes)
    def test_final_saved_plan_once_and_hash_tamper_stops_before_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);workspace=folder/'workspace';workspace.mkdir(mode=0o700)
            record={'outputs':{'vpc_id':'fixture-vpc','cnpg_backup_bucket_name':'fixture-bucket','external_secrets_secret_arn':'fixture-container'},
                    'zone':'fixture-zone','disk_ids':['fixture-disk'],'account':'fixture-owner'}
            h.p.write(workspace/'runtime-record.json',record)
            inputs=folder/'inputs.json';h.p.write(inputs,{})
            binary=folder/'destroy.tfplan';binary.write_bytes(b'fixture-binary');binary.chmod(0o600)
            plan=fixture_plan();h.p.write(folder/'destroy-plan.json',plan)
            text=folder/'destroy-plan.txt';text.write_text('fixture-plan');text.chmod(0o600)
            lock=folder/'lock';lock.write_text('fixture-lock')
            proof={'window_contract_sha256':m.window_digest(),'stage':'final','main':'a'*40,'human_reviewed':True,'inputs_sha256':h.p.digest(inputs),'state_sha256':'before',
                'runtime_record_sha256':h.p.digest(workspace/'runtime-record.json'),'created_at_utc':h.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'terraform_version':'1.9.8','provider_lock_sha256':h.p.digest(lock),'binary_sha256':h.p.digest(binary),
                'json_sha256':h.p.digest(folder/'destroy-plan.json'),'text_sha256':h.p.digest(text),
                'gate':m.plan_gate(plan,fixture_state(),'final')}
            path=folder/'plan-proof.json';h.p.write(path,proof)
            args=SimpleNamespace(proof=path,expected_proof_sha256=h.p.digest(path),expected_main='a'*40,inputs=inputs,workspace=workspace)
            original_digest=h.p.digest
            def digest(path):
                return original_digest(lock) if path==m.TF/'.terraform.lock.hcl' else ('after' if path==h.ROOT/h.p.STATE else original_digest(path))
            class FixtureRunner:
                state_hash='before';changing_state=False
                def __init__(self):self.applied=False;self.calls=[]
                def invoke(self,label,command,*args,**kwargs):
                    self.calls.append(label)
                    if label=='terraform-version-before-apply':return {'terraform_version':'1.9.8'}
                    if label=='terraform-workspace-before-apply':return b'default'
                    if label=='saved-plan-show':return plan
                    if label=='terraform-apply-saved-plan':self.applied=True;return b''
                    return {'final-eks':{'clusters':[]},'final-vpc':{'Vpcs':[]},'final-alias':{'ResourceRecordSets':[]},
                      'final-disks':{'Volumes':[]},'final-alb':{'LoadBalancers':[]},'final-backup-bucket':None,'final-container':None}[label]
            runner=FixtureRunner()
            with patch.object(h.p,'persistent'),patch.object(h.p,'digest',side_effect=digest),patch.object(m,'state',side_effect=lambda:{'resources':[]} if runner.applied else fixture_state()):
                binary.write_bytes(b'tampered')
                with self.assertRaises(ValueError):m.apply_plan(runner,args,record,'final')
                self.assertNotIn('terraform-apply-saved-plan',runner.calls)
                binary.write_bytes(b'fixture-binary')
                result=m.apply_plan(runner,args,record,'final')
            self.assertEqual(result['status'],'aws-test-final-delete-complete')
            self.assertEqual(runner.calls.count('terraform-apply-saved-plan'),1)
            self.assertTrue((workspace/'final-apply-attempt.json').exists())
            self.assertFalse(result['residual_cost_audit_executed'])

    def test_renewal_projection_and_budget_failure(self):
        c=h.p.load(h.ROOT/m.CONTRACT)
        value=m.projection(c)
        self.assertEqual(value['estimated_total_usd'],'29.55')
        self.assertFalse(value['estimate_is_billing_guarantee'])
        self.assertIsNone(value['historical_billed_spend_usd'])
        c['budget']['totalLimitUsd']='20.00'
        with self.assertRaises(ValueError):m.projection(c)
    def test_old_proof_cannot_enter_renewed_window(self):
        with self.assertRaises(ValueError):m.require_window({'main':'a'*40})
        with self.assertRaises(ValueError):m.require_window({'window_contract_sha256':'0'*64})
        m.require_window({'window_contract_sha256':m.window_digest()})
    def test_renewed_observer_deadline_preserves_reserve(self):
        at=h.p.utc('2026-09-13T10:40:00Z')
        c=m.o.source_checks()
        self.assertEqual(m.o.deadline(c,at),h.p.utc('2026-09-13T10:50:00Z'))
        self.assertEqual(c['implementationBaselineCommit'],'375417830174723598a2565b8f197f74c2c50697')
        with self.assertRaises(ValueError):m.o.deadline(c,h.p.utc('2026-09-13T11:00:00Z'))
    def test_attempt_markers_are_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'attempt.json';h.p.write(marker,{})
            with self.assertRaises(FileExistsError):h.p.write(marker,{})


if __name__=='__main__':unittest.main(verbosity=2)

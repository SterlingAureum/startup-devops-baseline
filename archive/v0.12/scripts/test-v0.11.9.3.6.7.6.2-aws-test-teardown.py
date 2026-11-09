#!/usr/bin/env python3
"""Offline behavioral gates for explicit staged deletion."""
import copy
import hashlib
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import shutil,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
import aws_test_immutable_root as h
spec=importlib.util.spec_from_file_location('teardown',h.ROOT/'scripts/execute-v0.11.9.3.6.7.6.2-aws-test-teardown.py')
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
            runner.delete('app','application','fixture');self.assertIn('--cascade=orphan',invoke.call_args.args[1]);self.assertEqual(invoke.call_args.args[1][-2:],['-o','name']);self.assertFalse(invoke.call_args.kwargs['json_output'])
            runner.delete('pool','nodepool','fixture');self.assertIn('--cascade=background',invoke.call_args.args[1])
    def test_resume_never_repeats_freeze_and_keeps_controllers(self):
        record={'apps':['child',h.p.APP],'alias':{},'zone':'fixture','pvs':[], 'new_instance_ids':['fixture'], 'outputs':{'vpc_id':'fixture'}}
        class FixtureRunner:
            kube=['fixture-kubectl']
            def __init__(self):self.calls=[]
            def get(self,label,*args):
                if label.startswith('resume-delete-check'):return {'spec':{},'metadata':{'uid':'fixture-uid','finalizers':[] if label.endswith(h.p.APP) else list(m.FINALIZERS)},'status':{}}
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
        record['app_uids']={name:'fixture-uid' for name in record['apps']}
        runner=FixtureRunner();m.runtime_cleanup(runner,record)
        self.assertEqual(runner.calls[0][0],'remove-remaining-app-'+h.p.APP)
        self.assertFalse(any(label.startswith('freeze-') for label,cmd in runner.calls))
        self.assertFalse(any(label=='orphan-remaining-'+h.p.APP for label,cmd in runner.calls))
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
        self.assertEqual(value['estimated_total_usd'],'31.97')
        self.assertFalse(value['estimate_is_billing_guarantee'])
        self.assertIsNone(value['historical_billed_spend_usd'])
        c['budget']['totalLimitUsd']='20.00'
        with self.assertRaises(ValueError):m.projection(c)
    def test_old_proof_cannot_enter_renewed_window(self):
        with self.assertRaises(ValueError):m.require_window({'main':'a'*40})
        with self.assertRaises(ValueError):m.require_window({'window_contract_sha256':'0'*64})
        m.require_window({'window_contract_sha256':m.window_digest()})
    def test_resume_window_preserves_reserve(self):
        c=m.source_checks()
        self.assertEqual(c['cleanupCompleteByUtc'],'2026-09-13T14:00:00Z')
        self.assertEqual(c['runtimeStopUtc'],'2026-09-13T12:30:00Z')
        self.assertEqual(c['renewedSchedule']['runtimeLatestStartUtc'],'2026-09-13T12:10:00Z')
    def test_paused_root_present_and_absent_supported(self):
        original={'apps':[h.p.APP,'child'],'app_specs':{name:{'source':{'targetRevision':'fixture'},'syncPolicy':{'automated':{'prune':True}}} for name in (h.p.APP,'child')}}
        uids={h.p.APP:'root-uid','child':'child-uid'}
        apps=[{'metadata':{'name':name,'uid':uids[name],'finalizers':[]},'spec':{'source':{'targetRevision':'fixture'},'syncPolicy':{}}} for name in original['apps']]
        self.assertEqual(len(m.resume_apps(apps,original,uids)),2)
        self.assertEqual(set(m.resume_apps(apps[1:],original,uids)),{'child'})
    def test_resume_rejects_recreated_active_unpaused_and_drifted_apps(self):
        original={'apps':[h.p.APP,'child'],'app_specs':{h.p.APP:{},'child':{}}};uids={h.p.APP:'root','child':'child'}
        app={'metadata':{'name':'child','uid':'child','finalizers':[]},'spec':{}}
        variants=[]
        x=copy.deepcopy(app);x['metadata']['uid']='replacement';variants.append(x)
        x=copy.deepcopy(app);x['metadata']['deletionTimestamp']='fixture';variants.append(x)
        x=copy.deepcopy(app);x['metadata']['finalizers']=['unknown'];variants.append(x)
        x=copy.deepcopy(app);x['spec']={'syncPolicy':{'automated':{}}};variants.append(x)
        x=copy.deepcopy(app);x['status']={'operationState':{'phase':'Running'}};variants.append(x)
        x=copy.deepcopy(app);x['spec']={'source':{'targetRevision':'other'}};variants.append(x)
        for value in variants:
            with self.assertRaises(ValueError):m.resume_apps([value],original,uids)
    def test_exact_failed_journal_rejects_later_mutations(self):
        record={'apps':[h.p.APP]+['child-'+str(x) for x in range(18)]}
        stages=['freeze-'+x for x in record['apps']]+['orphan-'+h.p.APP,'remove-app-'+h.p.APP]
        journal=[{'stage':x} for x in stages];m.journal_signature(journal,record)
        with self.assertRaises(ValueError):m.journal_signature(journal+[{'stage':'delete-test-alias'}],record)
        journal[0]['stage']='other'
        with self.assertRaises(ValueError):m.journal_signature(journal,record)
    def test_real_kubectl_delete_output_against_local_fixture_only(self):
        binary=shutil.which('kubectl');self.assertIsNotNone(binary,'kubectl required by target gate')
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,value):
                raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                path=self.path.split('?')[0]
                if path=='/api':value={'kind':'APIVersions','apiVersion':'v1','versions':['v1'],'serverAddressByClientCIDRs':[]}
                elif path=='/apis':value={'kind':'APIGroupList','apiVersion':'v1','groups':[]}
                elif path=='/api/v1':value={'kind':'APIResourceList','apiVersion':'v1','groupVersion':'v1','resources':[{'name':'configmaps','singularName':'configmap','namespaced':True,'kind':'ConfigMap','verbs':['get','delete','list']}]}
                else:value={'kind':'ConfigMap','apiVersion':'v1','metadata':{'name':'fixture-only','namespace':'default','uid':'fixture-uid'}}
                self.send(value)
            def do_DELETE(self):
                calls.append(self.path);self.send({'kind':'Status','apiVersion':'v1','status':'Success','details':{'name':'fixture-only','kind':'configmaps'},'code':200})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                common=[binary,'--kubeconfig=/dev/null','--server=http://127.0.0.1:'+str(server.server_port),'--token=fixture-only','--cache-dir='+folder,'delete','configmap','fixture-only','--wait=false','--cascade=orphan','-o']
                bad=subprocess.run(common+['json'],capture_output=True,timeout=20)
                self.assertEqual(bad.returncode,1);self.assertEqual(calls,[])
                self.assertEqual(hashlib.sha256(bad.stderr).hexdigest(),'228da5c0631e3e298986ee19118037856b3359b6fb9c8cfbd4171dc9484cf9f5')
                good=subprocess.run(common+['name'],capture_output=True,timeout=20)
                self.assertEqual(good.returncode,0);self.assertEqual(len(calls),1);self.assertEqual(good.stdout,b'configmap/fixture-only\n')
        finally:server.shutdown();server.server_close();thread.join()
    def test_prior_evidence_reads_original_marker_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);w=root/'prior';w.mkdir(mode=0o700);out=root/'output';out.mkdir(mode=0o700)
            names=[h.p.APP]+['child-'+str(x) for x in range(18)]
            record={'apps':names,'app_specs':{name:{'source':{'fixture':name},'syncPolicy':{'automated':{}}} for name in names}}
            proof={'human_reviewed':True,'runtime_record_sha256':'','state_sha256':'fixture-state','main':'fixture-main'}
            h.p.write(w/'runtime-record.json',record);proof['runtime_record_sha256']=h.p.digest(w/'runtime-record.json')
            h.p.write(w/'runtime-proof-reviewed.json',proof);h.p.write(w/'runtime-attempt.json',{'fixture':True})
            h.p.write(out/'failure.json',{'fixture':True})
            stages=['freeze-'+name for name in names]+['orphan-'+h.p.APP,'remove-app-'+h.p.APP]
            journal=out/'mutation-attempts.jsonl';journal.write_text('\n'.join(json.dumps({'stage':x}) for x in stages));journal.chmod(0o600)
            for name in names:h.p.write(out/('0000-freeze-'+name+'.stdout'),{'metadata':{'name':name,'uid':'uid-'+name},'spec':m.expected_paused(record['app_specs'][name])})
            h.p.write(out/('0000-orphan-'+h.p.APP+'.stdout'),{'metadata':{'name':h.p.APP,'uid':'uid-'+h.p.APP,'finalizers':[]}})
            error=out/('0000-remove-app-'+h.p.APP+'.stderr');error.write_text("error: unexpected -o output mode: json. We only support '-o name'\n");error.chmod(0o600)
            stdout=error.with_suffix('.stdout');stdout.write_bytes(b'');stdout.chmod(0o600)
            mapping={'runtimeRecord':w/'runtime-record.json','reviewedProof':w/'runtime-proof-reviewed.json','attemptMarker':w/'runtime-attempt.json',
                'failure':out/'failure.json','mutationJournal':journal,'deleteStderr':error}
            c={'implementationBaselineCommit':'fixture-main','priorFailure':{'artifacts':{key:{'sha256':h.p.digest(path)} for key,path in mapping.items()}}}
            args=SimpleNamespace(prior_workspace=w,prior_output=out,bundle=root/'bundle',deployment_result=root/'result')
            original=h.p.digest
            def digest(path):return 'fixture-state' if path==h.ROOT/h.p.STATE else original(path)
            marker=(w/'runtime-attempt.json').read_bytes()
            with patch.object(h.p,'persistent'),patch.object(h.p,'digest',side_effect=digest),patch.object(m.o,'reviewed_bundle',return_value=({'spec':record['app_specs'][h.p.APP]},[{'name':name} for name in names[1:]])),patch.object(m.o,'deployment_proof'):
                value,uids=m.prior_evidence(args,c)
            self.assertEqual(value,record);self.assertEqual(len(uids),19)
            self.assertEqual((w/'runtime-attempt.json').read_bytes(),marker)
            self.assertFalse((w/'runtime-resume-attempt.json').exists())
    def test_attempt_markers_are_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'attempt.json';h.p.write(marker,{})
            with self.assertRaises(FileExistsError):h.p.write(marker,{})


if __name__=='__main__':unittest.main(verbosity=2)

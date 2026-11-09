#!/usr/bin/env python3
"""Three-profile/two-phase offline composition, no cloud or CLI transport."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import guarded_runtime_simulation_v6774 as m
from guarded_attempt_journal import AttemptJournal
from guarded_plan_rules import managed_inventory
from guarded_runtime_rules import RuleViolation

ROOT=Path(__file__).resolve().parent.parent
T='2026-09-14T05:00:00Z';EXPIRES='2026-09-14T05:15:00Z';END='2026-09-14T07:00:00Z'
MAIN='a'*40
raw=lambda v:json.dumps(v,sort_keys=True).encode()

def scenario(directory,environment='aws-test',phase='eks-delete'):
    resources=[]
    definitions=[('eks','aws_eks_cluster'),('karpenter','aws_iam_role'),('cnpg_backup','aws_iam_role'),
                 ('external_secrets','aws_iam_role'),('vpc','aws_vpc'),('tls_dns','aws_acm_certificate')]
    if environment!='aws-prod':definitions += [('github_actions_runtime_identity','aws_eks_access_entry'),('fis','aws_fis_experiment_template')]
    for module,kind in definitions:
        resources.append({'module':'module.'+module,'mode':'managed','type':kind,'name':'fixture',
                          'instances':[{'attributes':{'id':'fixture-'+module}}]})
    state={'version':4,'resources':resources};inventory=managed_inventory(state)
    reviewed=tuple(r for r in inventory.values() if phase=='final-delete' or r['module'].removeprefix('module.') in m.DEPENDENCY_MODULES)
    plan={'terraform_version':'1.14.5','resource_changes':[{'address':r['address'],'module_address':r['module'],'mode':'managed','type':r['type'],
           'change':{'actions':['delete'],'before':{'id':r['id']},'after':None}} for r in reviewed]}
    steps=m.CLEANUP_STEPS[:m.CLEANUP_STEPS.index(phase)]
    receipts=[]
    for step in steps:
        text=raw({'step':step,'environment':environment,'confirmed':True,'simulation_only':True}).decode()
        receipts.append({'step':step,'raw':text,'sha256':m.sha(text.encode())})
    scope={'environment':environment,'phase':phase,'receipts':receipts,
           'reviewed_resources':list(reviewed),'reviewed_remote_absence':[]}
    inputs={'environment':environment,'region':'us-east-1','account':'0'*12,
            'cluster':'fixture-'+environment.removeprefix('aws-'),'budget_limit_usd':'36.00','terraform_version':'1.14.5','workspace':'default'}
    artifacts={'inputs':raw(inputs),'scope':raw(scope),'state':raw(state),'plan':raw(plan),'binary':b'fixture-saved-plan','text':b'fixture-readable-plan','provider_lock':b'fixture-readonly-lock'}
    approval={'schema':'offline-destroy-approval-v1','simulation_only':True,'environment':environment,'phase':phase,
        'main':MAIN,'hashes':{k:m.sha(v) for k,v in artifacts.items()},'journal_directory':str(directory),
        'start_utc':T,'end_utc':END,'created_at':T,'original_created_at':T,'expires_at':EXPIRES,'budget_limit_usd':'36.00'}
    cleanup={k:True for k in ('scope_verified','inventory_complete','applications_frozen','eks_absent','captured_compute_absent',
       'captured_volumes_absent','load_balancers_absent','target_groups_absent','test_dns_absent','captured_eni_absent','captured_sg_absent')}
    cleanup.update({k:0 for k in ('active_application_operations','applications','business_namespaces','nodeclaims','persistent_volumes',
       'captured_runtime_compute','captured_pv_volumes','load_balancers','target_groups','test_dns_records','nodepools','nodeclasses')})
    pre={'identity':{k:inputs[k] for k in ('environment','region','account','cluster')},'main':MAIN,'observed_at':T,
        'inventory_complete':True,'estimated_total_usd':'1.00','state_sha256':m.sha(artifacts['state']),
        'plan_sha256':m.sha(artifacts['plan']),'binary_sha256':m.sha(artifacts['binary']),
        'native_remote_absence':[],'cleanup':cleanup,'terraform_version':'1.14.5','workspace':'default',
        'text_sha256':m.sha(artifacts['text']),'provider_lock_sha256':m.sha(artifacts['provider_lock'])}
    selected={r['address'] for r in reviewed}
    after={'version':4,'resources':[r for r in resources if r['module']+'.'+r['type']+'.'+r['name'] not in selected]}
    post={k:copy.deepcopy(v) for k,v in pre.items()}
    post.update({'native_absent_addresses':sorted(selected),'state_after':after,'eks_absent':True,'final_cloud_absent':True})
    confirmations={'AWS_ENVIRONMENT':environment,'CONFIRM_'+environment.upper().replace('-','_')+'_OFFLINE_DESTROY':
                   'simulate-reviewed-'+environment+'-'+phase+'-once'}
    return {'artifacts':artifacts,'approval':approval,'observations':{'pre':raw(pre),'immediate':raw(pre),'post':raw(post)},
            'confirmations':confirmations,'environment':environment,'phase':phase}

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT.parent,prefix='adapter-fixture-')
        self.directory=Path(self.temp.name)/'journal';self.directory.mkdir(mode=0o700)
        self.s=scenario(self.directory);self.last_transport=None
    def tearDown(self):self.temp.cleanup()
    def run_case(self,s=None,*,samples=None,fail_at='',result=None,directory=None,approval_hash=None,transport=None):
        s=s or self.s;approval=raw(s['approval'])
        self.last_transport=transport or m.ScenarioTransport(s['observations'],result or raw({'success':True}),fail_at=fail_at)
        return m.OfflineDestroyAdapter(s['environment'],s['phase'],MAIN,repository_root=ROOT).run(s['artifacts'],approval,
            approval_hash or m.sha(approval),journal_directory=directory or self.directory,confirmations=s['confirmations'],
            transport=self.last_transport,clock=m.ScenarioClock(samples or (T,)*7))
    def refresh(self):self.s['approval']['hashes']={k:m.sha(v) for k,v in self.s['artifacts'].items()}
    def change_observation(self,label,fn):
        obj=json.loads(self.s['observations'][label]);fn(obj);self.s['observations'][label]=raw(obj)
    def change_artifact(self,key,fn):
        obj=json.loads(self.s['artifacts'][key]);fn(obj);self.s['artifacts'][key]=raw(obj)
    def snapshot(self):
        path=self.directory/'attempt.json';marker=json.loads(path.read_bytes())
        with AttemptJournal.open(self.directory,marker['binding'],m.sha(path.read_bytes()),repository_root=ROOT) as h:return h.snapshot()
    def no_fake_call(self):self.assertFalse(any(c[0]=='fake-apply' for c in self.last_transport.calls))
    def test_six_profile_phase_combinations(self):
        for environment in m.PROFILES:
            for phase in ('eks-delete','final-delete'):
                directory=Path(self.temp.name)/(environment+'-'+phase);directory.mkdir(mode=0o700)
                s=scenario(directory,environment,phase)
                with self.subTest(environment=environment,phase=phase):
                    report=self.run_case(s,directory=directory)
                    self.assertEqual(report['environment'],environment);self.assertEqual(report['phase'],phase)
                    self.assertFalse(report['prod_qualified']);self.assertFalse(report['cloud_mutation_executed'])
                    self.assertEqual(self.last_transport.calls,[('observe','pre'),('observe','immediate'),
                        ('fake-apply',m.sha(s['artifacts']['binary'])),('observe','post')])
    def test_fixed_fake_types_only(self):
        class Other(m.ScenarioTransport):pass
        with self.assertRaises(RuleViolation):self.run_case(transport=Other({},b'{}'))
        self.assertFalse((self.directory/'attempt.json').exists())
    def test_explicit_environment_and_phase_required(self):
        for environment,phase in (('','eks-delete'),('aws-test','apply'),('local','final-delete')):
            with self.assertRaises(RuleViolation):m.OfflineDestroyAdapter(environment,phase,MAIN,repository_root=ROOT)
    def test_approval_digest_main_target_phase_and_simulation_binding(self):
        saved=copy.deepcopy(self.s)
        for field,value in (('main','b'*40),('environment','aws-dev'),('phase','final-delete'),('simulation_only',False),('schema','live-approval')):
            self.s=copy.deepcopy(saved);self.s['approval'][field]=value
            with self.subTest(field=field),self.assertRaises(m.SimulationStopped):self.run_case()
            self.assertEqual(self.last_transport.calls,[])
        self.s=saved
        with self.assertRaises(m.SimulationStopped):self.run_case(approval_hash='f'*64)
    def test_each_artifact_byte_drift_rejected_before_observation(self):
        saved=copy.deepcopy(self.s)
        for key in m.ARTIFACT_KEYS:
            self.s=copy.deepcopy(saved);self.s['artifacts'][key]+=b' '
            with self.subTest(key=key),self.assertRaises(m.SimulationStopped):self.run_case()
            self.assertEqual(self.last_transport.calls,[])
    def test_journal_path_cannot_be_substituted(self):
        directory=Path(self.temp.name)/'new';directory.mkdir(mode=0o700)
        with self.assertRaises(m.SimulationStopped):self.run_case(directory=directory)
        self.assertEqual(self.last_transport.calls,[])
    def test_exact_confirmations_and_inherited_override_rejections(self):
        saved=copy.deepcopy(self.s)
        for key,value in (('CONFIRM_AWS_TEST_APPLY',''),('AWS_ENDPOINT_URL','fixture'),('TF_CLI_ARGS','fixture'),
                          ('AWS_ENVIRONMENT','aws-dev'),('CONFIRM_AWS_TEST_OFFLINE_DESTROY','simulate-reviewed-aws-test-eks-delete')):
            self.s=copy.deepcopy(saved);self.s['confirmations'][key]=value
            with self.subTest(key=key),self.assertRaises(m.SimulationStopped):self.run_case()
            self.assertEqual(self.last_transport.calls,[])
    def test_expired_or_renewed_proof_before_call(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=(EXPIRES,)*7)
        self.assertEqual(self.last_transport.calls,[])
        self.s['approval']['created_at']='2026-09-14T05:01:00Z'
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=('2026-09-14T05:01:00Z',)*7)
    def test_expiry_after_reservation_stops_without_fake_call(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=(T,T,T,T,EXPIRES,EXPIRES,EXPIRES))
        self.no_fake_call();self.assertEqual(self.snapshot()['sequence'],0)
    def test_expiry_during_intent_barrier_preserves_pending(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=(T,T,T,T,T,EXPIRES,EXPIRES))
        self.no_fake_call();self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_observation_age_rechecked_after_barrier(self):
        later='2026-09-14T05:01:01Z'
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=(T,T,T,T,T,later,later))
        self.no_fake_call();self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_stale_or_future_pre_observation_rejected(self):
        for observed in ('2026-09-14T04:58:59Z','2026-09-14T05:00:01Z'):
            self.change_observation('pre',lambda o:o.update(observed_at=observed))
            with self.assertRaises(m.SimulationStopped):self.run_case()
            self.no_fake_call()
    def test_clock_regression_rejected(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=('2026-09-14T05:00:01Z',T,T,T,T,T,T))
        self.no_fake_call()
    def test_scope_region_account_cluster_inventory_main_mismatch(self):
        saved=copy.deepcopy(self.s)
        for field,value in (('region','us-east-2'),('account','1'*12),('cluster','fixture-prod'),('environment','aws-dev')):
            self.s=copy.deepcopy(saved);self.change_observation('pre',lambda o:o['identity'].update({field:value}))
            with self.subTest(field=field),self.assertRaises(m.SimulationStopped):self.run_case()
            self.no_fake_call()
        self.s=copy.deepcopy(saved);self.change_observation('pre',lambda o:o.update(inventory_complete=False))
        with self.assertRaises(m.SimulationStopped):self.run_case()
    def test_unconfirmed_reordered_or_changed_receipt_rejected(self):
        saved=copy.deepcopy(self.s)
        for kind in ('hash','unconfirmed','order'):
            self.s=copy.deepcopy(saved)
            def change(o):
                if kind=='hash':o['receipts'][0]['sha256']='f'*64
                elif kind=='order':o['receipts'].reverse()
                else:
                    r=o['receipts'][0];obj=json.loads(r['raw']);obj['confirmed']=False;r['raw']=raw(obj).decode();r['sha256']=m.sha(r['raw'].encode())
            self.change_artifact('scope',change);self.refresh()
            with self.subTest(kind=kind),self.assertRaises(m.SimulationStopped):self.run_case()
            self.assertEqual(self.last_transport.calls,[])
    def test_cleanup_dependency_observations_gate_call(self):
        saved=copy.deepcopy(self.s)
        for key,value in (('applications',1),('business_namespaces',1),('persistent_volumes',1),('nodeclasses',1),('scope_verified',False)):
            self.s=copy.deepcopy(saved);self.change_observation('immediate',lambda o:o['cleanup'].update({key:value}))
            with self.subTest(key=key),self.assertRaises(m.SimulationStopped):self.run_case()
            self.no_fake_call()
            # New independently approved synthetic fixture directory for each case, never reset an existing marker.
            self.directory=Path(self.temp.name)/('case-'+key);self.directory.mkdir(mode=0o700)
            saved=scenario(self.directory)
    def test_plan_address_id_action_and_duplicate_drift(self):
        saved=copy.deepcopy(self.s)
        for kind in ('id','action','missing','duplicate'):
            self.s=copy.deepcopy(saved)
            def change(o):
                if kind=='id':o['resource_changes'][0]['change']['before']['id']='fixture-other'
                elif kind=='action':o['resource_changes'][0]['change']['actions']=['delete','create']
                elif kind=='missing':o['resource_changes'].pop()
                else:o['resource_changes'].append(copy.deepcopy(o['resource_changes'][0]))
            self.change_artifact('plan',change);self.refresh()
            with self.subTest(kind=kind),self.assertRaises(m.SimulationStopped):self.run_case()
            self.assertEqual(self.last_transport.calls,[])
    def test_targeted_cannot_delete_retained_vpc(self):
        scope=json.loads(self.s['artifacts']['scope']);state=json.loads(self.s['artifacts']['state'])
        scope['reviewed_resources']=list(managed_inventory(state).values());self.s['artifacts']['scope']=raw(scope);self.refresh()
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertEqual(self.last_transport.calls,[])
    def test_prod_rejects_dev_test_optional_modules(self):
        self.s=scenario(self.directory,'aws-prod')
        self.change_artifact('state',lambda o:o['resources'].append({'module':'module.fis','mode':'managed','type':'aws_fis_experiment_template',
           'name':'fixture','instances':[{'attributes':{'id':'fixture-extra'}}]}));self.refresh()
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertEqual(self.last_transport.calls,[])
    def test_budget_binding_ceiling_and_post_increase(self):
        self.s['approval']['budget_limit_usd']='35.00'
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.s['approval']['budget_limit_usd']='36.00';self.change_observation('post',lambda o:o.update(estimated_total_usd='36.01'))
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_exact_budget_edge_accepted(self):
        for label in ('pre','immediate','post'):self.change_observation(label,lambda o:o.update(estimated_total_usd='36.00'))
        self.assertEqual(self.run_case()['status'],'offline-destroy-stage-simulation-complete')
    def test_fresh_plan_state_binary_or_absence_drift_stops(self):
        saved=copy.deepcopy(self.s)
        for field,value in (('state_sha256','f'*64),('plan_sha256','f'*64),('binary_sha256','f'*64),('native_remote_absence',['fixture-other']),('provider_lock_sha256','f'*64),('text_sha256','f'*64),('workspace','other'),('terraform_version','1.14.0')):
            self.s=copy.deepcopy(saved);self.change_observation('pre',lambda o:o.update({field:value}))
            with self.subTest(field=field),self.assertRaises(m.SimulationStopped):self.run_case()
            self.no_fake_call()
    def test_native_remote_absence_requires_review_and_exact_facts(self):
        plan=json.loads(self.s['artifacts']['plan']);item=plan['resource_changes'].pop();plan['resource_drift']=[item]
        self.s['artifacts']['plan']=raw(plan)
        self.change_artifact('scope',lambda o:o.update(reviewed_remote_absence=[item['address']]))
        self.refresh()
        for label in ('pre','immediate'):self.change_observation(label,lambda o:o.update(plan_sha256=m.sha(self.s['artifacts']['plan']),native_remote_absence=[item['address']]))
        self.assertEqual(self.run_case()['reviewed_remote_absence_count'],1)
    def test_explicit_fake_failure_terminal_and_no_post_read(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(result=raw({'success':False}))
        self.assertTrue(self.snapshot()['failed']);self.assertNotIn(('observe','post'),self.last_transport.calls)
    def test_malformed_fake_result_preserves_pending(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(result=raw({'success':1}))
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
        self.assertFalse(self.snapshot()['failed'])
    def test_uncertain_fake_call_preserves_pending(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(fail_at='apply')
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
        self.assertEqual(sum(c[0]=='fake-apply' for c in self.last_transport.calls),1)
    def test_uncertain_postcondition_preserves_pending(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(fail_at='post')
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_post_native_or_retained_id_mismatch_no_completion(self):
        self.change_observation('post',lambda o:o['state_after']['resources'][0]['instances'][0]['attributes'].update(id='fixture-other'))
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan');self.assertFalse(self.snapshot()['complete'])
    def test_post_missing_native_absence_no_completion(self):
        self.change_observation('post',lambda o:o['native_absent_addresses'].pop())
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_post_deadline_stop(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(samples=(T,)*6+('2026-09-14T07:00:01Z',))
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_repeat_success_or_pending_journal_never_repeats_call(self):
        self.run_case()
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.no_fake_call();self.assertTrue(self.snapshot()['complete'])
    def test_repeat_pending_after_uncertain_call_never_repeats_call(self):
        with self.assertRaises(m.SimulationStopped):self.run_case(fail_at='apply')
        before=(self.directory/'events.jsonl').read_bytes()
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.no_fake_call();self.assertEqual((self.directory/'events.jsonl').read_bytes(),before)
        self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
    def test_completion_write_failure_does_not_create_receipt(self):
        with patch.object(AttemptJournal,'complete',side_effect=RuleViolation('fixture-completion-stop')):
            with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertFalse(self.snapshot()['complete'])
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.no_fake_call()
    def test_eks_review_cannot_omit_cluster_or_access_entry(self):
        scope=json.loads(self.s['artifacts']['scope']);plan=json.loads(self.s['artifacts']['plan'])
        address=next(r['address'] for r in scope['reviewed_resources'] if r['type']=='aws_eks_cluster')
        scope['reviewed_resources']=[r for r in scope['reviewed_resources'] if r['address']!=address]
        plan['resource_changes']=[r for r in plan['resource_changes'] if r['address']!=address]
        self.s['artifacts']['scope']=raw(scope);self.s['artifacts']['plan']=raw(plan);self.refresh()
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.assertEqual(self.last_transport.calls,[])
    def test_failed_reservation_preserves_existing_files(self):
        path=self.directory/'attempt.json';path.write_bytes(b'fixture-existing');path.chmod(0o600)
        with self.assertRaises(m.SimulationStopped):self.run_case()
        self.no_fake_call();self.assertEqual(path.read_bytes(),b'fixture-existing')
    def test_intent_fsync_failure_blocks_fake_call(self):
        real=AttemptJournal.before
        def failing(handle,*args):
            with patch('guarded_attempt_journal.os.fsync',side_effect=OSError('fixture-fsync')):return real(handle,*args)
        with patch.object(AttemptJournal,'before',failing):
            with self.assertRaises(m.SimulationStopped):self.run_case()
        self.no_fake_call();self.assertTrue((self.directory/'attempt.json').exists())
    def test_intent_exists_before_fake_transport_and_completion_after_post(self):
        original=m.ScenarioTransport.apply;original_observe=m.ScenarioTransport.observe
        def fake_apply(transport,binary):
            self.assertEqual(self.snapshot()['pending'],'apply-saved-plan')
            return original(transport,binary)
        def observe(transport,label):
            if label=='post':self.assertFalse(self.snapshot()['complete'])
            return original_observe(transport,label)
        with patch.object(m.ScenarioTransport,'apply',fake_apply),patch.object(m.ScenarioTransport,'observe',observe):self.run_case()
        self.assertTrue(self.snapshot()['complete'])
    def test_public_failure_report_contains_no_private_identifiers(self):
        self.change_observation('pre',lambda o:o['identity'].update(account='private-account'))
        with self.assertRaises(m.SimulationStopped) as caught:self.run_case()
        text=json.dumps(caught.exception.report)
        self.assertNotIn('private-account',text);self.assertNotIn(str(self.directory),text)
        self.assertFalse(caught.exception.report['cloud_mutation_executed'])
    def test_no_sdk_cli_network_environment_or_system_clock_imports(self):
        tree=ast.parse((ROOT/'scripts/guarded_runtime_simulation_v6774.py').read_text())
        imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{x.name for n in ast.walk(tree) if isinstance(n,ast.Import) for x in n.names}
        self.assertEqual(imports,{'__future__','hashlib','decimal','pathlib','re','guarded_runtime_rules','guarded_cleanup_rules','guarded_plan_rules','guarded_attempt_journal'})

if __name__=='__main__':unittest.main(verbosity=2)

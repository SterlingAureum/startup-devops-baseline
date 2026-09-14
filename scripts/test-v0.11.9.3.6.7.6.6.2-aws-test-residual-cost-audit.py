#!/usr/bin/env python3
"""Offline inherited audit coverage and typed instant Fleet absence regressions."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('instant_audit',HERE/'execute-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
spec=importlib.util.spec_from_file_location('previous_error_fixtures',HERE/'test-v0.11.9.3.6.7.6.6.1-aws-test-residual-cost-audit.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
f.m=m;f.f.m=m

class InstantFleetTests(f.ErrorRepairTests):
    def fleet(self):
        return {'FleetId':'fleet-fixture','Type':'instant','FleetState':'active',
            'ActivityStatus':'fulfilled','ReplaceUnhealthyInstances':False,
            'FulfilledCapacity':1.0,'FulfilledOnDemandCapacity':1.0,
            'TargetCapacitySpecification':{'TotalTargetCapacity':1,'OnDemandTargetCapacity':0,
                'SpotTargetCapacity':0,'DefaultTargetCapacityType':'on-demand'},
            'Tags':[{'Key':'Project','Value':m.PROJECT},{'Key':'Environment','Value':'test'}],
            'Instances':[{'InstanceIds':['i-abc']}]}
    def classify(self, row, label='fleet'):
        self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[row]}),b'')
        r=self.runner(label);r.compute_verified=True
        m.tagged_record(r,'arn:aws:ec2:us-east-1:'+f.f.ACCOUNT+':fleet/fleet-fixture',0,self.record)
        return r
    def test_observed_instant_active_fulfilled_passes_only_with_native_instance_absence(self):
        r=self.classify(self.fleet())
        self.assertEqual(r.instant_history_fleets,1);self.assertEqual(r.terminal_fleets,0)
        self.assertEqual(r.instant_history_instance_ids,{'i-abc'})
        self.assertTrue(any(c[2]=='describe-instances' and '--instance-ids' in c for c in self.calls))
    def test_instant_launched_instances_are_checked_fresh_after_previous_native_query(self):
        r=self.runner();r.compute_verified=True
        m.ec2_absence(r,'old-captured','describe-instances',['--instance-ids','i-abc'],'Reservations')
        self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[self.fleet()]}),b'')
        self.overrides['ec2','describe-instances']=(0,m.encode({'Reservations':[{'Instances':[{'InstanceId':'i-abc','State':{'Name':'running'}}]}]}),b'')
        with self.assertRaises(m.Stop):m.tagged_record(r,'arn:aws:ec2:us-east-1:'+f.f.ACCOUNT+':fleet/fleet-fixture',0,self.record)
        self.assertEqual(r.instant_history_fleets,0)
    def test_active_maintain_request_unknown_and_missing_types_remain_rejected(self):
        for index,kind in enumerate(('maintain','request','unknown',None)):
            row=self.fleet();row['Type']=kind
            with self.subTest(kind=kind),self.assertRaises(m.Stop):self.classify(row,'kind-'+str(index))
    def test_nonfulfilled_or_replenishing_instant_metadata_rejected(self):
        for index,(key,val) in enumerate((('ActivityStatus','pending_fulfillment'),('ActivityStatus',None),('ReplaceUnhealthyInstances',True),('ReplaceUnhealthyInstances',None),('FleetState','failed'),('FleetState','deleted_running'))):
            row=self.fleet();row[key]=val
            with self.subTest(key=key,val=val),self.assertRaises(m.Stop):self.classify(row,'meta-'+str(index))
    def test_wrong_native_identity_or_ownership_rejected(self):
        rows=[]
        row=self.fleet();row['FleetId']='fleet-other';rows.append(row)
        row=self.fleet();row['Tags'][1]['Value']='prod';rows.append(row)
        row=self.fleet();row.pop('Tags');rows.append(row)
        row=self.fleet();row['Tags'].append(copy.deepcopy(row['Tags'][0]));rows.append(row)
        for index,row in enumerate(rows):
            with self.subTest(index=index),self.assertRaises(m.Stop):self.classify(row,'ownership-'+str(index))
    def test_unplanned_or_malformed_or_missing_instance_ids_rejected(self):
        cases=[None,[],[{}],[{'InstanceIds':[]}],[{'InstanceIds':['i-def']}],
               [{'InstanceIds':['not-an-instance']}],[{'InstanceIds':['i-abc','i-abc']}]]
        for index,groups in enumerate(cases):
            row=self.fleet();row['Instances']=groups
            with self.subTest(index=index),self.assertRaises(m.Stop):self.classify(row,'ids-'+str(index))
    def test_every_nonterminated_instance_state_is_rejected(self):
        for index,state in enumerate(('pending','running','stopping','stopped','shutting-down',None)):
            self.overrides['ec2','describe-instances']=(0,m.encode({'Reservations':[{'Instances':[{'InstanceId':'i-abc','State':{'Name':state}}]}]}),b'')
            with self.subTest(state=state),self.assertRaises(m.Stop):self.classify(self.fleet(),'live-'+str(index))
    def test_exact_terminated_or_native_notfound_instances_accepted(self):
        self.overrides['ec2','describe-instances']=(0,m.encode({'Reservations':[{'Instances':[{'InstanceId':'i-abc','State':{'Name':'terminated'}}]}]}),b'')
        self.assertEqual(self.classify(self.fleet(),'terminated').instant_history_fleets,1)
        self.overrides['ec2','describe-instances']=self.absent('InvalidInstanceID.NotFound')
        self.assertEqual(self.classify(self.fleet(),'notfound').instant_history_fleets,1)
    def test_zero_capacity_requires_explicit_empty_instance_list(self):
        row=self.fleet();row.update(FulfilledCapacity=0,FulfilledOnDemandCapacity=0,Instances=[])
        self.assertEqual(self.classify(row,'zero').instant_history_fleets,1)
        row.pop('Instances')
        with self.assertRaises(m.Stop):self.classify(row,'missing-zero')
    def test_native_absence_proof_is_required_even_for_instant(self):
        self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[self.fleet()]}),b'')
        r=self.runner()
        with self.assertRaises(m.Stop):m.tagged_record(r,'arn:aws:ec2:us-east-1:'+f.f.ACCOUNT+':fleet/fleet-fixture',0,self.record)
        self.assertEqual(r.instant_history_fleets,0)
    def test_native_instance_permission_failure_retains_consumed_attempt_and_logs(self):
        original=self.backend
        def backend(cmd,out,err,timeout,env):
            if cmd[2]=='describe-instances' and '--instance-ids' in cmd and self.calls and self.calls[-1][2]=='describe-fleets':
                self.overrides['ec2','describe-instances']=self.absent('AccessDenied')
            return original(cmd,out,err,timeout,env)
        self.backend=backend
        self.overrides['resourcegroupstaggingapi','get-resources']=(0,m.encode({'ResourceTagMappingList':[{'ResourceARN':'arn:aws:ec2:us-east-1:'+f.f.ACCOUNT+':fleet/fleet-fixture'}]}),b'')
        self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[self.fleet()]}),b'')
        self.prepared();result=self.execution()
        self.assertEqual(result['status'],'aws-test-residual-cost-audit-stopped')
        self.assertTrue(result['audit_attempt_consumed']);self.assertTrue(result['full_audit_executed'])
        self.assertFalse(result['mutation_executed']);self.assertTrue((self.base/'execute'/'failure.json').exists())
    def test_five_distinct_instant_fleets_complete_three_phase_flow_without_duplicate_sweep_counts(self):
        self.overrides['resourcegroupstaggingapi','get-resources']=(0,m.encode({'ResourceTagMappingList':[{'ResourceARN':'arn:aws:ec2:us-east-1:'+f.f.ACCOUNT+':fleet/fleet-fixture-'+str(i)} for i in range(5)]}),b'')
        original=self.backend
        def backend(cmd,out,err,timeout,env):
            if cmd[2]=='describe-fleets':
                row=self.fleet();row['FleetId']=cmd[cmd.index('--fleet-ids')+1]
                self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[row]}),b'')
            return original(cmd,out,err,timeout,env)
        self.backend=backend
        self.prepared();result=self.execution()
        self.assertTrue(result['audit_passed']);self.assertEqual(result['accepted_instant_fleet_history_count'],5)
        self.assertEqual(result['verified_instant_fleet_instance_count'],1)
        self.assertEqual(result['terminal_or_expired_fleet_record_count'],0)
        self.assertNotIn(f.f.ACCOUNT,json.dumps(result));self.assertNotIn('arn:aws:',json.dumps(result))
    def test_shared_rules_are_environment_parameterized_but_executor_remains_test_only(self):
        for environment in ('dev','test','prod'):
            row=self.fleet();row['Tags'][1]['Value']=environment
            category,ids=m.fleet_rules.classify_fleet(row,'fleet-fixture',m.PROJECT,environment,m.PROJECT+'-'+environment)
            self.assertEqual(category,'instant-history');self.assertEqual(ids,('i-abc',))
        self.assertEqual(m.CLUSTER,m.PROJECT+'-test')
    def test_invalid_capacity_and_extra_native_instance_response_rejected(self):
        for index,val in enumerate((True,-1,None,'1')):
            row=self.fleet();row['FulfilledCapacity']=val
            with self.subTest(val=val),self.assertRaises(m.Stop):self.classify(row,'capacity-'+str(index))
        self.overrides['ec2','describe-instances']=(0,m.encode({'Reservations':[{'Instances':[{'InstanceId':'i-def','State':{'Name':'terminated'}}]}]}),b'')
        with self.assertRaises(m.Stop):self.classify(self.fleet(),'wrong-instance-response')

if __name__=='__main__':unittest.main(verbosity=2)

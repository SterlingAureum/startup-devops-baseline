#!/usr/bin/env python3
"""Offline behavioral tests; fake transport only, no AWS or Terraform invocation."""
import argparse
from datetime import datetime,timedelta,timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('strict_audit',HERE/'execute-v0.11.9.3.6.7.6.6-aws-test-residual-cost-audit.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
T=datetime(2026,9,14,2,tzinfo=timezone.utc)
ACCOUNT='1'*12
MAIN='b'*40
class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=m.ROOT.parent,prefix='offline-audit-fixture-')
        self.base=Path(self.temp.name);self.base.chmod(0o700)
        self.env=patch.dict(os.environ,{'AWS_ENVIRONMENT':'aws-test','EXPECTED_AWS_ACCOUNT_ID':ACCOUNT,'CONFIRM_AWS_TEST_RESIDUAL_COST_AUDIT_PREFLIGHT':m.PRE_CONFIRM},clear=True);self.env.start()
        self.c=m.source_checks()
        self.record={'account':ACCOUNT,'outputs':{'vpc_id':'vpc-abc','cnpg_backup_bucket_name':m.PROJECT+'-test-'+ACCOUNT+'-us-east-1-cnpg','external_secrets_secret_arn':'arn:aws:secretsmanager:us-east-1:'+ACCOUNT+':secret:'+m.PROJECT+'-test/demo-api/postgresql-abc123','external_secrets_secret_name':m.PROJECT+'-test/demo-api/postgresql'},'cluster_sg':'sg-abc','instance_ids':['i-abc'],'disk_ids':['vol-abc'],'zone':'fixture-zone','managed':{}}
        self.overrides={};self.calls=[];self.clock=lambda:T
        self.state_check=lambda c: c['finalStateSha256']
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def backend(self,cmd,out,err,timeout,env):
        self.assertEqual(env['AWS_MAX_ATTEMPTS'],'1');self.assertLessEqual(timeout,120)
        self.assertEqual(cmd[0],'aws');self.assertNotIn('--no-paginate',cmd)
        self.calls.append(cmd)
        service,op=cmd[1:3]
        if (service,op) in self.overrides:rc,raw,error=self.overrides[(service,op)]
        elif service=='s3api':rc,raw,error=self.absent('NoSuchBucket')
        elif service=='secretsmanager':rc,raw,error=self.absent('ResourceNotFoundException')
        elif service=='iam':rc,raw,error=self.absent('NoSuchEntity')
        elif service in ('events','fis') or op=='describe-certificate':rc,raw,error=self.absent('ResourceNotFoundException')
        elif service=='sqs':rc,raw,error=self.absent('AWS.SimpleQueueService.NonExistentQueue')
        else:
            keys={'list-clusters':'clusters','describe-instances':'Reservations','describe-volumes':'Volumes','describe-network-interfaces':'NetworkInterfaces','describe-nat-gateways':'NatGateways','describe-addresses':'Addresses','describe-vpcs':'Vpcs','describe-security-groups':'SecurityGroups','describe-internet-gateways':'InternetGateways','describe-snapshots':'Snapshots','describe-load-balancers':'LoadBalancers','describe-target-groups':'TargetGroups','list-certificates':'CertificateSummaryList','describe-log-groups':'logGroups','list-resource-record-sets':'ResourceRecordSets','get-resources':'ResourceTagMappingList','describe-fleets':'Fleets'}
            value={'Account':ACCOUNT,'Arn':'arn:aws:iam::'+ACCOUNT+':user/fixture'} if op=='get-caller-identity' else {keys[op]:[]}
            rc,raw,error=0,m.encode(value),b''
        api=''.join(x.title() for x in op.split('-')).encode()
        error=error.replace(b'the Fixture operation', b'the '+api+b' operation')
        m.write(out,raw);m.write(err,error);return rc
    def absent(self,code):return 254,b'',('An error occurred ('+code+') when calling the Fixture operation: fixture only\n').encode()
    def output(self,label):p=self.base/label;p.mkdir(mode=0o700);return p
    def runner(self,label='raw'):return m.Runner(self.output(label),self.c,T+timedelta(hours=1),self.backend,self.clock,self.state_check)
    def args(self,phase):
        return argparse.Namespace(phase=phase,expected_main=MAIN,inputs=None,runtime_record=None,final_result=None,eks_complete=None,start_utc=m.stamp(T-timedelta(minutes=1)),end_utc=m.stamp(T+timedelta(hours=1)),preflight_result=self.base/'preflight.json',expected_preflight_sha256=None,verify_result=self.base/'verify.json',expected_verify_sha256=None)
    def runphase(self,phase,label=None):
        args=self.args(phase)
        if args.preflight_result.exists():args.expected_preflight_sha256=m.digest(args.preflight_result.read_bytes())
        if args.verify_result.exists():args.expected_verify_sha256=m.digest(args.verify_result.read_bytes())
        return m.execute_phase(args,self.c,self.output(label or phase),self.clock,self.backend,self.state_check,lambda *_:None,lambda *_:self.record)
    def prepared(self):
        pre=self.runphase('preflight');m.write(self.base/'preflight.json',pre)
        verify=self.runphase('verify');self.assertEqual(verify['status'],'aws-test-residual-cost-audit-execution-inputs-verified');m.write(self.base/'verify.json',verify)
    def execution(self,label='execute'):
        os.environ['CONFIRM_AWS_TEST_RESIDUAL_COST_AUDIT_EXECUTION']=m.EXEC_CONFIRM
        return self.runphase('execute',label)
    def test_successful_three_phases_leave_one_marker_and_private_logs(self):
        self.prepared();result=self.execution()
        self.assertTrue(result['audit_passed']);self.assertFalse(result['mutation_executed']);self.assertFalse(result['account_wide_billing_audit'])
        self.assertTrue((self.base/'residual-audit-attempt.json').exists())
        for p in (self.base/'execute').iterdir():self.assertEqual(p.stat().st_mode&0o777,0o600)
        self.assertNotIn(ACCOUNT,json.dumps(result));self.assertNotIn('arn:aws:',json.dumps(result))
    def test_second_attempt_stops_before_any_aws_call(self):
        self.prepared();self.execution();before=len(self.calls)
        result=self.execution('second');self.assertEqual(result['status'],'aws-test-residual-cost-audit-stopped');self.assertEqual(len(self.calls),before)
    def test_verify_never_runs_full_audit(self):
        self.prepared();self.assertEqual({cmd[1] for cmd in self.calls},{'sts','eks','s3api','secretsmanager'})
    def test_execute_requires_separate_confirmation_before_cloud(self):
        self.prepared();before=len(self.calls)
        with self.assertRaises(m.Stop):self.runphase('execute')
        self.assertEqual(len(self.calls),before)
    def test_old_mutation_and_terraform_endpoint_flags_rejected(self):
        for key in ('CONFIRM_AWS_TEST_FINAL_DELETE','CONFIRM_AWS_DEV_APPLY','AWS_ENDPOINT_URL_EC2','TF_VAR_environment','AWS_TEST_APPLY_MODE'):
            with patch.dict(os.environ,{key:''}):
                with self.assertRaises(m.Stop):m.environment_check('preflight',os.environ)
    def test_wrong_environment_and_account_rejected(self):
        for env in ({'AWS_ENVIRONMENT':'aws-dev'},{'EXPECTED_AWS_ACCOUNT_ID':'invalid'}):
            with patch.dict(os.environ,env):
                with self.assertRaises(m.Stop):m.environment_check('preflight',os.environ)
    def test_live_account_mismatch_stops_and_preserves_raw(self):
        self.overrides['sts','get-caller-identity']=(0,m.encode({'Account':'2'*12,'Arn':'fixture'}),b'')
        result=self.runphase('preflight');self.assertEqual(result['stage'],'sts-account');self.assertEqual(len(self.calls),1);self.assertTrue((self.base/'preflight'/'failure.json').exists())
    def test_every_rehearsal_environment_blocks(self):
        for short in ('dev','test','prod'):
            self.overrides['eks','list-clusters']=(0,m.encode({'clusters':[m.PROJECT+'-'+short]}),b'')
            result=self.runphase('preflight',short);self.assertEqual(result['status'],'aws-test-residual-cost-audit-stopped')
    def test_bucket_permission_errors_never_mean_absence(self):
        for index,code in enumerate(('AccessDenied','Forbidden','InvalidAccessKeyId')):
            self.overrides['s3api','list-object-versions']=self.absent(code)
            result=self.runphase('preflight','bucket-'+str(index));self.assertEqual(result['stage'],'backup-bucket');self.assertNotEqual(result['status'],'aws-test-residual-cost-audit-preflight-ready-for-separate-approval')
    def test_malformed_error_and_mixed_stdout_rejected(self):
        r=self.runner()
        cases = [
            (254,b'',b'NoSuchBucket generic text'),
            (254,b'{}',self.absent('NoSuchBucket')[2]),
            (254,b'',self.absent('NoSuchBucket')[2]+self.absent('AccessDenied')[2]),
            (254,b'',self.absent('NoSuchBucket')[2].replace(b'the Fixture',b'the WrongAPI')),
        ]
        for index,value in enumerate(cases):
            self.overrides['s3api','list-object-versions']=value
            with self.assertRaises(m.Stop):r.invoke('error-'+str(index),'s3api','list-object-versions',absent=('NoSuchBucket',))
    def test_secret_absent_and_exact_tombstone_accepted_live_rejected(self):
        r=self.runner();self.assertFalse(m.preflight_cloud(r,self.record)['credential_tombstone_present'])
        for index,deleted in enumerate((None,'2026-09-20T00:00:00Z')):
            value={'ARN':self.record['outputs']['external_secrets_secret_arn'],'Name':self.record['outputs']['external_secrets_secret_name']}
            if deleted:value['DeletedDate']=deleted
            self.overrides['secretsmanager','describe-secret']=(0,m.encode(value),b'')
            r=self.runner('secret-'+str(index))
            if deleted:self.assertTrue(m.preflight_cloud(r,self.record)['credential_tombstone_present'])
            else:
                with self.assertRaises(m.Stop):m.preflight_cloud(r,self.record)
    def test_malformed_json_and_incomplete_pagination_fail_closed(self):
        for index,raw in enumerate((b'not-json',b'[]',b'{"clusters":[],"clusters":[]}',m.encode({'clusters':[],'NextToken':'more'}),m.encode({'clusters':[],'IsTruncated':True}))):
            self.overrides['eks','list-clusters']=(0,raw,b'')
            self.assertEqual(self.runphase('preflight','schema-'+str(index))['status'],'aws-test-residual-cost-audit-stopped')
    def test_missing_list_is_not_empty(self):
        self.overrides['eks','list-clusters']=(0,b'{}',b'')
        self.assertEqual(self.runphase('preflight')['status'],'aws-test-residual-cost-audit-stopped')
    def test_changed_preflight_branch_stops_before_full_audit(self):
        self.prepared();value={'ARN':self.record['outputs']['external_secrets_secret_arn'],'Name':self.record['outputs']['external_secrets_secret_name'],'DeletedDate':m.stamp(T)}
        self.overrides['secretsmanager','describe-secret']=(0,m.encode(value),b'')
        result=self.execution();self.assertFalse(result['full_audit_executed']);self.assertTrue(result['audit_attempt_consumed'])
    def test_expired_preflight_and_verify_stop(self):
        self.prepared();self.clock=lambda:T+timedelta(seconds=901)
        result=self.execution();self.assertFalse(result['audit_attempt_consumed']);self.assertEqual(len(self.calls),8)
        self.clock=lambda:T+timedelta(seconds=self.c['preflightTtlSeconds']+1)
        args=self.args('verify');args.end_utc=m.stamp(T+timedelta(hours=3));args.expected_preflight_sha256=m.digest(args.preflight_result.read_bytes())
        with self.assertRaises(m.Stop):m.check_preflight(args,self.c,m.private_json(args.preflight_result),self.clock)
    def test_extended_verify_ttl_rejected(self):
        self.prepared();p=self.base/'verify.json';value=m.private_json(p);p.unlink();value['verify_expires_at_utc']=m.stamp(T+timedelta(hours=1));m.write(p,value)
        self.assertFalse(self.execution()['audit_attempt_consumed'])
    def test_four_hour_window_and_minimum_remaining_enforced(self):
        args=self.args('verify');args.end_utc=m.stamp(T+timedelta(hours=5))
        with self.assertRaises(m.Stop):m.window(args,self.c,self.clock)
        args.end_utc=m.stamp(T+timedelta(seconds=899))
        with self.assertRaises(m.Stop):m.window(args,self.c,self.clock)
    def test_durable_file_modes_symlinks_and_existing_output(self):
        p=self.base/'private.json';m.write(p,{});p.chmod(0o644)
        with self.assertRaises(m.Stop):m.private_json(p)
        p.chmod(0o600);link=self.base/'link';link.symlink_to(p)
        with self.assertRaises(m.Stop):m.private_json(link)
        with self.assertRaises(m.Stop):m.checked_path(Path('/tmp'),0o700)
        with self.assertRaises(m.Stop):m.new_output(self.base)
    def test_state_change_stops_before_another_cloud_call(self):
        count=[0]
        def check(c):
            count[0]+=1
            if count[0]>1:raise m.Stop('state-drift-fixture')
        r=m.Runner(self.output('state'),self.c,T+timedelta(hours=1),self.backend,self.clock,check)
        with self.assertRaises(m.Stop):r.invoke('state-drift','sts','get-caller-identity')
        self.assertEqual(len(self.calls),1);self.assertEqual(len(r.manifest),1)
    def test_tagged_stale_eni_needs_native_notfound_access_denied_blocks(self):
        r=self.runner();arn='arn:aws:ec2:us-east-1:'+ACCOUNT+':network-interface/eni-abc'
        self.overrides['ec2','describe-network-interfaces']=self.absent('InvalidNetworkInterfaceID.NotFound');m.tagged_record(r,arn,0,self.record);self.assertEqual(r.stale_tagged,1)
        self.overrides['ec2','describe-network-interfaces']=self.absent('AccessDenied')
        with self.assertRaises(m.Stop):m.tagged_record(self.runner('bad-tag'),arn,1,self.record)
    def test_terminal_fleets_require_prior_compute_checks_deleted_running_rejected(self):
        arn='arn:aws:ec2:us-east-1:'+ACCOUNT+':fleet/fleet-fixture'
        for index,state in enumerate(('deleted','deleted_terminating','deleted_running','active')):
            self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[{'FleetId':'fleet-fixture','FleetState':state}]}),b'')
            r=self.runner('fleet-'+str(index));r.compute_verified=True
            if state in ('deleted','deleted_terminating'):m.tagged_record(r,arn,index,self.record);self.assertEqual(r.terminal_fleets,1)
            else:
                with self.assertRaises(m.Stop):m.tagged_record(r,arn,index,self.record)
        r=self.runner('unchecked-fleet');self.overrides['ec2','describe-fleets']=(0,m.encode({'Fleets':[{'FleetId':'fleet-fixture','FleetState':'deleted'}]}),b'')
        with self.assertRaises(m.Stop):m.tagged_record(r,arn,9,self.record)
    def test_unknown_tagged_and_foreign_account_resources_stop(self):
        r=self.runner()
        for arn in ('arn:aws:ec2:us-east-1:'+ACCOUNT+':unknown/fixture','arn:aws:ec2:us-east-1:'+('2'*12)+':volume/vol-abc'):
            with self.assertRaises(m.Stop):m.tagged_record(r,arn,0,self.record)
    def test_unknown_managed_type_and_surviving_detached_igw_stop(self):
        r=self.runner()
        with self.assertRaises(m.Stop):m.captured_resource(r,'aws_unknown',{'id':'fixture'},self.record,0)
        self.overrides['ec2','describe-internet-gateways']=(0,m.encode({'InternetGateways':[{'InternetGatewayId':'igw-abc'}]}),b'')
        with self.assertRaises(m.Residual):m.captured_resource(r,'aws_internet_gateway',{'id':'igw-abc'},self.record,1)
    def test_live_instance_in_shutting_down_state_blocks(self):
        self.overrides['ec2','describe-instances']=(0,m.encode({'Reservations':[{'Instances':[{'State':{'Name':'shutting-down'}}]}]}),b'')
        with self.assertRaises(m.Residual):m.native_sweep(self.runner(),self.record)
    def test_every_captured_managed_api_type_uses_only_read_operations(self):
        r=self.runner()
        known={
          'aws_iam_role':{'name':'fixture'},'aws_iam_role_policy':{'role':'fixture'},
          'aws_iam_role_policy_attachment':{'role':'fixture'},'aws_iam_policy':{'arn':'fixture'},
          'aws_iam_openid_connect_provider':{'arn':'fixture'},
          'aws_cloudwatch_event_rule':{'name':'fixture'},'aws_cloudwatch_event_target':{'rule':'fixture'},
          'aws_sqs_queue':{'url':'fixture'},'aws_sqs_queue_policy':{'queue_url':'fixture'},
          'aws_fis_experiment_template':{},'aws_acm_certificate':{'arn':'fixture'},
          'aws_acm_certificate_validation':{'certificate_arn':'fixture'},
          'aws_route53_record':{'zone_id':'fixture-zone','name':'fixture','type':'CNAME'},
          'aws_cloudwatch_log_group':{'name':'fixture'},'aws_eip':{'allocation_id':'fixture'},
          'aws_nat_gateway':{},'aws_ec2_tag':{'resource_id':'sg-abc'},'aws_internet_gateway':{}
        }
        for index,(kind,attrs) in enumerate(known.items()):m.captured_resource(r,kind,dict(id='fixture',**attrs),self.record,index)
        self.assertTrue(self.calls)
        self.assertTrue(all(cmd[2] in m.OPS[cmd[1]] for cmd in self.calls))
    def test_private_input_history_and_no_kubeconfig_dependency(self):
        c=dict(self.c);inputs={'aws_account_id':ACCOUNT,'kubeconfig_path':'missing-is-irrelevant'}
        record=dict(self.record);record['instance_ids']=['i-'+format(x+1,'x') for x in range(8)];record['disk_ids']=['vol-'+format(x+1,'x') for x in range(13)]
        record['managed']={'module.fixture.aws_s3_bucket.this['+str(x)+']':{'id':'fixture'} for x in range(90)}
        e=m.json_data((m.ROOT/c['teardownEvidencePath']).read_bytes())
        receipt={'main':c['teardownControlPlaneCommit'],'window_contract_sha256':c['historicalWindowSha256'],'state_sha256':c['intermediateStateSha256'],'runtime_record_sha256':c['runtimeRecordSha256']}
        args=self.args('preflight')
        for field,value,key in (('inputs',inputs,'privateInputsSha256'),('runtime_record',record,'runtimeRecordSha256'),('final_result',e['finalResultRestated'],'finalResultSha256')):
            path=self.base/(field+'.json');c[key]=m.write(path,value);setattr(args,field,path)
        receipt['runtime_record_sha256']=c['runtimeRecordSha256'];args.eks_complete=self.base/'receipt.json';c['eksCompleteSha256']=m.write(args.eks_complete,receipt)
        self.assertEqual(m.load_inputs(args,c)['account'],ACCOUNT)
        with patch.dict(os.environ,{'EXPECTED_AWS_ACCOUNT_ID':'2'*12}):
            with self.assertRaises(m.Stop):m.load_inputs(args,c)
        args.inputs.write_bytes(b'{}')
        with self.assertRaises(m.Stop):m.load_inputs(args,c)
    def test_empty_state_read_rejects_nonempty_corrupt_and_symlink(self):
        root=self.base/'fake-repository';path=root/m.STATE;path.parent.mkdir(parents=True)
        c=dict(self.c)
        with patch.object(m,'ROOT',root):
            for index,value in enumerate(({'version':4,'resources':[]},{'version':4,'resources':[{}]},{'version':4}, {'version':3,'resources':[]})):
                if path.exists():path.unlink()
                raw=m.encode(value);c['finalStateSha256']=m.write(path,raw)
                if index==0:self.assertEqual(m.empty_state(c),c['finalStateSha256'])
                else:
                    with self.assertRaises(m.Stop):m.empty_state(c)
            path.unlink();c['finalStateSha256']=m.write(path,b'corrupt')
            with self.assertRaises(Exception):m.empty_state(c)
            target=path.parent/'target';path.rename(target);path.symlink_to(target)
            with self.assertRaises(m.Stop):m.empty_state(c)
    def test_operation_and_pagination_bypass_commands_rejected(self):
        for service,op,params in (('ec2','delete-volume',[]),('secretsmanager','get-secret-value',[]),('ec2','describe-instances',['--no-paginate'])):
            with self.assertRaises(m.Stop):m.command(service,op,params)
    def test_reviewed_input_drift_during_cloud_call_stops(self):
        self.prepared();original=self.backend
        def changed(cmd,out,err,seconds,env):
            result=original(cmd,out,err,seconds,env)
            if cmd[1]=='ec2':
                p=self.base/'preflight.json';p.write_bytes(p.read_bytes()+b' ')
            return result
        self.backend=changed;result=self.execution()
        self.assertFalse(result['audit_passed']);self.assertTrue(result['audit_attempt_consumed']);self.assertTrue(result['full_audit_executed'])
    def test_full_audit_records_all_ninety_bound_managed_definitions(self):
        bucket=self.record['outputs']['cnpg_backup_bucket_name']
        self.record['managed']={'module.fixture.aws_s3_bucket_versioning.this['+str(x)+']':{'id':bucket,'bucket':bucket} for x in range(90)}
        self.record['instance_ids']=['i-'+format(x+1,'x') for x in range(8)]
        self.record['disk_ids']=['vol-'+format(x+1,'x') for x in range(13)]
        self.prepared();result=self.execution()
        self.assertTrue(result['audit_passed']);self.assertEqual(result['captured_managed_resource_count'],90)
    def test_timeout_preserves_manifest_and_consumes_attempt(self):
        self.prepared()
        old=self.backend
        def timeout(cmd,out,err,seconds,env):
            if cmd[1]=='ec2':m.write(out,b'partial-fixture');m.write(err,b'');raise TimeoutError('fixture only')
            return old(cmd,out,err,seconds,env)
        self.backend=timeout;result=self.execution();self.assertTrue(result['audit_attempt_consumed']);self.assertTrue(result['preserve_state_and_private_evidence']);self.assertTrue((self.base/'execute'/'raw-output-manifest.json').exists())
if __name__=='__main__':unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Explicitly renewed-window aws-test cleanup; no historical approval is reused."""
import argparse
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

import aws_test_immutable_root as h
p=h.p
spec=importlib.util.spec_from_file_location('cleanup_observer',h.ROOT/'scripts/observe-v0.11.9.3.6.7.6.1-aws-test-cleanup.py')
o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
CONTRACT='delivery/contracts/v0.11.9.3.6.7.6.1-aws-test-cleanup-window-renewal.json'
TF=h.ROOT/'infra/terraform/aws/environments/test'
AWS=o.AWS
PHASES={'verify-runtime':None,'execute-runtime':('CONFIRM_AWS_TEST_RUNTIME_CLEANUP','cleanup-reviewed-aws-test-runtime-once'),
        'plan-eks':('CONFIRM_AWS_TEST_TEARDOWN_PLAN','plan-reviewed-aws-test-teardown'),
        'plan-final':('CONFIRM_AWS_TEST_TEARDOWN_PLAN','plan-reviewed-aws-test-teardown'),
        'apply-eks':('CONFIRM_AWS_TEST_EKS_DELETE','apply-reviewed-aws-test-eks-delete-once'),
        'apply-final':('CONFIRM_AWS_TEST_FINAL_DELETE','apply-reviewed-aws-test-final-delete-once')}
FINALIZERS={'resources-finalizer.argocd.argoproj.io','resources-finalizer.argocd.argoproj.io/background'}


def source_checks():
    o.source_checks()
    c=p.load(h.ROOT/CONTRACT)
    for item in c['reviewedFiles']:p.require(p.digest(h.ROOT/item['path'])==item['sha256'],'teardown-source-drift')
    return c


def projection(c):
    model=c['costProjection'];start=p.utc(model['accountingStartUtc']);peak_start=p.utc(model['peakAssumedFromUtc']);end=p.utc(c['cleanupCompleteByUtc'])
    p.require(start<peak_start<end,'cost-accounting-boundaries')
    rates=p.load(h.ROOT/model['reviewedRatesContract'])['costEnvelope']
    idle=sum((p.amount(x) for x in rates['idleHourlyUsd'].values()),Decimal(0))
    peak=sum((p.amount(x) for x in rates['peakHourlyUsd'].values()),Decimal(0))
    estimate=idle*Decimal(str((peak_start-start).total_seconds()))/3600+peak*Decimal(str((end-peak_start).total_seconds()))/3600+p.amount(rates['fixedReserveUsd'])
    p.require(estimate<=p.amount(c['budget']['totalLimitUsd']),'renewed-projection-exceeds-budget')
    return {'estimated_total_usd':str(estimate.quantize(Decimal('0.01'),rounding=ROUND_CEILING)),
        'total_budget_limit_usd':c['budget']['totalLimitUsd'],'expected_spend_target_usd':'20.00',
        'historical_billed_spend_usd':None,'estimate_is_billing_guarantee':False,
        'rates_are_existing_reviewed_allowances':True,'current_price_quote_verified':False,
        'peak_assumed_from_utc':model['peakAssumedFromUtc'],'cleanup_complete_by_utc':c['cleanupCompleteByUtc']}


def window_digest():return p.digest(h.ROOT/CONTRACT)


def require_window(proof):p.require(proof.get('window_contract_sha256')==window_digest(),'renewed-window-proof-binding')


def confirmations(phase,environment):
    h.assert_confirmations(environment,False)
    expected=PHASES[phase]
    for key,value in set(x for x in PHASES.values() if x):
        p.require(environment.get(key)==value if expected and key==expected[0] else key not in environment,'phase-approval-required')
    p.require(not any(k.startswith(('TF_CLI_ARGS','TF_VAR_')) or k=='TF_WORKSPACE' for k in environment),'terraform-environment-override')


def state():return p.load(p.private((h.ROOT/p.STATE).absolute()))


def addresses(value):
    result={}
    for resource in value.get('resources',[]):
        if resource['mode']!='managed':continue
        base=(resource.get('module','')+'.' if resource.get('module') else '')+resource['type']+'.'+resource['name']
        for instance in resource.get('instances',[]):
            key=base+('['+json.dumps(instance['index_key'])+']' if 'index_key' in instance else '')
            p.require(key not in result,'duplicate-state-address')
            result[key]=instance['attributes']
    return result


class Runner(o.e.Runner):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.changing_state=False
    def check_time_and_state(self):
        remaining=(self.stop-h.now()).total_seconds()
        p.require(remaining>1,'cleanup-deadline-reached')
        if not self.changing_state:p.require(p.digest(h.ROOT/p.STATE)==self.state_hash,'unexpected-state-change')
        return remaining
    def invoke(self,label,command,mutation=False,json_output=True,absent_code=None):
        remaining=self.check_time_and_state();self.stage=label;self.sequence+=1
        prefix=f'{self.sequence:04d}-{label}'
        if mutation:
            self.mutation_attempted=True
            fd=os.open(self.output/'mutation-attempts.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            with os.fdopen(fd,'a') as journal:
                journal.write(json.dumps({'stage':label,'at_utc':p.timestamp(),'outcome_not_yet_known':True})+'\n');journal.flush();os.fsync(journal.fileno())
        with (self.output/(prefix+'.stdout')).open('xb') as stdout,(self.output/(prefix+'.stderr')).open('xb') as stderr:
            proc=subprocess.Popen(command,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,cwd=h.ROOT,env=self.environment,start_new_session=True)
            try:proc.wait(timeout=min(remaining,3600 if command[0]=='terraform' else 120))
            except BaseException:
                try:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=1)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                proc.wait();raise
        raw=(self.output/(prefix+'.stdout')).read_bytes()
        if proc.returncode and absent_code:
            err=(self.output/(prefix+'.stderr')).read_text()
            if re.search(r'\('+re.escape(absent_code)+r'\)',err):return None
        p.require(proc.returncode==0,'command-failed-preserve-state-and-evidence')
        return json.loads(raw) if json_output and raw.strip() else ({} if json_output else raw)
    def delete(self,label,kind,name,namespace=None):
        cmd=self.kube+['delete',kind,name,'--ignore-not-found=true','--wait=false','--cascade='+('orphan' if kind=='application' else 'background'),'-o','json']
        if namespace:cmd+=['-n',namespace]
        return self.invoke(label,cmd,mutation=True)
    def absent(self,label,kind,name,namespace=None):
        self.wait(label,lambda:self.get(label+'-read',kind,name,namespace,True),lambda value:not value)


def scope(r,args,c):
    invargs=argparse.Namespace(inputs=args.inputs,expected_main=args.expected_main,bundle=args.bundle,
        deployment_result=args.deployment_result,output_directory=args.output_directory/'fresh-inventory')
    observed=o.observe(invargs)
    reviewed=c['reviewedInventory']['summary']
    for key in ('active_application_operation_count','application_count','application_health_counts','nodes_count','nodeclaims_count','nodeclasses_count','nodepools_count','persistent_volumes_count','pvc_count','database_count','compute_counts_by_type','attached_volume_count','attached_volume_total_gib'):
        p.require(observed[key]==reviewed[key],'changed-reviewed-runtime-inventory')
    apps=r.get('captured-apps','applications.argoproj.io','','argocd')['items']
    root,source_map=o.reviewed_bundle(args.bundle,p.load(h.ROOT/o.CONTRACT))
    p.require(o.app_inventory(apps,root,source_map,reviewed['deployed_control_plane_commit'])['active_application_operation_count']==0,'active-sync-stop-before-mutation')
    pools=r.get('scope-nodepools','nodepools','')['items'];classes=r.get('scope-nodeclasses','ec2nodeclasses','')['items']
    p.require({x['metadata']['name'] for x in pools}=={'database-ondemand','application-ondemand'} and len(pools)==2,'unknown-nodepool-scope')
    p.require({x['metadata']['name'] for x in classes}=={'application','application-fis','database'} and len(classes)==3,'unknown-nodeclass-scope')
    for app in apps:p.require(set(app['metadata'].get('finalizers',[]))<=FINALIZERS,'unknown-application-finalizer')
    pvs=r.get('captured-pvs','pv','')['items']
    p.require(len(pvs)==5,'changed-pv-count')
    for pv in pvs:
        p.require(pv['spec'].get('csi',{}).get('driver')=='ebs.csi.aws.com' and
            pv['spec']['claimRef']['namespace'] in ('startup-apps','data-platform','observability') and
            re.fullmatch(r'vol-[0-9a-f]+',pv['spec']['csi']['volumeHandle']),'unknown-storage-scope')
    values=state();outputs={k:v['value'] for k,v in values['outputs'].items()}
    cluster=r.invoke('scope-cluster',AWS+['eks','describe-cluster','--name',p.CLUSTER])['cluster']
    instances=r.invoke('scope-instances',AWS+['ec2','describe-instances','--filters','Name=vpc-id,Values='+outputs['vpc_id']])
    live=[x for group in instances['Reservations'] for x in group['Instances'] if x['State']['Name'] not in ('terminated','shutting-down')]
    claims=r.get('scope-claims','nodeclaims','')['items']
    newids={x['status']['providerID'].rsplit('/',1)[-1] for x in claims}
    p.require(newids<={x['InstanceId'] for x in live},'nodeclaim-instance-not-in-target-vpc')
    p.require(len(claims)==4 and len(newids)==4 and len(live)==8,'changed-compute-count')
    groups={g['name'] for res in values['resources'] if res.get('type')=='aws_eks_node_group' for i in res['instances'] for item in i['attributes']['resources'] for g in item['autoscaling_groups']}
    for instance in live:
        new=instance['InstanceId'] in newids
        p.require(instance['State']['Name']=='running' and not instance.get('InstanceLifecycle') and
            instance['InstanceType']==('c6i.large' if new else 't3.medium'),'unknown-instance-scope')
        if not new:p.require(any(t['Key']=='aws:autoscaling:groupName' and t['Value'] in groups for t in instance.get('Tags',[])),'unknown-system-instance')
        p.require(all(x['Ebs']['DeleteOnTermination'] for x in instance['BlockDeviceMappings'] if x['DeviceName']==instance['RootDeviceName']),'retained-root-disk')
    diskids={x['Ebs']['VolumeId'] for instance in live for x in instance['BlockDeviceMappings']}
    p.require({pv['spec']['csi']['volumeHandle'] for pv in pvs}<=diskids,'pv-disk-not-attached-to-target-instance')
    p.require(len(diskids)==13,'changed-associated-disk-count')
    lbs=r.invoke('scope-alb',AWS+['elbv2','describe-load-balancers'])['LoadBalancers']
    lb=next(x for x in lbs if x['VpcId']==outputs['vpc_id'])
    zones=r.invoke('scope-zone',AWS+['route53','list-hosted-zones-by-name','--dns-name','aureumstack.com'])['HostedZones']
    zone=next(x for x in zones if x['Name']=='aureumstack.com.' and not x['Config']['PrivateZone'])['Id']
    records=r.invoke('scope-alias',AWS+['route53','list-resource-record-sets','--hosted-zone-id',zone])['ResourceRecordSets']
    alias=next(x for x in records if x['Name']=='demo.test.aureumstack.com.' and x['Type']=='A')
    return {'apps':sorted(x['metadata']['name'] for x in apps),'app_specs':{x['metadata']['name']:x['spec'] for x in apps},
        'nodepools':{x['metadata']['name']:x['spec'] for x in pools},'nodeclasses':{x['metadata']['name']:x['spec'] for x in classes},'pvs':pvs,'instance_ids':sorted(x['InstanceId'] for x in live),
        'new_instance_ids':sorted(newids),'disk_ids':sorted(diskids),'outputs':outputs,'zone':zone,'alias':alias,
        'alb_arn':lb['LoadBalancerArn'],'cluster_sg':cluster['resourcesVpcConfig']['clusterSecurityGroupId'],
        'account':r.inputs['aws_account_id'],'management_cidr':r.inputs['management_cidr'],'managed':addresses(values)}


def stable_scope(value):
    return {k:v for k,v in value.items() if k!='pvs'}|{'pvs':sorted((x['metadata']['name'],x['spec']['csi']['volumeHandle'],x['spec']['claimRef']['namespace'],x['spec']['claimRef']['name']) for x in value['pvs'])}


def runtime_cleanup(r,record):
    # Recheck every Application immediately before deliberate orphaning.
    order=[p.APP]+[name for name in record['apps'] if name!=p.APP]
    for name in order:
        app=r.get('freeze-check-'+name,'application',name,'argocd')
        p.require(app['spec']==record['app_specs'][name],'application-spec-drift-before-freeze')
        p.require(app.get('status',{}).get('operationState',{}).get('phase') not in ('Running','Terminating'),'active-sync-stop')
        p.require(set(app['metadata'].get('finalizers',[]))<=FINALIZERS,'unknown-finalizer-stop')
        r.invoke('freeze-'+name,r.kube+['patch','application',name,'-n','argocd','--type=merge','-p',json.dumps({'spec':{'syncPolicy':{'automated':None}}}),'--output=json'],True)
    for name in order:
        app=r.get('orphan-check-'+name,'application',name,'argocd')
        p.require(all(app['spec'].get(k)==record['app_specs'][name].get(k) for k in ('source','destination')),'application-target-drift-before-orphan')
        p.require(app.get('status',{}).get('operationState',{}).get('phase') not in ('Running','Terminating'),'active-sync-stop')
        p.require(set(app['metadata'].get('finalizers',[]))<=FINALIZERS,'unknown-finalizer-stop')
        r.invoke('orphan-'+name,r.kube+['patch','application',name,'-n','argocd','--type=merge','-p','{"metadata":{"finalizers":[]}}','--output=json'],True)
        r.delete('remove-app-'+name,'application',name,'argocd')
    change=r.invoke('delete-test-alias',AWS+['route53','change-resource-record-sets','--hosted-zone-id',record['zone'],'--change-batch',json.dumps({'Changes':[{'Action':'DELETE','ResourceRecordSet':record['alias']} ]})],True)
    r.wait('dns-delete-insync',lambda:r.invoke('dns-change',AWS+['route53','get-change','--id',change['ChangeInfo']['Id']]),lambda x:x['ChangeInfo']['Status']=='INSYNC')
    for ns in ('startup-apps','data-platform','observability'):r.delete('remove-namespace-'+ns,'namespace',ns)
    for ns in ('startup-apps','data-platform','observability'):r.absent('wait-namespace-'+ns,'namespace',ns)
    for pv in record['pvs']:r.delete('remove-pv','pv',pv['metadata']['name'])
    for name in ('database-ondemand','application-ondemand'):r.delete('remove-nodepool-'+name,'nodepool',name)
    r.wait('wait-nodeclaims',lambda:r.get('nodeclaims-read','nodeclaims',''),lambda x:not x['items'])
    for name in ('application','application-fis','database'):r.delete('remove-nodeclass-'+name,'ec2nodeclass',name)
    r.wait('wait-nodeclasses',lambda:r.get('nodeclasses-read','ec2nodeclasses',''),lambda x:not x['items'])
    for pv in record['pvs']:
        vol=pv['spec']['csi']['volumeHandle']
        def read_volume():return r.invoke('pv-volume-read',AWS+['ec2','describe-volumes','--filters','Name=volume-id,Values='+vol])['Volumes']
        current=r.wait('wait-pv-detach',read_volume,lambda xs:not xs or xs[0]['State']=='available')
        if current:r.invoke('delete-captured-pv-volume',AWS+['ec2','delete-volume','--volume-id',vol],True)
        r.wait('wait-pv-volume-deleted',read_volume,lambda xs:not xs)
    r.wait('wait-alb-removed',lambda:r.invoke('alb-removal-read',AWS+['elbv2','describe-load-balancers']),lambda x:not any(lb['VpcId']==record['outputs']['vpc_id'] for lb in x['LoadBalancers']))
    r.wait('wait-new-nodes-terminated',lambda:r.invoke('new-node-read',AWS+['ec2','describe-instances','--filters','Name=instance-id,Values='+','.join(record['new_instance_ids'])]),lambda x:all(i['State']['Name']=='terminated' for res in x['Reservations'] for i in res['Instances']))
    r.wait('wait-apps-removed',lambda:r.get('apps-remaining','applications.argoproj.io','','argocd'),lambda x:not x['items'])


def plan_gate(value,current,stage):
    known=addresses(current);deleted={};drift=set()
    for item in value.get('resource_drift',[]):
        if item['mode']=='managed':
            p.require(item['address'] in known and item['change']['actions']==['delete'] and item['change']['before'].get('id')==known[item['address']].get('id'),'unexpected-remote-drift')
            drift.add(item['address'])
    for item in value.get('resource_changes',[]):
        actions=item['change']['actions']
        p.require(actions in (['delete'],['no-op'],['read']),'create-update-replacement-forbidden')
        if item['mode']=='managed':
            p.require(item['address'] in known and actions!=['read'],'unknown-managed-plan-address')
            if actions==['delete']:
                p.require(item['change']['before'].get('id')==known[item['address']].get('id'),'plan-resource-id-drift')
                deleted[item['address']]=item['type']
    p.require(deleted,'empty-delete-plan')
    if stage=='eks':
        p.require(not any(a.startswith('module.vpc.') or t=='aws_vpc' for a,t in deleted.items()),'vpc-delete-in-eks-stage')
        p.require(list(deleted.values()).count('aws_eks_cluster')==1 and 'aws_eks_node_group' in deleted.values(),'eks-stage-must-remove-cluster-and-nodegroup')
    else:p.require(set(deleted)|drift==set(known),'final-plan-must-account-for-all-managed-state')
    return {'deleted':sorted(deleted),'drift':sorted(drift),'managed_delete_count':len(deleted),'reviewed_remote_absence_count':len(drift)}


def sg_safe(groups,interfaces,record):
    candidates=[x for x in groups if x['GroupId']==record['cluster_sg']]
    if not candidates:return False
    p.require(len(candidates)==1,'duplicate-cluster-sg')
    group=candidates[0]
    p.require(group['VpcId']==record['outputs']['vpc_id'] and group['OwnerId']==record['account'] and
        group['GroupName'].startswith('eks-cluster-sg-'+p.CLUSTER+'-') and group['Description'].startswith('EKS created security group'),'sg-ownership')
    p.require(not interfaces,'sg-still-has-interfaces')
    p.require(not any(pair['GroupId']==record['cluster_sg'] for g in groups if g['GroupId']!=record['cluster_sg'] for rule in g.get('IpPermissions',[])+g.get('IpPermissionsEgress',[]) for pair in rule.get('UserIdGroupPairs',[])),'sg-still-referenced-by-other-group')
    return True


def tfcmd(*args):return ['terraform','-chdir='+str(TF),*args]


def snapshot(output):
    target=output/'state-before.tfstate';shutil.copyfile(h.ROOT/p.STATE,target);target.chmod(0o600)


def make_plan(r,args,record,stage):
    lock=TF/'.terraform.lock.hcl';p.require(lock.is_file() and not lock.is_symlink(),'existing-provider-lock-required')
    lock_hash=p.digest(lock)
    version=r.invoke('terraform-version',tfcmd('version','-json'))['terraform_version']
    p.require((1,8)<=tuple(map(int,version.split('.')[:2]))<(2,0),'unsupported-terraform-version')
    p.require(r.invoke('terraform-workspace',tfcmd('workspace','show'),json_output=False).strip()==b'default','default-terraform-workspace-required')
    r.invoke('terraform-init',tfcmd('init','-input=false','-lockfile=readonly'),json_output=False)
    p.require(p.digest(lock)==lock_hash,'provider-lock-changed')
    binary=args.output_directory/'destroy.tfplan'
    cmd=tfcmd('plan','-destroy','-input=false','-lock-timeout=0s','-out='+str(binary),'-var=eks_public_access_cidrs='+json.dumps([record['management_cidr']]))
    if stage=='eks':cmd+=['-target=module.eks']
    r.invoke('terraform-plan',cmd,json_output=False)
    binary.chmod(0o600)
    value=r.invoke('terraform-show-json',tfcmd('show','-json',str(binary)))
    p.write(args.output_directory/'destroy-plan.json',value)
    text=r.invoke('terraform-show-text',tfcmd('show','-no-color',str(binary)),json_output=False)
    fd=os.open(args.output_directory/'destroy-plan.txt',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(text)
    gate=plan_gate(value,state(),stage)
    proof={'window_contract_sha256':window_digest(),'status':'aws-test-'+stage+'-delete-plan-produced','stage':stage,'main':args.expected_main,
        'inputs_sha256':p.digest(args.inputs),'state_sha256':r.state_hash,'created_at_utc':p.timestamp(),
        'binary_sha256':p.digest(binary),'json_sha256':p.digest(args.output_directory/'destroy-plan.json'),
        'text_sha256':p.digest(args.output_directory/'destroy-plan.txt'),'provider_lock_sha256':lock_hash,'terraform_version':version,
        'runtime_record_sha256':p.digest(args.workspace/'runtime-record.json'),'gate':gate,'human_reviewed':False}
    p.write(args.output_directory/'plan-proof.json',proof)
    return {k:v for k,v in proof.items() if k not in ('gate','inputs_sha256','runtime_record_sha256')}|{'managed_delete_count':gate['managed_delete_count'],'reviewed_remote_absence_count':gate['reviewed_remote_absence_count'],'terraform_apply_executed':False}


def apply_plan(r,args,record,stage):
    proof=h.read_private(args.proof);require_window(proof);p.require(p.digest(args.proof)==args.expected_proof_sha256,'approved-plan-proof-hash')
    p.require(proof['stage']==stage and proof['main']==args.expected_main and proof['human_reviewed'] is True,'human-delete-plan-review-required')
    p.require(proof['inputs_sha256']==p.digest(args.inputs) and proof['state_sha256']==r.state_hash and proof['runtime_record_sha256']==p.digest(args.workspace/'runtime-record.json'),'plan-input-state-binding')
    p.require(0<=(h.now()-p.utc(proof['created_at_utc'])).total_seconds()<=1800,'delete-plan-expired')
    p.require(r.invoke('terraform-version-before-apply',tfcmd('version','-json'))['terraform_version']==proof['terraform_version'],'terraform-version-drift')
    p.require(r.invoke('terraform-workspace-before-apply',tfcmd('workspace','show'),json_output=False).strip()==b'default','default-terraform-workspace-required')
    folder=args.proof.parent
    for name,key in (('destroy.tfplan','binary_sha256'),('destroy-plan.json','json_sha256'),('destroy-plan.txt','text_sha256')):
        p.private(folder/name);p.require(p.digest(folder/name)==proof[key],'saved-plan-bytes')
    p.require(p.digest(TF/'.terraform.lock.hcl')==proof['provider_lock_sha256'],'provider-lock-drift')
    value=r.invoke('saved-plan-show',tfcmd('show','-json',str(folder/'destroy.tfplan')))
    p.require(plan_gate(value,state(),stage)==proof['gate'],'saved-plan-gate-drift')
    p.write(args.workspace/(stage+'-apply-attempt.json'),{'proof_sha256':args.expected_proof_sha256,'at_utc':p.timestamp(),'outcome_not_yet_known':True})
    before=set(addresses(state()));r.changing_state=True
    r.invoke('terraform-apply-saved-plan',tfcmd('apply','-input=false','-lock-timeout=0s',str(folder/'destroy.tfplan')),True,json_output=False)
    r.changing_state=False;r.state_hash=p.digest(h.ROOT/p.STATE)
    p.require(set(addresses(state()))==before-set(proof['gate']['deleted'])-set(proof['gate']['drift']),'post-apply-state-addresses')
    if stage=='eks':
        inventory=r.invoke('eks-absence',AWS+['eks','list-clusters'])['clusters'];p.require(p.CLUSTER not in inventory,'eks-still-present')
        groups=r.invoke('orphan-sg-scope',AWS+['ec2','describe-security-groups','--filters','Name=vpc-id,Values='+record['outputs']['vpc_id']])['SecurityGroups']
        interfaces=r.invoke('orphan-sg-interfaces',AWS+['ec2','describe-network-interfaces','--filters','Name=group-id,Values='+record['cluster_sg']])['NetworkInterfaces']
        if sg_safe(groups,interfaces,record):r.invoke('delete-reviewed-orphan-eks-sg',AWS+['ec2','delete-security-group','--group-id',record['cluster_sg']],True)
        groups=r.invoke('orphan-sg-absence',AWS+['ec2','describe-security-groups','--filters','Name=vpc-id,Values='+record['outputs']['vpc_id']])['SecurityGroups']
        p.require(not any(g['GroupId']==record['cluster_sg'] for g in groups),'orphan-sg-still-present')
        p.write(args.workspace/'eks-complete.json',{'window_contract_sha256':window_digest(),'main':args.expected_main,'state_sha256':r.state_hash,'runtime_record_sha256':p.digest(args.workspace/'runtime-record.json')})
    else:
        p.require(not addresses(state()),'managed-state-not-empty')
        p.require(p.CLUSTER not in r.invoke('final-eks',AWS+['eks','list-clusters'])['clusters'],'eks-not-absent')
        vpc=r.invoke('final-vpc',AWS+['ec2','describe-vpcs','--filters','Name=vpc-id,Values='+record['outputs']['vpc_id']])['Vpcs'];p.require(not vpc,'vpc-not-absent')
        records=r.invoke('final-alias',AWS+['route53','list-resource-record-sets','--hosted-zone-id',record['zone']])['ResourceRecordSets'];p.require(not any(x['Name']=='demo.test.aureumstack.com.' and x['Type'] in ('A','AAAA','CNAME') for x in records),'test-alias-residual')
        volumes=r.invoke('final-disks',AWS+['ec2','describe-volumes','--filters','Name=volume-id,Values='+','.join(record['disk_ids'])])['Volumes'];p.require(not volumes,'captured-disk-residual')
        lbs=r.invoke('final-alb',AWS+['elbv2','describe-load-balancers'])['LoadBalancers'];p.require(not any(x['VpcId']==record['outputs']['vpc_id'] for x in lbs),'alb-residual')
        bucket=r.invoke('final-backup-bucket',AWS+['s3api','list-object-versions','--bucket',record['outputs']['cnpg_backup_bucket_name'],'--expected-bucket-owner',record['account']],absent_code='NoSuchBucket');p.require(bucket is None,'backup-bucket-not-absent')
        secret=r.invoke('final-container',AWS+['secretsmanager','describe-secret','--secret-id',record['outputs']['external_secrets_secret_arn']],absent_code='ResourceNotFoundException');p.require(secret is None or secret.get('DeletedDate'),'credential-container-still-live')
    return {'status':'aws-test-'+stage+'-delete-complete','terraform_apply_executed_once':True,'terraform_state_sha256':r.state_hash,
        'residual_cost_audit_executed':False,'automatic_retry_performed':False,'next_action':'review-final-delete-plan' if stage=='eks' else 'review-separate-residual-cost-audit'}


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=PHASES)
    for name in ('inputs','workspace','output-directory','bundle','deployment-result','proof'):parser.add_argument('--'+name,type=Path,required=name in ('inputs','workspace','output-directory'))
    parser.add_argument('--expected-main',required=True);parser.add_argument('--expected-proof-sha256')
    args=parser.parse_args();r=None
    try:
        c=source_checks();cost_model=projection(c);confirmations(args.phase,os.environ);p.exact_main(args.expected_main,c['implementationBaselineCommit'])
        inputs=h.read_private(args.inputs)
        p.require(set(inputs)=={'aws_account_id','management_cidr','kubeconfig_path','recovery_summary_path','old_temporary_evidence_lost'},'input-fields')
        prior=p.load(h.ROOT/p.CONTRACT)
        for key,hashkey in (('kubeconfig_path','kubeconfigSha256'),('recovery_summary_path','observationSha256')):
            p.private(Path(inputs[key]));p.persistent(Path(inputs[key]));p.require(p.digest(Path(inputs[key]))==prior['recovery'][hashkey],'recovery-input-drift')
        end=p.utc(c['runtimeStopUtc'] if 'runtime' in args.phase else c['cleanupCompleteByUtc'])
        p.require((end-h.now()).total_seconds()>=(1200 if 'runtime' in args.phase else 900),'insufficient-cleanup-time')
        h.new_directory(args.output_directory)
        if args.phase=='verify-runtime':h.new_directory(args.workspace)
        else:p.private(args.workspace,0o700);p.persistent(args.workspace)
        r=Runner(args.output_directory,inputs,end,p.digest(h.ROOT/p.STATE));snapshot(args.output_directory)
        p.require(r.invoke('account',AWS+['sts','get-caller-identity'])['Account']==inputs['aws_account_id'],'account-mismatch')
        if args.phase=='verify-runtime':
            p.require(args.bundle and args.deployment_result,'deployment-evidence-required')
            record=scope(r,args,c);p.write(args.workspace/'runtime-record.json',record)
            proof={'window_contract_sha256':window_digest(),'cost_projection':cost_model,'status':'aws-test-runtime-cleanup-inputs-verified','main':args.expected_main,'created_at_utc':p.timestamp(),
                'inputs_sha256':p.digest(args.inputs),'state_sha256':r.state_hash,'runtime_record_sha256':p.digest(args.workspace/'runtime-record.json'),
                'human_reviewed':False,'teardown_authorized':False}
            p.write(args.workspace/'runtime-proof.json',proof);result=proof|{'runtime_resource_inventory_review_required':True}
        else:
            p.require(args.proof and args.expected_proof_sha256,'bound-proof-required')
            proof=h.read_private(args.proof);require_window(proof);p.require(p.digest(args.proof)==args.expected_proof_sha256,'proof-hash')
            record=h.read_private(args.workspace/'runtime-record.json')
            p.require(record['account']==inputs['aws_account_id'],'runtime-account-binding')
            if args.phase=='execute-runtime':
                p.require(proof['main']==args.expected_main and proof['human_reviewed'] is True and proof['inputs_sha256']==p.digest(args.inputs) and proof['state_sha256']==r.state_hash and proof['runtime_record_sha256']==p.digest(args.workspace/'runtime-record.json'),'runtime-proof-binding')
                p.require(0<=(h.now()-p.utc(proof['created_at_utc'])).total_seconds()<=900,'runtime-proof-expired')
                p.write(args.workspace/'runtime-attempt.json',{'proof_sha256':args.expected_proof_sha256,'at_utc':p.timestamp(),'outcome_not_yet_known':True})
                p.require(args.bundle and args.deployment_result,'deployment-evidence-required')
                fresh=scope(r,args,c);p.require(stable_scope(fresh)==stable_scope(record),'immediate-runtime-scope-drift')
                runtime_cleanup(r,record);r.check_time_and_state()
                receipt={'window_contract_sha256':window_digest(),'main':args.expected_main,'state_sha256':r.state_hash,'runtime_record_sha256':p.digest(args.workspace/'runtime-record.json')}
                p.write(args.workspace/'runtime-complete.json',receipt)
                result={'status':'aws-test-runtime-cleanup-complete','terraform_command_executed':False,'eks_deleted':False,'next_action':'separately-approve-eks-delete-plan'}
            elif args.phase.startswith('plan-'):
                stage=args.phase.removeprefix('plan-');receipt=h.read_private(args.workspace/('runtime-complete.json' if stage=='eks' else 'eks-complete.json'))
                p.require(proof==receipt and receipt['main']==args.expected_main and receipt['state_sha256']==r.state_hash and receipt['runtime_record_sha256']==p.digest(args.workspace/'runtime-record.json'),'stage-receipt-binding')
                p.write(args.workspace/(stage+'-plan-attempt.json'),{'receipt_sha256':args.expected_proof_sha256,'at_utc':p.timestamp()})
                result=make_plan(r,args,record,stage)
            else:result=apply_plan(r,args,record,args.phase.removeprefix('apply-'))
        r.check_time_and_state();p.exact_main(args.expected_main,c['implementationBaselineCommit'])
        result.update(window_contract_sha256=window_digest(),cost_projection=cost_model,control_plane_commit=args.expected_main,cleanup_complete_by_utc=c['cleanupCompleteByUtc'],automatic_retry_performed=False)
        p.write(args.output_directory/'result.json',result);print(json.dumps(result,indent=2,sort_keys=True));return 0
    except (Exception,KeyboardInterrupt):
        failure={'status':'aws-test-teardown-stopped','stage':r.stage if r else 'local-inputs','mutation_attempted':bool(r and r.mutation_attempted),
            'outcome_requires_read_only_review':True,'automatic_retry_performed':False,'preserve_state_and_private_evidence':True}
        if r:
            try:p.write(args.output_directory/'failure.json',failure)
            except OSError:pass
        print(json.dumps(failure,indent=2,sort_keys=True));print('Stopped: preserve evidence/state; no automatic repair or retry.',file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())

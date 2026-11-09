#!/usr/bin/env python3
"""Verify partial cleanup, delete only configuration remnants, then staged saved plans."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys

import aws_test_immutable_root as h
p = h.p
spec = importlib.util.spec_from_file_location('frozen_teardown', h.ROOT / 'scripts/execute-v0.11.9.3.6.7.6.2-aws-test-teardown.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CONTRACT = 'delivery/contracts/v0.11.9.3.6.7.6.3-aws-test-remaining-cleanup.json'
TF = m.TF
AWS = m.AWS
Runner = m.Runner
state, addresses, tfcmd, snapshot, sg_safe = m.state, m.addresses, m.tfcmd, m.snapshot, m.sg_safe
PHASES = {
    'verify-remaining': None,
    'execute-remaining': ('CONFIRM_AWS_TEST_REMAINING_RUNTIME', 'cleanup-reviewed-aws-test-config-remnants-once'),
    'plan-eks': ('CONFIRM_AWS_TEST_TEARDOWN_PLAN', 'plan-reviewed-aws-test-teardown'),
    'apply-eks': ('CONFIRM_AWS_TEST_EKS_DELETE', 'apply-reviewed-aws-test-eks-delete-once'),
    'plan-final': ('CONFIRM_AWS_TEST_TEARDOWN_PLAN', 'plan-reviewed-aws-test-teardown'),
    'apply-final': ('CONFIRM_AWS_TEST_FINAL_DELETE', 'apply-reviewed-aws-test-final-delete-once')
}

def source_checks():
    m.source_checks()
    c = p.load(h.ROOT / CONTRACT)
    for item in c['reviewedFiles']:
        p.require(p.digest(h.ROOT / item['path']) == item['sha256'], 'remaining-source-drift')
    return c

def window_digest():
    return p.digest(h.ROOT / CONTRACT)

def require_window(proof):
    p.require(proof.get('window_contract_sha256') == window_digest(), 'remaining-window-proof-binding')

def confirmations(phase, environment):
    h.assert_confirmations(environment, False)
    p.require(not any(key in environment for key in ('CONFIRM_AWS_TEST_RUNTIME_CLEANUP', 'CONFIRM_AWS_TEST_RUNTIME_RESUME')), 'consumed-runtime-approval')
    expected = PHASES[phase]
    for key, value in set(x for x in PHASES.values() if x):
        p.require(environment.get(key) == value if expected and key == expected[0] else key not in environment, 'separate-remaining-phase-approval')
    p.require(not any(key.startswith(('TF_CLI_ARGS', 'TF_VAR_')) or key == 'TF_WORKSPACE' for key in environment), 'terraform-environment-override')

def checked(path, expected):
    value = h.read_private(path)
    p.require(p.digest(path) == expected, 'private-history-hash')
    return value

def history(args, c):
    required = (args.prior_workspace, args.prior_result, args.repair_result, args.observation_directory)
    p.require(all(required), 'partial-history-required')
    artifacts = c['history']
    original = checked(args.prior_workspace / 'runtime-record.json', artifacts['runtimeRecord'])
    proof = checked(args.prior_workspace / 'runtime-proof-reviewed.json', artifacts['reviewedProof'])
    failure = checked(args.prior_result, artifacts['failure'])
    repair = checked(args.repair_result, artifacts['esoCleanupResult'])
    observation = checked(args.observation_directory / 'summary.json', artifacts['remainingObservation'])
    marker = h.read_private(args.prior_workspace / 'runtime-resume-attempt.json')
    p.require(marker['proof_sha256'] == artifacts['reviewedProof'] and proof['human_reviewed'] is True, 'consumed-attempt-binding')
    p.require(proof['runtime_record_sha256'] == artifacts['runtimeRecord'] and proof['state_sha256'] == c['stateSha256'], 'consumed-proof-binding')
    p.require(failure['stage'] == 'wait-namespace-startup-apps' and failure['mutation_attempted'] is True and failure['automatic_retry_performed'] is False, 'partial-failure-boundary')
    p.require(repair['status'] == 'aws-test-externalsecret-finalizer-cleanup-complete' and repair['namespace_absent'] is True and repair['state_unchanged'] is True and repair['automatic_retry_performed'] is False, 'eso-repair-boundary')
    for key in ('secret_value_read', 'aws_mutation_executed', 'terraform_command_executed'):
        p.require(repair[key] is False, 'eso-repair-action-boundary')
    p.require(observation['account_verified'] is True and observation['state_unchanged'] is True and observation['mutation_executed'] is False, 'observation-boundary')
    result = copy.deepcopy(original)
    result['remnant_uids'] = {}
    result['observation_file_digests'] = {}
    for label in ('nodepools', 'nodeclasses'):
        path = args.observation_directory / (label + '.stdout')
        items = h.read_private(path)['items']
        p.require({x['metadata']['name']: x['spec'] for x in items} == original[label], 'observed-config-spec')
        result['remnant_uids'][label] = {x['metadata']['name']: x['metadata']['uid'] for x in items}
        result['observation_file_digests'][label] = p.digest(path)
    return result

def controller_ready(r):
    items = r.get('system-controller-status', 'deployments', '', 'kube-system')['items']
    by_name = {x['metadata']['name']: x for x in items}
    for name in ('karpenter', 'aws-load-balancer-controller'):
        p.require(name in by_name, 'required-controller-missing')
        x = by_name[name]
        p.require(x['spec'].get('replicas', 1) > 0 and x.get('status', {}).get('readyReplicas', 0) == x['spec'].get('replicas', 1) and x['status'].get('observedGeneration', 0) >= x['metadata']['generation'], 'required-controller-unready')

def runtime_absence(r, record, configurations):
    p.require(not r.get('remaining-apps', 'applications.argoproj.io', '', 'argocd')['items'], 'application-returned')
    for ns in ('startup-apps', 'data-platform', 'observability'):
        p.require(not r.get('remaining-ns-' + ns, 'namespace', ns, optional=True), 'namespace-still-present')
    for label, kind in (('persistent-volumes', 'pv'), ('pvcs', 'pvc'), ('nodeclaims', 'nodeclaims')):
        command = r.kube + ['get', kind, '-o', 'json'] + (['-A'] if kind == 'pvc' else [])
        p.require(not r.invoke('remaining-' + label, command)['items'], 'runtime-storage-or-claims-remain')
    fresh = {}
    for label, kind in (('nodepools', 'nodepools'), ('nodeclasses', 'ec2nodeclasses')):
        items = r.get('remaining-' + label, kind, '')['items']
        if configurations:
            p.require({x['metadata']['name']: x['spec'] for x in items} == record[label] and {x['metadata']['name']: x['metadata']['uid'] for x in items} == record['remnant_uids'][label], 'configuration-recreated-or-drifted')
            p.require(not any(x['metadata'].get('deletionTimestamp') for x in items), 'configuration-deletion-in-progress')
        else:
            p.require(not items, 'configuration-remnants-present')
        fresh[label] = items
    return fresh

def cloud_scope(r, record, eks_present):
    inventory = r.invoke('remaining-eks-inventory', AWS + ['eks', 'list-clusters'])['clusters']
    active = set(inventory) & {p.CLUSTER, 'startup-devops-baseline-dev', 'startup-devops-baseline-prod'}
    p.require(active == ({p.CLUSTER} if eks_present else set()), 'unexpected-rehearsal-environment')
    vpc = record['outputs']['vpc_id']
    if eks_present:
        cluster = r.invoke('remaining-eks-network', AWS + ['eks', 'describe-cluster', '--name', p.CLUSTER])['cluster']
        network = cluster['resourcesVpcConfig']
        p.require(cluster['status'] == 'ACTIVE' and network['vpcId'] == vpc and network['clusterSecurityGroupId'] == record['cluster_sg'] and network['endpointPublicAccess'] and network['endpointPrivateAccess'] and network['publicAccessCidrs'] == [record['management_cidr']], 'eks-network-drift')
        config = r.invoke('remaining-kube-auth', r.kube + ['config', 'view', '--minify', '-o', 'json'])
        p.kube_auth(config, cluster['endpoint'])
    reservations = r.invoke('remaining-compute', AWS + ['ec2', 'describe-instances', '--filters', 'Name=vpc-id,Values=' + vpc])['Reservations']
    live = [x for reservation in reservations for x in reservation['Instances'] if x['State']['Name'] != 'terminated']
    systems = set(record['instance_ids']) - set(record['new_instance_ids'])
    p.require({x['InstanceId'] for x in live} == (systems if eks_present else set()), 'unexpected-or-unremoved-compute')
    root_ids = set()
    if eks_present:
        groups = {g['name'] for res in state()['resources'] if res.get('type') == 'aws_eks_node_group' for i in res['instances'] for item in i['attributes']['resources'] for g in item['autoscaling_groups']}
        for instance in live:
            p.require(instance['State']['Name'] == 'running' and instance['InstanceType'] == 't3.medium' and not instance.get('InstanceLifecycle'), 'system-compute-drift')
            p.require(any(t['Key'] == 'aws:autoscaling:groupName' and t['Value'] in groups for t in instance.get('Tags', [])), 'system-asg-drift')
            mappings = instance['BlockDeviceMappings']
            p.require(len(mappings) == 1 and mappings[0]['DeviceName'] == instance['RootDeviceName'] and mappings[0]['Ebs']['DeleteOnTermination'], 'unexpected-or-retained-system-disk')
            root_ids.add(mappings[0]['Ebs']['VolumeId'])
        p.require(len(live) == 4 and len(root_ids) == 4 and root_ids <= set(record['disk_ids']), 'system-root-membership')
    volumes = r.invoke('remaining-captured-disks', AWS + ['ec2', 'describe-volumes', '--filters', 'Name=volume-id,Values=' + ','.join(record['disk_ids'])])['Volumes']
    p.require({x['VolumeId'] for x in volumes} == root_ids, 'captured-business-volume-remains')
    for volume in volumes:
        p.require(volume['State'] == 'in-use' and volume['Size'] == 30 and volume['VolumeType'] == 'gp3' and volume['Iops'] == 3000 and volume['Throughput'] == 125 and len(volume['Attachments']) == 1 and volume['Attachments'][0]['InstanceId'] in systems, 'system-volume-drift')
    if eks_present:
        attached = r.invoke('remaining-system-disk-inventory', AWS + ['ec2', 'describe-volumes', '--filters', 'Name=attachment.instance-id,Values=' + ','.join(sorted(systems))])['Volumes']
        p.require({x['VolumeId'] for x in attached} == root_ids, 'unexpected-system-volume')
    for service, operation, key in (('elbv2', 'describe-load-balancers', 'LoadBalancers'), ('elbv2', 'describe-target-groups', 'TargetGroups')):
        items = r.invoke('remaining-' + operation, AWS + [service, operation])[key]
        p.require(not any(x.get('VpcId') == vpc for x in items), 'alb-or-targetgroup-remains')
    records = r.invoke('remaining-dns', AWS + ['route53', 'list-resource-record-sets', '--hosted-zone-id', record['zone']])['ResourceRecordSets']
    p.require(not any(x['Name'] == 'demo.test.aureumstack.com.' and x['Type'] in ('A', 'AAAA', 'CNAME') for x in records), 'test-dns-returned')
    return {'system_instance_count': len(live), 'captured_volume_count': len(volumes), 'captured_volume_total_gib': sum(x['Size'] for x in volumes), 'volume_inventory_exhaustive': False}

def configuration_cleanup(r, record):
    for label, kind in (('nodepools', 'nodepool'), ('nodeclasses', 'ec2nodeclass')):
        for name in sorted(record[label]):
            current = r.get('config-delete-check-' + name, kind, name)
            p.require(current['metadata']['uid'] == record['remnant_uids'][label][name] and current['spec'] == record[label][name] and not current['metadata'].get('deletionTimestamp'), 'configuration-delete-drift')
            api = 'karpenter.sh/v1' if label == 'nodepools' else 'karpenter.k8s.aws/v1'
            plural = 'nodepools' if label == 'nodepools' else 'ec2nodeclasses'
            p.require(current['apiVersion'] == api, 'unexpected-configuration-api')
            manifest = r.output / (label + '-' + name + '-delete.json')
            p.write(manifest, {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Background', 'preconditions': {'uid': current['metadata']['uid'], 'resourceVersion': current['metadata']['resourceVersion']}})
            r.invoke('delete-config-' + name, r.kube + ['delete', '--raw=/apis/' + api + '/' + plural + '/' + name, '-f', str(manifest)], mutation=True)
        list_kind = 'nodepools' if label == 'nodepools' else 'ec2nodeclasses'
        r.wait('wait-' + label, lambda: r.get('config-' + label + '-after', list_kind, ''), lambda x: not x['items'])
    p.require(not r.get('config-claims-after', 'nodeclaims', '')['items'], 'nodeclaim-created-during-cleanup')

def plan_gate(value, current, stage):
    gate = m.plan_gate(value, current, stage)
    if stage == 'eks':
        p.require(all(address.startswith('module.eks.') for address in gate['deleted'] + gate['drift']), 'non-eks-resource-in-target-plan')
    return gate

def final_inventory(r, record):
    value = r.invoke('final-backup-inventory-review', AWS + ['s3api', 'list-object-versions', '--bucket', record['outputs']['cnpg_backup_bucket_name'], '--expected-bucket-owner', record['account']])
    versions = sorted((x['Key'], x['VersionId'], x.get('Size', 0)) for x in value.get('Versions', []))
    markers = sorted((x['Key'], x['VersionId']) for x in value.get('DeleteMarkers', []))
    container = r.invoke('final-container-metadata-review', AWS + ['secretsmanager', 'describe-secret', '--secret-id', record['outputs']['external_secrets_secret_arn']])
    p.require(container['ARN'] == record['outputs']['external_secrets_secret_arn'] and not container.get('DeletedDate') and any('AWSCURRENT' in stages for stages in container.get('VersionIdsToStages', {}).values()), 'credential-container-metadata-drift')
    normalized = {'versions': versions, 'markers': markers}
    p.write(r.output / 'backup-inventory-reviewed.json', normalized)
    p.write(r.output / 'container-inventory-reviewed.json', {'arn': container['ARN'], 'version_stages': container['VersionIdsToStages']})
    return {'backup_inventory_digest': h.hash_value(normalized), 'container_inventory_digest': h.hash_value({'arn': container['ARN'], 'version_stages': container['VersionIdsToStages']}), 'backup_version_count': len(versions), 'backup_delete_marker_count': len(markers), 'backup_recorded_bytes': sum(x[2] for x in versions), 'inventory_is_atomic': False}

def make_plan(r,args,record,stage):
    inventory = final_inventory(r, record) if stage == 'final' else {}
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
    proof.update(inventory)
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
    if stage == 'final':
        current_inventory = final_inventory(r, record)
        p.require(all(proof.get(key) == current_inventory[key] for key in ('backup_inventory_digest', 'container_inventory_digest')), 'backup-or-container-inventory-changed')
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=PHASES)
    for name in ('inputs', 'workspace', 'output-directory', 'proof', 'prior-workspace', 'prior-result', 'repair-result', 'observation-directory'):
        parser.add_argument('--' + name, type=Path, required=name in ('inputs', 'workspace', 'output-directory'))
    parser.add_argument('--expected-main', required=True)
    parser.add_argument('--expected-proof-sha256')
    args = parser.parse_args()
    r = None
    try:
        c = source_checks()
        cost = m.projection(c)
        confirmations(args.phase, os.environ)
        p.exact_main(args.expected_main, c['implementationBaselineCommit'])
        inputs = checked(args.inputs, c['inputsSha256'])
        p.require(set(inputs) == {'aws_account_id', 'management_cidr', 'kubeconfig_path', 'recovery_summary_path', 'old_temporary_evidence_lost'} and inputs['old_temporary_evidence_lost'] is True, 'recovery-input-fields')
        for key, expected in c['recovery'].items():
            p.require(key in inputs, 'missing-recovery-input')
            path = Path(inputs[key])
            p.private(path)
            p.private(path.parent, 0o700)
            p.persistent(path)
            p.require(p.digest(path) == expected, 'recovery-file-drift')
        stop = p.utc(c['runtimeStopUtc'] if 'remaining' in args.phase else c['cleanupCompleteByUtc'])
        p.require((stop - h.now()).total_seconds() >= (1200 if 'remaining' in args.phase else 900), 'insufficient-new-cleanup-time')
        if args.phase in ('verify-remaining', 'execute-remaining', 'plan-eks', 'apply-eks'):
            p.require(p.digest(h.ROOT / p.STATE) == c['stateSha256'], 'original-state-changed')
        h.new_directory(args.output_directory)
        if args.phase == 'verify-remaining':
            h.new_directory(args.workspace)
        else:
            p.private(args.workspace, 0o700)
            p.persistent(args.workspace)
        r = Runner(args.output_directory, inputs, stop, p.digest(h.ROOT / p.STATE))
        r.environment['AWS_MAX_ATTEMPTS'] = '1'
        r.environment['AWS_RETRY_MODE'] = 'standard'
        snapshot(args.output_directory)
        p.require(r.invoke('account', AWS + ['sts', 'get-caller-identity'])['Account'] == inputs['aws_account_id'], 'account-mismatch')
        if args.phase == 'verify-remaining':
            record = history(args, c)
            p.require(record['account'] == inputs['aws_account_id'] and record['management_cidr'] == inputs['management_cidr'] and addresses(state()) == record['managed'], 'history-input-state-binding')
            runtime_absence(r, record, True)
            counts = cloud_scope(r, record, True)
            controller_ready(r)
            p.write(args.workspace / 'runtime-record.json', record)
            proof = {'window_contract_sha256': window_digest(), 'status': 'aws-test-remaining-config-inputs-verified', 'main': args.expected_main, 'created_at_utc': p.timestamp(), 'inputs_sha256': p.digest(args.inputs), 'state_sha256': r.state_hash, 'runtime_record_sha256': p.digest(args.workspace / 'runtime-record.json'), 'human_reviewed': False, 'schedule_review_required': True, 'cost_projection': cost}
            p.write(args.workspace / 'runtime-proof.json', proof)
            result = proof | counts | {'remaining_nodepool_count': 2, 'remaining_nodeclass_count': 3, 'teardown_authorized': False}
        else:
            p.require(args.proof and args.expected_proof_sha256, 'bound-proof-required')
            proof = h.read_private(args.proof)
            require_window(proof)
            p.require(p.digest(args.proof) == args.expected_proof_sha256, 'approved-proof-hash')
            record = h.read_private(args.workspace / 'runtime-record.json')
            p.require(record['account'] == inputs['aws_account_id'] and record['management_cidr'] == inputs['management_cidr'], 'private-record-input-binding')
            if args.phase == 'execute-remaining':
                p.require(proof['human_reviewed'] is True and proof['schedule_review_required'] is False and proof['main'] == args.expected_main and proof['inputs_sha256'] == p.digest(args.inputs) and proof['state_sha256'] == r.state_hash and proof['runtime_record_sha256'] == p.digest(args.workspace / 'runtime-record.json'), 'human-config-and-schedule-review')
                p.require(0 <= (h.now() - p.utc(proof['created_at_utc'])).total_seconds() <= 900, 'config-proof-expired')
                p.write(args.workspace / 'remaining-runtime-attempt.json', {'proof_sha256': args.expected_proof_sha256, 'at_utc': p.timestamp(), 'outcome_not_yet_known': True})
                runtime_absence(r, record, True)
                cloud_scope(r, record, True)
                controller_ready(r)
                configuration_cleanup(r, record)
                runtime_absence(r, record, False)
                cloud_scope(r, record, True)
                p.write(args.workspace / 'runtime-complete.json', {'window_contract_sha256': window_digest(), 'main': args.expected_main, 'state_sha256': r.state_hash, 'runtime_record_sha256': p.digest(args.workspace / 'runtime-record.json')})
                result = {'status': 'aws-test-remaining-config-cleanup-complete', 'configuration_delete_count': 5, 'completed_runtime_deletions_repeated': False, 'terraform_command_executed': False, 'next_action': 'separately-approve-eks-delete-plan'}
            else:
                stage = args.phase.split('-', 1)[1]
                if stage == 'eks':
                    runtime_absence(r, record, False)
                    cloud_scope(r, record, True)
                else:
                    cloud_scope(r, record, False)
                if args.phase.startswith('plan-'):
                    receipt = h.read_private(args.workspace / ('runtime-complete.json' if stage == 'eks' else 'eks-complete.json'))
                    p.require(proof == receipt and receipt['main'] == args.expected_main and receipt['state_sha256'] == r.state_hash and receipt['runtime_record_sha256'] == p.digest(args.workspace / 'runtime-record.json'), 'stage-receipt-binding')
                    p.write(args.workspace / (stage + '-plan-attempt.json'), {'receipt_sha256': args.expected_proof_sha256, 'at_utc': p.timestamp()})
                    result = make_plan(r, args, record, stage)
                else:
                    result = apply_plan(r, args, record, stage)
        r.check_time_and_state()
        p.exact_main(args.expected_main, c['implementationBaselineCommit'])
        result.update(window_contract_sha256=window_digest(), cost_projection=cost, control_plane_commit=args.expected_main, cleanup_complete_by_utc=c['cleanupCompleteByUtc'], automatic_retry_performed=False)
        p.write(args.output_directory / 'result.json', result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        failure = {'status': 'aws-test-teardown-stopped', 'stage': r.stage if r else 'local-inputs', 'mutation_attempted': bool(r and r.mutation_attempted), 'outcome_requires_read_only_review': True, 'automatic_retry_performed': False, 'preserve_state_and_private_evidence': True}
        if r:
            try:
                p.write(args.output_directory / 'failure.json', failure)
            except OSError:
                pass
        print(json.dumps(failure, indent=2, sort_keys=True))
        print('Stopped: preserve evidence/state; no automatic repair or retry.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())

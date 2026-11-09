#!/usr/bin/env python3
"""Exact state-bound EKS dependency deletion; preserved plan clocks and separate approvals."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import aws_test_immutable_root as h
p = h.p
spec = importlib.util.spec_from_file_location('frozen_remaining', h.ROOT / 'scripts/execute-v0.11.9.3.6.7.6.3-aws-test-teardown.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CONTRACT = 'delivery/contracts/v0.11.9.3.6.7.6.4-aws-test-eks-dependency-plan-repair.json'
TF, AWS, Runner = m.TF, m.AWS, m.Runner
state, addresses, tfcmd, snapshot, sg_safe = m.state, m.addresses, m.tfcmd, m.snapshot, m.sg_safe
runtime_absence, cloud_scope, final_inventory = m.runtime_absence, m.cloud_scope, m.final_inventory
PHASES = {'adopt-eks': None, **{x: m.PHASES[x] for x in ('plan-eks', 'apply-eks', 'plan-final', 'apply-final')}}

def source_checks():
    m.source_checks()
    c = p.load(h.ROOT / CONTRACT)
    for item in c['reviewedFiles']:
        p.require(p.digest(h.ROOT / item['path']) == item['sha256'], 'dependency-source-drift')
    return c

def window_digest():
    return p.digest(h.ROOT / CONTRACT)

def require_window(proof):
    p.require(proof.get('window_contract_sha256') == window_digest(), 'dependency-window-binding')

def confirmations(phase, environment):
    h.assert_confirmations(environment, False)
    p.require(not any(key in environment for key in ('CONFIRM_AWS_TEST_RUNTIME_CLEANUP', 'CONFIRM_AWS_TEST_RUNTIME_RESUME', 'CONFIRM_AWS_TEST_REMAINING_RUNTIME')), 'consumed-runtime-approval')
    expected = PHASES[phase]
    for key, value in set(x for x in PHASES.values() if x):
        p.require(environment.get(key) == value if expected and key == expected[0] else key not in environment, 'separate-dependency-phase-approval')
    p.require(not any(key.startswith(('TF_CLI_ARGS', 'TF_VAR_')) or key == 'TF_WORKSPACE' for key in environment), 'terraform-environment-override')

def checked(path, expected):
    value = h.read_private(path)
    p.require(p.digest(path) == expected, 'private-history-hash')
    return value

def selected_addresses(current, definitions):
    expected = {(x['module'], x['type'], x['name']): x['count'] for x in definitions}
    p.require(len(expected) == len(definitions), 'duplicate-definition')
    selected = {}
    counts = Counter()
    known = addresses(current)
    for res in current.get('resources', []):
        key = (res.get('module', ''), res['type'], res['name'])
        if res['mode'] != 'managed' or key not in expected:
            continue
        base = '.'.join(key)
        for instance in res.get('instances', []):
            address = base + ('[' + json.dumps(instance['index_key']) + ']' if 'index_key' in instance else '')
            p.require(not instance.get('deposed') and address in known and known[address].get('id'), 'unclassified-or-idless-state')
            selected[address] = (res['type'], key[0])
            counts[key] += 1
    p.require(dict(counts) == expected, 'exact-definition-state-counts')
    return selected

def plan_gate(value, current, stage):
    if stage != 'eks':
        return m.m.plan_gate(value, current, stage)
    c = p.load(h.ROOT / CONTRACT)
    selected = selected_addresses(current, c['allowedDefinitions'])
    p.require(len(selected) == c['exactManagedDeleteCount'], 'exact-delete-state-count')
    p.require(dict(Counter(module for _, module in selected.values())) == c['expectedModuleCounts'], 'exact-module-counts')
    p.require(not any(x['mode'] == 'managed' for x in value.get('resource_drift', [])), 'managed-drift-forbidden')
    changes = value.get('resource_changes', [])
    p.require(len(changes) == len(selected), 'exact-plan-change-count')
    seen = set()
    known = addresses(current)
    for item in changes:
        address = item['address']
        p.require(item['mode'] == 'managed' and item['change']['actions'] == ['delete'] and address in selected and address not in seen, 'non-exact-dependency-delete')
        p.require(item['type'] == selected[address][0] and item.get('module_address') == selected[address][1], 'plan-definition-mismatch')
        p.require(item['change']['before'].get('id') == known[address]['id'] and item['change'].get('after') is None, 'plan-resource-id-drift')
        seen.add(address)
    p.require(seen == set(selected), 'missing-dependency-delete')
    return {'deleted': sorted(seen), 'drift': [], 'managed_delete_count': len(seen), 'reviewed_remote_absence_count': 0}

def original_plan_time(folder, c):
    binary = folder / 'destroy.tfplan'
    p.private(binary)
    observed = datetime.fromtimestamp(binary.stat().st_mtime, timezone.utc).replace(microsecond=0)
    # Start conservatively at prior runtime completion, never at adoption/mtime.
    created = p.utc(c['originalPlanEarliestAtUtc'])
    p.require(observed >= created, 'original-plan-time-unavailable')
    p.require(created >= p.utc(c['originalPlanEarliestAtUtc']), 'original-plan-time-unavailable')
    p.require(0 <= (h.now() - created).total_seconds() <= c['savedPlanTtlSeconds'], 'original-delete-plan-expired-no-auto-replan')
    return created.strftime('%Y-%m-%dT%H:%M:%SZ')

def prior_history(args, c):
    p.require(args.prior_workspace and args.prior_result and args.gate_observation, 'failed-plan-history-required')
    p.private(args.prior_workspace, 0o700)
    p.persistent(args.prior_workspace)
    failure = checked(args.prior_result, c['history']['failure'])
    p.require(failure['stage'] == 'terraform-show-text' and failure['mutation_attempted'] is False and failure['automatic_retry_performed'] is False, 'failed-plan-boundary')
    observation = checked(args.gate_observation, c['history']['gateObservation'])
    p.require(observation['action_counts'] == {'delete': 50} and not observation['managed_drift_by_type_and_action'] and observation['mutation_executed'] is False and observation['terraform_command_executed'] is False, 'observed-plan-boundary')
    record = checked(args.prior_workspace / 'runtime-record.json', c['history']['runtimeRecord'])
    receipt = checked(args.prior_workspace / 'runtime-complete.json', c['history']['runtimeComplete'])
    p.require(receipt['window_contract_sha256'] == c['originalWindowDigest'] and receipt['main'] == c['implementationBaselineCommit'] and receipt['state_sha256'] == c['stateSha256'] and receipt['runtime_record_sha256'] == c['history']['runtimeRecord'], 'runtime-completion-binding')
    marker = h.read_private(args.prior_workspace / 'eks-plan-attempt.json')
    p.require(marker['receipt_sha256'] == c['history']['runtimeComplete'], 'failed-plan-marker-binding')
    return record

def adopt_plan(r, args, record, c, original_created):
    folder = args.plan_directory
    p.private(folder, 0o700)
    p.persistent(folder)
    for name, key in (('destroy.tfplan', 'binaryDigest'), ('destroy-plan.json', 'jsonDigest'), ('destroy-plan.txt', 'textDigest')):
        p.private(folder / name)
        p.require(p.digest(folder / name) == c['existingCandidate'][key], 'original-candidate-bytes')
    p.private(folder / 'state-before.tfstate')
    p.require(p.digest(folder / 'state-before.tfstate') == c['stateSha256'], 'original-candidate-state')
    version = r.invoke('terraform-version', tfcmd('version', '-json'))['terraform_version']
    p.require(r.invoke('terraform-workspace', tfcmd('workspace', 'show'), json_output=False).strip() == b'default', 'default-terraform-workspace-required')
    p.require(h.read_private(folder / 'destroy-plan.json')['terraform_version'] == version, 'terraform-version-drift')
    lock = TF / '.terraform.lock.hcl'
    p.require(lock.is_file() and not lock.is_symlink(), 'existing-provider-lock-required')
    lock_hash = p.digest(lock)
    value = r.invoke('original-saved-plan-show-json', tfcmd('show', '-json', str(folder / 'destroy.tfplan')))
    p.write(args.output_directory / 'destroy-plan.json', value)
    p.require(p.digest(args.output_directory / 'destroy-plan.json') == c['existingCandidate']['jsonDigest'], 'original-show-json-drift')
    text = r.invoke('original-saved-plan-show-text', tfcmd('show', '-no-color', str(folder / 'destroy.tfplan')), json_output=False)
    p.require(__import__('hashlib').sha256(text).hexdigest() == c['existingCandidate']['textDigest'], 'original-show-text-drift')
    for name in ('destroy.tfplan', 'destroy-plan.txt'):
        with (folder / name).open('rb') as src:
            fd = os.open(args.output_directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as dest:
                dest.write(src.read())
    p.require(p.digest(lock) == lock_hash, 'provider-lock-drift')
    r.stage = 'machine-plan-gate'
    gate = plan_gate(value, state(), 'eks')
    original_plan_time(folder, c)
    runtime_absence(r, record, False)
    cloud_scope(r, record, True)
    proof = {'window_contract_sha256': window_digest(), 'status': 'aws-test-eks-delete-plan-adopted-with-original-clock', 'stage': 'eks', 'main': args.expected_main,
             'inputs_sha256': p.digest(args.inputs), 'state_sha256': r.state_hash, 'created_at_utc': original_created,
             'adopted_at_utc': p.timestamp(), 'original_plan_clock_reset': False, 'original_failure_sha256': c['history']['failure'],
             'binary_sha256': c['existingCandidate']['binaryDigest'], 'json_sha256': c['existingCandidate']['jsonDigest'], 'text_sha256': c['existingCandidate']['textDigest'],
             'provider_lock_sha256': lock_hash, 'terraform_version': version, 'runtime_record_sha256': p.digest(args.workspace / 'runtime-record.json'), 'gate': gate, 'human_reviewed': False}
    p.write(args.output_directory / 'plan-proof.json', proof)
    return {k: v for k, v in proof.items() if k not in ('gate', 'inputs_sha256', 'runtime_record_sha256')} | {'managed_delete_count': 50, 'terraform_apply_executed': False}

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
    r.stage = "machine-plan-gate"
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
    r.stage = 'saved-plan-gate'
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
    for name in ('inputs', 'workspace', 'output-directory', 'proof', 'prior-workspace', 'prior-result', 'gate-observation', 'plan-directory'):
        parser.add_argument('--' + name, type=Path, required=name in ('inputs', 'workspace', 'output-directory'))
    parser.add_argument('--expected-main', required=True)
    parser.add_argument('--expected-proof-sha256')
    args = parser.parse_args()
    r = None
    try:
        c = source_checks()
        cost = m.m.projection(c)
        confirmations(args.phase, os.environ)
        p.exact_main(args.expected_main, c['implementationBaselineCommit'])
        inputs = checked(args.inputs, c['inputsSha256'])
        p.require(set(inputs) == {'aws_account_id', 'management_cidr', 'kubeconfig_path', 'recovery_summary_path', 'old_temporary_evidence_lost'} and inputs['old_temporary_evidence_lost'] is True, 'recovery-input-fields')
        for key, expected in c['recovery'].items():
            path = Path(inputs[key])
            p.private(path)
            p.private(path.parent, 0o700)
            p.persistent(path)
            p.require(p.digest(path) == expected, 'recovery-file-drift')
        stop = p.utc(c['cleanupCompleteByUtc'])
        p.require((stop - h.now()).total_seconds() >= c['minimumTerraformStartSeconds'], 'insufficient-cleanup-time')
        stage = args.phase.split('-', 1)[1]
        initialize = args.phase in ('adopt-eks', 'plan-eks')
        if stage == 'eks':
            p.require(p.digest(h.ROOT / p.STATE) == c['stateSha256'], 'original-state-changed')
        if args.phase == 'adopt-eks':
            p.require(args.plan_directory, 'original-plan-directory-required')
            original_created = original_plan_time(args.plan_directory, c)
        if initialize:
            record = prior_history(args, c)
            p.require(addresses(state()) == record['managed'], 'original-managed-state-binding')
            h.new_directory(args.workspace)
            p.write(args.workspace / 'runtime-record.json', record)
            p.write(args.workspace / 'runtime-complete.json', {'window_contract_sha256': window_digest(), 'main': args.expected_main, 'state_sha256': c['stateSha256'], 'runtime_record_sha256': p.digest(args.workspace / 'runtime-record.json')})
        else:
            p.private(args.workspace, 0o700)
            p.persistent(args.workspace)
            record = h.read_private(args.workspace / 'runtime-record.json')
            p.require(p.digest(args.workspace / 'runtime-record.json') == c['history']['runtimeRecord'], 'runtime-record-drift')
            p.require(args.proof and args.expected_proof_sha256, 'bound-proof-required')
            proof = checked(args.proof, args.expected_proof_sha256)
            require_window(proof)
            if args.phase.startswith('apply-'):
                p.require(0 <= (h.now() - p.utc(proof['created_at_utc'])).total_seconds() <= c['savedPlanTtlSeconds'], 'delete-plan-expired')
                p.require(not (args.workspace / (stage + '-apply-attempt.json')).exists() and not (args.workspace / (stage + '-apply-attempt.json')).is_symlink(), 'existing-apply-attempt')
        p.require(record['account'] == inputs['aws_account_id'] and record['management_cidr'] == inputs['management_cidr'], 'record-input-binding')
        h.new_directory(args.output_directory)
        r = Runner(args.output_directory, inputs, stop, p.digest(h.ROOT / p.STATE))
        r.environment['AWS_MAX_ATTEMPTS'] = '1'
        r.environment['AWS_RETRY_MODE'] = 'standard'
        snapshot(args.output_directory)
        p.require(r.invoke('account', AWS + ['sts', 'get-caller-identity'])['Account'] == inputs['aws_account_id'], 'account-mismatch')
        if stage == 'eks':
            runtime_absence(r, record, False)
        cloud_scope(r, record, stage == 'eks')
        if initialize:
            p.write(args.workspace / 'eks-plan-attempt.json', {'original_failure_sha256': c['history']['failure'], 'at_utc': p.timestamp(), 'phase': args.phase})
            if args.phase == 'adopt-eks':
                result = adopt_plan(r, args, record, c, original_created)
            else:
                result = make_plan(r, args, record, 'eks')
        elif args.phase.startswith('plan-'):
            receipt = h.read_private(args.workspace / 'eks-complete.json')
            p.require(proof == receipt and receipt['main'] == args.expected_main and receipt['state_sha256'] == r.state_hash and receipt['runtime_record_sha256'] == p.digest(args.workspace / 'runtime-record.json'), 'stage-receipt-binding')
            p.write(args.workspace / 'final-plan-attempt.json', {'receipt_sha256': args.expected_proof_sha256, 'at_utc': p.timestamp()})
            result = make_plan(r, args, record, 'final')
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

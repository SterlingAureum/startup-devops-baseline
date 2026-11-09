#!/usr/bin/env python3
"""Strict, separately reviewed aws-test read-only residual inventory; no Terraform."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = 'delivery/contracts/v0.11.9.3.6.7.6.6.1-aws-test-audit-error-envelope-repair.json'
STATE = 'infra/terraform/aws/environments/test/terraform.tfstate'
PRE_CONFIRM = 'observe-reviewed-aws-test-residual-cost-audit-preflight'
EXEC_CONFIRM = 'execute-reviewed-aws-test-residual-cost-audit-once'
PROJECT = 'startup-devops-baseline'
CLUSTER = PROJECT + '-test'
HOST = 'demo.test.aureumstack.com.'
OPS = {
 'sts': {'get-caller-identity'}, 'eks': {'list-clusters'},
 'ec2': {'describe-instances', 'describe-volumes', 'describe-network-interfaces',
         'describe-nat-gateways', 'describe-addresses', 'describe-vpcs',
         'describe-security-groups', 'describe-internet-gateways', 'describe-snapshots', 'describe-fleets'},
 'elbv2': {'describe-load-balancers', 'describe-target-groups'},
 's3api': {'list-object-versions'}, 'secretsmanager': {'describe-secret'},
 'logs': {'describe-log-groups'}, 'acm': {'describe-certificate', 'list-certificates'},
 'route53': {'list-resource-record-sets'},
 'iam': {'get-role', 'get-policy', 'get-open-id-connect-provider'},
 'events': {'describe-rule', 'list-targets-by-rule'}, 'sqs': {'get-queue-attributes'},
 'fis': {'get-experiment-template'}, 'resourcegroupstaggingapi': {'get-resources'}
}

class Stop(Exception):
    pass
class Residual(Stop):
    pass

def require(ok, label):
    if not ok: raise Stop(label)
def now(): return datetime.now(timezone.utc).replace(microsecond=0)
def stamp(value=None): return (value or now()).strftime('%Y-%m-%dT%H:%M:%SZ')
def utc(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value), 'utc-format')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
def encode(value): return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
def digest(value): return hashlib.sha256(value).hexdigest()
def json_data(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'duplicate-json-key'); result[k] = v
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(Stop('nonfinite-json')))
    require(isinstance(value, dict), 'json-object-required')
    return value

def checked_path(path, mode, persistent=True):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'symlink-path-rejected')
    require(path.exists(), 'required-file-missing')
    require((path.is_dir() if mode == 0o700 else path.is_file()), 'regular-private-path-required')
    require(stat.S_IMODE(path.stat().st_mode) == mode and path.stat().st_uid == os.getuid(), 'private-mode-or-owner')
    if persistent:
        resolved = path.resolve()
        require(not any(resolved.is_relative_to(Path(x)) for x in ('/tmp', '/var/tmp', '/dev', '/proc')), 'durable-private-path-required')
        require(not resolved.is_relative_to(ROOT), 'private-evidence-outside-repository-required')
    return path

def private_json(path, expected=None):
    path = checked_path(path, 0o600); checked_path(path.parent, 0o700)
    raw = path.read_bytes()
    if expected: require(digest(raw) == expected, 'private-evidence-digest-drift')
    return json_data(raw)

def write(path, value):
    raw = value if isinstance(value, bytes) else encode(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return digest(raw)

def new_output(path):
    path = Path(path).absolute()
    checked_path(path.parent, 0o700)
    require(not path.exists() and not path.is_symlink(), 'fresh-output-directory-required')
    path.mkdir(mode=0o700)
    return checked_path(path, 0o700)

def source_checks(root=ROOT):
    c = json_data((root / CONTRACT).read_bytes())
    for item in c['reviewedFiles']:
        require(digest((root / item['path']).read_bytes()) == item['sha256'], 'reviewed-source-drift')
    return c

def main_check(expected, baseline):
    require(re.fullmatch('[0-9a-f]{40}', expected) and expected != baseline, 'fresh-main-required')
    env = os.environ.copy(); env['GIT_TERMINAL_PROMPT'] = '0'
    def git(*args):
        p = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, env=env, timeout=30)
        require(p.returncode == 0, 'exact-main-read-failed'); return p.stdout.decode().strip()
    require(git('branch', '--show-current') == 'main' and not git('status', '--porcelain'), 'clean-main-required')
    require(git('rev-parse', 'HEAD') == git('rev-parse', 'origin/main') == expected, 'main-drift')
    git('merge-base', '--is-ancestor', baseline, expected)
    require(git('ls-remote', 'origin', 'refs/heads/main') == expected + '\trefs/heads/main', 'remote-main-drift')

def environment_check(phase, env):
    require(env.get('AWS_ENVIRONMENT') == 'aws-test', 'aws-test-only')
    require(re.fullmatch('[0-9]{12}', env.get('EXPECTED_AWS_ACCOUNT_ID', '')), 'private-account-required')
    allowed = {'CONFIRM_AWS_TEST_RESIDUAL_COST_AUDIT_PREFLIGHT'}
    require(env.get('CONFIRM_AWS_TEST_RESIDUAL_COST_AUDIT_PREFLIGHT') == PRE_CONFIRM, 'preflight-confirmation-required')
    if phase == 'execute':
        allowed.add('CONFIRM_AWS_TEST_RESIDUAL_COST_AUDIT_EXECUTION')
        require(env.get('CONFIRM_AWS_TEST_RESIDUAL_COST_AUDIT_EXECUTION') == EXEC_CONFIRM, 'separate-execution-confirmation-required')
    require(not any(k.startswith('CONFIRM_') and k not in allowed for k in env), 'unrelated-confirmation-rejected')
    require(not any(k.startswith(('AWS_ENDPOINT_URL', 'TF_CLI_ARGS', 'TF_VAR_')) or k in ('AWS_TEST_APPLY_MODE', 'TF_WORKSPACE') for k in env), 'endpoint-or-terraform-override-rejected')

def empty_state(c):
    path = checked_path(ROOT / STATE, 0o600, persistent=False)
    raw = path.read_bytes(); require(digest(raw) == c['finalStateSha256'], 'state-digest-drift')
    value = json_data(raw)
    require(value.get('version') == 4 and value.get('resources') == [], 'strict-empty-state-required')
    return digest(raw)

def load_inputs(args, c):
    inputs = private_json(args.inputs, c['privateInputsSha256'])
    record = private_json(args.runtime_record, c['runtimeRecordSha256'])
    result = private_json(args.final_result, c['finalResultSha256'])
    receipt = private_json(args.eks_complete, c['eksCompleteSha256'])
    evidence = json_data((ROOT / c['teardownEvidencePath']).read_bytes())
    require(result == evidence['finalResultRestated'], 'final-result-content-binding')
    require(receipt['main'] == c['teardownControlPlaneCommit'] and receipt['window_contract_sha256'] == c['historicalWindowSha256'] and receipt['runtime_record_sha256'] == c['runtimeRecordSha256'] and receipt['state_sha256'] == c['intermediateStateSha256'], 'eks-receipt-binding')
    account = os.environ['EXPECTED_AWS_ACCOUNT_ID']
    require(inputs.get('aws_account_id') == record.get('account') == account, 'private-account-binding')
    require(len(record.get('managed', {})) == 90, 'captured-managed-inventory-count')
    outputs = record['outputs']
    require(re.fullmatch('vpc-[0-9a-f]+', outputs['vpc_id']), 'captured-vpc-format')
    require(outputs['cnpg_backup_bucket_name'] == PROJECT + '-test-' + account + '-us-east-1-cnpg', 'captured-bucket-scope')
    require(outputs['external_secrets_secret_name'] == PROJECT + '-test/demo-api/postgresql', 'captured-container-scope')
    require(re.fullmatch('arn:aws:secretsmanager:us-east-1:' + account + ':secret:' + re.escape(outputs['external_secrets_secret_name']) + '-[A-Za-z0-9]+', outputs['external_secrets_secret_arn']), 'captured-container-arn')
    require(re.fullmatch('sg-[0-9a-f]+', record['cluster_sg']), 'captured-group-format')
    require(len(record['instance_ids']) == 8 and len(set(record['instance_ids'])) == 8 and all(re.fullmatch('i-[0-9a-f]+', x) for x in record['instance_ids']), 'captured-compute-format')
    require(len(record['disk_ids']) == 13 and len(set(record['disk_ids'])) == 13 and all(re.fullmatch('vol-[0-9a-f]+', x) for x in record['disk_ids']), 'captured-volume-format')
    return record

def command(service, operation, params):
    require(operation in OPS.get(service, set()), 'non-read-only-command-rejected')
    require(not any(x in params for x in ('--endpoint-url', '--no-sign-request', '--no-paginate', '--max-items', '--starting-token', '--query', '--region', '--output')), 'command-override-rejected')
    return ['aws', service, operation, *params, '--region', 'us-east-1', '--output', 'json', '--no-cli-pager', '--no-cli-auto-prompt', '--cli-connect-timeout', '10', '--cli-read-timeout', '60']

def transport(cmd, stdout, stderr, timeout, env):
    with stdout.open('xb') as out, stderr.open('xb') as err:
        proc = subprocess.Popen(cmd, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                cwd=ROOT, env=env, start_new_session=True)
        try: return proc.wait(timeout=timeout)
        except BaseException:
            try: os.killpg(proc.pid, signal.SIGTERM); proc.wait(timeout=1)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            proc.wait(); raise

def complete(value):
    require(not any(value.get(k) for k in ('NextToken', 'nextToken', 'NextMarker', 'Marker', 'NextContinuationToken', 'PaginationToken', 'IsTruncated')), 'incomplete-pagination-rejected')
    return value

def array(value, key, objects=True):
    require(isinstance(value, dict) and key in value and isinstance(value[key], list), 'missing-response-list')
    items = value[key]
    require(all(isinstance(x, dict if objects else str) for x in items), 'response-list-schema')
    return items

def none(items, label):
    if items: raise Residual(label)

def absence_error(stderr, stdout, operation, allowed):
    """Accept one exact CLI error line and optional zero-retry annotation only."""
    if stdout.strip(): return False
    lines = [line for line in stderr.splitlines() if line.strip()]
    if len(lines) != 1: return False
    match = re.fullmatch(
        rb'An error occurred \(([A-Za-z0-9_.-]+)\) when calling the '
        rb'([A-Za-z0-9]+) operation(?: \(reached max retries: 0\))?:[^\r\n]*',
        lines[0])
    return bool(match and match[1].decode() in allowed and
                match[2].decode().lower() == operation.replace('-', ''))

class Runner:
    def __init__(self, output, c, stop, backend=transport, clock=now, state_check=empty_state):
        self.output, self.c, self.stop = output, c, stop
        self.backend, self.clock, self.state_check = backend, clock, state_check
        self.sequence, self.stage, self.manifest = 0, 'local-inputs', []
        self.full_started = False
        self.input_check = lambda: None
        self.cache = {}; self.absent_arns = set(); self.compute_verified = False; self.terminal_fleets = 0; self.stale_tagged = 0
        self.environment = os.environ.copy()
        self.environment.update(AWS_PAGER='', AWS_CLI_AUTO_PROMPT='off', AWS_MAX_ATTEMPTS='1', AWS_RETRY_MODE='standard')
    def check(self):
        require((self.stop - self.clock()).total_seconds() > 1, 'audit-window-expired')
        self.state_check(self.c); self.input_check()
    def invoke(self, label, service, operation, params=(), absent=(), cached=False):
        self.check(); self.stage = label
        cmd = command(service, operation, list(params)); key = tuple(cmd)
        if cached and key in self.cache: return self.cache[key]
        self.sequence += 1; prefix = f'{self.sequence:04d}-{label}'
        out, err = self.output / (prefix + '.stdout'), self.output / (prefix + '.stderr')
        rc = None
        try:
            rc = self.backend(cmd, out, err, min(120, (self.stop - self.clock()).total_seconds()), self.environment)
        finally:
            entry = {'stage': label, 'exit_code': rc}
            for name, path in (('stdout', out), ('stderr', err)):
                if path.exists():
                    require(stat.S_IMODE(path.stat().st_mode) == 0o600, 'raw-output-private-mode')
                    entry[name + '_sha256'] = digest(path.read_bytes()); entry[name + '_bytes'] = path.stat().st_size
            self.manifest.append(entry)
        self.check()
        if rc:
            require(absence_error(err.read_bytes(), out.read_bytes(), operation, absent), 'aws-error-not-absence')
            value = None
        else: value = complete(json_data(out.read_bytes()))
        if cached: self.cache[key] = value
        return value
    def save_manifest(self):
        return write(self.output / 'raw-output-manifest.json', self.manifest)

def identity(r, account):
    value = r.invoke('sts-account', 'sts', 'get-caller-identity')
    require(value.get('Account') == account and isinstance(value.get('Arn'), str) and re.fullmatch('arn:aws:(?:iam|sts)::' + account + ':.+', value['Arn']), 'live-account-mismatch')

def preflight_cloud(r, record):
    identity(r, record['account'])
    clusters = array(r.invoke('eks-inventory', 'eks', 'list-clusters'), 'clusters', False)
    none([x for x in clusters if x in {PROJECT + '-dev', CLUSTER, PROJECT + '-prod'}], 'active-rehearsal-cluster')
    outputs = record['outputs']
    bucket = r.invoke('backup-bucket', 's3api', 'list-object-versions', ['--bucket', outputs['cnpg_backup_bucket_name'], '--expected-bucket-owner', record['account']], ('NoSuchBucket',), cached=True)
    require(bucket is None, 'backup-bucket-not-absent')
    container = r.invoke('credential-container', 'secretsmanager', 'describe-secret', ['--secret-id', outputs['external_secrets_secret_arn']], ('ResourceNotFoundException',), cached=True)
    tombstone = container is not None
    if tombstone:
        require(container.get('ARN') == outputs['external_secrets_secret_arn'] and container.get('Name') == outputs['external_secrets_secret_name'], 'container-response-scope')
        require(isinstance(container.get('DeletedDate'), (str, int, float)) and not isinstance(container['DeletedDate'], bool) and bool(container['DeletedDate']), 'live-container-remains')
    return {'account_verified': True, 'account_id_emitted': False,
            'active_rehearsal_environment_count': 0, 'backup_bucket_absent': True,
            'credential_container_absent_or_tombstone': True, 'credential_tombstone_present': tombstone}

def base_result(args, c, cloud):
    return {'control_plane_commit': args.expected_main, 'target_environment': 'aws-test',
            'aws_region': 'us-east-1', 'teardown_evidence_sha256': c['teardownEvidenceSha256'],
            'terraform_state_sha256': c['finalStateSha256'], 'terraform_state_resource_block_count': 0,
            'terraform_state_resource_instance_count': 0, 'private_inputs_sha256': c['privateInputsSha256'],
            'runtime_record_sha256': c['runtimeRecordSha256'], **cloud,
            'mutation_executed': False, 'terraform_command_executed': False,
            'secret_value_read': False, 'automatic_retry_performed': False,
            'private_resource_identity_emitted': False}

def stable(value):
    return {k: v for k, v in value.items() if k not in ('observed_at_utc', 'raw_output_manifest_sha256')}

def check_preflight(args, c, fresh, clock=now):
    value = private_json(args.preflight_result, args.expected_preflight_sha256)
    require(value.get('status') == 'aws-test-residual-cost-audit-preflight-ready-for-separate-approval', 'reviewed-preflight-status')
    require(stable(value) == stable(fresh), 'immediate-preflight-drift')
    age = (clock() - utc(value['observed_at_utc'])).total_seconds()
    require(0 <= age <= c['preflightTtlSeconds'], 'reviewed-preflight-expired')
    return value

def window(args, c, clock=now):
    start, end, current = utc(args.start_utc), utc(args.end_utc), clock()
    require(0 < (end-start).total_seconds() <= c['maximumWindowSeconds'], 'audit-window-duration')
    require(start <= current and (end-current).total_seconds() >= c['minimumStartRemainingSeconds'], 'audit-start-window-expired')
    return end

def instances(value):
    return [x for res in array(value, 'Reservations') for x in array(res, 'Instances')]

def ec2_absence(r, label, operation, params, key, codes=(), live=lambda x: True):
    value = r.invoke(label, 'ec2', operation, params, codes, cached=True)
    if value is not None: none([x for x in (instances(value) if key == 'Reservations' else array(value, key)) if live(x)], label)

def native_sweep(r, record):
    # Native APIs are authoritative for their tagged identities; stale tag-index rows
    # are never ignored until an exact ID lookup has also passed.
    specs = [('describe-instances', 'Reservations', lambda x: x['State']['Name'] != 'terminated'),
             ('describe-volumes', 'Volumes', lambda x: True),
             ('describe-network-interfaces', 'NetworkInterfaces', lambda x: True),
             ('describe-nat-gateways', 'NatGateways', lambda x: x['State'] != 'deleted'),
             ('describe-addresses', 'Addresses', lambda x: True),
             ('describe-vpcs', 'Vpcs', lambda x: True),
             ('describe-snapshots', 'Snapshots', lambda x: True)]
    filters = [['Name=tag:Project,Values=' + PROJECT, 'Name=tag:Environment,Values=test'],
               ['Name=tag:kubernetes.io/cluster/' + CLUSTER + ',Values=owned,shared']]
    for selector, tags in enumerate(filters):
        for op, key, live in specs:
            params = ['--filter' if op == 'describe-nat-gateways' else '--filters', *tags]
            if op == 'describe-snapshots': params += ['--owner-ids', record['account']]
            ec2_absence(r, f'native-{selector}-{op}', op, params, key, live=live)
    ec2_absence(r, 'captured-vpc', 'describe-vpcs', ['--vpc-ids', record['outputs']['vpc_id']], 'Vpcs', ('InvalidVpcID.NotFound',))
    for index, iid in enumerate(record['instance_ids']):
        ec2_absence(r, f'captured-instance-{index}', 'describe-instances', ['--instance-ids', iid], 'Reservations', ('InvalidInstanceID.NotFound',), lambda x: x['State']['Name'] != 'terminated')
    for index, vid in enumerate(record['disk_ids']):
        ec2_absence(r, f'captured-volume-{index}', 'describe-volumes', ['--volume-ids', vid], 'Volumes', ('InvalidVolume.NotFound',))
    ec2_absence(r, 'captured-security-group', 'describe-security-groups', ['--group-ids', record['cluster_sg']], 'SecurityGroups', ('InvalidGroup.NotFound',))
    for operation, key in (('describe-load-balancers', 'LoadBalancers'), ('describe-target-groups', 'TargetGroups')):
        none([x for x in array(r.invoke('native-' + operation, 'elbv2', operation), key) if x['VpcId'] == record['outputs']['vpc_id']], operation)
    certs = array(r.invoke('certificate-inventory', 'acm', 'list-certificates', ['--includes', json.dumps({'keyTypes': ['RSA_1024','RSA_2048','RSA_3072','RSA_4096','EC_prime256v1','EC_secp384r1','EC_secp521r1']})]), 'CertificateSummaryList')
    none([x for x in certs if x['DomainName'].rstrip('.') == HOST.rstrip('.')], 'test-certificate')
    logs = array(r.invoke('test-log-inventory', 'logs', 'describe-log-groups', ['--log-group-name-prefix', '/aws/eks/' + CLUSTER + '/cluster']), 'logGroups')
    none([x for x in logs if x['logGroupName'] == '/aws/eks/' + CLUSTER + '/cluster'], 'test-log-group')
    dns = array(r.invoke('test-dns-inventory', 'route53', 'list-resource-record-sets', ['--hosted-zone-id', record['zone']], cached=True), 'ResourceRecordSets')
    none([x for x in dns if x['Name'].rstrip('.') + '.' == HOST and x['Type'] in ('A', 'AAAA', 'CNAME')], 'test-dns')

def captured_resource(r, kind, attrs, record, index):
    label = f'captured-managed-{index}'
    invoke = lambda service, op, params, absent=(): r.invoke(label, service, op, params, absent, cached=True)
    # Network dependencies cannot remain after the captured VPC is absent.
    contained = {'aws_vpc', 'aws_subnet', 'aws_route_table', 'aws_route_table_association', 'aws_route'}
    if kind in contained: return
    if kind.startswith('aws_s3_bucket'):
        require(attrs.get('bucket', attrs.get('id')) == record['outputs']['cnpg_backup_bucket_name'], 'captured-bucket-config-scope'); return
    if kind == 'aws_secretsmanager_secret':
        require(attrs['arn'] == record['outputs']['external_secrets_secret_arn'], 'captured-container-state-scope'); return
    if kind in ('aws_eks_cluster', 'aws_eks_addon', 'aws_eks_node_group', 'aws_eks_access_entry'):
        require(attrs.get('cluster_name', attrs.get('name')) == CLUSTER, 'captured-eks-scope'); return
    if kind in ('aws_iam_role', 'aws_iam_role_policy', 'aws_iam_role_policy_attachment'):
        value = invoke('iam', 'get-role', ['--role-name', attrs['name'] if kind == 'aws_iam_role' else attrs['role']], ('NoSuchEntity',))
        require(value is None, 'captured-role-remains')
    elif kind == 'aws_iam_policy':
        require(invoke('iam','get-policy',['--policy-arn',attrs['arn']],('NoSuchEntity',)) is None, 'captured-policy-remains')
    elif kind == 'aws_iam_openid_connect_provider':
        require(invoke('iam','get-open-id-connect-provider',['--open-id-connect-provider-arn',attrs['arn']],('NoSuchEntity',)) is None, 'captured-oidc-remains')
    elif kind in ('aws_cloudwatch_event_rule','aws_cloudwatch_event_target'):
        params = ['--name' if kind.endswith('_rule') else '--rule', attrs['name'] if kind.endswith('_rule') else attrs['rule']]
        if attrs.get('event_bus_name'): params += ['--event-bus-name',attrs['event_bus_name']]
        value = invoke('events','describe-rule' if kind.endswith('_rule') else 'list-targets-by-rule',params,('ResourceNotFoundException',))
        if kind.endswith('_rule'): require(value is None, 'captured-event-rule-remains')
        elif value is not None: none(array(value,'Targets'),'captured-event-target-remains')
    elif kind in ('aws_sqs_queue','aws_sqs_queue_policy'):
        require(invoke('sqs','get-queue-attributes',['--queue-url',attrs.get('url', attrs.get('queue_url',attrs['id'])),'--attribute-names','QueueArn'],('AWS.SimpleQueueService.NonExistentQueue','QueueDoesNotExist')) is None, 'captured-queue-remains')
    elif kind == 'aws_fis_experiment_template':
        require(invoke('fis','get-experiment-template',['--id',attrs['id']],('ResourceNotFoundException',)) is None, 'captured-fis-template-remains')
    elif kind in ('aws_acm_certificate','aws_acm_certificate_validation'):
        require(invoke('acm','describe-certificate',['--certificate-arn',attrs['arn'] if kind == 'aws_acm_certificate' else attrs['certificate_arn']],('ResourceNotFoundException',)) is None, 'captured-certificate-remains')
    elif kind == 'aws_route53_record':
        rows = array(invoke('route53','list-resource-record-sets',['--hosted-zone-id',attrs['zone_id']]), 'ResourceRecordSets')
        none([x for x in rows if x['Name'].rstrip('.') == attrs['name'].rstrip('.') and x['Type'] == attrs['type']], 'captured-dns-remains')
    elif kind == 'aws_cloudwatch_log_group':
        rows = array(invoke('logs','describe-log-groups',['--log-group-name-prefix',attrs['name']]),'logGroups')
        none([x for x in rows if x['logGroupName'] == attrs['name']], 'captured-log-group-remains')
    elif kind == 'aws_eip':
        ec2_absence(r,label,'describe-addresses',['--allocation-ids',attrs.get('allocation_id',attrs['id'])],'Addresses',('InvalidAllocationID.NotFound',))
    elif kind == 'aws_internet_gateway':
        ec2_absence(r,label,'describe-internet-gateways',['--internet-gateway-ids',attrs['id']],'InternetGateways',('InvalidInternetGatewayID.NotFound',))
    elif kind == 'aws_nat_gateway':
        ec2_absence(r,label,'describe-nat-gateways',['--nat-gateway-ids',attrs['id']],'NatGateways',('NatGatewayNotFound',),lambda x:x['State']!='deleted')
    elif kind == 'aws_ec2_tag':
        require(re.fullmatch('sg-[0-9a-f]+',attrs['resource_id']), 'unknown-captured-ec2-tag-resource')
        ec2_absence(r,label,'describe-security-groups',['--group-ids',attrs['resource_id']],'SecurityGroups',('InvalidGroup.NotFound',))
    else: raise Stop('unclassified-managed-resource-type')

def tagged_record(r, arn, index, record):
    label = f'tag-classification-{index}'
    require(isinstance(arn,str), 'tagged-arn-format')
    if arn == 'arn:aws:s3:::' + record['outputs']['cnpg_backup_bucket_name'] and arn in r.absent_arns:
        r.stale_tagged += 1; return
    require(re.fullmatch('arn:aws:[^:]+:[^:]*:' + record['account'] + ':.+',arn), 'tagged-arn-account-or-partition')
    if arn in r.absent_arns: r.stale_tagged += 1; return
    fleet = re.fullmatch(r'arn:aws:ec2:us-east-1:[0-9]+:fleet/(fleet-[a-z0-9-]+)',arn)
    if fleet:
        value = r.invoke(label,'ec2','describe-fleets',['--fleet-ids',fleet[1]],('InvalidFleetId.NotFound',))
        if value is not None:
            rows=array(value,'Fleets'); require(len(rows)==1 and rows[0]['FleetId']==fleet[1] and rows[0]['FleetState'] in ('deleted','deleted_terminating') and r.compute_verified,'nonterminal-fleet-record')
        r.terminal_fleets += 1; return
    ec2 = re.fullmatch(r'arn:aws:ec2:us-east-1:[0-9]+:(instance|volume|network-interface|natgateway|elastic-ip|vpc|security-group)/([a-z0-9-]+)',arn)
    if ec2:
        specs={'instance':('describe-instances','--instance-ids','Reservations',('InvalidInstanceID.NotFound',)),
               'volume':('describe-volumes','--volume-ids','Volumes',('InvalidVolume.NotFound',)),
               'network-interface':('describe-network-interfaces','--network-interface-ids','NetworkInterfaces',('InvalidNetworkInterfaceID.NotFound',)),
               'natgateway':('describe-nat-gateways','--nat-gateway-ids','NatGateways',('NatGatewayNotFound',)),
               'elastic-ip':('describe-addresses','--allocation-ids','Addresses',('InvalidAllocationID.NotFound',)),
               'vpc':('describe-vpcs','--vpc-ids','Vpcs',('InvalidVpcID.NotFound',)),
               'security-group':('describe-security-groups','--group-ids','SecurityGroups',('InvalidGroup.NotFound',))}
        op,flag,key,codes=specs[ec2[1]]
        live=(lambda x:x['State']['Name']!='terminated') if ec2[1]=='instance' else ((lambda x:x['State']!='deleted') if ec2[1]=='natgateway' else (lambda x:True))
        ec2_absence(r,label,op,[flag,ec2[2]],key,codes,live); r.stale_tagged+=1; return
    if arn == record['outputs']['external_secrets_secret_arn']: return # exact metadata checked above
    raise Residual('unclassified-tagged-resource-remains')

def full_audit(r, record):
    r.full_started = True
    native_sweep(r, record)
    r.compute_verified = True
    for index,(address,attrs) in enumerate(sorted(record['managed'].items())):
        require(isinstance(attrs,dict) and attrs.get('id'), 'idless-captured-managed-resource')
        match=re.search(r'(?:^|\.)(aws_[a-z0-9_]+)\.[A-Za-z_][A-Za-z0-9_]*(?:\[.*\])?$',address)
        require(match is not None, 'unclassified-managed-address')
        kind=match[1]
        captured_resource(r,kind,attrs,record,index)
        for value in (attrs.get('arn'),attrs.get('certificate_arn')):
            if kind != 'aws_secretsmanager_secret' and isinstance(value,str) and value.startswith('arn:aws:'): r.absent_arns.add(value)
    seen=set()
    for index,tags in enumerate(([f'Key=Project,Values={PROJECT}','Key=Environment,Values=test'],[f'Key=elbv2.k8s.aws/cluster,Values={CLUSTER}'])):
        rows=array(r.invoke(f'tagged-sweep-{index}','resourcegroupstaggingapi','get-resources',['--tag-filters',*tags]),'ResourceTagMappingList')
        for row in rows:
            arn=row['ResourceARN']
            if arn not in seen: tagged_record(r,arn,len(seen),record); seen.add(arn)
    return {'audit_scope':'captured aws-test resources and test/cluster tagged us-east-1 resources; captured global IAM and DNS',
            'captured_managed_resource_count':len(record['managed']),
            'terminal_or_expired_fleet_record_count':r.terminal_fleets,
            'accepted_stale_tagged_record_count':r.stale_tagged,
            'account_wide_billing_audit':False,'inventory_is_atomic':False,
            'untracked_untagged_resource_inventory_exhaustive':False}

def execute_phase(args, c, output, clock=now, backend=transport, state_check=empty_state, git_check=main_check, input_loader=load_inputs):
    environment_check(args.phase, os.environ)
    git_check(args.expected_main,c['implementationBaselineCommit']); state_check(c)
    record=input_loader(args,c)
    stop = clock()+timedelta(seconds=c['maximumPreflightSeconds']) if args.phase=='preflight' else window(args,c,clock)
    r=Runner(output,c,stop,backend,clock,state_check)
    def bound_check():
        pairs=[(args.inputs,c['privateInputsSha256']), (args.runtime_record,c['runtimeRecordSha256']),
               (args.final_result,c['finalResultSha256']), (args.eks_complete,c['eksCompleteSha256'])]
        if args.phase!='preflight': pairs.append((args.preflight_result,args.expected_preflight_sha256))
        if args.phase=='execute': pairs.append((args.verify_result,args.expected_verify_sha256))
        for path,expected in pairs:
            if path is not None: private_json(path,expected)
    r.input_check=bound_check
    authorized=False; attempted=False
    try:
        reviewed_verify=None
        if args.phase=='execute':
            reviewed_verify=private_json(args.verify_result,args.expected_verify_sha256)
            require(reviewed_verify.get('status')=='aws-test-residual-cost-audit-execution-inputs-verified' and reviewed_verify.get('execution_authorized') is False,'reviewed-verify-status')
            require(reviewed_verify['control_plane_commit']==args.expected_main and reviewed_verify['reviewed_preflight_sha256']==args.expected_preflight_sha256 and reviewed_verify['start_utc']==args.start_utc and reviewed_verify['end_utc']==args.end_utc,'reviewed-verify-bindings')
            require(utc(reviewed_verify['verified_at_utc'])<=clock()<utc(reviewed_verify['verify_expires_at_utc']),'reviewed-verify-expired')
            require(utc(reviewed_verify['verify_expires_at_utc']) == min(stop, utc(reviewed_verify['verified_at_utc']) + timedelta(seconds=c['verifyTtlSeconds'])), 'verify-ttl-binding')
            authorized=True
            marker=Path(args.preflight_result).absolute().parent/'residual-audit-attempt.json'
            checked_path(marker.parent,0o700)
            write(marker,{'verify_sha256':args.expected_verify_sha256,'preflight_sha256':args.expected_preflight_sha256,'control_plane_commit':args.expected_main,'attempted_at_utc':stamp(clock()),'automatic_retry_performed':False})
            attempted=True
        cloud=preflight_cloud(r,record)
        fresh={**base_result(args,c,cloud),'status':'aws-test-residual-cost-audit-preflight-ready-for-separate-approval',
               'observed_at_utc':stamp(clock()),'execution_authorized':False,'full_audit_executed':False,
               'next_action':'review-preflight-before-separate-read-only-audit-approval'}
        if args.phase=='preflight': result=fresh
        else:
            check_preflight(args,c,fresh,clock)
            common={**base_result(args,c,cloud),'reviewed_preflight_sha256':args.expected_preflight_sha256,'immediate_preflight_matched':True,'start_utc':args.start_utc,'end_utc':args.end_utc}
            if args.phase=='verify':
                result={**common,'status':'aws-test-residual-cost-audit-execution-inputs-verified','verified_at_utc':stamp(clock()),'verify_expires_at_utc':stamp(min(stop,clock()+timedelta(seconds=c['verifyTtlSeconds']))),'execution_authorized':False,'full_audit_executed':False,'next_action':'obtain-separate-aws-test-residual-cost-audit-approval'}
            else:
                report=full_audit(r,record)
                result={**common,**report,'status':'aws-test-residual-cost-audit-complete','completed_at_utc':stamp(clock()),'execution_authorized':True,'full_audit_executed':True,'audit_passed':True,'residual_identity_found':False,'continuing_cost_identity_found':False,'reviewed_verify_sha256':args.expected_verify_sha256,'next_action':'record-aws-test-residual-cost-audit-execution-evidence'}
        r.check();git_check(args.expected_main,c['implementationBaselineCommit']);r.check()
        result['raw_output_manifest_sha256']=r.save_manifest();write(output/'result.json',result)
        return result
    except BaseException as exc:
        failure={'status':'aws-test-residual-cost-audit-stopped','stage':r.stage,'execution_authorized':authorized,
                 'audit_attempt_consumed':attempted,'full_audit_executed':r.full_started,
                 'audit_passed':False,'residual_identity_found':True if isinstance(exc,Residual) else None,
                 'continuing_cost_identity_found':None,'mutation_executed':False,'terraform_command_executed':False,
                 'secret_value_read':False,'automatic_retry_performed':False,'preserve_state_and_private_evidence':True,
                 'next_action':'review-private-output-and-obtain-new-approval-before-another-attempt'}
        if not (output/'raw-output-manifest.json').exists():failure['raw_output_manifest_sha256']=r.save_manifest()
        if not (output/'failure.json').exists():write(output/'failure.json',failure)
        return failure

def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=('preflight','verify','execute'))
    parser.add_argument('--expected-main',required=True)
    for flag in ('inputs','runtime-record','final-result','eks-complete','private-output-directory'):
        parser.add_argument('--'+flag,required=True,type=Path)
    for flag in ('preflight-result','verify-result'):parser.add_argument('--'+flag,type=Path)
    for flag in ('expected-preflight-sha256','expected-verify-sha256','start-utc','end-utc'):parser.add_argument('--'+flag)
    args=parser.parse_args();output=None
    try:
        if args.phase!='preflight':
            require(args.preflight_result and args.start_utc and args.end_utc and re.fullmatch('[0-9a-f]{64}',args.expected_preflight_sha256 or ''),'verify-inputs-required')
        if args.phase=='execute':require(args.verify_result and re.fullmatch('[0-9a-f]{64}',args.expected_verify_sha256 or ''),'reviewed-verify-required')
        output=new_output(args.private_output_directory)
        result=execute_phase(args,source_checks(),output)
    except BaseException:
        result={'status':'aws-test-residual-cost-audit-stopped','stage':'local-inputs','full_audit_executed':False,'mutation_executed':False,'terraform_command_executed':False,'secret_value_read':False,'automatic_retry_performed':False,'preserve_state_and_private_evidence':True}
        if output and not (output/'failure.json').exists():write(output/'failure.json',result)
    print(json.dumps(result,sort_keys=True))
    failed=result['status']=='aws-test-residual-cost-audit-stopped'
    if failed:print('STOP: read-only audit stopped; preserve evidence; do not retry or repair automatically.',file=sys.stderr)
    return int(failed)
if __name__=='__main__':raise SystemExit(main())

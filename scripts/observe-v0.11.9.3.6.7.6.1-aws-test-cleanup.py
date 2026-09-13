#!/usr/bin/env python3
"""Read-only renewed-window inventory; historical deployment evidence stays unchanged."""
import argparse
from datetime import timedelta
import importlib.util
import json
import os
from pathlib import Path
import sys

import aws_test_immutable_root as h

p = h.p
CONTRACT = 'delivery/contracts/v0.11.9.3.6.7.5.2.1-aws-test-root-deployment-execution-evidence.json'
spec = importlib.util.spec_from_file_location('root_executor', h.ROOT / 'scripts/execute-v0.11.9.3.6.7.5.2-aws-test-root-deployment.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
WINDOW_CONTRACT = 'delivery/contracts/v0.11.9.3.6.7.6.1-aws-test-cleanup-window-renewal.json'
AWS = ['aws', '--region', 'us-east-1', '--output', 'json']
ALLOWED_AWS = {('sts', 'get-caller-identity'), ('eks', 'list-clusters'), ('eks', 'describe-cluster'),
               ('ec2', 'describe-instances'), ('ec2', 'describe-volumes'), ('elbv2', 'describe-load-balancers'),
               ('elbv2', 'describe-tags'), ('route53', 'list-hosted-zones-by-name'),
               ('route53', 'list-resource-record-sets'), ('secretsmanager', 'describe-secret'),
               ('s3api', 'list-object-versions')}


def source_checks(root=h.ROOT):
    h.source_checks(root)
    prior=p.load(root/'delivery/contracts/v0.11.9.3.6.7.6-aws-test-guarded-teardown.json')
    for item in prior['reviewedFiles']:
        p.require(p.digest(root/item['path'])==item['sha256'],'historical-teardown-source-drift')
    c = p.load(root / CONTRACT)
    for item in c['reviewedFiles']:
        p.require(p.digest(root / item['path']) == item['sha256'], 'cleanup-source-drift')
    window=p.load(root/WINDOW_CONTRACT)
    for item in window['reviewedFiles']:
        p.require(p.digest(root/item['path'])==item['sha256'],'renewal-source-drift')
    c=dict(c);c['cleanupPreparation']=dict(c['cleanupPreparation'])
    c['cleanupPreparation']['cleanupCompleteByUtc']=window['cleanupCompleteByUtc']
    c['cleanupPreparation']['minimumRemainingCleanupSeconds']=5400
    return c


class Observer(e.Runner):
    def call(self, label, command, payload=None, mutation=False, optional=False):
        p.require(not mutation and payload is None, 'observation-cannot-mutate')
        allowed = command[:len(AWS)] == AWS and tuple(command[len(AWS):len(AWS)+2]) in ALLOWED_AWS
        if command[:len(self.kube)] == self.kube:
            args = command[len(self.kube):]
            allowed = bool(args) and (args[0] == 'get' or args[:2] == ['config', 'view'])
        p.require(allowed, 'command-not-in-read-only-allowlist')
        return super().call(label, command, optional=optional)


def deadline(c, at):
    end = p.utc(c['cleanupPreparation']['cleanupCompleteByUtc'])
    latest = end - timedelta(seconds=c['cleanupPreparation']['minimumRemainingCleanupSeconds'])
    p.require(at < latest, 'insufficient-time-for-cleanup-inventory-and-execution')
    return min(at + timedelta(seconds=600), latest)


def reviewed_bundle(bundle, c):
    p.private(bundle, 0o700); p.persistent(bundle)
    plan = h.read_private(bundle / 'private-root-plan.json')
    p.require(p.digest(bundle / 'private-root-plan.json') == c['artifacts']['privatePlan']['sha256'], 'historical-plan-bytes')
    for name, key in (('root-application.json', 'root_manifest_sha256'), ('application-source-map.json', 'source_map_sha256')):
        h.read_private(bundle / name)
        p.require(p.digest(bundle / name) == plan[key], 'historical-manifest-bytes')
    p.require(plan['expected_main'] == c['implementationBaselineCommit'], 'historical-deployment-main')
    return p.load(bundle / 'root-application.json'), p.load(bundle / 'application-source-map.json')


def deployment_proof(path, c):
    value = h.read_private(path)
    p.require(p.digest(path) == c['artifacts']['executionResult']['sha256'] and value == c['executionSummary'], 'deployment-proof')
    return value


def app_inventory(items, root, source_map, deployed):
    expected = {x['name']: x for x in source_map}
    apps = {x['metadata']['name']: x for x in items}
    p.require(len(apps) == len(items) and set(apps) == set(expected) | {p.APP}, 'unexpected-application-inventory')
    p.require(apps[p.APP]['spec'] == root['spec'], 'deployed-root-drift')
    for name, item in expected.items():
        app = apps[name]
        p.require(app['spec']['source'] == item['source'] and app['spec']['destination'] == item['destination'], 'deployed-child-drift')
        if app['spec']['source']['repoURL'] == p.REPO:
            p.require(app['spec']['source']['targetRevision'] == deployed, 'deployed-child-revision')
    active = sum(x.get('status', {}).get('operationState', {}).get('phase') in ('Running', 'Terminating') for x in items)
    return {'application_count': len(items), 'active_application_operation_count': active,
            'application_health_counts': {health: sum(x.get('status', {}).get('health', {}).get('status') == health for x in items)
                for health in sorted({x.get('status', {}).get('health', {}).get('status', 'Unknown') for x in items})}}


def observe(args):
    c = source_checks()
    p.exact_main(args.expected_main,p.load(h.ROOT/WINDOW_CONTRACT)['implementationBaselineCommit'])
    h.assert_confirmations(os.environ, False)
    p.exact_main(args.expected_main, c['implementationBaselineCommit'])
    _, inputs, state = p.local_inputs(args.inputs, args.expected_main)
    h.read_private(args.inputs)
    outputs = {key: item['value'] for key, item in state['outputs'].items()}
    h.validate_outputs(outputs, inputs['aws_account_id'])
    deployment_proof(args.deployment_result, c)
    root, source_map = reviewed_bundle(args.bundle, c)
    stop = deadline(c, h.now())
    h.new_directory(args.output_directory)
    runner = Observer(args.output_directory, inputs, stop, p.digest(h.ROOT / p.STATE))
    try:
        identity = runner.call('identity', AWS + ['sts', 'get-caller-identity'])
        p.require(identity['Account'] == inputs['aws_account_id'], 'account-mismatch')
        inventory = runner.call('clusters', AWS + ['eks', 'list-clusters'])['clusters']
        p.require(set(inventory) & {p.CLUSTER, 'startup-devops-baseline-dev', 'startup-devops-baseline-prod'} == {p.CLUSTER}, 'rehearsal-inventory')
        cluster = runner.call('cluster', AWS + ['eks', 'describe-cluster', '--name', p.CLUSTER])['cluster']
        network = cluster['resourcesVpcConfig']
        p.require(cluster['status'] == 'ACTIVE' and network['vpcId'] == outputs['vpc_id'] and
                  network['endpointPublicAccess'] and network['endpointPrivateAccess'] and
                  network['publicAccessCidrs'] == [inputs['management_cidr']], 'eks-target-or-api-drift')
        config = runner.call('kubeconfig', runner.kube + ['config', 'view', '--minify', '-o', 'json'])
        p.kube_auth(config, cluster['endpoint'])
        runner.get('api-namespace', 'namespace', 'kube-system')
        apps = runner.get('applications', 'applications.argoproj.io', '', 'argocd')['items']
        summary = app_inventory(apps, root, source_map, c['implementationBaselineCommit'])
        for label, kind, namespace in (('nodes', 'nodes', None), ('nodepools', 'nodepools', None),
            ('nodeclaims', 'nodeclaims', None), ('nodeclasses', 'ec2nodeclasses', None),
            ('persistent-volumes', 'pv', None), ('database', 'clusters.postgresql.cnpg.io', 'data-platform')):
            value = runner.get(label, kind, '', namespace)
            summary[label.replace('-', '_') + '_count'] = len(value['items'])
        pvcs = runner.call('persistent-claims', runner.kube + ['get', 'pvc', '-A', '-o', 'json'])['items']
        summary['pvc_count'] = len(pvcs)
        allowed_namespaces = {x['destination'].get('namespace') for x in source_map}
        p.require(all(x['metadata']['namespace'] in allowed_namespaces for x in pvcs), 'unexpected-pvc-namespace')
        instances = runner.call('vpc-compute', AWS + ['ec2', 'describe-instances', '--filters', 'Name=vpc-id,Values=' + outputs['vpc_id']])
        live = [x for r in instances['Reservations'] for x in r['Instances'] if x['State']['Name'] not in ('terminated', 'shutting-down')]
        summary['compute_counts_by_type'] = {t: sum(x['InstanceType'] == t for x in live) for t in sorted({x['InstanceType'] for x in live})}
        if live:
            volumes = runner.call('attached-disks', AWS + ['ec2', 'describe-volumes', '--filters', 'Name=attachment.instance-id,Values=' + ','.join(x['InstanceId'] for x in live)])['Volumes']
            summary['attached_volume_count'] = len(volumes)
            summary['attached_volume_total_gib'] = sum(x['Size'] for x in volumes)
        else:
            summary.update(attached_volume_count=0, attached_volume_total_gib=0)
        summary['volume_inventory_exhaustive'] = False
        lbs = runner.call('load-balancers', AWS + ['elbv2', 'describe-load-balancers'])['LoadBalancers']
        target_lbs = [x for x in lbs if x['VpcId'] == outputs['vpc_id']]
        p.require(len(target_lbs) == 1 and target_lbs[0]['Type'] == 'application' and target_lbs[0]['Scheme'] == 'internet-facing', 'unexpected-load-balancer-scope')
        tags = runner.call('load-balancer-tags', AWS + ['elbv2', 'describe-tags', '--resource-arns', target_lbs[0]['LoadBalancerArn']])
        tagmap = {x['Key']: x['Value'] for x in tags['TagDescriptions'][0]['Tags']}
        p.require(tagmap.get('elbv2.k8s.aws/cluster') == p.CLUSTER and tagmap.get('ingress.k8s.aws/stack') == 'startup-apps/demo-api', 'alb-owner')
        zones = runner.call('zones', AWS + ['route53', 'list-hosted-zones-by-name', '--dns-name', 'aureumstack.com'])['HostedZones']
        zone = [x for x in zones if x['Name'] == 'aureumstack.com.' and not x['Config']['PrivateZone']]
        p.require(len(zone) == 1, 'public-zone')
        records = runner.call('dns-records', AWS + ['route53', 'list-resource-record-sets', '--hosted-zone-id', zone[0]['Id']])['ResourceRecordSets']
        record = [x for x in records if x['Name'] == 'demo.test.aureumstack.com.' and x['Type'] in ('A', 'AAAA', 'CNAME')]
        lb = target_lbs[0]
        p.require(len(record) == 1 and record[0]['Type'] == 'A' and record[0]['AliasTarget']['DNSName'].rstrip('.') == 'dualstack.' + lb['DNSName'].rstrip('.') and
                  record[0]['AliasTarget']['HostedZoneId'] == lb['CanonicalHostedZoneId'], 'dns-alb-ownership')
        metadata = runner.call('credential-metadata', AWS + ['secretsmanager', 'describe-secret', '--secret-id', outputs['external_secrets_secret_arn']])
        p.require(metadata['ARN'] == outputs['external_secrets_secret_arn'] and not metadata.get('DeletedDate'), 'credential-container')
        objects = runner.call('backup-versions', AWS + ['s3api', 'list-object-versions', '--bucket', outputs['cnpg_backup_bucket_name'], '--expected-bucket-owner', inputs['aws_account_id']])
        summary.update(backup_version_count=len(objects.get('Versions', [])), backup_delete_marker_count=len(objects.get('DeleteMarkers', [])),
                       backup_recorded_version_bytes=sum(x['Size'] for x in objects.get('Versions', [])),
                       backup_inventory_is_atomic=False, secret_metadata_present=True,
                       current_credential_version_present=any('AWSCURRENT' in v for v in metadata.get('VersionIdsToStages', {}).values()))
        p.exact_main(args.expected_main, c['implementationBaselineCommit']); runner.check_time_and_state()
        summary.update(status='aws-test-cleanup-read-only-inventory-complete', observed_at_utc=p.timestamp(),
                       control_plane_commit=args.expected_main, deployed_control_plane_commit=c['implementationBaselineCommit'],
                       deployment_result_sha256=c['artifacts']['executionResult']['sha256'], terraform_state_sha256=p.digest(h.ROOT / p.STATE),
                       mutation_executed=False, terraform_command_executed=False, credential_value_read=False,
                       teardown_authorized=False, automatic_retry_performed=False, cleanup_complete_by_utc=c['cleanupPreparation']['cleanupCompleteByUtc'],
                       next_action='review-private-inventory-and-implement-guarded-teardown-before-separate-approval')
        p.write(args.output_directory / 'summary.json', summary)
        return summary
    except (Exception, KeyboardInterrupt):
        p.write(args.output_directory / 'failure.json', {'status': 'cleanup-inventory-stopped', 'stage': runner.stage,
            'mutation_executed': False, 'automatic_retry_performed': False, 'preserve_private_evidence': True})
        raise ValueError('cleanup-observation-stopped') from None


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--expected-main', required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--deployment-result', type=Path, required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(observe(args), indent=2, sort_keys=True))
        return 0
    except (Exception, KeyboardInterrupt):
        print('Stopped: preserve private inventory and state; no automatic retry or repair.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

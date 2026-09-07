#!/usr/bin/env python3
"""Approval-protected read-only prod observation. Live acceptance deferred to v0.11 end."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
sys.dont_write_bytecode = True
import aws_test_feature_common as c

spec = importlib.util.spec_from_file_location('observability_checks', Path(__file__).with_name('check-aws-test-observability-qualification.py'))
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
CLUSTER = 'startup-devops-baseline-prod'
OVERLAY = 'clusters/aws/overlays/prod'
ROOT_APP = 'startup-devops-aws-prod-root'
CONTRACT = c.ROOT / 'delivery/contracts/v0.11.8.3-prod-read-only-qualification.json'


def environment():
    env = c.environment()
    env.pop('TF_DIR', None)
    env.update(AWS_ENVIRONMENT='aws-prod', CLUSTER_NAME=CLUSTER)
    return env


def aws(*args):
    return c.run(['aws', '--region', c.REGION, *args], env=environment())


def release():
    value = c.yaml.safe_load((c.ROOT / 'apps/demo-api/helm/values/releases/aws-prod.yaml').read_text())
    image = value['image']
    c.require(bool(re.fullmatch(r'sha256:[0-9a-f]{64}', image.get('digest', ''))), 'Prod release must declare an exact digest.')
    version = value['release']['applicationVersion']
    c.require(isinstance(version, str) and bool(version.strip()), 'Prod application version missing.')
    return version, image['repository'] + '@' + image['digest']


def approve(args, image):
    # No subprocess, network or external environment probes before this guard.
    c.require(args.confirm == 'approved-prod-read-only' and args.operator_observation,
              'Explicit approved-prod-read-only confirmation and operator observation mode are required.')
    c.require(args.approval is not None, 'External approval record is required before any AWS access.')
    c.require(bool(re.fullmatch(r'[0-9]{12}', args.account)) and bool(re.fullmatch(r'[0-9a-f]{40}', args.sha)),
              'Expected account/full SHA required.')
    path = Path(args.approval)
    c.require(not path.is_symlink() and path.is_file(), 'Approval must be a regular non-symlink file.')
    raw = path.read_bytes()
    record = json.loads(raw)
    expected = {'environment': 'aws-prod', 'account': args.account, 'region': c.REGION,
                'cluster': CLUSTER, 'sha': args.sha, 'application_version': args.application_version,
                'image': image, 'action': 'observe', 'mode': 'operator-observation'}
    c.require(isinstance(record, dict) and record.get('approved') is True
              and all(record.get(k) == v for k, v in expected.items()), 'Approval scope mismatch or not approved.')
    c.require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', record.get('reference', ''))),
              'Approval needs a nonempty external review reference.')
    c.require(bool(re.fullmatch(r'arn:aws:(iam|sts)::' + args.account + r':[^\s]+', record.get('actor_arn', ''))),
              'Approval must bind the exact operator IAM/STS ARN.')
    start = datetime.fromisoformat(record['issued_at'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(record['expires_at'].replace('Z', '+00:00'))
    c.require(start.tzinfo is not None and end.tzinfo is not None
              and start <= datetime.now(timezone.utc) < end
              and 0 < (end - start).total_seconds() <= 3600, 'Approval expired, future-dated or exceeds one hour.')
    return record, hashlib.sha256(raw).hexdigest()


def preflight(args, approval):
    c.require(c.git('branch', '--show-current') == 'main', 'Live prod observation requires reviewed main, not feature.')
    c.require(not c.git('status', '--porcelain') and c.git('rev-parse', 'HEAD') == args.sha,
              'Clean main at the expected SHA required.')
    remote = c.git('ls-remote', '--exit-code', c.REPO, 'refs/heads/main').split()
    c.require(remote and remote[0] == args.sha, 'Remote main differs; stop and review.')
    actor = json.loads(aws('sts', 'get-caller-identity', '--output', 'json'))
    c.require(actor.get('Account') == args.account and actor.get('Arn') == approval['actor_arn'],
              'AWS account/operator differs from approval.')


def discover(args):
    proc = c.subprocess.run(['aws', '--region', c.REGION, 'eks', 'describe-cluster', '--name', CLUSTER,
                             '--output', 'json'], env=environment(), text=True, capture_output=True, timeout=90)
    if proc.returncode:
        c.require(re.search(r'\(ResourceNotFoundException\) when calling the DescribeCluster operation', proc.stderr),
                  'Prod discovery failed; not evidence of absent runtime.')
        return None
    cluster = json.loads(proc.stdout)['cluster']
    c.require(cluster.get('arn') == f'arn:aws:eks:{c.REGION}:{args.account}:cluster/{CLUSTER}'
              and cluster.get('name') == CLUSTER and cluster.get('status') == 'ACTIVE', 'Unexpected or inactive prod cluster.')
    return cluster


def kube_env(args, cluster, directory):
    env = environment()
    env['KUBECONFIG'] = str(Path(directory) / 'kubeconfig')
    c.run(['aws', '--region', c.REGION, 'eks', 'update-kubeconfig', '--name', CLUSTER,
           '--kubeconfig', env['KUBECONFIG']], env=env)
    config = json.loads(c.run(['kubectl', 'config', 'view', '--minify', '-o', 'json'], env=env))
    c.require(config['current-context'] == cluster['arn']
              and config['clusters'][0]['cluster']['server'] == cluster['endpoint'], 'Prod kubeconfig endpoint/context mismatch.')
    return env


def expected_applications(env, cluster):
    renderer = ['kustomize', 'build'] if shutil.which('kustomize') else ['kubectl', 'kustomize']
    objects = list(c.yaml.safe_load_all(c.run([*renderer, c.ROOT / OVERLAY], env=env)))
    apps = {x['metadata']['name']: x for x in objects if x and x.get('kind') == 'Application'}
    root = c.yaml.safe_load((c.ROOT / OVERLAY / 'root-app.yaml').read_text())
    c.require(root['metadata']['name'] == ROOT_APP, 'Prod root declaration mismatch.')
    apps[ROOT_APP] = root
    # Only the documented runtime VPC field differs from Git source rendering.
    apps['aws-load-balancer-controller']['spec']['source']['helm']['valuesObject']['vpcId'] = cluster['resourcesVpcConfig']['vpcId']
    return apps


def check_applications(items, expected, sha):
    contract = json.loads(CONTRACT.read_text())
    names = set(contract['same_repository_applications']) | set(contract['external_applications']) | {ROOT_APP}
    actual = {x['metadata']['name']: x for x in items}
    c.require(len(actual) == len(items) and set(actual) == set(expected) == names, 'Prod Application inventory mismatch.')
    for name, app in actual.items():
        wanted, spec = expected[name]['spec'], app['spec']
        c.require(all(spec.get(key) == wanted.get(key) for key in ('source', 'destination', 'project')),
                  f'Prod Application source/destination/project drift: {name}')
        source = spec['source']
        if 'chart' in source:
            revision = source['targetRevision']
            c.require(source['chart'] == contract['external_applications'][name]['chart']
                      and revision == contract['external_applications'][name]['version'], 'Prod chart pin mismatch.')
        else:
            c.require(source.get('repoURL') == c.REPO and source.get('targetRevision') == 'main', 'Prod must use canonical main source.')
            revision = sha
        state = app.get('status', {})
        c.require(state.get('sync', {}).get('status') == 'Synced'
                  and state['sync'].get('revision') == revision
                  and state.get('health', {}).get('status') == 'Healthy', f'Prod Application not converged: {name}')


def observe(args, env, cluster, image, checks, capabilities):
    def passed(identifier, value):
        checks.append({'id': identifier, 'outcome': 'passed', 'observedValue': value, 'diagnostic': None})
    for words in ('get pods -n observability', 'get applications.argoproj.io -n argocd',
                  'get rollouts.argoproj.io -n startup-apps', 'create pods/portforward -n observability'):
        c.require(c.can_i(env, *words.split()), 'Required prod observation permission missing.')
    passed('identity.rbac-mode', 'operator-credentials-read-only-code; least-privilege-not-verified')
    expected = expected_applications(env, cluster)
    check_applications(c.get(env, '-n', 'argocd', 'get', 'applications')['items'], expected, args.sha)
    passed('gitops.revisions', args.sha)
    rollout = c.get(env, '-n', 'startup-apps', 'get', 'rollout', 'demo-api')
    shared.check_rollout(rollout, args.application_version, image)
    passed('release.rollout', 'healthy-exact-version-and-stable-hash')
    passed('release.image', image)
    pods = c.get(env, '-n', 'startup-apps', 'get', 'pods', '-l', 'app.kubernetes.io/name=demo-api')['items']
    active = [x for x in pods if not x['metadata'].get('deletionTimestamp') and x.get('status', {}).get('phase') != 'Succeeded']
    c.require(len(active) == rollout['spec'].get('replicas', 1), 'Prod active Pod count mismatch.')
    for pod in active:
        containers = [x for x in pod['spec']['containers'] if x['name'] == 'demo-api']
        c.require(len(containers) == 1 and containers[0]['image'] == image
                  and any(x['type'] == 'Ready' and x['status'] == 'True' for x in pod.get('status', {}).get('conditions', [])),
                  'Prod Pod identity/readiness mismatch.')
    c.require(c.load_capacity().runtime_ready(c.get(env, '-n', 'observability', 'get', 'deployment,daemonset,statefulset'),
                                             c.get(env, '-n', 'observability', 'get', 'pods')), 'Prod monitoring workloads not ready.')
    passed('monitoring.workloads', 'ready')
    with shared.forward(env, 'observability-metrics-prometheus', 9090) as url:
        shared.check_demo_targets(shared.api(url + '/api/v1/targets')['activeTargets'], rollout, active,
                                  args.application_version, image, environment='aws-prod')
        passed('prometheus.target', 'up')
        rules = [r['name'] for group in shared.api(url + '/api/v1/rules')['groups'] for r in group['rules']]
        for name in ('demo_api:slo_availability:ratio30d', 'demo_api:slo_latency:ratio30d',
                     'demo_api:slo_availability_burn_rate:ratio1h', 'demo_api:slo_latency_burn_rate:ratio1h',
                     'DemoApiAvailabilityErrorBudgetFastBurn', 'DemoApiLatencyErrorBudgetFastBurn', 'PrometheusTargetDown'):
            c.require(rules.count(name) == 1, f'Prod rule absent or duplicated: {name}')
        passed('prometheus.rules', 'required-rules-present')
    dashboards = c.get(env, '-n', 'observability', 'get', 'configmaps', '-l', 'grafana_dashboard=1')['items']
    c.require({x['metadata']['name'] for x in dashboards} ==
              {f'observability-dashboard-{x}-overview' for x in ('capacity', 'data', 'delivery', 'platform', 'service', 'slo')},
              'Prod dashboard ConfigMap inventory mismatch.')
    passed('grafana.configmaps', 6)
    with shared.forward(env, 'observability-metrics-alertmanager', 9093):
        passed('alertmanager.ready', True)
    names = c.kube(env, '-n', 'observability', 'get', 'deployment,statefulset,daemonset,service', '-o', 'name').lower()
    c.require(not any(x in names for x in ('loki', 'alloy', 'tempo', 'otel-collector', 'opentelemetry')), 'Undeclared prod logs/traces runtime.')
    passed('logs-traces.absent', 'not-deployed')
    shared.check_rollout(c.get(env, '-n', 'startup-apps', 'get', 'rollout', 'demo-api'), args.application_version, image)
    check_applications(c.get(env, '-n', 'argocd', 'get', 'applications')['items'], expected, args.sha)
    for key, refs in {'metrics': ['prometheus.target'], 'dashboards': ['grafana.configmaps'],
                      'alerts': ['prometheus.rules', 'alertmanager.ready']}.items():
        capabilities[key] = {'status': 'supported-verified', 'evidenceCheckIds': refs}
    for key in ('logs', 'traces'):
        capabilities[key] = {'status': 'not-deployed', 'evidenceCheckIds': ['logs-traces.absent']}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--application-version', required=True)
    parser.add_argument('--approval', type=Path)
    parser.add_argument('--confirm', default='')
    parser.add_argument('--operator-observation', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    version, image = release()
    approval, fingerprint = approve(args, image)
    c.require(args.application_version == version, 'Expected version differs from declared PROD release.')
    c.require(not args.output.exists() and not args.output.is_symlink(), 'Evidence path exists; use a new filename.')
    c.run(['bash', c.ROOT / 'scripts/check-environment-observability-qualification-policy.sh'],
          env={**environment(), 'QUALIFICATION_ENVIRONMENT': 'aws-prod', 'QUALIFICATION_ACTION': 'observe',
               'APPROVED_PRODUCTION_OBSERVATION': 'true'})
    preflight(args, approval)
    started = shared.now()
    checks = []
    capabilities = {k: {'status': 'supported-not-verified', 'evidenceCheckIds': []} for k in
                    ('metrics', 'dashboards', 'alerts', 'logs', 'traces', 'slo', 'progressiveDeliveryTelemetry')}
    status, diagnostic = 'qualified', None
    try:
        cluster = discover(args)
        if cluster is None:
            status = 'waiting-runtime'
            checks.append({'id': 'runtime.discovery', 'outcome': 'not-run', 'observedValue': None, 'diagnostic': 'environment-absent'})
        else:
            with tempfile.TemporaryDirectory(prefix='aws-prod-observe-') as directory:
                observe(args, kube_env(args, cluster, directory), cluster, image, checks, capabilities)
        c.require(approve(args, image)[1] == fingerprint, 'Approval changed during observation.')
        preflight(args, approval)
    except Exception as error:
        status, diagnostic = 'failed', str(error)
        checks.append({'id': 'runtime.failure', 'outcome': 'failed', 'observedValue': None, 'diagnostic': 'observation-failed; see local console'})
    document = {'schemaVersion': 'v0.11.8.0', 'qualificationVersion': 'v0.11.8.3', 'environment': 'aws-prod',
                'status': status, 'observationWindow': {'startedAt': started, 'finishedAt': shared.now()},
                'identity': {'awsAccountId': args.account, 'awsRegion': c.REGION, 'clusterName': CLUSTER,
                             'kubeContext': f'arn:aws:eks:{c.REGION}:{args.account}:cluster/{CLUSTER}',
                             'repositoryCommit': args.sha, 'targetRevision': args.sha, 'applicationVersion': version},
                'approval': {'required': True, 'approved': True, 'reference': approval['reference']},
                'capabilities': capabilities, 'checks': checks}
    shared.validate_evidence(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(document, handle, indent=2)
        handle.write('\n')
    print(f'status={status}; evidence={args.output}')
    if diagnostic:
        print(diagnostic, file=sys.stderr)
    return {'qualified': 0, 'waiting-runtime': 2, 'failed': 1}[status]


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from error

#!/usr/bin/env python3
"""Read-only exact-release test observation; no deploy, promote, exec or traffic generation."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
sys.dont_write_bytecode = True
import aws_test_feature_common as c


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def validate_evidence(document):
    checks = document['checks']
    ids = {x['id'] for x in checks}
    c.require(len(ids) == len(checks), 'Duplicate evidence check IDs.')
    c.require(bool(document['identity']['applicationVersion']), 'Empty application version.')
    for capability in document['capabilities'].values():
        c.require(set(capability['evidenceCheckIds']) <= ids, 'Unknown evidence check reference.')
    if document['status'] == 'qualified':
        c.require(checks and all(x['outcome'] == 'passed' for x in checks), 'Qualified evidence requires all checks to pass.')
        c.require(document['capabilities']['metrics']['status'] == 'supported-verified', 'Qualified evidence needs verified metrics.')


def check_rollout(obj, version, image):
    status, spec = obj.get('status', {}), obj['spec']
    c.require(obj['metadata'].get('annotations', {}).get('platform.startup.dev/application-version') == version,
              'Rollout application version differs from declared test release.')
    count = spec.get('replicas', 1)
    c.require(count > 0 and status.get('phase') == 'Healthy' and not status.get('pauseConditions')
              and not spec.get('paused') and str(status.get('observedGeneration')) == str(obj['metadata']['generation'])
              and all(status.get(k) == count for k in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')),
              'Rollout is not fully converged; review canary/analysis/pause separately, no automatic promotion.')
    c.require(status.get('stableRS') and status['stableRS'] == status.get('currentPodHash'), 'Stable/current Rollout hash mismatch.')
    containers = [x for x in spec['template']['spec']['containers'] if x['name'] == 'demo-api']
    c.require(len(containers) == 1 and containers[0]['image'] == image, 'Rollout image digest mismatch.')


def check_applications(items, sha, expected_sources):
    contract = json.loads(c.CONTRACT.read_text())
    by_name = {x['metadata']['name']: x for x in items}
    names = contract['same_repository_applications'] + ['startup-devops-aws-test-root']
    for name in names:
        c.require(name in by_name, f'Missing Application: {name}')
        app = by_name[name]
        source, status = app['spec']['source'], app.get('status', {})
        c.require(source['repoURL'] == c.REPO and source['targetRevision'] == c.BRANCH,
                  f'Wrong source for {name}.')
        if name != 'startup-devops-aws-test-root':
            c.require(source == expected_sources[name], f'Application source/path/Helm values drifted: {name}')
        c.require(status.get('sync', {}).get('revision') == sha and status['sync'].get('status') == 'Synced'
                  and status.get('health', {}).get('status') == 'Healthy', f'Application not converged to exact SHA: {name}')
    c.require(by_name['startup-devops-aws-test-root']['spec']['source']['path'] == c.OVERLAY, 'Root does not use test feature overlay.')
    charts = {}
    for app in items:
        source = app.get('spec', {}).get('source', {})
        chart = source.get('chart')
        if chart:
            c.require(chart not in charts, 'Duplicate external chart.')
            expected = expected_sources[app['metadata']['name']]
            c.require(source.get('repoURL') == expected.get('repoURL') and chart == expected.get('chart'),
                      f'External Chart repository mismatch: {chart}')
            charts[chart] = source['targetRevision']
            status = app.get('status', {})
            c.require(status.get('sync', {}).get('status') == 'Synced'
                      and status['sync'].get('revision') == source['targetRevision']
                      and status.get('health', {}).get('status') == 'Healthy', f'External chart not healthy: {chart}')
    c.require(charts == contract['external_charts'], 'External Chart inventory/pins mismatch.')


@contextmanager
def forward(env, service, remote):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen(['kubectl', '-n', 'observability', 'port-forward', '--address=127.0.0.1',
                             f'service/{service}', f'{port}:{remote}'], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(30):
            c.require(proc.poll() is None, f'Port forward exited for {service}.')
            try:
                with urllib.request.urlopen(url + '/-/ready', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError(f'{service} did not become ready.')
        yield url
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def api(url):
    with urllib.request.urlopen(url, timeout=15) as response:
        value = json.load(response)
    c.require(value.get('status') == 'success', 'Prometheus query failed.')
    return value['data']


def observe(args, env, checks, capabilities):
    def passed(identifier, value):
        checks.append({'id': identifier, 'outcome': 'passed', 'observedValue': value, 'diagnostic': None})
    for words in ('get pods -n observability', 'get applications.argoproj.io -n argocd',
                  'get rollouts.argoproj.io -n startup-apps', 'create pods/portforward -n observability'):
        c.require(c.can_i(env, *words.split()), 'Required observation RBAC missing.')
    if args.operator_observation:
        passed('identity.rbac-mode', 'operator-credentials-read-only-code; least-privilege-not-verified')
    else:
        for words in ('get secrets -n observability', 'create pods/exec -n observability',
                      'patch deployments.apps -n observability', 'patch rollouts.argoproj.io -n startup-apps'):
            c.require(not c.can_i(env, *words.split()),
                      'Actor is not bounded read-only; select reviewed operator mode explicitly or use the runtime role.')
        passed('identity.rbac-mode', 'bounded-read-only-and-portforward')
    version, image = c.release()
    c.require(args.application_version == version, 'Expected application version differs from the declared test release.')
    renderer = ['kustomize', 'build'] if shutil.which('kustomize') else ['kubectl', 'kustomize']
    rendered = c.run([*renderer, c.ROOT / c.OVERLAY], env=env)
    expected_sources = {x['metadata']['name']: x['spec']['source'] for x in c.yaml.safe_load_all(rendered)
                        if x and x.get('kind') == 'Application'}
    apps = c.get(env, '-n', 'argocd', 'get', 'applications')['items']
    check_applications(apps, args.sha, expected_sources)
    passed('gitops.revisions', args.sha)
    rollout = c.get(env, '-n', 'startup-apps', 'get', 'rollout', 'demo-api')
    check_rollout(rollout, version, image)
    passed('release.image', image)
    passed('release.rollout', 'healthy-exact-version-and-stable-hash')
    pods = c.get(env, '-n', 'startup-apps', 'get', 'pods', '-l', 'app.kubernetes.io/name=demo-api')['items']
    active = [p for p in pods if not p['metadata'].get('deletionTimestamp') and p.get('status', {}).get('phase') != 'Succeeded']
    c.require(len(active) == rollout['spec'].get('replicas', 1), 'Unexpected active demo-api Pod count.')
    for pod in active:
        containers = [x for x in pod['spec']['containers'] if x['name'] == 'demo-api']
        c.require(len(containers) == 1 and containers[0]['image'] == image
                  and any(x['type'] == 'Ready' and x['status'] == 'True' for x in pod.get('status', {}).get('conditions', [])),
                  'Application Pod identity/readiness mismatch.')
    resources = c.get(env, '-n', 'observability', 'get', 'deployment,daemonset,statefulset')
    monitoring_pods = c.get(env, '-n', 'observability', 'get', 'pods')
    c.require(c.load_capacity().runtime_ready(resources, monitoring_pods), 'Monitoring workloads not converged.')
    passed('monitoring.workloads', 'ready')
    with forward(env, 'observability-metrics-prometheus', 9090) as url:
        targets = api(url + '/api/v1/targets')['activeTargets']
        check_demo_targets(targets, rollout, active, version, image)
        passed('prometheus.target', 'up')
        rules = [r['name'] for group in api(url + '/api/v1/rules')['groups'] for r in group['rules']]
        for name in ('demo_api:slo_availability:ratio30d', 'demo_api:slo_latency:ratio30d',
                     'demo_api:slo_availability_burn_rate:ratio1h', 'demo_api:slo_latency_burn_rate:ratio1h',
                     'DemoApiAvailabilityErrorBudgetFastBurn', 'DemoApiLatencyErrorBudgetFastBurn', 'PrometheusTargetDown'):
            c.require(rules.count(name) == 1, f'Required Prometheus rule missing/duplicated: {name}')
        passed('prometheus.rules', 'required-rules-present')
        query = urllib.parse.urlencode({'query': 'demo_api:slo_http_requests:rate30d{deployment_environment_name="aws-test"}'})
        series = api(url + '/api/v1/query?' + query)['result']
        slo = 'supported-verified' if series else 'supported-not-verified'
        passed('slo.series', slo)
    dashboards = c.get(env, '-n', 'observability', 'get', 'configmaps', '-l', 'grafana_dashboard=1')['items']
    expected = {f'observability-dashboard-{name}-overview' for name in ('capacity', 'data', 'delivery', 'platform', 'service', 'slo')}
    c.require({x['metadata']['name'] for x in dashboards} == expected, 'Dashboard ConfigMap inventory mismatch.')
    passed('grafana.configmaps', 6)
    with forward(env, 'observability-metrics-alertmanager', 9093):
        passed('alertmanager.ready', True)
    names = c.kube(env, '-n', 'observability', 'get', 'deployment,statefulset,daemonset,service', '-o', 'name').lower()
    c.require(not any(x in names for x in ('loki', 'alloy', 'tempo', 'otel-collector', 'opentelemetry')), 'Undeclared logging/tracing runtime.')
    passed('logs-traces.absent', 'not-deployed')
    # Recheck release and source at the end; do not issue stale successful evidence.
    check_rollout(c.get(env, '-n', 'startup-apps', 'get', 'rollout', 'demo-api'), version, image)
    check_applications(c.get(env, '-n', 'argocd', 'get', 'applications')['items'], args.sha, expected_sources)
    c.preflight(args.account, args.sha)
    capabilities.update({
        'metrics': {'status': 'supported-verified', 'evidenceCheckIds': ['prometheus.target']},
        'dashboards': {'status': 'supported-verified', 'evidenceCheckIds': ['grafana.configmaps']},
        'alerts': {'status': 'supported-verified', 'evidenceCheckIds': ['prometheus.rules', 'alertmanager.ready']},
        'logs': {'status': 'not-deployed', 'evidenceCheckIds': ['logs-traces.absent']},
        'traces': {'status': 'not-deployed', 'evidenceCheckIds': ['logs-traces.absent']},
        'slo': {'status': slo, 'evidenceCheckIds': ['slo.series']},
        'progressiveDeliveryTelemetry': {'status': 'supported-not-verified', 'evidenceCheckIds': ['release.rollout']},
    })


def check_demo_targets(targets, rollout, pods, version, image, environment='aws-test'):
    """Check target identity, not a single hard-coded Service/job spelling."""
    canary = rollout.get('spec', {}).get('strategy', {}).get('canary', {})
    stable = canary.get('stableService', 'demo-api')
    services = {stable, canary.get('canaryService', stable)}
    names = {pod['metadata']['name'] for pod in pods}
    candidates = [t for t in targets if
                  t.get('scrapePool') == 'serviceMonitor/startup-apps/demo-api/0'
                  or (t.get('labels', {}).get('namespace') == 'startup-apps'
                      and (t.get('labels', {}).get('service_name') == 'demo-api'
                           or t.get('labels', {}).get('service') in services))]
    summary = [{'labels': t.get('labels', {}), 'health': t.get('health'),
                'lastError': t.get('lastError', '')} for t in candidates]
    def require(ok, message):
        c.require(ok, message + '; demo-api targets=' + json.dumps(summary, sort_keys=True))
    require(bool(candidates), 'No discovered demo-api targets')
    require(bool(names), 'No active demo-api Pods to verify')
    stable_pods = set()
    for target in candidates:
        labels = target.get('labels', {})
        require(target.get('scrapePool') == 'serviceMonitor/startup-apps/demo-api/0'
                and labels.get('namespace') == 'startup-apps'
                and labels.get('service_name') == 'demo-api'
                and labels.get('deployment_environment_name') == environment
                and labels.get('service_version') == version
                and labels.get('container_image_digest') == image.split('@', 1)[1]
                and labels.get('service') in services
                and labels.get('job') == labels.get('service')
                and labels.get('endpoint') == 'http'
                and labels.get('pod') in names,
                'Demo-api target environment/release/service/Pod identity mismatch')
        require(target.get('health') == 'up', 'Demo-api target is not up')
        if labels['service'] == stable:
            stable_pods.add(labels['pod'])
    require(stable_pods == names, 'Stable Service targets do not cover all active demo-api Pods')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', default=os.environ.get('EXPECTED_AWS_ACCOUNT_ID', ''))
    parser.add_argument('--sha', default=os.environ.get('EXPECTED_CONTROL_PLANE_SHA', ''))
    parser.add_argument('--application-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--operator-observation', action='store_true',
                        help='Explicit local operator mode: code is read-only, actor least privilege is not verified.')
    args = parser.parse_args()
    c.preflight(args.account, args.sha)
    c.require(not args.output.exists(), 'Evidence path exists; use a new filename.')
    c.run(['bash', c.ROOT / 'scripts/check-environment-observability-qualification-policy.sh'],
          env={**c.environment(), 'QUALIFICATION_ENVIRONMENT': 'aws-test', 'QUALIFICATION_ACTION': 'observe'})
    started = now()
    checks = []
    capabilities = {name: {'status': 'supported-not-verified', 'evidenceCheckIds': []} for name in (
        'metrics', 'dashboards', 'alerts', 'logs', 'traces', 'slo', 'progressiveDeliveryTelemetry')}
    status, diagnostic = 'qualified', None
    try:
        if c.discover(args.account) is None:
            status = 'waiting-runtime'
            checks.append({'id': 'runtime.discovery', 'outcome': 'not-run', 'observedValue': None, 'diagnostic': 'environment-absent'})
        else:
            with tempfile.TemporaryDirectory(prefix='aws-test-observe-') as directory:
                observe(args, c.kube_env(args.account, directory), checks, capabilities)
    except Exception as error:
        status = 'failed'
        diagnostic = str(error)
        checks.append({'id': 'runtime.failure', 'outcome': 'failed', 'observedValue': None,
                       'diagnostic': 'observation-failed; see local console'})
    document = {'schemaVersion': 'v0.11.8.0', 'qualificationVersion': 'v0.11.8.2', 'environment': 'aws-test',
                'status': status, 'observationWindow': {'startedAt': started, 'finishedAt': now()},
                'identity': {'awsAccountId': args.account, 'awsRegion': c.REGION, 'clusterName': c.CLUSTER,
                             'kubeContext': f'arn:aws:eks:{c.REGION}:{args.account}:cluster/{c.CLUSTER}',
                             'repositoryCommit': args.sha, 'targetRevision': args.sha, 'applicationVersion': args.application_version},
                'approval': {'required': False, 'approved': False, 'reference': None},
                'capabilities': capabilities, 'checks': checks}
    validate_evidence(document)
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
    except (RuntimeError, ValueError, OSError) as error:
        raise SystemExit(str(error)) from error

#!/usr/bin/env python3
"""Explicit local-only rehearsal phases; never promotes or performs rollback."""
import argparse
from contextlib import ExitStack
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'feature/v0.11-observability-sre-baseline'
REPO = 'https://github.com/SterlingAureum/startup-devops-baseline.git'
METRICS = {'canary-prometheus-target-up', 'canary-minimum-eligible-requests',
           'canary-availability-error-budget-burn-rate', 'canary-latency-error-budget-burn-rate',
           'stable-availability-error-budget-remaining', 'stable-latency-error-budget-remaining'}
ANN = 'platform.startup.dev/'
COMMAND_TIMEOUT_SECONDS = 900
IDENTITY_WAIT_SECONDS = 120
IDENTITY_POLL_SECONDS = 2


def require(ok, message):
    if not ok:
        raise ValueError(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(argv, env=None):
    return subprocess.check_output(argv, cwd=ROOT, env=env, text=True, timeout=60)


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)


def git_identity():
    require(not run(['git', 'status', '--porcelain']).strip(), 'Commit all changes before live rehearsal')
    require(run(['git', 'branch', '--show-current']).strip() == BRANCH, 'Feature branch required')
    sha = run(['git', 'rev-parse', 'HEAD']).strip()
    remote = run(['git', 'ls-remote', '--exit-code', REPO, 'refs/heads/' + BRANCH]).split()
    require(remote and remote[0] == sha, 'Push exact feature HEAD first')
    return sha


def get(env, resource, namespace='startup-apps'):
    return json.loads(run(['kubectl', '-n', namespace, 'get', resource, '-o', 'json'], env))


def snapshot(env):
    data = {key: get(env, resource) for key, resource in
            [('rollout', 'rollout/demo-api'), ('analyses', 'analysisruns'), ('pods', 'pods'),
             ('stable_service', 'service/demo-api-stable'), ('stable_endpoints', 'endpoints/demo-api-stable')]}
    data['applications'] = [get(env, 'application/' + name, 'argocd') for name in ('startup-devops-root', 'demo-api')]
    data['analysis_template'] = get(env, 'analysistemplate/demo-api-canary-health')
    return data


def gate_profile(data):
    steps = data['rollout']['spec'].get('strategy', {}).get('canary', {}).get('steps', [])
    require(len(steps) == 7 and steps[0].get('setWeight') == 20 and
            steps[3].get('setWeight') == 50 and steps[4] == {'pause': {}} and
            steps[6].get('setWeight') == 100, 'Expected current local human-governed Canary steps')
    for index in (2, 5):
        require(steps[index].get('analysis', {}).get('templates') == [{'templateName': 'demo-api-canary-health'}],
                'Expected two demo-api-canary-health gates')
    metrics = data['analysis_template']['spec'].get('metrics', [])
    require(len(metrics) == 6 and {x['name'] for x in metrics} == METRICS, 'Existing six-metric SLO template required')


def healthy(rollout):
    s = rollout.get('status', {})
    n = rollout['spec'].get('replicas', 0)
    require(n > 0 and s.get('phase') == 'Healthy' and s.get('currentPodHash') and
            s.get('currentPodHash') == s.get('stableRS') and
            s.get('readyReplicas') == n and s.get('availableReplicas') == n and
            not s.get('pauseConditions') and not s.get('abort'), 'Healthy converged baseline/final required')


def stable_ready(data):
    r = data['rollout']
    require(data['stable_service']['spec']['selector'].get('rollouts-pod-template-hash') ==
            r['status']['stableRS'], 'Stable service selector is stale')
    subsets = data['stable_endpoints'].get('subsets', [])
    require(subsets and not any(s.get('notReadyAddresses') for s in subsets), 'Stable endpoints unready')
    targets = {a.get('targetRef', {}).get('uid') for s in subsets for a in s.get('addresses', [])}
    pods = {p['metadata']['uid'] for p in data['pods']['items'] if
            p['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == r['status']['stableRS'] and
            not p['metadata'].get('deletionTimestamp')}
    require(pods and None not in targets and targets == pods, 'Stable endpoints do not cover current stable pods')


def bounded_command(argv, env, log):
    """Run one phase while retaining and mirroring every output line."""
    process = subprocess.Popen(argv, env=env, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1,
                               start_new_session=True)
    reader_errors = []

    def mirror():
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)
        except BaseException as exc:
            reader_errors.append(exc)

    reader = threading.Thread(target=mirror, name='rehearsal-output', daemon=True)
    reader.start()
    try:
        try:
            code = process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f'Phase command exceeded {COMMAND_TIMEOUT_SECONDS} seconds; inspect command.log') from exc
        reader.join(timeout=5)
        require(not reader.is_alive(), 'Phase output reader did not finish; inspect command.log')
        if reader_errors:
            raise ValueError(f'Phase output capture failed: {reader_errors[0]}')
        require(code == 0, f'Phase command failed with exit {code}; inspect command.log')
    finally:
        # The process group is owned by this attempt, including port-forwards.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def wait_snapshot_identity(env, expected_version, expected_identity, timeout=IDENTITY_WAIT_SECONDS,
                           poll=IDENTITY_POLL_SECONDS):
    """Wait through transient rollout scaling until all matching release Pods are Ready."""
    deadline = time.monotonic() + timeout
    last_error = None
    announced = False
    while True:
        data = snapshot(env)
        try:
            identity = image_identity(data, expected_version)
            require(identity == expected_identity, 'Candidate binary image differs from prepared baseline')
            if announced:
                print('Release Pod/imageID convergence confirmed.', flush=True)
            return data, identity
        except ValueError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            raise ValueError(f'Release Pod/imageID did not converge within {timeout} seconds: {last_error}')
        if not announced:
            print(f'Waiting up to {timeout} seconds for all release Pods to become Ready with imageID; '
                  'this is expected briefly while Canary replicas scale.', flush=True)
            announced = True
        time.sleep(poll)


def bundle_path(value):
    raw = str(value).strip()
    require(raw, 'Bundle path is empty')
    require(not re.match(r'^(?:export\s+)?REHEARSAL_DIR\s*=', raw),
            'Pass only the path after the prompt, for example /tmp/local-release-rehearsal.ABC123/run; '
            'do not enter REHEARSAL_DIR=/tmp/...')
    path = Path(raw).expanduser().resolve()
    require(not path.is_relative_to(ROOT),
            'Private evidence must be outside the repository; example: --bundle /tmp/local-release-rehearsal.ABC123/run')
    return path


def image_identity(data, expected_version):
    r = data['rollout']
    require(r['metadata'].get('annotations', {}).get(ANN + 'application-version') == expected_version,
            'Application version mismatch')
    containers = r['spec']['template']['spec']['containers']
    require(len(containers) == 1, 'This profile supports the single demo-api container only')
    container = containers[0]
    selector = r['spec']['selector']['matchLabels']
    pods = [p for p in data['pods']['items'] if not p['metadata'].get('deletionTimestamp') and
            all(p['metadata'].get('labels', {}).get(k) == v for k, v in selector.items()) and
            p['metadata'].get('annotations', {}).get(ANN + 'application-version') == expected_version]
    require(pods, 'No matching live release pods')
    ids = set()
    for pod in pods:
        statuses = [s for s in pod.get('status', {}).get('containerStatuses', []) if s['name'] == container['name']]
        require(len(statuses) == 1 and statuses[0].get('ready') and statuses[0].get('imageID'), 'Release pod not Ready/imageID absent')
        require(next(c['image'] for c in pod['spec']['containers'] if c['name'] == container['name']) == container['image'], 'Pod image reference mismatch')
        ids.add(statuses[0]['imageID'])
    require(len(ids) == 1, 'Inconsistent runtime image IDs')
    return {'reference': container['image'], 'runtime_image_id': ids.pop(), 'pull_policy': container.get('imagePullPolicy')}


def fresh_analyses(data, plan, count):
    r = data['rollout']
    require(r['metadata']['uid'] == plan['rollout_uid'], 'Rollout was recreated')
    rid = r['metadata'].get('annotations', {}).get(ANN + 'release-id')
    require(rid and rid != plan['baseline_release_id'], 'Candidate release ID is not new')
    found = []
    for a in data['analyses']['items']:
        if not any(x.get('name') == 'expected-release-id' and x.get('value') == rid for x in a['spec'].get('args', [])):
            continue
        require(a['metadata']['uid'] not in plan['old_analysis_uids'], 'Historical analysis reused')
        require(dt.datetime.fromisoformat(a['metadata']['creationTimestamp'].replace('Z', '+00:00')) >=
                dt.datetime.fromisoformat(plan['started_at']), 'Stale analysis timestamp')
        require(any(o.get('uid') == plan['rollout_uid'] and o.get('kind') == 'Rollout'
                    for o in a['metadata'].get('ownerReferences', [])), 'Analysis owner mismatch')
        phase = a.get('status', {}).get('phase')
        require(phase not in ('Failed', 'Error', 'Inconclusive'), 'Candidate analysis failed; preserve evidence and stop')
        if phase == 'Successful':
            results = a['status'].get('metricResults', [])
            require(len(results) == 6 and {x['name'] for x in results} == METRICS and
                    all(x.get('phase') == 'Successful' for x in results), 'Six successful SLO metrics required')
            found.append(a['metadata']['uid'])
    require(len(set(found)) >= count, 'Insufficient distinct fresh successful analyses')
    return sorted(found)


def isolated(context, directory):
    require(re.fullmatch(r'kind-[A-Za-z0-9._-]+', context), 'Explicit kind context required')
    kubectl = shutil.which('kubectl')
    argocd = shutil.which('argocd')
    require(kubectl, 'kubectl required')
    config = run([kubectl, '--context', context, 'config', 'view', '--minify', '--flatten', '--raw', '-o', 'json'])
    payload = json.loads(config)
    host = urlparse(payload['clusters'][0]['cluster']['server']).hostname
    require(host in ('127.0.0.1', 'localhost', '::1'), 'Only loopback kind API servers allowed')
    require(not payload['clusters'][0]['cluster'].get('insecure-skip-tls-verify'), 'TLS verification required')
    path = directory / 'kubeconfig'
    payload['contexts'][0]['context']['namespace'] = 'argocd'
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LANG', 'TMPDIR', 'SSH_AUTH_SOCK') if k in os.environ}
    env['KUBECONFIG'] = str(path)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # Force all legacy Argo CD calls to the same isolated Kubernetes API.
    # No persisted Argo CD server/token or caller override is inherited.
    if argocd:
        shim = directory / 'argocd'
        import shlex
        shim.write_text('#!/bin/sh\nexec ' + shlex.quote(argocd) + ' --core "$@"\n')
        shim.chmod(0o700)
        env['PATH'] = str(directory) + os.pathsep + env['PATH']
    cluster_uid = get(env, 'namespace/kube-system', 'default')['metadata']['uid']
    nodes = get(env, 'nodes', 'default')['items']
    require(nodes and all(n['metadata']['name'].startswith(context[5:] + '-') for n in nodes), 'kind node identity mismatch')
    return env, cluster_uid, payload['clusters'][0]['cluster']['server']


def execute(args):
    bundle = bundle_path(args.bundle)
    require(args.confirm == ('deploy-reviewed-local' if args.phase == 'deploy' else
                             'generate-local-traffic' if args.phase in ('first-analysis', 'second-analysis') else
                             'observe-local'), 'Explicit matching --confirm required')
    if args.phase == 'prepare':
        require(args.context and args.version and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', args.version), 'Context and concrete candidate version required')
        require(args.review and args.recovery_owner, 'Review reference and recovery owner required')
        bundle.mkdir(mode=0o700, parents=True, exist_ok=False)
    plan = None if args.phase == 'prepare' else json.loads((bundle / 'plan.json').read_text())
    with tempfile.TemporaryDirectory(prefix='local-rehearsal-') as tmp, ExitStack() as resources:
        env, uid, server = isolated(args.context if plan is None else plan['context'], Path(tmp))
        sha = git_identity()
        if plan:
            require(uid == plan['cluster_uid'] and server == plan['server'] and sha == plan['source_commit'], 'Cluster/source changed; stop')
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(plan['started_at'])).total_seconds()
            require(0 <= age <= 14400, 'Rehearsal plan expired (4 hours); inspect state before preparing again')
        lock = resources.enter_context((bundle / (args.phase + '.lock')).open('a'))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not (bundle / (args.phase + '.passed.json')).exists(), 'Phase already passed; do not replay it')
        attempt = bundle / (args.phase + '-' + uuid.uuid4().hex)
        attempt.mkdir(mode=0o700)
        try:
            data = snapshot(env)
            write(attempt / 'before.json', data)
            if plan is None:
                gate_profile(data)
                healthy(data['rollout'])
                stable_ready(data)
                baseline = data['rollout']['metadata']['annotations'][ANN + 'application-version']
                require(args.version != baseline, 'Candidate version must be new')
                require(not any(x.get('name') == 'expected-version' and x.get('value') == args.version
                                for a in data['analyses']['items'] for x in a['spec'].get('args', [])), 'Candidate version already has analysis history')
                require(not any(a.get('status', {}).get('phase') in ('Pending', 'Running') for a in data['analyses']['items']), 'An analysis is still active')
                identity = image_identity(data, baseline)
                require(identity['pull_policy'] == 'Never' and '@' not in identity['reference'] and ':' in identity['reference'].rsplit('/', 1)[-1], 'Use existing local tag with pullPolicy Never')
                plan = dict(context=args.context, cluster_uid=uid, server=server, source_commit=sha,
                            started_at=now(), candidate_version=args.version, baseline_version=baseline,
                            baseline_release_id=data['rollout']['metadata']['annotations'][ANN + 'release-id'],
                            rollout_uid=data['rollout']['metadata']['uid'], image=identity,
                            old_analysis_uids=[a['metadata']['uid'] for a in data['analyses']['items']],
                            review_reference=args.review, recovery_owner=args.recovery_owner,
                            identity_kind='local-tag-plus-runtime-image-id', runtime_qualified=False)
                write(bundle / 'plan.json', plan)
            else:
                if args.phase == 'deploy':
                    gate_profile(data)
                    healthy(data['rollout'])
                    stable_ready(data)
                    require(image_identity(data, plan['baseline_version']) == plan['image'], 'Baseline image changed')
                    require(data['rollout']['metadata']['uid'] == plan['rollout_uid'], 'Baseline rollout recreated')
                    require(not (bundle / 'deploy.started.json').exists(), 'Deployment already attempted; inspect and recover explicitly')
                    write(bundle / 'deploy.started.json', {'at': now()})
                    repo, tag = plan['image']['reference'].rsplit(':', 1)
                    env.update(TARGET_REVISION=plan['source_commit'], IMAGE_REPOSITORY=repo,
                               IMAGE_TAG=tag, APPLICATION_VERSION=plan['candidate_version'])
                    script = 'deploy-local-feature-gitops.sh'
                else:
                    prerequisites = {'first-analysis': 'prepare', 'human-review': 'first-analysis',
                                     'second-analysis': 'human-review', 'final': 'second-analysis'}
                    require((bundle / (prerequisites[args.phase] + '.passed.json')).exists(), 'Previous phase has not passed')
                    if args.phase in ('human-review', 'second-analysis', 'final'):
                        require((bundle / 'deploy.passed.json').exists(), 'Deployment did not pass')
                    if args.phase == 'human-review':
                        require(args.review, 'Record an explicit review reference')
                    env.update(CLOSURE_PHASE=args.phase, EXPECTED_APPLICATION_VERSION=plan['candidate_version'])
                    script = 'check-local-slo-progressive-delivery-closure.sh'
                with (attempt / 'command.log').open('x') as log:
                    print(f'{args.phase} started; live output is mirrored below and retained at '
                          f'{attempt / "command.log"}', flush=True)
                    if args.phase == 'first-analysis':
                        print('Terminal 1 action: start deploy now; do not wait for first-analysis to exit.', flush=True)
                    elif args.phase == 'second-analysis':
                        print('Terminal 1 action: wait for the traffic/waiting signal below, then run the documented '
                              'manual promote command once.', flush=True)
                    bounded_command(['bash', str(ROOT / 'scripts' / script)], env, log)
                if args.phase == 'deploy':
                    data = snapshot(env)
                else:
                    data, _ = wait_snapshot_identity(env, plan['candidate_version'], plan['image'])
                write(attempt / 'after.json', data)
                if args.phase != 'deploy':
                    require((bundle / 'deploy.started.json').exists(), 'No deployment attempt belongs to this bundle')
                    ids = fresh_analyses(data, plan, 2 if args.phase in ('second-analysis', 'final') else 1)
                    if args.phase == 'final':
                        healthy(data['rollout'])
                        stable_ready(data)
                        for app in data['applications']:
                            require(app['spec']['source']['repoURL'] == REPO and
                                    app['spec']['source']['targetRevision'] == plan['source_commit'] and
                                    app['status']['sync']['revision'] == plan['source_commit'] and
                                    app['status']['sync']['status'] == 'Synced', 'Final GitOps source/sync mismatch')
                    write(attempt / 'analysis-identities.json', ids)
            write(bundle / (args.phase + '.passed.json'), {'at': now(), 'attempt': attempt.name,
                  'review_reference': args.review, 'runtime_qualified': args.phase == 'final'})
            print(f'{args.phase} passed; evidence={attempt}', flush=True)
        except BaseException as exc:
            write(attempt / 'failure.json', {'at': now(), 'error': str(exc), 'runtime_qualified': False})
            try:
                write(attempt / 'failure-state.json', snapshot(env))
            except Exception:
                pass
            raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'deploy', 'first-analysis', 'human-review', 'second-analysis', 'final'])
    p.add_argument('--bundle', required=True,
                   help='private evidence path only, e.g. /tmp/local-release-rehearsal.ABC123/run')
    p.add_argument('--confirm', required=True)
    p.add_argument('--context')
    p.add_argument('--version')
    p.add_argument('--review')
    p.add_argument('--recovery-owner')
    args = p.parse_args()
    try:
        execute(args)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        p.exit(1, f'Stopped: {exc}\nPreserve the bundle. No automatic promote, retry or rollback.\n')


if __name__ == '__main__':
    main()

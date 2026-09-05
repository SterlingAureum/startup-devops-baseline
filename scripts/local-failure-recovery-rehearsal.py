#!/usr/bin/env python3
"""Explicit local candidate-rejection phases; never promotes or retries automatically."""
import argparse
from contextlib import ExitStack
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load('successful_rehearsal', ROOT / 'scripts/local-release-rehearsal.py')
PLAN = load('failure_recovery_plan', ROOT / 'scripts/check-v0.11.9.2.0-failure-recovery-plan.py')
PHASES = ('prepare', 'arm', 'traffic', 'rejection-review', 'abort-check',
          'recovery-approval', 'restore', 'final')
CONFIRM = {
    'prepare': 'observe-local',
    'arm': 'deploy-reviewed-local-fault-candidate',
    'traffic': 'generate-reviewed-candidate-fault-traffic',
    'rejection-review': 'observe-local',
    'abort-check': 'observe-local',
    'recovery-approval': 'approve-reviewed-local-recovery',
    'restore': 'restore-reviewed-local-baseline',
    'final': 'observe-local',
}
PREVIOUS = dict(zip(PHASES[1:], PHASES[:-1]))


def env_value(pod, name):
    values = [item.get('value', '') for container in pod['spec'].get('containers', [])
              for item in container.get('env', []) if item.get('name') == name]
    BASE.require(len(values) == 1, f'Pod must contain exactly one {name}')
    return values[0]


def template_env(data, name):
    containers = data['rollout']['spec']['template']['spec']['containers']
    BASE.require(len(containers) == 1, 'Single demo-api container required')
    values = [item.get('value', '') for item in containers[0].get('env', []) if item.get('name') == name]
    BASE.require(len(values) == 1, f'Rollout template must contain exactly one {name}')
    return values[0]


def live_pods(data):
    selector = data['rollout']['spec']['selector']['matchLabels']
    return [pod for pod in data['pods']['items'] if not pod['metadata'].get('deletionTimestamp') and
            all(pod['metadata'].get('labels', {}).get(k) == v for k, v in selector.items())]


def ready(pod):
    return any(item.get('type') == 'Ready' and item.get('status') == 'True'
               for item in pod.get('status', {}).get('conditions', []))


def assert_fault_isolation(data, plan, digest, candidate_required):
    pods = live_pods(data)
    stable_hash = data['rollout']['status'].get('stableRS')
    stable = [pod for pod in pods if
              pod['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == stable_hash]
    BASE.require(stable and all(ready(pod) for pod in stable), 'Stable Pods are not Ready')
    for pod in stable:
        BASE.require(pod['metadata'].get('annotations', {}).get(BASE.ANN + 'release-id') ==
                     plan['baseline']['release_id'], 'Stable release identity changed')
        BASE.require(env_value(pod, 'REHEARSAL_FAULT_MODE') == 'disabled' and
                     env_value(pod, 'REHEARSAL_FAULT_TOKEN_SHA256') == '',
                     'Stable Pod retained fault configuration')
    candidates = [pod for pod in pods if pod['metadata'].get('annotations', {}).get(
        BASE.ANN + 'application-version') == plan['candidate']['application_version']]
    if candidate_required:
        BASE.require(candidates and all(ready(pod) for pod in candidates), 'Candidate Pods are not Ready')
        for pod in candidates:
            BASE.require(env_value(pod, 'REHEARSAL_FAULT_MODE') == 'availability-503' and
                         env_value(pod, 'REHEARSAL_FAULT_TOKEN_SHA256') == digest,
                         'Candidate fault configuration mismatch')
    else:
        BASE.require(not candidates, 'Candidate Pods exist before arm or after final recovery')


def failed_analysis(data, state):
    matches = []
    for analysis in data['analyses']['items']:
        if not any(arg.get('name') == 'expected-release-id' and
                   arg.get('value') == state['candidate_release_id']
                   for arg in analysis['spec'].get('args', [])):
            continue
        BASE.require(analysis['metadata']['uid'] not in state['old_analysis_uids'],
                     'Historical AnalysisRun was reused')
        matches.append(analysis)
    BASE.require(matches, 'No release-bound candidate AnalysisRun exists')
    latest = sorted(matches, key=lambda item: item['metadata']['creationTimestamp'])[-1]
    if state.get('failed_analysis_uid'):
        BASE.require(latest['metadata']['uid'] == state['failed_analysis_uid'],
                     'Reviewed failed AnalysisRun identity changed')
    BASE.require(latest.get('status', {}).get('phase') == 'Failed',
                 'Candidate AnalysisRun did not fail as required')
    results = latest['status'].get('metricResults', [])
    target = [result for result in results if
              result.get('name') == 'canary-availability-error-budget-burn-rate']
    BASE.require(len(target) == 1 and target[0].get('phase') == 'Failed' and
                 any(measurement.get('value') is not None for measurement in target[0].get('measurements', [])),
                 'Exact measured availability burn-rate failure is absent')
    BASE.require(not any(result.get('phase') in ('Error', 'Inconclusive') for result in results),
                 'Provider Error/Inconclusive is not an intentional SLO rejection')
    return latest['metadata']['uid']


def elapsed_seconds(start, end=None):
    start_value = dt.datetime.fromisoformat(start.replace('Z', '+00:00'))
    end_value = (dt.datetime.now(dt.timezone.utc) if end is None else
                 dt.datetime.fromisoformat(end.replace('Z', '+00:00')))
    return (end_value - start_value).total_seconds()


def assert_gitops_restored(data, source_commit):
    applications = {item['metadata']['name']: item for item in data['applications']}
    BASE.require(set(applications) == {'startup-devops-root', 'demo-api'},
                 'Expected Root and demo-api GitOps Applications')
    for name, application in applications.items():
        source = application['spec']['source']
        sync = application['status']['sync']
        BASE.require(source['repoURL'] == BASE.REPO and
                     source['targetRevision'] == source_commit and
                     sync['revision'] == source_commit and sync['status'] == 'Synced',
                     f'{name} GitOps source/sync was not restored')


def wait_arm(env, plan, digest, timeout=180, poll=2):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() <= deadline:
        data = BASE.snapshot(env)
        try:
            BASE.require(data['rollout']['metadata']['annotations'][BASE.ANN + 'application-version'] ==
                         plan['candidate']['application_version'], 'Candidate version not observed')
            assert_fault_isolation(data, plan, digest, True)
            identity = BASE.image_identity(data, plan['candidate']['application_version'])
            BASE.require(identity['reference'] == plan['candidate']['image_reference'] and
                         identity['runtime_image_id'] == plan['candidate']['runtime_image_id'],
                         'Candidate binary differs from healthy baseline')
            return data
        except (ValueError, KeyError) as exc:
            last_error = exc
        time.sleep(poll)
    raise ValueError(f'Candidate fault isolation did not converge within {timeout} seconds: {last_error}')


def require_source(plan):
    BASE.require(BASE.git_identity() == plan['source_commit'], 'Plan source commit differs from exact pushed HEAD')


def read_json(path):
    return json.loads(path.read_text())


def execute(args):
    bundle = BASE.bundle_path(args.bundle)
    BASE.require(args.confirm == CONFIRM[args.phase], 'Explicit matching --confirm required')
    if args.phase == 'prepare':
        BASE.require(args.plan, '--plan is required for prepare')
        plan_source = Path(args.plan).expanduser().resolve()
        plan = read_json(plan_source)
        PLAN.validate(plan)
        BASE.require(bundle == Path(plan['evidence_directory']).expanduser().resolve(),
                     '--bundle must exactly match plan evidence_directory')
        bundle.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        plan = read_json(bundle / 'plan.json')
        PLAN.validate(plan)
        BASE.require((bundle / (PREVIOUS[args.phase] + '.passed.json')).exists(),
                     'Previous phase has not passed')
    with tempfile.TemporaryDirectory(prefix='local-failure-recovery-') as tmp, ExitStack() as resources:
        env, cluster_uid, server = BASE.isolated(plan['context'], Path(tmp))
        require_source(plan)
        if args.phase != 'prepare':
            state = read_json(bundle / 'state.json')
            BASE.require((cluster_uid, server) == (state['cluster_uid'], state['server']),
                         'Cluster identity changed')
        lock = resources.enter_context((bundle / (args.phase + '.lock')).open('a'))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        BASE.require(not (bundle / (args.phase + '.passed.json')).exists(),
                     'Phase already passed; do not replay it')
        attempt = bundle / (args.phase + '-' + uuid.uuid4().hex)
        attempt.mkdir(mode=0o700)
        try:
            data = BASE.snapshot(env)
            BASE.write(attempt / 'before.json', data)
            if args.phase == 'prepare':
                BASE.healthy(data['rollout'])
                BASE.stable_ready(data)
                rollout = data['rollout']
                baseline = plan['baseline']
                BASE.require(rollout['metadata']['uid'] == baseline['rollout_uid'] and
                             rollout['metadata']['annotations'][BASE.ANN + 'release-id'] == baseline['release_id'] and
                             rollout['metadata']['annotations'][BASE.ANN + 'application-version'] ==
                             baseline['application_version'], 'Observed baseline identity differs from plan')
                identity = BASE.image_identity(data, baseline['application_version'])
                BASE.require(identity['reference'] == baseline['image_reference'] and
                             identity['runtime_image_id'] == baseline['runtime_image_id'],
                             'Observed baseline image differs from plan')
                assert_fault_isolation(data, plan, '', False)
                token = secrets.token_urlsafe(32)
                token_path = bundle / 'fault-token.private'
                token_path.write_text(token)
                token_path.chmod(0o600)
                digest = hashlib.sha256(token.encode()).hexdigest()
                BASE.write(bundle / 'plan.json', plan)
                state = {'cluster_uid': cluster_uid, 'server': server,
                         'source_commit': plan['source_commit'], 'prepared_at': BASE.now(),
                         'token_sha256': digest,
                         'old_analysis_uids': [item['metadata']['uid'] for item in data['analyses']['items']]}
                BASE.write(bundle / 'state.json', state)
            elif args.phase == 'arm':
                BASE.healthy(data['rollout'])
                BASE.stable_ready(data)
                assert_fault_isolation(data, plan, '', False)
                BASE.require(not (bundle / 'arm.started.json').exists(),
                             'Candidate deployment already attempted; inspect state')
                BASE.write(bundle / 'arm.started.json', {'at': BASE.now()})
                repository, tag = plan['candidate']['image_reference'].rsplit(':', 1)
                env.update(TARGET_REVISION=plan['source_commit'], IMAGE_REPOSITORY=repository,
                           IMAGE_TAG=tag, APPLICATION_VERSION=plan['candidate']['application_version'],
                           REHEARSAL_FAULT_MODE='availability-503',
                           REHEARSAL_FAULT_TOKEN_SHA256=state['token_sha256'])
                with (attempt / 'command.log').open('x') as log:
                    BASE.bounded_command(['bash', str(ROOT / 'scripts/deploy-local-feature-gitops.sh')], env, log)
                data = wait_arm(env, plan, state['token_sha256'])
                state['candidate_release_id'] = data['rollout']['metadata']['annotations'][BASE.ANN + 'release-id']
                BASE.require(state['candidate_release_id'] != plan['baseline']['release_id'],
                             'Candidate release ID must be fresh')
                (bundle / 'state.json').write_text(json.dumps(state, indent=2))
            elif args.phase == 'traffic':
                assert_fault_isolation(data, plan, state['token_sha256'], True)
                traffic_env = dict(env, CONTEXT=plan['context'],
                                   EXPECTED_CANDIDATE_RELEASE_ID=state['candidate_release_id'],
                                   EXPECTED_BASELINE_RELEASE_ID=plan['baseline']['release_id'],
                                   EXPECTED_TOKEN_SHA256=state['token_sha256'],
                                   FAULT_TOKEN_FILE=str(bundle / 'fault-token.private'),
                                   MAX_REQUESTS=str(plan['fault']['max_requests']),
                                   ANALYSIS_WAIT_SECONDS=str(plan['fault']['max_seconds']),
                                   CONFIRM_LOCAL_REJECTION_TRAFFIC=args.confirm)
                with (attempt / 'command.log').open('x') as log:
                    BASE.bounded_command(['bash', str(ROOT / 'scripts/run-local-candidate-rejection-traffic.sh')],
                                         traffic_env, log)
                data = BASE.snapshot(env)
                state['failed_analysis_uid'] = failed_analysis(data, state)
                (bundle / 'state.json').write_text(json.dumps(state, indent=2))
            elif args.phase == 'rejection-review':
                BASE.require(args.review == plan['review_reference'], 'Exact rejection review reference required')
                failed_analysis(data, state)
                assert_fault_isolation(data, plan, state['token_sha256'], True)
            elif args.phase == 'abort-check':
                failed_analysis(data, state)
                BASE.require(data['rollout'].get('status', {}).get('abort') is True,
                             'Rollout abort is not observed; review and run the documented manual abort if required')
            elif args.phase == 'recovery-approval':
                BASE.require(args.review == plan['review_reference'], 'Exact recovery review reference required')
                failed_analysis(data, state)
                BASE.require(data['rollout'].get('status', {}).get('abort') is True,
                             'Recovery cannot be approved before abort is observed')
                state['recovery_approved_at'] = BASE.now()
                (bundle / 'state.json').write_text(json.dumps(state, indent=2))
            elif args.phase == 'restore':
                BASE.require(data['rollout'].get('status', {}).get('abort') is True,
                             'Restore requires the reviewed aborted candidate state')
                BASE.require(state.get('recovery_approved_at'), 'Recovery approval timestamp is absent')
                state['restore_started_at'] = BASE.now()
                (bundle / 'state.json').write_text(json.dumps(state, indent=2))
                repository, tag = plan['baseline']['image_reference'].rsplit(':', 1)
                env.update(TARGET_REVISION=plan['source_commit'], IMAGE_REPOSITORY=repository,
                           IMAGE_TAG=tag, APPLICATION_VERSION=plan['baseline']['application_version'],
                           REHEARSAL_FAULT_MODE='disabled', REHEARSAL_FAULT_TOKEN_SHA256='')
                with (attempt / 'command.log').open('x') as log:
                    BASE.bounded_command(['bash', str(ROOT / 'scripts/deploy-local-feature-gitops.sh')], env, log)
                data = BASE.snapshot(env)
                BASE.require(data['rollout']['metadata']['annotations'][BASE.ANN + 'application-version'] ==
                             plan['baseline']['application_version'],
                             'GitOps desired baseline version was not restored')
                BASE.require(template_env(data, 'REHEARSAL_FAULT_MODE') == 'disabled' and
                             template_env(data, 'REHEARSAL_FAULT_TOKEN_SHA256') == '',
                             'GitOps desired fault-disabled configuration was not restored')
                state['desired_baseline_restored_at'] = BASE.now()
                (bundle / 'state.json').write_text(json.dumps(state, indent=2))
            elif args.phase == 'final':
                BASE.healthy(data['rollout'])
                BASE.stable_ready(data)
                identity = BASE.image_identity(data, plan['baseline']['application_version'])
                BASE.require(identity['reference'] == plan['baseline']['image_reference'] and
                             identity['runtime_image_id'] == plan['baseline']['runtime_image_id'],
                             'Recovered binary differs from known-good baseline')
                assert_fault_isolation(data, plan, '', False)
                analysis_uid = failed_analysis(data, state)
                assert_gitops_restored(data, plan['source_commit'])
                finished_at = BASE.now()
                whole_seconds = elapsed_seconds(state['prepared_at'], finished_at)
                recovery_seconds = elapsed_seconds(state['recovery_approved_at'], finished_at)
                BASE.require(whole_seconds <= plan['whole_rehearsal_max_seconds'],
                             'Whole rehearsal exceeded its reviewed time bound')
                BASE.require(recovery_seconds <= plan['recovery']['max_seconds'],
                             'Recovery exceeded its reviewed time bound')
                BASE.write(bundle / 'qualification.json', {
                    'version': 'v0.11.9.2.2',
                    'runtime_qualified': True,
                    'environment': 'local',
                    'source_commit': plan['source_commit'],
                    'rollout_uid': plan['baseline']['rollout_uid'],
                    'baseline_release_id': plan['baseline']['release_id'],
                    'failed_analysis_uid': analysis_uid,
                    'fault_mode': 'disabled',
                    'whole_rehearsal_seconds': whole_seconds,
                    'recovery_seconds': recovery_seconds,
                    'finished_at': finished_at,
                })
            if args.phase != 'prepare':
                BASE.write(attempt / 'after.json', data)
            BASE.write(bundle / (args.phase + '.passed.json'),
                       {'at': BASE.now(), 'attempt': attempt.name, 'review_reference': args.review,
                        'runtime_qualified': args.phase == 'final'})
            print(f'{args.phase} passed; evidence={attempt}', flush=True)
        except BaseException as exc:
            BASE.write(attempt / 'failure.json', {'at': BASE.now(), 'error': str(exc),
                                                  'runtime_qualified': False})
            try:
                BASE.write(attempt / 'failure-state.json', BASE.snapshot(env))
            except Exception:
                pass
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=PHASES)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--plan')
    parser.add_argument('--review')
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args()
    try:
        execute(args)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Stopped: {exc}\nPreserve the bundle. No automatic promote, retry, abort or rollback.\n')


if __name__ == '__main__':
    main()

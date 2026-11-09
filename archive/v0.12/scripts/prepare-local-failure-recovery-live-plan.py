#!/usr/bin/env python3
"""Create an exact read-only local failure/recovery plan from a healthy runtime."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = load('successful_rehearsal', ROOT / 'scripts/local-release-rehearsal.py')
FAILURE = load('failure_recovery_rehearsal', ROOT / 'scripts/local-failure-recovery-rehearsal.py')
PLAN = load('failure_recovery_plan', ROOT / 'scripts/check-v0.11.9.2.0-failure-recovery-plan.py')


def concrete(value, name):
    PLAN.concrete(value, name)
    return value


def create(args):
    BASE.require(args.confirm == 'observe-and-write-local-plan', 'Explicit plan confirmation required')
    BASE.require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', args.candidate_version or ''),
                 'Concrete candidate version required')
    for value, name in ((args.review, 'review reference'), (args.operator, 'operator'),
                        (args.recovery_owner, 'recovery owner')):
        concrete(value, name)
    plan_path = Path(args.plan).expanduser().resolve()
    bundle = BASE.bundle_path(args.bundle)
    BASE.require(not plan_path.is_relative_to(ROOT), 'Private plan must be outside the repository')
    BASE.require(not plan_path.exists(), 'Plan path already exists; choose a new path')
    BASE.require(not bundle.exists(), 'Evidence bundle already exists; choose a new path')
    plan_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='local-failure-recovery-preflight-') as tmp:
        env, _, _ = BASE.isolated(args.context, Path(tmp))
        source_commit = BASE.git_identity()
        data = BASE.snapshot(env)
        BASE.gate_profile(data)
        BASE.healthy(data['rollout'])
        BASE.stable_ready(data)
        BASE.require(not any(item.get('status', {}).get('phase') in ('Pending', 'Running')
                             for item in data['analyses']['items']), 'An AnalysisRun is still active')
        rollout = data['rollout']
        baseline_version = rollout['metadata']['annotations'][BASE.ANN + 'application-version']
        BASE.require(args.candidate_version != baseline_version,
                     'Candidate version must differ from the healthy baseline')
        BASE.require(not any(pod['metadata'].get('annotations', {}).get(
            BASE.ANN + 'application-version') == args.candidate_version
            for pod in data['pods']['items'] if not pod['metadata'].get('deletionTimestamp')),
            'Candidate version already exists in live Pods')
        identity = BASE.image_identity(data, baseline_version)
        BASE.require(identity['pull_policy'] == 'Never' and '@' not in identity['reference'] and
                     ':' in identity['reference'].rsplit('/', 1)[-1],
                     'Expected an existing local tagged image with pullPolicy Never')
        FAILURE.assert_fault_isolation(data, {'baseline': {
            'release_id': rollout['metadata']['annotations'][BASE.ANN + 'release-id'],
            'application_version': baseline_version},
            'candidate': {'application_version': args.candidate_version}}, '', False)

        plan = {
            'schema_version': 'v0.11.9.2.0-plan-v1', 'environment': 'local',
            'branch': PLAN.BRANCH, 'source_commit': source_commit, 'context': args.context,
            'review_reference': args.review, 'operator': args.operator,
            'recovery_owner': args.recovery_owner, 'evidence_directory': str(bundle),
            'baseline': {
                'application_version': baseline_version,
                'release_id': rollout['metadata']['annotations'][BASE.ANN + 'release-id'],
                'rollout_uid': rollout['metadata']['uid'],
                'image_reference': identity['reference'],
                'runtime_image_id': identity['runtime_image_id'], 'fault_mode': 'disabled'},
            'candidate': {
                'application_version': args.candidate_version,
                'image_reference': identity['reference'],
                'runtime_image_id': identity['runtime_image_id'],
                'fault_mode': 'availability-503'},
            'fault': {'mechanism': 'candidate-version-header-availability',
                      'service': 'demo-api-canary', 'route': '/version',
                      'header_name': 'X-Rehearsal-Fault', 'response_status': 503,
                      'max_requests': args.max_requests, 'max_seconds': args.analysis_wait_seconds,
                      'cleanup_max_seconds': 300},
            'expected_rejection': {
                'metric': 'canary-availability-error-budget-burn-rate',
                'analysis_phase': 'Failed', 'provider_error_accepted': False,
                'no_data_accepted': False},
            'recovery': {'method': 'gitops-known-good-baseline-restore',
                         'manual_authorization_required': True, 'max_seconds': 600},
            'whole_rehearsal_max_seconds': 1800,
        }
        PLAN.validate(plan)
        with plan_path.open('x') as stream:
            json.dump(plan, stream, indent=2)
        plan_path.chmod(0o600)
        print(json.dumps({'status': 'live_plan_prepared', 'plan': str(plan_path),
                          'bundle': str(bundle), 'source_commit': source_commit,
                          'baseline_version': baseline_version,
                          'candidate_version': args.candidate_version,
                          'execution_started': False, 'runtime_qualified': False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True)
    parser.add_argument('--candidate-version', required=True)
    parser.add_argument('--review', required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--recovery-owner', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--max-requests', type=int, default=80)
    parser.add_argument('--analysis-wait-seconds', type=int, default=180)
    parser.add_argument('--confirm', required=True)
    args = parser.parse_args()
    try:
        create(args)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Stopped: {exc}\nNo fault, traffic, deployment, abort, retry or recovery was executed.\n')


if __name__ == '__main__':
    main()

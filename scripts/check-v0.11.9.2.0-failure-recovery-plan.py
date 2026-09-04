#!/usr/bin/env python3
"""Validate one v0.11.9.2.0 local failure/recovery plan offline only."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'feature/v0.11-observability-sre-baseline'
TOP_FIELDS = {'schema_version', 'environment', 'branch', 'source_commit', 'context',
              'review_reference', 'operator', 'recovery_owner', 'evidence_directory',
              'baseline', 'candidate', 'fault', 'expected_rejection', 'recovery',
              'whole_rehearsal_max_seconds'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def concrete(value, name):
    require(isinstance(value, str) and value.strip(), f'Concrete {name} required')
    require(not any(marker in value for marker in ('REPLACE', 'TODO', '<', '>')),
            f'Concrete {name} required')


def validate(plan):
    require(isinstance(plan, dict) and set(plan) == TOP_FIELDS,
            'Plan fields must match the v0.11.9.2.0 template exactly')
    require(plan['schema_version'] == 'v0.11.9.2.0-plan-v1', 'Plan schema mismatch')
    require(plan['environment'] == 'local', 'Only local failure/recovery design is supported')
    require(plan['branch'] == BRANCH, 'Exact feature branch required')
    require(isinstance(plan['source_commit'], str) and
            re.fullmatch(r'[0-9a-f]{40}', plan['source_commit']), 'Full lowercase source commit required')
    require(isinstance(plan['context'], str) and
            re.fullmatch(r'kind-[A-Za-z0-9._-]+', plan['context']), 'Explicit kind context required')
    for name in ('review_reference', 'operator', 'recovery_owner'):
        concrete(plan[name], name)
    concrete(plan['evidence_directory'], 'evidence_directory')
    evidence = Path(plan['evidence_directory'])
    require(evidence.is_absolute(), 'Absolute private evidence directory required')
    require(not evidence.resolve().is_relative_to(ROOT), 'Evidence directory must be outside repository')

    baseline = plan['baseline']
    candidate = plan['candidate']
    require(isinstance(baseline, dict) and set(baseline) == {
        'application_version', 'release_id', 'rollout_uid', 'image_reference',
        'runtime_image_id', 'fault_mode'}, 'Baseline identity fields mismatch')
    require(isinstance(candidate, dict) and set(candidate) == {
        'application_version', 'image_reference', 'runtime_image_id', 'fault_mode'},
        'Candidate identity fields mismatch')
    for release_name, release in (('baseline', baseline), ('candidate', candidate)):
        require(isinstance(release['application_version'], str) and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', release['application_version']),
                f'Concrete {release_name} application_version required')
        require(isinstance(release['image_reference'], str) and
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9./_-]*:[A-Za-z0-9][A-Za-z0-9._-]{0,127}',
                             release['image_reference']),
                f'Concrete tagged {release_name} image_reference required')
        require(re.fullmatch(r'containerd://sha256:[0-9a-f]{64}', release['runtime_image_id'] or ''),
                f'Concrete {release_name} runtime_image_id required')
    concrete(baseline['release_id'], 'baseline release_id')
    concrete(baseline['rollout_uid'], 'baseline rollout_uid')
    require(baseline['application_version'] != candidate['application_version'],
            'Candidate version must differ from baseline')
    require(baseline['image_reference'] == candidate['image_reference'] and
            baseline['runtime_image_id'] == candidate['runtime_image_id'],
            'Candidate must reuse the exact healthy baseline image reference and runtime imageID')
    require(baseline['fault_mode'] == 'disabled', 'Healthy baseline fault mode must be disabled')
    require(candidate['fault_mode'] == 'availability-503', 'Candidate fault mode mismatch')

    fault = plan['fault']
    require(isinstance(fault, dict) and set(fault) == {
        'mechanism', 'service', 'route', 'header_name', 'response_status', 'max_requests',
        'max_seconds', 'cleanup_max_seconds'}, 'Fault fields mismatch')
    require(fault['mechanism'] == 'candidate-version-header-availability', 'Unsupported fault mechanism')
    require((fault['service'], fault['route'], fault['header_name'], fault['response_status']) ==
            ('demo-api-canary', '/version', 'X-Rehearsal-Fault', 503), 'Fault target mismatch')
    require(type(fault['max_requests']) is int and 20 <= fault['max_requests'] <= 80,
            'Fault request bound must be 20..80')
    require(type(fault['max_seconds']) is int and 30 <= fault['max_seconds'] <= 180,
            'Fault duration bound must be 30..180 seconds')
    require(type(fault['cleanup_max_seconds']) is int and 30 <= fault['cleanup_max_seconds'] <= 300,
            'Fault cleanup bound must be 30..300 seconds')

    rejection = plan['expected_rejection']
    require(rejection == {'metric': 'canary-availability-error-budget-burn-rate',
                           'analysis_phase': 'Failed', 'provider_error_accepted': False,
                           'no_data_accepted': False}, 'Expected rejection must be an exact measured SLO failure')
    recovery = plan['recovery']
    require(isinstance(recovery, dict) and set(recovery) == {
        'method', 'manual_authorization_required', 'max_seconds'}, 'Recovery fields mismatch')
    require(recovery['method'] == 'gitops-known-good-baseline-restore' and
            recovery['manual_authorization_required'] is True, 'Recovery must be explicit and human-authorized')
    require(type(recovery['max_seconds']) is int and 60 <= recovery['max_seconds'] <= 600,
            'Recovery bound must be 60..600 seconds')
    require(type(plan['whole_rehearsal_max_seconds']) is int and
            600 <= plan['whole_rehearsal_max_seconds'] <= 1800,
            'Whole rehearsal bound must be 600..1800 seconds')
    return {'status': 'failure_recovery_plan_validated_offline',
            'runtime_qualified': False, 'execution_authorized': False,
            'fault_implemented': False,
            'checks_not_performed': ['git_identity', 'cluster_identity', 'baseline_health',
                                     'fault_injection', 'analysis_failure', 'abort',
                                     'recovery', 'stable_availability']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(json.loads(args.plan.read_text())), indent=2))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f'Plan rejected: {exc}\nNo execution is authorized.\n')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Local reviewed evidence archive. Never observes, qualifies or promotes a runtime."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CAPS = {'metrics', 'dashboards', 'alerts', 'logs', 'traces', 'slo', 'progressiveDeliveryTelemetry'}
STATUSES = {'supported-verified', 'supported-not-verified', 'not-deployed', 'not-applicable'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key.')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Non-finite JSON number is not allowed.')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


def timestamp(value):
    require(isinstance(value, str), 'Timestamp must be a string.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Timestamp must include timezone.')
    return parsed


def validate_evidence(raw, kind):
    doc = read_json(raw)
    require(kind in ('raw', 'redacted'), 'Evidence kind must be explicit.')
    require(isinstance(doc, dict) and set(doc) == {'schemaVersion', 'qualificationVersion', 'environment', 'status',
            'observationWindow', 'identity', 'approval', 'capabilities', 'checks'}, 'Unsupported evidence shape; summaries/legacy evidence are not runtime payloads.')
    require(doc['schemaVersion'] == 'v0.11.8.0', 'Unsupported schema version.')
    env = doc['environment']
    require(env in ('local', 'aws-dev', 'aws-test', 'aws-prod'), 'Unknown environment.')
    require(doc['qualificationVersion'] in ('v0.11.8.1', 'v0.11.8.2', 'v0.11.8.3', 'v0.11.8.4'), 'Unknown qualification version.')
    require(doc['status'] in ('qualified', 'waiting-runtime', 'failed'), 'Unknown evidence status.')
    window = doc['observationWindow']
    require(set(window) == {'startedAt', 'finishedAt'} and timestamp(window['startedAt']) <= timestamp(window['finishedAt']), 'Invalid observation window.')
    identity = doc['identity']
    required = {'clusterName', 'kubeContext', 'repositoryCommit', 'targetRevision', 'applicationVersion'}
    require(required <= set(identity) <= required | {'awsAccountId', 'awsRegion'}, 'Invalid identity fields.')
    for key in required:
        require(isinstance(identity[key], str) and bool(identity[key].strip()), 'Empty identity field.')
    for key in ('repositoryCommit', 'targetRevision'):
        require(re.fullmatch(r'[0-9a-f]{40}', identity[key]), 'Expected exact SHA.')
    require(identity['repositoryCommit'] == identity['targetRevision'], 'Source/target SHA mismatch.')
    if env.startswith('aws-'):
        account, region = identity.get('awsAccountId', ''), identity.get('awsRegion', '')
        require(isinstance(account, str) and (bool(re.fullmatch(r'[0-9]{12}', account)) if kind == 'raw' else account == '***'),
                'Raw account must be 12 digits; redacted account must be ***.')
        require(isinstance(region, str) and bool(re.fullmatch(r'[a-z]{2}-[a-z]+-[0-9]+', region)), 'Invalid AWS region.')
        cluster = 'startup-devops-baseline-' + env.removeprefix('aws-')
        require(identity['clusterName'] == cluster and identity['kubeContext'] == f'arn:aws:eks:{region}:{account}:cluster/{cluster}',
                'Cross-environment/context identity mismatch.')
    approval = doc['approval']
    require({'required', 'approved'} <= set(approval) <= {'required', 'approved', 'reference'}
            and type(approval['required']) is bool and type(approval['approved']) is bool, 'Invalid approval shape.')
    require(approval.get('reference') is None or isinstance(approval['reference'], str), 'Invalid approval reference.')
    if env == 'aws-prod':
        require(approval['required'] and approval['approved'] and isinstance(approval.get('reference'), str)
                and bool(approval['reference'].strip()), 'Prod evidence requires recorded approval.')
    checks = doc['checks']
    require(isinstance(checks, list) and bool(checks), 'Evidence checks missing.')
    by_id = {}
    for check in checks:
        require({'id', 'outcome'} <= set(check) <= {'id', 'outcome', 'observedValue', 'diagnostic'}, 'Invalid check shape.')
        name = check['id']
        require(isinstance(name, str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]+', name) and name not in by_id, 'Invalid/duplicate check ID.')
        require(check['outcome'] in ('passed', 'failed', 'not-run'), 'Invalid check outcome.')
        require(check.get('observedValue') is None or isinstance(check['observedValue'], (str, int, float, bool)), 'Check value must be scalar.')
        require(check.get('diagnostic') is None or isinstance(check['diagnostic'], str), 'Invalid diagnostic.')
        by_id[name] = check
    require(set(doc['capabilities']) == CAPS, 'Capability inventory mismatch.')
    for capability in doc['capabilities'].values():
        require(set(capability) == {'status', 'evidenceCheckIds'} and capability['status'] in STATUSES, 'Invalid capability.')
        refs = capability['evidenceCheckIds']
        require(isinstance(refs, list) and all(isinstance(x, str) for x in refs)
                and len(refs) == len(set(refs)) and set(refs) <= set(by_id), 'Unknown/duplicate check reference.')
        if capability['status'] == 'supported-verified':
            require(refs and all(by_id[x]['outcome'] == 'passed' for x in refs), 'Verified capability needs passing checks.')
    verified = any(x['status'] == 'supported-verified' for x in doc['capabilities'].values())
    if doc['status'] == 'qualified':
        require(verified and all(x['outcome'] == 'passed' for x in checks), 'Qualified evidence has nonpassing checks.')
    if doc['status'] == 'waiting-runtime':
        require(not verified and any(x['outcome'] == 'not-run' for x in checks)
                and not any(x['outcome'] == 'failed' for x in checks), 'Waiting runtime cannot imply verified or failed runtime.')
    if doc['status'] == 'failed':
        require(any(x['outcome'] != 'passed' for x in checks), 'Failed evidence needs an unsuccessful check.')
    return doc


def summary(doc):
    checks = doc['checks']
    modes = [x.get('observedValue') for x in checks if x['id'] in ('identity.rbac-mode', 'rbac.read-only')]
    images = [x.get('observedValue') for x in checks if x['id'] == 'release.image']
    return {'environment': doc['environment'], 'status': doc['status'], 'identity': doc['identity'],
            'observationWindow': doc['observationWindow'], 'capabilities': doc['capabilities'],
            'mode': modes[0] if len(modes) == 1 else 'not-recorded',
            'image': images[0] if len(images) == 1 else None,
            'current_runtime_qualified': False, 'promotion_eligible': False}


def safe_root(path):
    path = Path(path).expanduser()
    require(not path.is_symlink(), 'Archive must not be a symlink.')
    resolved = path.resolve()
    require(resolved != Path('/') and not resolved.is_relative_to(ROOT), 'Use a dedicated private archive outside the repository.')
    return resolved


def register(root, source, kind, reference):
    require(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', reference)), 'Review reference required.')
    source = Path(source)
    require(source.is_file() and not source.is_symlink(), 'Evidence must be a regular file.')
    raw = source.read_bytes()
    doc = validate_evidence(raw, kind)
    root = safe_root(root)
    if root.exists():
        verify(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    entry = root / digest(raw)
    # Atomic reservation prevents duplicate/concurrent registration overwrites.
    # An interrupted directory is kept for diagnosis; verification fails closed.
    entry.mkdir(mode=0o700)
    record = {'indexVersion': 'v0.11.8.4', 'sha256': entry.name, 'kind': kind,
              'reviewReference': reference, 'registeredAt': datetime.now(timezone.utc).isoformat(),
              'summary': summary(doc)}
    with (entry / 'evidence.json').open('xb') as handle:
        handle.write(raw)
    with (entry / 'record.json').open('x') as handle:
        json.dump(record, handle, indent=2)
        handle.write('\n')
    return entry.name


def verify(root, baseline=None):
    root = safe_root(root)
    require(root.is_dir(), 'Archive directory does not exist.')
    entries = {}
    for entry in sorted(root.iterdir()):
        require(not entry.is_symlink() and entry.is_dir() and re.fullmatch(r'[0-9a-f]{64}', entry.name), 'Unexpected archive entry.')
        require({x.name for x in entry.iterdir()} == {'evidence.json', 'record.json'}, 'Incomplete/unexpected archive entry files.')
        for filename in ('evidence.json', 'record.json'):
            require(not (entry / filename).is_symlink() and (entry / filename).is_file(), 'Redirected archive file.')
        raw = (entry / 'evidence.json').read_bytes()
        record_raw = (entry / 'record.json').read_bytes()
        record = read_json(record_raw)
        require(set(record) == {'indexVersion', 'sha256', 'kind', 'reviewReference', 'registeredAt', 'summary'}
                and record['indexVersion'] == 'v0.11.8.4', 'Invalid index record.')
        require(record['sha256'] == entry.name == digest(raw), 'Evidence hash changed.')
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', record['reviewReference']), 'Missing review reference.')
        timestamp(record['registeredAt'])
        require(record['summary'] == summary(validate_evidence(raw, record['kind'])), 'Index summary differs from evidence.')
        entries[entry.name] = digest(record_raw)
    if baseline is not None:
        old = read_json(Path(baseline).read_bytes())
        require(set(old) == {'indexVersion', 'entries'} and old['indexVersion'] == 'v0.11.8.4'
                and isinstance(old['entries'], dict), 'Invalid baseline snapshot.')
        require(all(entries.get(key) == value for key, value in old['entries'].items()), 'Append-only violation: old entry removed or changed.')
    return {'indexVersion': 'v0.11.8.4', 'entries': entries}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    add = sub.add_parser('register')
    add.add_argument('--archive', required=True)
    add.add_argument('--evidence', required=True)
    add.add_argument('--kind', choices=('raw', 'redacted'), required=True)
    add.add_argument('--review-reference', required=True)
    for name in ('verify', 'snapshot'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--archive', required=True)
        cmd.add_argument('--baseline')
        if name == 'snapshot':
            cmd.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.action == 'register':
        print('Archived historical evidence: ' + register(args.archive, args.evidence, args.kind, args.review_reference))
    else:
        snapshot = verify(args.archive, args.baseline)
        if args.action == 'snapshot':
            output = Path(args.output).expanduser()
            require(not output.resolve().is_relative_to(safe_root(args.archive)), 'Keep snapshots outside the archive entries directory.')
            with output.open('x') as handle:
                json.dump(snapshot, handle, indent=2)
                handle.write('\n')
        print(f'Archive verified: {len(snapshot["entries"])} historical entries; no runtime qualification performed.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise SystemExit(str(error)) from error

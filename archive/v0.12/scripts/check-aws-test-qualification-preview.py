#!/usr/bin/env python3
"""Offline rendered-manifest checks. Never contacts AWS or Kubernetes APIs."""
import argparse
import copy
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'delivery/contracts/v0.11.8.2.0-aws-test-qualification-prerequisites.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def index(documents):
    result = {}
    for item in documents:
        if not item:
            continue
        key = (item['apiVersion'], item['kind'], item['metadata'].get('namespace', ''), item['metadata']['name'])
        require(key not in result, f'duplicate resource: {key}')
        result[key] = item
    return result


def validate(stable, preview, contract):
    stable, preview = index(stable), index(preview)
    require(stable.keys() == preview.keys(), 'resource inventory changed')
    git_names, charts = set(), {}
    expected = copy.deepcopy(stable)
    for key, item in expected.items():
        if item['kind'] != 'Application':
            continue
        source = item['spec']['source']
        name = item['metadata']['name']
        if source.get('repoURL') == contract['repository']:
            require(source['targetRevision'] == 'main', f'stable test revision changed: {name}')
            git_names.add(name)
            source['targetRevision'] = contract['qualification_revision']
        else:
            chart = source.get('chart')
            require(chart in contract['external_charts'],
                    f'unexpected external source: application={name}, chart={chart}')
            revision = source.get('targetRevision')
            require(revision == contract['external_charts'][chart],
                    f'external Chart revision mismatch: application={name}, chart={chart}, '
                    f'expected={contract["external_charts"][chart]}, actual={revision}')
            require(chart not in charts,
                    f'duplicate external Chart: application={name}, chart={chart}')
            charts[chart] = revision
        if name == 'monitoring-aws-test':
            g = contract['grafana']
            source['helm']['valuesObject']['grafana']['admin'] = {
                'existingSecret': g['secret'], 'userKey': g['user_key'], 'passwordKey': g['password_key']}
    require(git_names == set(contract['same_repository_applications']), 'same-repository inventory mismatch')
    require(charts == contract['external_charts'], 'external Chart pins/inventory changed')
    require(expected == preview, 'preview differs outside allowed revisions/Grafana Secret, or required changes missing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stable', type=Path, required=True)
    parser.add_argument('--preview', type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(list(yaml.safe_load_all(args.stable.read_text())),
                 list(yaml.safe_load_all(args.preview.read_text())), json.loads(CONTRACT.read_text()))
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        raise SystemExit(f'FAIL: {error}') from error
    print('PASS: aws-test qualification preview boundary (offline only; not live acceptance).')


if __name__ == '__main__':
    main()

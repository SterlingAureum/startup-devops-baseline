#!/usr/bin/env python3
"""Create-only runtime Secret; never print, persist, or rotate credentials."""
import base64
import json
import os
import re
import secrets
import subprocess
import sys


def kube(*args, data=None):
    result = subprocess.run(['kubectl', '--request-timeout=30s', *args],
                            input=data, text=True, capture_output=True)
    if result.returncode:
        # Do not echo API responses that might contain a credential manifest.
        raise SystemExit('Kubernetes operation failed; check context/RBAC (credential output suppressed).')
    return result.stdout


def main():
    account = os.environ.get('EXPECTED_AWS_ACCOUNT_ID', '')
    region = os.environ.get('AWS_REGION', 'us-east-1')
    if not re.fullmatch(r'\d{12}', account):
        raise SystemExit('EXPECTED_AWS_ACCOUNT_ID is required.')
    expected = f'arn:aws:eks:{region}:{account}:cluster/startup-devops-baseline-dev'
    if kube('config', 'current-context').strip() != expected:
        raise SystemExit('Context must be the exact intended aws-dev EKS ARN.')
    if os.environ.get('CONFIRM_GRAFANA_SECRET') != 'prepare-aws-dev':
        raise SystemExit('Set CONFIRM_GRAFANA_SECRET=prepare-aws-dev.')
    namespace = kube('get', 'namespace', 'observability', '--ignore-not-found', '-o', 'json')
    if not namespace.strip():
        kube('create', 'namespace', 'observability')
    target = 'observability-grafana-admin'

    def read(name):
        raw = kube('-n', 'observability', 'get', 'secret', name, '--ignore-not-found', '-o', 'json')
        return json.loads(raw) if raw.strip() else None

    def validate(secret):
        data = secret.get('data', {})
        for key in ('admin-user', 'admin-password'):
            if not base64.b64decode(data.get(key, ''), validate=True):
                raise SystemExit('Credential Secret has missing or empty keys; refusing overwrite.')
        return {key: data[key] for key in ('admin-user', 'admin-password')}

    existing = read(target)
    if existing is not None:
        validate(existing)
        print('Existing independent Grafana Secret preserved.')
        return
    source = read('observability-metrics-grafana')
    if source is not None:
        data = validate(source)
    else:
        data = {key: base64.b64encode(value.encode()).decode() for key, value in
                [('admin-user', 'admin'), ('admin-password', secrets.token_urlsafe(36))]}
    manifest = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
                'metadata': {'name': target, 'namespace': 'observability'}, 'data': data}
    # No Argo tracking metadata copied. Create refuses an unexpected existing target.
    kube('create', '-f', '-', data=json.dumps(manifest))
    print('Independent Grafana Secret prepared. No credential values were printed.')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Explicitly authorized test-only plan/apply/bootstrap; never qualifies or promotes."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
sys.dont_write_bytecode = True
import aws_test_feature_common as c
import yaml


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tf(*args, **kwargs):
    return c.run(['terraform', f'-chdir={c.TF}', *args], **kwargs)


def variable_inputs():
    """Fingerprint the single permitted local variable file, without parsing HCL."""
    c.require(not c.TF.is_symlink(), 'Terraform root must not be a symlink.')
    for path in c.TF.iterdir():
        c.require(not (path.name.endswith('.auto.tfvars') or path.name.endswith('.auto.tfvars.json')
                       or path.name == 'terraform.tfvars.json'),
                  f'Unreviewed additional variable file: {path.name}; only terraform.tfvars is supported.')
    local = c.TF / 'terraform.tfvars'
    c.require(not local.is_symlink(), 'terraform.tfvars must not be a symlink.')
    c.require(not local.exists() or local.is_file(), 'terraform.tfvars must be a regular file.')
    return {'terraform.tfvars': digest(local) if local.exists() else None}


def initialize():
    variable_inputs()
    for name in ('.terraform', 'terraform.tfstate'):
        c.require(not (c.TF / name).is_symlink(), f'Refusing redirected test state: {name}')
    cache = c.TF / '.terraform/terraform.tfstate'
    if cache.exists():
        backend = json.loads(cache.read_text()).get('backend', {})
        c.require(backend.get('type', 'local') == 'local' and not backend.get('config', {}).get('path'),
                  'Use the independent default local test backend; no state migration is automatic.')
    tf('init', '-input=false')
    c.require(tf('workspace', 'show').strip() == 'default', 'Only the independent default test workspace is allowed.')


def check_plan(document, account, cidr):
    variables = {k: v['value'] for k, v in document['variables'].items()}
    expected = {'environment': 'test', 'project_name': 'startup-devops-baseline',
                'aws_region': c.REGION, 'eks_node_min_size': 4, 'eks_node_desired_size': 4,
                'eks_node_max_size': 4, 'eks_public_access_cidrs': [cidr]}
    c.require(all(variables.get(k) == v for k, v in expected.items()), 'Plan variables differ from the fixed test/capacity/IP contract.')
    enabled = variables.get('enable_github_actions_runtime_identity', False)
    role = variables.get('github_actions_runtime_role_arn')
    expected_role = f'arn:aws:iam::{account}:role/startup-devops-baseline-test-github-runtime-read-role'
    c.require(type(enabled) is bool, 'Runtime identity flag must be Boolean.')
    c.require(role is None or role == expected_role, 'Runtime Role must be the exact test role in the expected account.')
    c.require(not enabled or role == expected_role, 'Enabled runtime identity requires the exact test Role ARN.')
    changes = document.get('resource_changes', [])
    c.require(not any('delete' in x['change']['actions'] for x in changes),
              'Plan contains deletion/replacement; review separately, no automatic destructive repair.')
    clusters = [x for x in changes if x['type'] == 'aws_eks_cluster']
    c.require(len(clusters) == 1, 'Plan must identify exactly one test EKS cluster.')
    for item in changes:
        after = item['change'].get('after') or {}
        arn = after.get('arn') or ''
        if arn.startswith('arn:aws:') and len(arn.split(':')) > 4 and arn.split(':')[4]:
            c.require(arn.split(':')[4] in (account, 'aws'), 'Plan includes a different AWS account.')
        tags = after.get('tags_all') or after.get('tags') or {}
        c.require(tags.get('Environment', 'test') in ('test', 'aws-test'), 'Plan includes a non-test resource tag.')
    c.require(clusters[0]['change']['after']['name'] == c.CLUSTER, 'Plan targets a non-test cluster.')
    entries = [x for x in changes if x['type'] == 'aws_eks_access_entry'
               and x.get('address', '').startswith('module.github_actions_runtime_identity[')]
    c.require(len(entries) == (1 if enabled else 0), 'Runtime EKS access entry inventory does not match the enable flag.')
    if enabled:
        entry = entries[0]['change']['after']
        c.require(entry.get('principal_arn') == expected_role and entry.get('cluster_name') == c.CLUSTER
                  and entry.get('kubernetes_groups') == ['demo-api-runtime-qualification'],
                  'Runtime EKS access entry differs from the bounded test mapping.')
    return expected_role if enabled else None


def check_role_exists(role):
    if role:
        actual = c.aws('iam', 'get-role', '--role-name', role.rsplit('/', 1)[1],
                       '--query', 'Role.Arn', '--output', 'text').strip()
        c.require(actual == role, 'Persistent test runtime Role is absent or mismatched; no Role is created automatically.')


def check_test_secret(account, document=None):
    """Read metadata only; never delete, restore, import or read credentials."""
    name = 'startup-devops-baseline-test/demo-api/postgresql'
    proc = c.subprocess.run(
        ['aws', '--region', c.REGION, 'secretsmanager', 'describe-secret',
         '--secret-id', name, '--output', 'json'],
        env=c.environment(), text=True, capture_output=True, timeout=90)
    if proc.returncode:
        absent = re.search(r'\(ResourceNotFoundException\) when calling the DescribeSecret operation', proc.stderr)
        c.require(absent, 'Test Secret metadata lookup failed (not confirmed absent). Check AWS credentials, '
                  'secretsmanager:DescribeSecret permission and connectivity; no recovery action was executed.')
        return
    secret = json.loads(proc.stdout)
    c.require(isinstance(secret, dict), 'Malformed test Secret metadata response; stop.')
    prefix = f'arn:aws:secretsmanager:{c.REGION}:{account}:secret:{name}-'
    c.require(secret.get('Name') == name and bool(re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9]{6}', secret.get('ARN', ''))),
              'Test Secret metadata identity mismatch; stop and review the account/region/name.')
    c.require(not secret.get('DeletedDate'),
              'Test Secret is scheduled for deletion; its name is not reusable. '
              'See docs/V0.11.8.2.2_TEST_CLOSURE_AND_REBUILD.md. '
              'Preserve Terraform state; explicitly review recovery or permanent deletion, then generate a new plan. '
              'No Secret was deleted or restored by this preflight.')
    if document is not None:
        creating = any(item.get('address') == 'module.external_secrets.aws_secretsmanager_secret.this'
                       and 'create' in item.get('change', {}).get('actions', [])
                       for item in document.get('resource_changes', []))
        c.require(not creating, 'An active same-name test Secret already exists but the plan would create it. '
                  'Review ownership/state separately; no automatic import or deletion is allowed.')


def plan(args):
    address = ipaddress.ip_address(args.management_ip)
    c.require(address.version == 4 and address.is_global, 'Provide your current globally routable management IPv4; never commit it.')
    cidr = f'{address}/32'
    inputs = variable_inputs()
    profile_hash = digest(c.PROFILE)
    check_test_secret(args.account)
    initialize()
    state = c.TF / 'terraform.tfstate'
    resources = json.loads(state.read_text()).get('resources', []) if state.exists() else []
    cluster = c.discover(args.account)
    if args.mode == 'create':
        c.require(not resources and cluster is None, 'Test state/cluster already exists; inspect and use resume.')
    else:
        c.require(resources, 'Resume requires existing test state; do not import/adopt an unmanaged cluster automatically.')
    bundle = Path(args.bundle).expanduser().resolve()
    c.require(not bundle.is_relative_to(c.ROOT), 'Keep the sensitive plan bundle outside the repository.')
    bundle.mkdir(mode=0o700, parents=True, exist_ok=False)
    output = bundle / 'review.tfplan'
    tf('plan', '-input=false', f'-out={output}', f'-var-file={c.PROFILE}',
       '-var=environment=test', '-var=project_name=startup-devops-baseline',
       f'-var=aws_region={c.REGION}', f'-var=eks_public_access_cidrs=["{cidr}"]', timeout=1800)
    document = json.loads(tf('show', '-json', output))
    role = check_plan(document, args.account, cidr)
    check_test_secret(args.account, document)
    check_role_exists(role)
    c.require(variable_inputs() == inputs and digest(c.PROFILE) == profile_hash,
              'Variable inputs changed while planning; generate a new reviewed plan.')
    # Finish human-readable rendering before recording a completed plan bundle.
    tf('show', '-no-color', output, capture=False)
    record = {'account': args.account, 'sha': args.sha, 'region': c.REGION, 'cluster': c.CLUSTER,
              'mode': args.mode, 'cluster_present': cluster is not None,
              'created_at': time.time(), 'plan_sha256': digest(output),
              'profile_sha256': profile_hash, 'variable_inputs': inputs, 'cidr': cidr}
    (bundle / 'review.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'Plan saved: {bundle}. Review cost/resource changes. Apply is a separate command; plan expires after one hour.')


def apply(args):
    c.require(args.confirm == 'apply-reviewed-aws-test', 'Explicit apply confirmation is required.')
    bundle = Path(args.bundle).expanduser().resolve()
    c.require((bundle / 'review.json').is_file() and (bundle / 'review.tfplan').is_file(),
              'Incomplete plan bundle: review.json or review.tfplan is missing. Run plan successfully with a new bundle path; do not create review.json manually.')
    record = json.loads((bundle / 'review.json').read_text())
    output = bundle / 'review.tfplan'
    c.require(record['account'] == args.account and record['sha'] == args.sha
              and record['region'] == c.REGION and record['cluster'] == c.CLUSTER, 'Plan identity mismatch.')
    c.require(0 <= time.time() - record['created_at'] <= 3600, 'Plan expired; regenerate and review.')
    c.require(digest(output) == record['plan_sha256'] and digest(c.PROFILE) == record['profile_sha256'], 'Plan/profile changed after review.')
    c.require('variable_inputs' in record, 'Legacy plan has no variable fingerprint; generate a new plan with v0.11.8.2.1.2.')
    c.require(variable_inputs() == record['variable_inputs'], 'terraform.tfvars was added, removed or changed since plan review; generate a new plan.')
    initialize()
    document = json.loads(tf('show', '-json', output))
    role = check_plan(document, args.account, record['cidr'])
    check_test_secret(args.account, document)
    check_role_exists(role)
    cluster = c.discover(args.account)
    c.require((cluster is not None) == record['cluster_present'], 'Cluster existence changed since planning.')
    c.require(variable_inputs() == record['variable_inputs'] and digest(c.PROFILE) == record['profile_sha256'],
              'Variable inputs changed during apply preflight; regenerate the plan.')
    tf('apply', '-input=false', output, timeout=5400, capture=False)
    c.aws('eks', 'wait', 'cluster-active', '--name', c.CLUSTER, timeout=1800)
    cluster = c.discover(args.account)
    c.require(cluster['resourcesVpcConfig']['publicAccessCidrs'] == [record['cidr']], 'Unexpected endpoint allowlist.')
    print('Infrastructure apply completed. Node readiness/bootstrap and qualification remain separate.')


def secret(env):
    raw = c.kube(env, 'get', 'namespace', 'observability', '--ignore-not-found', '-o', 'json')
    if not raw.strip():
        c.kube(env, 'create', 'namespace', 'observability')
    raw = c.kube(env, '-n', 'observability', 'get', 'secret', 'observability-grafana-admin', '--ignore-not-found', '-o', 'json')
    if raw.strip():
        values = json.loads(raw).get('data', {})
        for key in ('admin-user', 'admin-password'):
            c.require(bool(base64.b64decode(values.get(key, ''), validate=True)), 'Existing Grafana Secret invalid; refusing overwrite.')
        print('Existing test Grafana Secret preserved; no rotation.')
        return
    data = {k: base64.b64encode(v.encode()).decode() for k, v in
            [('admin-user', 'admin'), ('admin-password', secrets.token_urlsafe(36))]}
    obj = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque', 'metadata': {
        'name': 'observability-grafana-admin', 'namespace': 'observability'}, 'data': data}
    c.kube(env, 'create', '-f', '-', data=json.dumps(obj))
    print('Independent test Grafana Secret created. No dev credentials copied.')


def bootstrap(args):
    c.require(args.confirm == 'bootstrap-reviewed-aws-test', 'Explicit bootstrap confirmation is required.')
    c.require(bool(re.fullmatch(r'v\d+\.\d+\.\d+', args.argocd_version)), 'Supply a reviewed exact Argo CD release, not stable/latest.')
    initialize()
    c.require(tf('output', '-raw', 'eks_cluster_name').strip() == c.CLUSTER, 'Terraform output does not identify test.')
    c.require(tf('output', '-raw', 'environment_name').strip() == 'test', 'Terraform output environment mismatch.')
    with tempfile.TemporaryDirectory(prefix='aws-test-bootstrap-') as directory:
        env = c.kube_env(args.account, directory)
        c.wait_capacity(env)
        # Existing root must already be the feature mode; never silently replace
        # a stable-main root that happens to use the same Application name.
        namespace = c.kube(env, 'get', 'namespace', 'argocd', '--ignore-not-found', '-o', 'json')
        if namespace.strip():
            server = c.kube(env, '-n', 'argocd', 'get', 'deployment', 'argocd-server', '--ignore-not-found', '-o', 'json')
            if server.strip():
                images = [x['image'] for x in json.loads(server)['spec']['template']['spec']['containers']
                          if x['name'] == 'argocd-server']
                c.require(len(images) == 1 and images[0].endswith(':' + args.argocd_version),
                          'Existing Argo CD version differs; upgrades/digest-tag migration need separate review.')
            crd = c.kube(env, 'get', 'crd', 'applications.argoproj.io', '--ignore-not-found', '-o', 'json')
            if crd.strip():
                apps = c.get(env, '-n', 'argocd', 'get', 'applications')
                for app in apps['items']:
                    name = app['metadata']['name']
                    if name.startswith('startup-devops-') and name.endswith('-root'):
                        source = app['spec']['source']
                        c.require(name == 'startup-devops-aws-test-root' and source['path'] == c.OVERLAY
                                  and source['targetRevision'] == c.BRANCH, 'Conflicting root exists; do not replace it automatically.')
        secret(env)
        root = yaml.safe_load((c.ROOT / 'clusters/aws/overlays/test/root-app.yaml').read_text())
        root['spec']['source'].update(path=c.OVERLAY, targetRevision=c.BRANCH)
        source_file = Path(directory) / 'feature-root.yaml'
        source_file.write_text(yaml.safe_dump(root))
        env.update(ARGOCD_VERSION=args.argocd_version, SOURCE_FILE=str(source_file),
                   TARGET_REVISION=c.BRANCH, ROOT_APPLICATION='startup-devops-aws-test-root',
                   DEMO_APPLICATION='demo-api-aws-test', DEMO_HOSTNAME='demo.test.aureumstack.com',
                   DEMO_ACCEPTED_HEALTH_STATUSES='Healthy,Suspended,Progressing')
        c.run(['bash', c.ROOT / 'scripts/bootstrap-eks-argocd.sh'], env=env, capture=False, timeout=2400)
        c.preflight(args.account, args.sha)
        c.run(['bash', c.ROOT / 'scripts/deploy-aws-dev-root-app.sh'], env=env, capture=False, timeout=7200)
    print('Bootstrap completed; review any canary pause separately. No promote or qualification was performed.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', default=os.environ.get('EXPECTED_AWS_ACCOUNT_ID', ''))
    parser.add_argument('--sha', default=os.environ.get('EXPECTED_CONTROL_PLANE_SHA', ''))
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--mode', choices=('create', 'resume'), required=True)
    p.add_argument('--management-ip', required=True)
    p.add_argument('--bundle', required=True)
    p = sub.add_parser('apply')
    p.add_argument('--bundle', required=True)
    p.add_argument('--confirm', required=True)
    p = sub.add_parser('bootstrap')
    p.add_argument('--argocd-version', required=True)
    p.add_argument('--confirm', required=True)
    args = parser.parse_args()
    c.preflight(args.account, args.sha)
    c.release()
    {'plan': plan, 'apply': apply, 'bootstrap': bootstrap}[args.action](args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error)) from error

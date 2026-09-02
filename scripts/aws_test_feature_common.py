"""Fixed-target AWS test guards shared by mutation and observation entrypoints."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'feature/v0.11-observability-sre-baseline'
REPO = 'https://github.com/SterlingAureum/startup-devops-baseline.git'
CLUSTER = 'startup-devops-baseline-test'
REGION = 'us-east-1'
TF = ROOT / 'infra/terraform/aws/environments/test'
PROFILE = ROOT / 'delivery/profiles/aws-test-observability-qualification.tfvars'
OVERLAY = 'clusters/aws/overlays/test-feature-qualification'
CONTRACT = ROOT / 'delivery/contracts/v0.11.8.2.0-aws-test-qualification-prerequisites.json'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def environment():
    # Preserve configured AWS authentication; never inherit Terraform CLI/var
    # injection, target overrides, or a user's active kubeconfig into helpers.
    allowed = {'PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'SSL_CERT_FILE',
               'SSL_CERT_DIR', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY',
               'https_proxy', 'http_proxy', 'no_proxy'}
    env = {k: v for k, v in os.environ.items() if k in allowed or k.startswith('AWS_')}
    for key in list(env):
        if key.startswith('AWS_ENDPOINT_URL') or key in ('AWS_DATA_PATH', 'AWS_CA_BUNDLE'):
            del env[key]
    env.update(AWS_REGION=REGION, AWS_DEFAULT_REGION=REGION, AWS_PAGER='',
               AWS_ENVIRONMENT='aws-test', CLUSTER_NAME=CLUSTER, TF_DIR=str(TF),
               PYTHONDONTWRITEBYTECODE='1')
    return env


def run(args, env=None, data=None, timeout=120, capture=True):
    proc = subprocess.run([str(x) for x in args], env=env or environment(),
                          input=data, text=True, capture_output=capture, timeout=timeout)
    require(proc.returncode == 0, f'Command failed: {args[0]} (exit {proc.returncode}); inspect the operation locally.')
    return proc.stdout if capture else ''


def aws(*args, **kwargs):
    return run(['aws', '--region', REGION, *args], **kwargs)


def git(*args):
    return run(['git', '-C', ROOT, *args]).strip()


def preflight(account, sha):
    require(bool(re.fullmatch(r'[0-9]{12}', account)), 'Expected AWS account must have 12 digits.')
    require(bool(re.fullmatch(r'[0-9a-f]{40}', sha)), 'Expected SHA must be a full lowercase commit.')
    require(git('branch', '--show-current') == BRANCH, 'Use the reviewed feature branch, not main/dev/prod.')
    require(not git('status', '--porcelain'), 'Commit all changes before live execution.')
    require(git('rev-parse', 'HEAD') == sha, 'Local HEAD differs from expected SHA.')
    remote = git('ls-remote', '--exit-code', REPO, f'refs/heads/{BRANCH}').split()
    require(remote and remote[0] == sha, 'Push the reviewed SHA; remote branch moved or differs.')
    require(aws('sts', 'get-caller-identity', '--query', 'Account', '--output', 'text').strip() == account,
            'AWS account mismatch.')


def discover(account):
    proc = subprocess.run(['aws', '--region', REGION, 'eks', 'describe-cluster', '--name', CLUSTER],
                          env=environment(), text=True, capture_output=True, timeout=90)
    if proc.returncode:
        require('ResourceNotFoundException' in proc.stderr, 'EKS discovery failed; not evidence that the cluster is absent.')
        return None
    cluster = json.loads(proc.stdout)['cluster']
    require(cluster['arn'] == f'arn:aws:eks:{REGION}:{account}:cluster/{CLUSTER}', 'Unexpected EKS ARN.')
    return cluster


def kube_env(account, directory):
    cluster = discover(account)
    require(cluster and cluster['status'] == 'ACTIVE', 'Exact test cluster must be ACTIVE.')
    env = environment()
    env['KUBECONFIG'] = str(Path(directory) / 'kubeconfig')
    aws('eks', 'update-kubeconfig', '--name', CLUSTER, '--kubeconfig', env['KUBECONFIG'], env=env)
    actual = run(['kubectl', 'config', 'view', '--minify', '-o', 'json'], env=env)
    config = json.loads(actual)
    require(config['current-context'] == cluster['arn'], 'Unexpected Kubernetes context.')
    require(config['clusters'][0]['cluster']['server'] == cluster['endpoint'], 'Kubernetes endpoint mismatch.')
    return env


def kube(env, *args, data=None):
    return run(['kubectl', '--request-timeout=30s', *args], env=env, data=data, timeout=45)


def get(env, *args):
    return json.loads(kube(env, *args, '-o', 'json'))


def can_i(env, *args):
    proc = subprocess.run(['kubectl', '--request-timeout=30s', 'auth', 'can-i', *args],
                          env=env, text=True, capture_output=True, timeout=45)
    value = proc.stdout.strip()
    require((proc.returncode == 0 and value == 'yes') or (proc.returncode == 1 and value == 'no'),
            'RBAC discovery failed; API/auth failures are not a denied-permission result.')
    return value == 'yes'


def release():
    value = yaml.safe_load((ROOT / 'apps/demo-api/helm/values/releases/aws-test.yaml').read_text())
    image = value['image']
    require(bool(re.fullmatch(r'sha256:[0-9a-f]{64}', image.get('digest', ''))), 'Test release must pin an image digest.')
    version = value['release']['applicationVersion']
    require(bool(version) and bool(re.fullmatch(r'[0-9a-f]{40}', value['delivery']['sourceCommit'])),
            'Test release identity is incomplete; do not promote implicitly.')
    return version, image['repository'] + '@' + image['digest']


def load_capacity():
    spec = importlib.util.spec_from_file_location('capacity', ROOT / 'scripts/check-aws-dev-system-capacity.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wait_capacity(env, seconds=900):
    capacity = load_capacity()
    deadline = time.monotonic() + seconds
    while True:
        nodes = get(env, 'get', 'nodes', '-l', 'workload=system')
        pods = get(env, 'get', 'pods', '-A')
        if capacity.evaluate(nodes, pods, 'strict'):
            return
        require(time.monotonic() < deadline, 'System Pod-slot readiness timed out; inspect nodes/pending Pods and rerun bootstrap.')
        time.sleep(10)

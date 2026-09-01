#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT_DIR}" <<'PY'
import os, pathlib, subprocess, sys, tempfile
root = pathlib.Path(sys.argv[1])
mock = '''#!/usr/bin/env python3
import os, sys, json
name = os.path.basename(sys.argv[0]); args = sys.argv[1:]; case = os.environ['CASE']
with open(os.environ['CALL_LOG'], 'a') as f: f.write(name + ' ' + ' '.join(args) + '\\n')
if name == 'terraform':
    if 'show' in args:
        if case == 'state-error': sys.exit(1)
        print(json.dumps({'values':{'root_module':{'resources':[{'address':'existing'}]}}} if case == 'state-full' else {'format_version':'1.0'}))
    sys.exit(0)
if name == 'kubectl': sys.exit(0)
if name == 'aws':
    if args[:2] == ['sts','get-caller-identity']:
        print('999999999999' if case == 'account' else '123456789012'); sys.exit(0)
    if args[:2] == ['eks','describe-cluster']:
        if '--query' in args: print('8.8.8.8/32'); sys.exit(0)
        if case in ('existing','maintain'):
            print(json.dumps({'cluster':{'logging':{'clusterLogging':[{'enabled':True,'types':['api']}]}}})); sys.exit(0)
        print('An error occurred (AccessDeniedException)' if case == 'denied' else 'An error occurred (ResourceNotFoundException)', file=sys.stderr); sys.exit(1)
    sys.exit(0)
sys.exit(0)
'''
with tempfile.TemporaryDirectory() as tmp:
    temp = pathlib.Path(tmp)
    for cmd in ('aws','terraform','kubectl','curl'):
        path = temp / cmd; path.write_text(mock); path.chmod(0o755)
    cases = [('create',True),('denied',False),('existing',False),('account',False),
             ('state-full',False),('state-error',False),('missing-maintain',False),('maintain',True)]
    for case, success in cases:
        env = dict(os.environ)
        for key in ('AWS_ENVIRONMENT','TF_DIR','CLUSTER_NAME','EKS_ACCESS_MODE','EKS_CLUSTER_LOG_TYPES_JSON'):
            env.pop(key, None)
        log = temp / (case + '.log')
        env.update(PATH=str(temp)+os.pathsep+env['PATH'], CASE=case, CALL_LOG=str(log),
                   MANAGEMENT_PUBLIC_IP='8.8.8.8', EXPECTED_AWS_ACCOUNT_ID='123456789012',
                   CONFIRM_AWS_DEV_APPLY='create-ephemeral-aws-dev',
                   CONFIRM_EKS_API_CIDR_UPDATE='restrict-current-ip')
        maintenance = case in ('missing-maintain','maintain')
        script = 'apply-eks-api-access-cidr.sh' if maintenance else 'apply-aws-dev.sh'
        result = subprocess.run(['bash',str(root/'scripts'/script)],env=env,input='apply-aws-dev\n',text=True,capture_output=True)
        assert (result.returncode == 0) == success, (case,result.stdout,result.stderr)
        calls = log.read_text()
        applied = any(line.startswith('terraform ') and ' apply ' in line for line in calls.splitlines())
        assert applied == success, (case,calls)
        if case == 'maintain': assert 'eks_enabled_cluster_log_types=["api"]' in calls
        if case == 'create': assert 'eks_enabled_cluster_log_types=[]' in calls
        if case in ('denied','existing','account','missing-maintain'):
            assert 'terraform ' not in calls
        print('PASS:',case)
print('v0.11.8.1.3 mocked AWS entrypoint tests passed; no cloud operations performed.')
PY
bash -n "${ROOT_DIR}/scripts/apply-aws-dev.sh"
bash -n "${ROOT_DIR}/scripts/apply-eks-api-access-cidr.sh"

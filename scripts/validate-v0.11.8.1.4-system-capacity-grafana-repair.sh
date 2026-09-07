#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT_DIR}" <<'PY'
import base64, copy, importlib.util, json, os, pathlib, subprocess, sys, tempfile
from unittest.mock import patch
root = pathlib.Path(sys.argv[1])
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, root/'scripts'/file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
capacity = load('capacity','check-aws-dev-system-capacity.py')
secret = load('secret','prepare-aws-dev-grafana-secret.py')
def fixture(count, used):
    nodes={'items':[]}; pods={'items':[]}
    for i in range(count):
        name=f'n{i}'
        nodes['items'].append({'metadata':{'name':name,'labels':{'workload':'system'}},'status':{'allocatable':{'pods':'17'},'conditions':[{'type':'Ready','status':'True'}]}})
        pods['items'] += [{'spec':{'nodeName':name},'status':{'phase':'Running'}} for _ in range(used[i])]
    return nodes,pods
assert not capacity.evaluate(*fixture(2,[17,17]))
assert not capacity.evaluate(*fixture(4,[17,17,4,4]))
assert capacity.evaluate(*fixture(4,[15,15,8,8]))

account='123456789012'
context=f'arn:aws:eks:us-east-1:{account}:cluster/startup-devops-baseline-dev'
data={'data':{k:base64.b64encode(v.encode()).decode() for k,v in [('admin-user','admin'),('admin-password','fixture-password')]}}
for case in ('existing','copy','new','malformed','denied','wrong-context'):
    writes=[]
    def kube(*args, data=None):
        if args[:2] == ('config','current-context'): return 'wrong' if case=='wrong-context' else context
        if args[:2] == ('get','namespace'): return '{}'
        if 'get' in args and 'secret' in args:
            if case=='denied': raise SystemExit('fixture denied')
            target='observability-grafana-admin' in args
            if target and case=='existing': return json.dumps(globals()['data'])
            if target: return ''
            if case=='malformed': return '{"data":{}}'
            return json.dumps(globals()['data']) if case=='copy' else ''
        if args == ('create','-f','-'):
            writes.append(json.loads(data)); return ''
        raise AssertionError(args)
    with patch.dict(os.environ,{'EXPECTED_AWS_ACCOUNT_ID':account,'AWS_REGION':'us-east-1','CONFIRM_GRAFANA_SECRET':'prepare-aws-dev'}), patch.object(secret,'kube',kube):
        try:
            secret.main()
            assert case not in ('malformed','denied','wrong-context')
        except SystemExit:
            assert case in ('malformed','denied','wrong-context')
    assert len(writes)==(1 if case in ('copy','new') else 0)
    if case=='copy': assert writes[0]['data']==data['data']
    if writes: assert 'annotations' not in writes[0]['metadata']

text=(root/'scripts/scale-aws-dev-system-capacity.sh').read_text()
validator=text.split("<<'PY'\n",1)[1].split('\nPY\n',1)[0]
good={'resource_changes':[{'address':'module.eks.aws_eks_node_group.general','change':{'actions':['update'],'before':{'scaling_config':[{'min_size':2,'max_size':3,'desired_size':2}]},'after':{'scaling_config':[{'min_size':4,'max_size':4,'desired_size':4}]},'after_unknown':{}}}]}
with tempfile.TemporaryDirectory() as td:
    for case in ('good','replace','other','scale-down'):
        plan=copy.deepcopy(good); item=plan['resource_changes'][0]
        if case=='replace': item['change']['actions']=['delete','create']
        if case=='other': item['address']='module.eks.aws_eks_cluster.this'
        if case=='scale-down': item['change']['before']['scaling_config'][0]['desired_size']=5
        path=pathlib.Path(td)/'plan.json'; path.write_text(json.dumps(plan))
        result=subprocess.run([sys.executable,'-c',validator,str(path)],capture_output=True)
        assert (result.returncode==0)==(case=='good'),case
overlay=(root/'clusters/aws/overlays/dev/kustomization.yaml').read_text()
assert 'existingSecret: observability-grafana-admin' in overlay
assert 'passwordKey: admin-password' in overlay
for env in ('test','prod'):
    assert 'observability-grafana-admin' not in (root/f'clusters/aws/overlays/{env}/kustomization.yaml').read_text()
profile=(root/'infra/terraform/aws/environments/dev/observability-capacity.auto.tfvars').read_text()
for key in ('desired','min','max'):
    import re
    assert re.search(r'eks_node_'+key+r'_size\s*=\s*4',profile)
print('v0.11.8.1.4 capacity, credentials, plan restrictions and environment-boundary fixtures passed.')
PY
bash -n "${ROOT_DIR}/scripts/scale-aws-dev-system-capacity.sh"

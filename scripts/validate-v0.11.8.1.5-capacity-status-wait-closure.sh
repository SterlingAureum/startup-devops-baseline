#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT_DIR}" <<'PY'
import contextlib, copy, importlib.util, io, json, os, pathlib, subprocess, sys
from unittest.mock import patch
root=pathlib.Path(sys.argv[1])
def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,root/'scripts'/filename)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
capacity=load('capacity','check-aws-dev-system-capacity.py')
waiter=load('waiter','wait-aws-dev-system-nodes.py')
def fixture(occupancy):
    nodes={'items':[]}; pods={'items':[]}
    for i,used in enumerate(occupancy):
        nodes['items'].append({'metadata':{'name':f'n{i}','labels':{'workload':'system','eks.amazonaws.com/nodegroup':waiter.GROUP}},'status':{'allocatable':{'pods':'17'},'conditions':[{'type':'Ready','status':'True'}]}})
        pods['items'] += [{'metadata':{'namespace':'kube-system'},'spec':{'nodeName':f'n{i}'},'status':{'phase':'Running'}} for _ in range(used)]
    return nodes,pods
nodes,pods=fixture([16,7,17,7])
with contextlib.redirect_stdout(io.StringIO()) as output:
    assert capacity.evaluate(nodes,pods,'operational')
assert 'WARN: per_node_reserve_low' in output.getvalue()
assert not capacity.evaluate(nodes,pods,'strict')
assert not capacity.evaluate(*fixture([17,17]),'operational')
assert not capacity.evaluate(*fixture([16,16,16,16]),'operational')
pending=copy.deepcopy(pods)
pending['items'].append({'metadata':{'namespace':'observability'},'spec':{},'status':{'phase':'Pending'}})
assert not capacity.evaluate(nodes,pending,'operational')
assert capacity.evaluate(*fixture([15,7,15,7]),'strict')

resources={'items':[]}
for kind,name in [('Deployment','observability-metrics-operator'),('Deployment','observability-metrics-grafana'),('Deployment','observability-metrics-kube-state-metrics'),('DaemonSet','observability-metrics-prometheus-node-exporter'),('StatefulSet','prometheus-observability-metrics-prometheus'),('StatefulSet','alertmanager-observability-metrics-alertmanager')]:
    status={'observedGeneration':1,'readyReplicas':1,'updatedReplicas':1,'availableReplicas':1}
    if kind=='DaemonSet': status.update(desiredNumberScheduled=8,numberReady=8,numberAvailable=8,updatedNumberScheduled=8)
    resources['items'].append({'kind':kind,'metadata':{'name':name,'generation':1},'spec':{'replicas':1},'status':status})
assert capacity.runtime_ready(resources,pods)
assert not capacity.runtime_ready({'items':[]},pods)
bad=copy.deepcopy(resources); bad['items'][3]['status']['numberReady']=7
assert not capacity.runtime_ready(bad,pods)
bad=copy.deepcopy(resources); bad['items'][0]['status']['observedGeneration']=0
assert not capacity.runtime_ready(bad,pods)
assert not capacity.runtime_ready(resources,pending)

# Exercise CLI mode selection and exit status against an info65-style snapshot.
for mode, expected in [('operational',0),('strict',1)]:
    responses=['arn:aws:eks:us-east-1:123456789012:cluster/startup-devops-baseline-dev',json.dumps(nodes),json.dumps(pods)]
    if mode=='operational': responses.append(json.dumps(resources))
    with patch.dict(os.environ,{'EXPECTED_AWS_ACCOUNT_ID':'123456789012','AWS_REGION':'us-east-1'}),patch.object(sys,'argv',['check','--mode',mode]),patch.object(capacity.subprocess,'check_output',side_effect=responses),contextlib.redirect_stdout(io.StringIO()) as output:
        try: capacity.main(); raise AssertionError('Missing CLI exit')
        except SystemExit as error: assert error.code==expected
    assert ('WARN:' if mode=='operational' else 'FAIL:') in output.getvalue()

# Main-path API denial and identity failures cannot produce a warning/pass.
env={'EXPECTED_AWS_ACCOUNT_ID':'123456789012','AWS_REGION':'us-east-1'}
with patch.dict(os.environ,env),patch.object(sys,'argv',['check']),patch.object(capacity.subprocess,'check_output',side_effect=subprocess.CalledProcessError(1,['kubectl'])):
    try: capacity.main(); raise AssertionError('API failure accepted')
    except subprocess.CalledProcessError: pass
with patch.dict(os.environ,env),patch.object(sys,'argv',['check']),patch.object(capacity.subprocess,'check_output',return_value='wrong-context'):
    try: capacity.main(); raise AssertionError('Wrong context accepted')
    except SystemExit as error: assert error.code!='0'

# Fake clock: no real sleep, network, Kubernetes or AWS writes.
now=[0.0]
def pause(seconds): now[0]+=seconds
snapshots=iter([fixture([17,17])[0],nodes])
waiter.wait(lambda remaining:next(snapshots),30,5,clock=lambda:now[0],pause=pause)
assert now[0]==5
wrong=copy.deepcopy(nodes)
for node in wrong['items']: node['metadata']['labels']['eks.amazonaws.com/nodegroup']='other-group'
assert waiter.ready_nodes(wrong)==[]
now[0]=0
try:
    waiter.wait(lambda remaining:wrong,12,5,clock=lambda:now[0],pause=pause)
    raise AssertionError('Timeout accepted')
except TimeoutError: assert now[0]==12
try:
    waiter.wait(lambda remaining:(_ for _ in ()).throw(subprocess.CalledProcessError(1,['kubectl'])),12,5,clock=lambda:0,pause=pause)
    raise AssertionError('Denied API accepted')
except subprocess.CalledProcessError: pass
bad=copy.deepcopy(nodes); bad['items'][0]['status']['conditions'][0]['status']='False'
assert len(waiter.ready_nodes(bad))==3
contract=json.loads((root/'delivery/contracts/v0.11.8.1.5-capacity-status-wait-closure.json').read_text())
assert contract['operationalWarningExitCode']==0 and contract['strictReserveFailureExitCode']==1
assert contract['automaticEviction'] is False and contract['nodeReadyWaitSeconds']==900
scale=(root/'scripts/scale-aws-dev-system-capacity.sh').read_text()
assert scale.index('--check-context') < scale.index('terraform -chdir=')
assert scale.rfind('wait-aws-dev-system-nodes.py') > scale.index('apply -input=false')
assert (root/'docs/V0.11.8.1.4_AWS_SYSTEM_POD_CAPACITY_INCIDENT.md').is_file()
print('v0.11.8.1.5 operational/strict, readiness, identity, timeout and API-error fixtures passed.')
PY
bash -n "${ROOT_DIR}/scripts/scale-aws-dev-system-capacity.sh"

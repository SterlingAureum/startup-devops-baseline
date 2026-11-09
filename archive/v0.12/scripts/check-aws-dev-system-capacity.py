#!/usr/bin/env python3
"""Read-only Pod-slot preflight; not a CPU/memory or scheduling guarantee."""
import json
import os
import re
import subprocess
import sys
import argparse


def evaluate(nodes, pods, mode='strict'):
    if mode not in ('strict', 'operational'):
        raise ValueError('Unknown capacity mode')
    active = [p for p in pods['items'] if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
    eligible = [n for n in nodes['items'] if n.get('metadata', {}).get('labels', {}).get('workload') == 'system'
                and not n.get('spec', {}).get('unschedulable')
                and not any(t.get('effect') in ('NoSchedule','NoExecute') for t in n.get('spec', {}).get('taints', []))
                and any(c['type'] == 'Ready' and c['status'] == 'True' for c in n.get('status', {}).get('conditions', []))]
    free = []
    for node in eligible:
        name = node['metadata']['name']
        cap = int(node['status']['allocatable']['pods'])
        used = sum(p.get('spec', {}).get('nodeName') == name for p in active)
        free.append(cap-used)
        print(f'{name}: slots={cap}, assigned={used}, free={cap-used}')
    pending = sum(not p.get('spec', {}).get('nodeName') and
                  (p.get('spec', {}).get('nodeSelector', {}).get('workload') == 'system'
                   or p.get('metadata', {}).get('namespace') == 'observability') for p in active)
    print(f'Eligible system nodes={len(eligible)}, unassigned relevant Pods={pending}, total free={sum(free)}')
    # 8 slots reserve missing monitoring instances, hooks and rolling surges.
    baseline = len(eligible) >= 4 and sum(free) >= pending+8 and all(f >= 0 for f in free)
    reserve = min(free, default=0) >= 1
    passed = baseline and (reserve if mode == 'strict' else pending == 0)
    if not passed:
        reason = 'capacity_or_unassigned_pods' if not baseline or (mode == 'operational' and pending) else 'per_node_reserve'
        print(f'FAIL: {reason}; no automatic relocation is performed.')
    elif not reserve:
        print('WARN: per_node_reserve_low; operational Pod-slot check passed, strict reserve policy unmet.')
    else:
        print('PASS: Pod-slot budget; CPU/memory and full qualification remain separate.')
    return passed


def runtime_ready(resources, pods):
    required = {
        ('Deployment','observability-metrics-operator'),
        ('Deployment','observability-metrics-grafana'),
        ('Deployment','observability-metrics-kube-state-metrics'),
        ('DaemonSet','observability-metrics-prometheus-node-exporter'),
        ('StatefulSet','prometheus-observability-metrics-prometheus'),
        ('StatefulSet','alertmanager-observability-metrics-alertmanager'),
    }
    inventory = {(r['kind'],r['metadata']['name']):r for r in resources['items']}
    if not required <= inventory.keys():
        print('FAIL: required monitoring workload missing'); return False
    for key in sorted(required):
        obj = inventory[key]; status = obj.get('status', {})
        if status.get('observedGeneration', -1) < obj['metadata']['generation']:
            print(f'FAIL: unobserved workload generation {key}'); return False
        if key[0] == 'DaemonSet':
            count = status.get('desiredNumberScheduled',0)
            good = count > 0 and all(status.get(k,0) == count for k in ('numberReady','numberAvailable','updatedNumberScheduled')) and status.get('numberMisscheduled',0)==0
        else:
            count = obj['spec'].get('replicas',1)
            good = count > 0 and status.get('readyReplicas',0)==count and status.get('updatedReplicas',0)==count
            if key[0]=='Deployment': good = good and status.get('availableReplicas',0)==count
        if not good:
            print(f'FAIL: workload not ready {key}'); return False
    for pod in pods['items']:
        if pod.get('metadata', {}).get('namespace') != 'observability': continue
        status=pod.get('status',{})
        if status.get('phase')=='Succeeded': continue
        if status.get('phase')!='Running' or not any(c['type']=='Ready' and c['status']=='True' for c in status.get('conditions',[])):
            print('FAIL: observability Pod not Ready'); return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('operational','strict'), default='operational')
    args = parser.parse_args()
    account = os.environ.get('EXPECTED_AWS_ACCOUNT_ID', '')
    if not re.fullmatch(r'\d{12}', account):
        raise SystemExit('EXPECTED_AWS_ACCOUNT_ID required')
    region = os.environ.get('AWS_REGION','us-east-1')
    def kube(*args):
        return subprocess.check_output(['kubectl','--request-timeout=30s',*args], text=True, timeout=40)
    if kube('config','current-context').strip() != f'arn:aws:eks:{region}:{account}:cluster/startup-devops-baseline-dev':
        raise SystemExit('Wrong Kubernetes context')
    nodes = json.loads(kube('get','nodes','-l','workload=system','-o','json'))
    pods = json.loads(kube('get','pods','-A','-o','json'))
    if args.mode == 'operational':
        resources=json.loads(kube('-n','observability','get','deployment,daemonset,statefulset','-o','json'))
        if not runtime_ready(resources,pods): sys.exit(1)
    sys.exit(0 if evaluate(nodes, pods, args.mode) else 1)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f'FAIL: inventory/API error ({type(error).__name__}); state not verified.',file=sys.stderr)
        sys.exit(1)

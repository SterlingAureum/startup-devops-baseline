#!/usr/bin/env python3
"""Read-only Pod-slot preflight; not a CPU/memory or scheduling guarantee."""
import json
import os
import re
import subprocess
import sys


def evaluate(nodes, pods):
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
    passed = len(eligible) >= 4 and min(free, default=0) >= 1 and sum(free) >= pending+8
    print('PASS: Pod-slot budget only; inspect CPU/memory requests and runtime readiness separately.' if passed
          else 'FAIL: add capacity or review per-node placement; do not delete arbitrary Pods.')
    return passed


def main():
    account = os.environ.get('EXPECTED_AWS_ACCOUNT_ID', '')
    if not re.fullmatch(r'\d{12}', account):
        raise SystemExit('EXPECTED_AWS_ACCOUNT_ID required')
    region = os.environ.get('AWS_REGION','us-east-1')
    def kube(*args):
        return subprocess.check_output(['kubectl','--request-timeout=30s',*args], text=True)
    if kube('config','current-context').strip() != f'arn:aws:eks:{region}:{account}:cluster/startup-devops-baseline-dev':
        raise SystemExit('Wrong Kubernetes context')
    nodes = json.loads(kube('get','nodes','-l','workload=system','-o','json'))
    pods = json.loads(kube('get','pods','-A','-o','json'))
    sys.exit(0 if evaluate(nodes, pods) else 1)


if __name__ == '__main__':
    main()

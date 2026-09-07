#!/usr/bin/env python3
"""Read-only bounded wait for the exact dev managed node group."""
import argparse
import json
import os
import re
import subprocess
import sys
import time

GROUP='startup-devops-baseline-dev-general'


def ready_nodes(payload):
    result=[]
    for node in payload['items']:
        labels=node['metadata']['labels']
        if labels.get('workload')!='system' or labels.get('eks.amazonaws.com/nodegroup')!=GROUP: continue
        spec=node.get('spec',{})
        if spec.get('unschedulable') or any(t.get('effect') in ('NoSchedule','NoExecute') for t in spec.get('taints',[])): continue
        if any(c['type']=='Ready' and c['status']=='True' for c in node['status']['conditions']):
            result.append(node['metadata']['name'])
    return result


def wait(fetch, timeout, interval, clock=time.monotonic, pause=time.sleep):
    end=clock()+timeout
    while True:
        remaining=end-clock()
        if remaining<=0: raise TimeoutError('Node wait deadline exceeded; no retry of Terraform required.')
        payload=fetch(remaining)
        names=ready_nodes(payload)
        print(f'Ready schedulable system nodes in {GROUP}: {len(names)}/4',flush=True)
        if len(names)>=4 and clock()<=end:
            print('Node readiness passed; Pod placement, reserves and monitoring acceptance are separate.')
            return
        remaining=end-clock()
        if remaining<=0: raise TimeoutError('Node wait deadline exceeded; inspect node inventory.')
        pause(min(interval,remaining))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-context',action='store_true')
    parser.add_argument('--timeout',type=int,default=900)
    parser.add_argument('--interval',type=int,default=10)
    args=parser.parse_args()
    if not 1<=args.timeout<=3600 or not 1<=args.interval<=60: raise ValueError('Invalid wait bounds')
    account=os.environ.get('EXPECTED_AWS_ACCOUNT_ID','')
    region=os.environ.get('AWS_REGION','us-east-1')
    if not re.fullmatch(r'\d{12}',account): raise ValueError('EXPECTED_AWS_ACCOUNT_ID required')
    context=subprocess.check_output(['kubectl','config','current-context'],text=True,timeout=15).strip()
    if context!=f'arn:aws:eks:{region}:{account}:cluster/startup-devops-baseline-dev':
        raise ValueError('Wrong Kubernetes context')
    if args.check_context: return
    def fetch(remaining):
        raw=subprocess.check_output(['kubectl','--request-timeout=15s','get','nodes','-l',
            f'workload=system,eks.amazonaws.com/nodegroup={GROUP}','-o','json'],text=True,timeout=min(20,remaining))
        return json.loads(raw)
    try:
        wait(fetch,args.timeout,args.interval)
    except TimeoutError:
        print('TIMEOUT: expansion may already be applied. This waiter does not undo or repeat it.',file=sys.stderr)
        # Bounded, read-only diagnostics. Never read Secrets or modify nodes.
        for command in (['get','nodes','-l','workload=system','-o','wide'], ['get','pods','-n','observability','-o','wide']):
            try: subprocess.run(['kubectl','--request-timeout=10s',*command],timeout=12,check=False)
            except subprocess.SubprocessError: pass
        raise


if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,TypeError,OSError,TimeoutError,subprocess.SubprocessError) as error:
        print(f'FAIL: {error}',file=sys.stderr)
        sys.exit(1)

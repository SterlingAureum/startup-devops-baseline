#!/usr/bin/env python3
"""Render the locked Chart twice; assert stable Grafana credentials contract."""
import json
import pathlib
import subprocess
import tempfile
import yaml

root = pathlib.Path(__file__).resolve().parents[1]
app = yaml.safe_load((root/'clusters/aws/base/platform/monitoring.yaml').read_text())
values = app['spec']['source']['helm']['valuesObject']
overlay = yaml.safe_load((root/'clusters/aws/overlays/dev/kustomization.yaml').read_text())
patch = next(p for p in overlay['patches'] if p['target']['name']=='monitoring-aws-dev')
values['grafana']['admin'] = yaml.safe_load(patch['patch'])[0]['value']
with tempfile.TemporaryDirectory() as td:
    work=pathlib.Path(td)
    path=work/'values.json'; path.write_text(json.dumps(values))
    subprocess.run(['helm','pull','kube-prometheus-stack','--repo',app['spec']['source']['repoURL'],
                    '--version','88.5.0','--destination',td],check=True)
    renders=[]
    for _ in range(2):
        rendered=subprocess.check_output(['helm','template','observability-metrics',str(work/'kube-prometheus-stack-88.5.0.tgz'),
                                         '--namespace','observability','--kube-version','1.36.0','-f',str(path)],text=True)
        docs=[d for d in yaml.safe_load_all(rendered) if d]
        assert not any(d['kind']=='Secret' and d['metadata']['name']=='observability-metrics-grafana' for d in docs)
        deployment=next(d for d in docs if d['kind']=='Deployment' and d['metadata']['name']=='observability-metrics-grafana')
        assert 'checksum/secret' not in deployment['spec']['template']['metadata'].get('annotations',{})
        refs=[e['valueFrom']['secretKeyRef'] for c in deployment['spec']['template']['spec']['containers']
              for e in c.get('env',[]) if 'secretKeyRef' in e.get('valueFrom',{})]
        assert {'name':'observability-grafana-admin','key':'admin-password'} in refs
        renders.append(deployment)
    assert renders[0]==renders[1], 'Grafana Deployment rendering is not deterministic'
print('Locked Chart 88.5.0: independent Secret reference and deterministic Grafana render passed.')

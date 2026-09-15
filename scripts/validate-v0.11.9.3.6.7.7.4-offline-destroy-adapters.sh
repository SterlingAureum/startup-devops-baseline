#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);cp='delivery/contracts/v0.11.9.3.6.7.7.4-shared-offline-destroy-adapters.json'
c=json.loads((root/cp).read_text());sha=lambda p:hashlib.sha256((root/p).read_bytes()).hexdigest()
assert sha(cp)=='0ba0aef6bbee3250727291c7931f153d622125c8cb1d009ba32ddd13becc57fb','contract drift'
assert c['schemaVersion']==c['version']=='v0.11.9.3.6.7.7.4'
assert c['implementationBaselineCommit']=='7f688e991ed6144fc29b762301741f8eb1813a5e'
assert c['status']=='shared-offline-destroy-adapters-implemented'
assert c['historicalTeardownAndScopedAuditClosed']
assert not any(c[k] for k in ('existingLiveAdaptersModified','completeAdapterMigrationImplemented','newLiveExecutionAuthorized','historicalApprovalsReusable','prodQualified'))
assert c['implementedPhases']==['eks-delete','final-delete'] and c['successfulFixtureMatrixSize']==6
for prefix in ('core','test'):assert sha(c[prefix+'Path'])==c[prefix+'Sha256']
for item in c['frozenSources']:assert sha(item['path'])==item['sha256'],item['path']
methods=sorted(n.name for n in ast.walk(ast.parse((root/c['testPath']).read_text())) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'))
assert methods==c['testMethods'] and len(methods)==c['testMethodCount']==39
tree=ast.parse((root/c['corePath']).read_text())
assert {n.name for n in tree.body if isinstance(n,ast.ClassDef)}==set(c['publicClasses'])
allowed={'__future__','hashlib','decimal','pathlib','re','guarded_runtime_rules','guarded_cleanup_rules','guarded_plan_rules','guarded_attempt_journal'}
for n in ast.walk(tree):
    if isinstance(n,ast.Import):assert all(x.name in allowed for x in n.names)
    if isinstance(n,ast.ImportFrom):assert n.module in allowed
    if isinstance(n,ast.Call):
        if isinstance(n.func,ast.Name):assert n.func.id not in {'exec','eval','__import__','print','open'}
        if isinstance(n.func,ast.Attribute):assert n.func.attr not in {'now','utcnow','Popen','getenv','unlink','write_text','read_bytes','read_text'}
# Profiles are explicit and match frozen Terraform module definitions.
for profile in c['environmentProfiles']:
    e=profile['environment'].removeprefix('aws-');text=(root/('infra/terraform/aws/environments/'+e+'/main.tf')).read_text()
    assert set(re.findall(r'^module "([A-Za-z_][A-Za-z0-9_]*)"',text,re.M))==set(profile['managedModuleNames'])
for p in (cp,'docs/V0.11.9.3.6.7.7.4_SHARED_OFFLINE_DESTROY_ADAPTERS.md'):
    text=(root/p).read_text()
    assert '/home/sterling/' not in text and 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert sha('.gitleaksignore')=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.4 source/AST/profile/privacy pins passed; fixed fake destroy adapters only.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.4-offline-destroy-adapters.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.3-plan-scope-and-attempt-journal.sh"
echo "v0.11.9.3.6.7.7.4 passed; three-profile destroy composition validated offline."

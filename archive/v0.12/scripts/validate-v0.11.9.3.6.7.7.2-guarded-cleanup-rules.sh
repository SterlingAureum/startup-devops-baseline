#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);cp='delivery/contracts/v0.11.9.3.6.7.7.2-shared-guarded-cleanup-rules.json'
c=json.loads((root/cp).read_text());digest=lambda p:hashlib.sha256((root/p).read_bytes()).hexdigest()
assert digest(cp)=='30e4a853f9e64e946659afa3502b7b3139a9162242cf75a03e6d5329896e5f52','cleanup contract drift'
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.7.2'
assert c['implementationBaselineCommit']=='9b0d172eee26a612c2c492a8ae5e0c361108dfa8'
assert c['status']=='shared-guarded-cleanup-rules-implemented-offline'
assert c['historicalTeardownAndScopedAuditClosed']
assert not any(c[k] for k in ('existingLiveAdaptersModified','completeAdapterMigrationImplemented','newLiveExecutionAuthorized','historicalApprovalsReusable','prodQualified'))
assert not any(c['effectFlags'].values())
for prefix in ('core','test'):assert digest(c[prefix+'Path'])==c[prefix+'Sha256']
for item in c['frozenSources']:assert digest(item['path'])==item['sha256'],item['path']
tree=ast.parse((root/c['corePath']).read_text())
assert set(c['publicRuleFunctions'])<={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
allowed={'__future__','re','guarded_runtime_rules'}
for n in ast.walk(tree):
    if isinstance(n,ast.Import):assert all(x.name in allowed for x in n.names)
    if isinstance(n,ast.ImportFrom):assert n.module in allowed
    if isinstance(n,ast.Call):
        if isinstance(n.func,ast.Name):assert n.func.id not in {'open','exec','eval','__import__','print'}
        if isinstance(n.func,ast.Attribute):assert n.func.attr not in {'now','utcnow','run','Popen','write_text','read_text','getenv'}
methods=sorted(n.name for n in ast.walk(ast.parse((root/c['testPath']).read_text())) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'))
assert methods==c['testMethods'] and len(methods)==c['testMethodCount']==28
assert c['implementedReviewIds']==['eso-cleanup-order','orphan-eni-sg']
assert c['dependencySteps']==['freeze-applications','drain-external-secrets','delete-business-namespaces','drain-runtime','delete-node-config','eks-delete','eni-sg-cleanup','final-delete']
for path in (cp,'docs/V0.11.9.3.6.7.7.2_SHARED_GUARDED_CLEANUP_RULES.md'):
    text=(root/path).read_text()
    assert not any(x in text for x in ('/home/sterling/','arn:aws:','AKIA','secretMetadataSha256'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert digest('.gitleaksignore')=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.2 cleanup pure-rule/source/AST/privacy gates passed; adapters remain pending.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.2-guarded-cleanup-rules.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.1-guarded-runtime-rules.sh"
echo "v0.11.9.3.6.7.7.2 passed; shared cleanup rules validated offline."

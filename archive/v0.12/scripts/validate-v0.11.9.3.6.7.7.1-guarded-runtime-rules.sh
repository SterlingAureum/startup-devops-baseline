#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);cp='delivery/contracts/v0.11.9.3.6.7.7.1-shared-guarded-runtime-pure-rules.json'
c=json.loads((root/cp).read_text());digest=lambda p:hashlib.sha256((root/p).read_bytes()).hexdigest()
assert digest(cp)=='1037ae9da4c3275601b68ad2c802ca645affdd8af8f26e9055d83c4f0a5c5e39','shared rules contract drift'
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.7.1'
assert c['implementationBaselineCommit']=='6927b6a256bb45ad85a12d9f8824a3b0e1352b68'
assert c['status']=='shared-guarded-runtime-pure-rules-implemented-offline'
assert c['historicalTeardownAndScopedAuditClosed']
assert not any(c[k] for k in ('historicalApprovalsReusable','completeCommonAdapterMigrationImplemented','existingLiveAdaptersModified','newLiveExecutionAuthorized','prodQualified'))
assert not any(c['moduleEffects'].values())
for prefix in ('core','test'):assert digest(c[prefix+'Path'])==c[prefix+'Sha256'],prefix
for item in c['frozenReviewSources']:assert digest(item['path'])==item['sha256'],item['path']
tree=ast.parse((root/c['corePath']).read_text())
functions={n.name for n in tree.body if isinstance(n,ast.FunctionDef)}
assert set(c['publicRuleFunctions'])<=functions
allowed={'__future__','collections','datetime','json','re','typing'}
for n in ast.walk(tree):
    if isinstance(n,ast.Import):assert all(x.name in allowed for x in n.names)
    if isinstance(n,ast.ImportFrom):assert n.module in allowed
    if isinstance(n,ast.Call):
        if isinstance(n.func,ast.Name):assert n.func.id not in {'open','eval','exec','__import__','print','input'}
        if isinstance(n.func,ast.Attribute):assert n.func.attr not in {'now','utcnow','today','read_bytes','read_text','write_bytes','write_text','getenv','run','Popen'}
tests=ast.parse((root/c['testPath']).read_text())
methods=sorted(n.name for n in ast.walk(tests) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'))
assert methods==c['testMethods'] and len(methods)==c['testMethodCount']==29
assert c['implementedReviewIds']==['aws-error-envelope','state-data-classification','proof-clock-attempt']
assert c['remainingReviewIds']==['eso-cleanup-order','eks-dependency-closure','orphan-eni-sg']
assert not c['stateSemantics']['historicalSevenAddressWaiverEmbedded']
assert c['clockSemantics']['originalCreationTimestampRequired']
for path in (cp,'docs/V0.11.9.3.6.7.7.1_SHARED_GUARDED_RUNTIME_PURE_RULES.md'):
    text=(root/path).read_text()
    assert not any(x in text for x in ('/home/sterling/','arn:aws:','AKIA','secretMetadataSha256'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert digest('.gitleaksignore')=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.1 pure rule/source/AST/privacy gates passed; no adapter migration or live approval.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.1-guarded-runtime-rules.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7-cross-environment-guarded-runtime-review.sh"
echo "v0.11.9.3.6.7.7.1 passed; shared pure rules validated offline."

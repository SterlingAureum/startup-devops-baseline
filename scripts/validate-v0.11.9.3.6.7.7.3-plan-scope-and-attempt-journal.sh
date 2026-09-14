#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);cp='delivery/contracts/v0.11.9.3.6.7.7.3-shared-plan-scope-and-attempt-journal.json'
c=json.loads((root/cp).read_text());sha=lambda p:hashlib.sha256((root/p).read_bytes()).hexdigest()
assert sha(cp)=='aab810753dbd6cfcdd80037a2399fb25eaccadd57884f2de0291dde04c37e10b','contract drift'
assert c['schemaVersion']==c['version']=='v0.11.9.3.6.7.7.3'
assert c['implementationBaselineCommit']=='38d51cd0e9161373c8614fb28e606e99c5cc5dac'
assert c['status']=='shared-plan-scope-and-attempt-journal-implemented-offline'
assert c['historicalTeardownAndScopedAuditClosed']
assert not any(c[k] for k in ('existingLiveAdaptersModified','completeAdapterMigrationImplemented','newLiveExecutionAuthorized','historicalApprovalsReusable','prodQualified'))
for item in c['modules']+c['frozenSources']:assert sha(item['path'])==item['sha256'],item['path']
assert sha(c['testPath'])==c['testSha256']
methods=sorted(n.name for n in ast.walk(ast.parse((root/c['testPath']).read_text())) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'))
assert methods==c['testMethods'] and len(methods)==c['testMethodCount']==36
for item in c['modules']:
    tree=ast.parse((root/item['path']).read_text())
    allowed={'__future__','json','guarded_runtime_rules'}
    if item['path'].endswith('journal.py'):allowed|={'fcntl','hashlib','os','pathlib','re','stat'}
    for n in ast.walk(tree):
        if isinstance(n,ast.Import):assert all(x.name in allowed for x in n.names)
        if isinstance(n,ast.ImportFrom):assert n.module in allowed
        if isinstance(n,ast.Call):
            if isinstance(n.func,ast.Name):assert n.func.id not in {'exec','eval','__import__','print'}
            if isinstance(n.func,ast.Attribute):assert n.func.attr not in {'now','utcnow','run','Popen','getenv','unlink','truncate','ftruncate'}
for p in (cp,'docs/V0.11.9.3.6.7.7.3_SHARED_PLAN_SCOPE_AND_ATTEMPT_JOURNAL.md'):
    text=(root/p).read_text()
    assert '/home/sterling/' not in text and 'arn:aws:' not in text and 'AKIA' not in text
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',text) is None
assert sha('.gitleaksignore')=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7.3 source/AST/privacy pins passed; no live adapter migration.')
PYTHON
PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT_DIR/scripts/test-v0.11.9.3.6.7.7.3-plan-scope-and-attempt-journal.py"
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.7.2-guarded-cleanup-rules.sh"
echo "v0.11.9.3.6.7.7.3 passed; exact plan and durable journal validated offline."

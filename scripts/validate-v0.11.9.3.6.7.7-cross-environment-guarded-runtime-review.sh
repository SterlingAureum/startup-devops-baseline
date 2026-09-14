#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 - "$ROOT_DIR" <<'PYTHON'
import ast,hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1])
cp='delivery/contracts/v0.11.9.3.6.7.7-cross-environment-guarded-runtime-review.json'
c=json.loads((root/cp).read_text())
digest=lambda p:hashlib.sha256((root/p).read_bytes()).hexdigest()
assert digest(cp)=='a94fefb61c3771954e905a55309a0db881e23a1b2a6feb72ddbabd58e3a1c58f','review contract drift'
assert c['version']==c['schemaVersion']=='v0.11.9.3.6.7.7'
assert c['implementationBaselineCommit']=='383966da430bf560403e399978a549c6efd38348'
assert c['status']=='cross-environment-guarded-runtime-reviewed-offline'
assert c['historicalTeardownAndScopedAuditClosed']
assert not any(c[k] for k in ('commonRuntimeMigrationImplemented','liveExecutionAuthorized','prodQualified','historicalApprovalsReusable'))
pins={s['path']:s['sha256'] for s in c['reviewSources']}
assert len(pins)==len(c['reviewSources'])
for path,sha in pins.items():
    assert not Path(path).is_absolute() and '..' not in Path(path).parts
    assert re.fullmatch('[0-9a-f]{64}',sha) and digest(path)==sha,path
profiles=c['environmentProfiles']
assert [p['environment'] for p in profiles]==['aws-dev','aws-test','aws-prod']
for p in profiles:
    path=p['terraformMainPath'];assert path in pins and not p['liveAdapterEnabledByThisIncrement']
    actual=sorted(set(re.findall(r'source\s*=\s*"(../../modules/[^"]+)"',(root/path).read_text())))
    assert actual==p['moduleSources'],p['environment']
findings={f['id']:f for f in c['findings']}
assert set(findings)=={'aws-error-envelope','state-data-classification','eso-cleanup-order','eks-dependency-closure','orphan-eni-sg','instant-fleet-history','proof-clock-attempt'}
gaps={i for i,f in findings.items() if f['coverageStatus'].startswith('partial-regression')}
assert gaps==set(c['unresolvedCoverageIds'])=={'eso-cleanup-order','orphan-eni-sg'}
for f in findings.values():
    assert f['observedBoundary'] and f['futureAcceptance'] and f['replayReferences']
    for t in f['replayReferences']:
        assert t['path'] in pins
        methods={n.name for n in ast.walk(ast.parse((root/t['path']).read_text())) if isinstance(n,ast.FunctionDef)}
        assert t['method'].startswith('test_') and t['method'] in methods,t
assert [x['name'] for x in c['proposedCoreInterfaces']]==['EnvironmentProfile','ReviewProof','ServiceObservation','PlanScope','CleanupDependencies','AttemptJournal']
assert len(c['migrationSequence'])==4 and len(c['scopeLimits'])==4
assert c['predecessorReplayGate'] in pins
assert 'AUDIT_PATH = ROOT / "scripts/validate-aws-cost-cleanup.sh"' in (root/'scripts/execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py').read_text()
assert 'fleet_rules.classify_fleet(' in (root/'scripts/execute-v0.11.9.3.6.7.6.6.2-aws-test-residual-cost-audit.py').read_text()
for path in (cp,'docs/V0.11.9.3.6.7.7_CROSS_ENVIRONMENT_GUARDED_RUNTIME_REVIEW.md'):
    public=(root/path).read_text()
    assert not any(x in public for x in ('/home/sterling/','arn:aws:','AKIA','secretMetadataSha256'))
    assert re.search(r'(?<![A-Za-z0-9])[0-9]{12}(?![A-Za-z0-9])',public) is None
assert digest('.gitleaksignore')=='a346e54f717b6b076560273da964b20697e0b727fe2d44e3d16b7c128fbd13ca'
print('v0.11.9.3.6.7.7 source/profile/AST/coverage-gap/privacy review passed; migration remains pending.')
PYTHON
bash "$ROOT_DIR/scripts/validate-v0.11.9.3.6.7.6.6.3-residual-cost-audit-execution-evidence.sh"
echo "v0.11.9.3.6.7.7 passed; offline cross-environment review only."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path('delivery/contracts/v0.11.9.2.2.2-baseline-restoration-traffic-guard.json').read_text())
assert contract['version'] == 'v0.11.9.2.2.2'
assert contract['traffic']['minimumEligibleRequests'] == 20
assert contract['restoration']['gitOpsSyncIsNotRuntimeSuccess'] is True
assert contract['restoration']['healthyRequiredBeforeRestoredMessage'] is True
assert contract['restoration']['newAnalysisRunRequiredPerCheckpoint'] is True
assert contract['automaticPromote'] is False
assert contract['automaticRetry'] is False

restore = Path('scripts/restore-local-gitops-baseline.sh').read_text()
for marker in (
    'rollout_phase="$(jq', 'rollout_abort="$(jq', 'rollout_stable="$(jq',
    'rollout_current="$(jq',
    'GitOps baseline is Synced, but the demo-api runtime baseline is not restored',
    'exit 2', 'restored and runtime-qualified',
):
    assert marker in restore, marker
assert restore.index('if [ "${rollout_phase}" != "Healthy" ]') < restore.index('restored and runtime-qualified')

observer = Path('scripts/run-local-baseline-restoration-analysis.sh').read_text()
for marker in (
    'first-analysis|second-analysis|final',
    'observe-reviewed-local-baseline-recovery',
    'required_count=$((existing_count + 1))',
    'MINIMUM_MATCHING_ANALYSIS_RUNS="${required_count}"',
    "Generating bounded traffic", 'CLOSURE_PHASE=final',
):
    assert marker in observer, marker
for forbidden in ('rollouts promote', 'rollouts retry', 'rollouts abort'):
    assert forbidden not in observer, forbidden

analysis = Path('apps/demo-api/helm/templates/analysis-template.yaml').read_text()
for marker in ('route="/version"', 'minimumRequests', 'canary-minimum-eligible-requests'):
    assert marker in analysis, marker
PY

bash -n scripts/restore-local-gitops-baseline.sh
bash -n scripts/run-local-baseline-restoration-analysis.sh

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/restore-local-gitops-baseline.sh \
    scripts/run-local-baseline-restoration-analysis.sh
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

bash scripts/validate-v0.11.9.2.2.1-empty-digest-gitops-convergence-repair.sh
bash scripts/validate-v0.11.3.5-pre-merge-baseline-restoration.sh
bash scripts/validate-v0.9-lifecycle-contracts.sh
echo "v0.11.9.2.2.2 baseline restoration traffic guard passed; no live operation was executed."

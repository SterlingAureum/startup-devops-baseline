#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path(
    'delivery/contracts/v0.11.9.2.2.3.2-recovery-rollout-closure.json'
).read_text())
assert contract['version'] == 'v0.11.9.2.2.3.2'
assert contract['clusterMutation'] is False
assert contract['requiredAnalysisRuns'] == 2
assert contract['promotionOwner'] == 'human-operator'
assert contract['promotionPrecondition'] == 'second-observer-generating-bounded-traffic'
assert contract['historicalFailedAnalysisRuns'] == 'retain-as-evidence-do-not-retry'

accepted = contract['acceptedObservation']
assert accepted['sourceRevision'] == 'fc87e64688aba209e712ade0baf0573e5fae68ca'
assert accepted['rolloutRevision'] == 68
assert accepted['firstAnalysisRun'].endswith('-68-2')
assert accepted['secondAnalysisRun'].endswith('-68-5')
assert accepted['finalRolloutPhase'] == 'Healthy'
assert accepted['abort'] is False
assert accepted['replicaSetHash'] == '54fb66bc49'

document = Path('docs/V0.11.9.2.2.3.2_RECOVERY_ROLLOUT_CLOSURE.md').read_text()
ordered_markers = (
    'MINIMUM_MATCHING_ANALYSIS_RUNS=1',
    'bash scripts/deploy-local-feature-gitops.sh',
    'MINIMUM_MATCHING_ANALYSIS_RUNS=2',
    '==> Generating bounded traffic across Prometheus scrape intervals',
    'kubectl argo rollouts promote demo-api -n startup-apps',
    'kubectl argo rollouts status demo-api -n startup-apps --timeout 5m',
)
positions = [document.index(marker) for marker in ordered_markers]
assert positions == sorted(positions), 'two-terminal operation order changed'
assert 'kubectl -n startup-apps argo rollouts promote demo-api' in document
assert 'invalid because kubectl interprets the flag before resolving the plugin' in document
assert 'must not be retried' in document
assert 'performs no Kubernetes, Rollout, traffic\nor AWS operation' in document

for relative in (
    'scripts/rollout-status.sh',
    'scripts/rollout-promote.sh',
    'scripts/rollout-abort.sh',
    'scripts/rollout-watch.sh',
    'docs/LOCAL_DEPLOYMENT.md',
    'docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md',
    'docs/ROLLBACK_RUNBOOK.md',
):
    content = Path(relative).read_text()
    assert 'kubectl -n startup-apps argo rollouts' not in content, relative
    assert 'kubectl argo rollouts' in content, relative
PY

echo "v0.11.9.2.2.3.2 recovery Rollout closure contract passed; no live operation was executed."

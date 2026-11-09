#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path('delivery/contracts/v0.11.9.2.2.3-prometheus-identity-traffic-lifetime.json').read_text())
assert contract['version'] == 'v0.11.9.2.2.3'
assert all(contract['repair'].values())
assert contract['automaticPromote'] is False
assert contract['automaticRetry'] is False
assert contract['realClusterMutationDuringValidation'] is False

traffic = Path('scripts/check-local-slo-aware-rollout-analysis.sh').read_text()
for marker in (
    'PROMETHEUS_TARGET_WAIT_SECONDS', 'PROMETHEUS_SERVICE',
    'Waiting for Prometheus target identity', '--data-urlencode "query=${target_query}"',
    'platform_release_id=\\"${expected_release_id}\\"',
    'traffic_pid', 'stop-traffic', 'through AnalysisRun completion',
    'kill -0 "${traffic_pid}"',
):
    assert marker in traffic, marker
assert traffic.index('Waiting for Prometheus target identity') < traffic.index('Generating bounded traffic')
assert traffic.index('Generating bounded traffic') < traffic.index('Waiting for successful SLO-aware AnalysisRun')

template = Path('apps/demo-api/helm/templates/analysis-template.yaml').read_text()
assert 'sum(up{job="demo-api-canary",platform_release_id="{{ `{{ args.expected-release-id }}` }}"})' in template

observer = Path('scripts/run-local-baseline-restoration-analysis.sh').read_text()
for forbidden in ('rollouts promote', 'rollouts retry', 'rollouts abort'):
    assert forbidden not in observer
PY

bash -n scripts/check-local-slo-aware-rollout-analysis.sh
bash scripts/validate-v0.11.9.2.2.2-baseline-restoration-traffic-guard.sh
echo "v0.11.9.2.2.3 Prometheus identity and traffic-lifetime repair passed; no live operation was executed."

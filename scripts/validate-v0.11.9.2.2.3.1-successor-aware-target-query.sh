#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path('delivery/contracts/v0.11.9.2.2.3.1-successor-aware-target-query.json').read_text())
assert contract['version'] == 'v0.11.9.2.2.3.1'
assert contract['historicalContractPreserved'] is True
assert contract['currentTemplateQuery'] == 'job-and-platform-release-id'
assert contract['clusterMutation'] is False

validator = Path('scripts/validate-v0.11.3.2-prometheus-no-data-hardening.sh').read_text()
for marker in ('prometheus_identity_successor', 'current_target_query',
               'v0.11.9.2.2.3-prometheus-identity-traffic-lifetime.json'):
    assert marker in validator, marker

query = 'sum(up{job="demo-api-canary",platform_release_id="<expected-release-id>"})'
for relative in ('docs/ARGO_ROLLOUTS_ANALYSIS_FLOW.md', 'docs/OBSERVABILITY.md', 'docs/LOCAL_DEPLOYMENT.md'):
    assert query in Path(relative).read_text(), relative
PY

bash scripts/validate-v0.11.3.2-prometheus-no-data-hardening.sh
bash scripts/validate-v0.11.9.2.2.3-prometheus-identity-traffic-lifetime.sh
echo "v0.11.9.2.2.3.1 successor-aware target query repair passed; no live operation was executed."

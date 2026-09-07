#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import yaml
import sys

root = Path(sys.argv[1])
repair = json.loads((root / 'delivery/contracts/v0.11.8.2.0.1-barman-chart-identity-render-coverage-repair.json').read_text())
contract = json.loads((root / 'delivery/contracts/v0.11.8.2.0-aws-test-qualification-prerequisites.json').read_text())
source = yaml.safe_load((root / 'clusters/aws/base/platform/barman-cloud-plugin.yaml').read_text())
assert repair['predecessor'] == 'v0.11.8.2.0'
assert repair['live_operations'] is False and repair['prod_in_scope'] is False
assert source['metadata']['name'] == repair['application_name']
assert source['spec']['source']['chart'] == repair['chart_name']
assert source['spec']['source']['targetRevision'] == repair['chart_version']
assert contract['external_charts'][repair['chart_name']] == repair['chart_version']
assert repair['application_name'] not in contract['external_charts']
historical = (root / 'scripts/check-aws-gitops-revision-boundary.sh').read_text()
assert '"plugin-barman-cloud": "0.7.0"' in historical
assert '"barman-cloud-plugin": "0.7.0"' not in historical
fixture = (root / 'scripts/validate-v0.11.8.1.2-aws-dev-pre-merge-feature-revision-qualification.sh').read_text()
assert '"plugin-barman-cloud":"0.7.0"' in fixture
assert '"barman-cloud-plugin":"0.7.0"' not in fixture
print('Static Barman Application/Chart identity contract passed.')
PY
python3 "${ROOT_DIR}/scripts/test-aws-test-qualification-prerequisites.py"
if command -v kustomize >/dev/null 2>&1 || command -v kubectl >/dev/null 2>&1; then
  "${ROOT_DIR}/scripts/check-aws-test-qualification-preview.sh"
  "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh"
else
  echo 'SKIP: real Kustomize rendering; run both standalone render checks locally.'
fi
echo 'v0.11.8.2.0.1 repair validation passed; no live operation was performed.'

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path(
    'delivery/contracts/v0.11.9.2.2.3.3-request-series-image-compatibility.json'
).read_text())
assert contract['version'] == 'v0.11.9.2.2.3.3'
assert contract['incidentRevision'] == 69
assert contract['rejectedBaselineImageTag'] == 'sha-3e50802'
assert all(contract['repair'].values())
assert contract['automaticPromote'] is False
assert contract['automaticRetry'] is False
assert contract['clusterMutationDuringValidation'] is False

traffic = Path('scripts/check-local-slo-aware-rollout-analysis.sh').read_text()
for marker in (
    'PROMETHEUS_REQUEST_SERIES_WAIT_SECONDS',
    'Waiting for release-scoped Candidate request metrics',
    'Release-scoped Candidate request metrics are ready',
    'Candidate target is up, but release-scoped /version request metrics did not appear',
    'ANALYSIS_RUN_EXCLUDED_UIDS_JSON',
    '$excluded | index($uid) | not',
):
    assert marker in traffic, marker
assert traffic.index('Generating bounded traffic') < traffic.index(
    'Waiting for release-scoped Candidate request metrics')
assert traffic.index('Waiting for release-scoped Candidate request metrics') < traffic.index(
    'Waiting for successful SLO-aware AnalysisRun')

runner = Path('scripts/run-local-baseline-restoration-analysis.sh').read_text()
assert runner.index('excluded_uids=') < runner.index('if [ "${PHASE}" = first-analysis ]')
assert 'ANALYSIS_RUN_EXCLUDED_UIDS_JSON="${excluded_uids}"' in runner
assert 'required_count=$((existing_count + 1))' not in runner
assert 'Only an AnalysisRun created after this observer started' in runner

restore = Path('scripts/restore-local-feature-baseline.sh').read_text()
for marker in (
    'baseline_image_tag=', 'sha-3e50802',
    'was rejected by live revision 69',
    'No Kubernetes restoration operation was started',
):
    assert marker in restore, marker
assert restore.index('if [ "${baseline_image_tag}" = "sha-3e50802" ]') < restore.index(
    'exec "${ROOT_DIR}/scripts/restore-local-gitops-baseline.sh"')

historical = Path('scripts/validate-v0.11.3.5-pre-merge-baseline-restoration.sh').read_text()
assert 'dynamic restore fixture is superseded by the rejected-image pre-mutation contract' in historical

doc = Path('docs/V0.11.9.2.2.3.3_REQUEST_SERIES_IMAGE_COMPATIBILITY.md').read_text()
for marker in ('Revision 69', 'necessary but insufficient', 'Do not promote or retry revision 69',
               'newly published immutable image', 'does not publish an image'):
    assert marker in doc, marker
PY

bash -n scripts/check-local-slo-aware-rollout-analysis.sh
bash -n scripts/run-local-baseline-restoration-analysis.sh
bash -n scripts/restore-local-feature-baseline.sh
bash scripts/validate-v0.11.9.2.2.2-baseline-restoration-traffic-guard.sh
bash scripts/validate-v0.11.9.2.2.3-prometheus-identity-traffic-lifetime.sh
echo "v0.11.9.2.2.3.3 request-series image compatibility repair passed; no live operation was executed."

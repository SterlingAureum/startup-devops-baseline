#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path(
    'delivery/contracts/v0.11.9.2.2.3.3.3-baseline-restoration-closure.json'
).read_text())
assert contract['version'] == 'v0.11.9.2.2.3.3.3'
assert contract['predecessor'] == 'v0.11.9.2.2.3.3.2'
assert contract['reviewedRevision'] == (
    'ab03a439f44c9766b951668dd344b6717e327a03'
)

release = contract['release']
assert release == {
    'applicationVersion': 'sha-cf0a6bc',
    'releaseId': 'demo-api-cf0a6bcbc466-cdffd3d71763',
    'sourceCommit': 'cf0a6bcbc466b61f2018a0a92c961d7c03f128e8',
    'imageDigest': (
        'sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623'
    ),
}

rollout = contract['rollout']
assert rollout['name'] == 'demo-api'
assert rollout['namespace'] == 'startup-apps'
assert rollout['revision'] == 70
assert rollout['phase'] == 'Healthy'
assert rollout['abort'] is False
assert rollout['step'] == '7/7'
assert rollout['stableReplicaSet'] == '7557fdfb9b'
assert rollout['currentPodHash'] == rollout['stableReplicaSet']
assert rollout['desiredReplicas'] == rollout['readyReplicas'] == 3

assert contract['analysisRuns'] == [
    {
        'name': 'demo-api-7557fdfb9b-70-2',
        'step': 2,
        'phase': 'Successful',
    },
    {
        'name': 'demo-api-7557fdfb9b-70-5',
        'step': 5,
        'phase': 'Successful',
    },
]

for application in ('root', 'application'):
    argo = contract['argoCD'][application]
    assert argo['targetRevision'] == contract['reviewedRevision']
    assert argo['syncStatus'] == 'Synced'
    assert argo['healthStatus'] == 'Healthy'
    assert argo['diffEmpty'] is True

restoration = contract['idempotentRestoration']
assert restoration['result'] == 'passed'
assert restoration['targetRevision'] == contract['reviewedRevision']
assert restoration['rolloutRevisionBefore'] == 70
assert restoration['rolloutRevisionAfter'] == 70
assert restoration['newRevisionCreated'] is False

retained = contract['retainedEvidence']
assert retained['revision69AnalysisRun'] == 'demo-api-79696cc48f-69-2'
assert retained['revision69Phase'] == 'Failed'
assert retained['retryPerformed'] is False
assert retained['promotionPerformed'] is False

assert contract['repair'] == {
    'file': 'scripts/restore-local-feature-baseline.sh',
    'portableAwkQuoteRemoval': True,
    'stderrExpected': '',
}
for field in (
    'automaticRestore',
    'automaticPromote',
    'automaticRetry',
    'clusterMutationDuringValidation',
    'awsMutationDuringValidation',
):
    assert contract[field] is False, field

restore = Path('scripts/restore-local-feature-baseline.sh').read_text()
portable = 'gsub(/"/, "", $2)'
nonportable = 'gsub(/\\"/, "", $2)'
assert portable in restore
assert nonportable not in restore

document = Path(
    'docs/V0.11.9.2.2.3.3.3_BASELINE_RESTORATION_CLOSURE.md'
).read_text()
for marker in (
    'revision 70',
    'demo-api-7557fdfb9b-70-2',
    'demo-api-7557fdfb9b-70-5',
    'no revision 71',
    'Final feature-revision alignment',
):
    assert marker in document, marker

quality_gates = Path('scripts/validate-ci-quality-gates.sh').read_text()
assert 'validate-v0.11.9.2.2.3.3.3-baseline-restoration-closure.sh' in quality_gates
PY

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT
baseline_image_tag="$(
  awk '
    /^image:/ { in_image=1; next }
    in_image && /^[^[:space:]]/ { exit }
    in_image && $1 == "tag:" { gsub(/"/, "", $2); print $2; exit }
  ' apps/demo-api/helm/values.yaml 2>"${tmp_dir}/awk.stderr"
)"
if [ "${baseline_image_tag}" != "sha-cf0a6bc" ]; then
  echo "Unexpected parsed baseline image tag: ${baseline_image_tag}" >&2
  exit 1
fi
if [ -s "${tmp_dir}/awk.stderr" ]; then
  echo "Baseline image tag parser wrote unexpected stderr:" >&2
  sed 's/^/  /' "${tmp_dir}/awk.stderr" >&2
  exit 1
fi

bash -n scripts/restore-local-feature-baseline.sh
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x scripts/restore-local-feature-baseline.sh
else
  echo "SKIP: shellcheck unavailable; CI and the operator workstation must run it."
fi

bash scripts/validate-v0.11.9.2.2.3.3.2-immutable-local-baseline-image.sh
echo "v0.11.9.2.2.3.3.3 baseline restoration closure passed; no live operation was executed."

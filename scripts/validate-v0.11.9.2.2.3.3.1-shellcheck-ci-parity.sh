#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path

contract = json.loads(Path(
    'delivery/contracts/v0.11.9.2.2.3.3.1-shellcheck-ci-parity.json'
).read_text())
assert contract['version'] == 'v0.11.9.2.2.3.3.1'
assert contract['failedWorkflowRunId'] == '34035241036'
assert contract['failureStage'] == 'quality-gates-before-build-and-push'
assert contract['shellcheckFindings'] == ['SC1091', 'SC2097', 'SC2098', 'SC2015']
assert all(contract['repair'].values())
assert contract['imagePublishedByFailedRun'] is False
assert contract['promotionCreatedByFailedRun'] is False
assert contract['automaticWorkflowRetry'] is False
assert contract['automaticPromote'] is False
assert contract['automaticRetry'] is False
assert contract['clusterMutationDuringValidation'] is False

restore = Path('scripts/restore-local-gitops-baseline.sh').read_text()
for marker in (
    'resolved_target_revision="${TARGET_REVISION}"',
    'TARGET_REVISION="${resolved_target_revision}"',
    'GIT_TARGET_REVISION="${resolved_target_revision}"',
):
    assert marker in restore, marker
assert 'GIT_TARGET_REVISION="${TARGET_REVISION}"' not in restore

runner = Path('scripts/run-local-baseline-restoration-analysis.sh').read_text()
assert 'if [ "${rollout_phase}" != Paused ] || [ "${rollout_step}" != 4 ]; then' in runner
assert '[ "${rollout_phase}" = Paused ] && [ "${rollout_step}" = 4 ]' not in runner

guard = Path(
    'scripts/validate-v0.11.9.2.2.2-baseline-restoration-traffic-guard.sh'
).read_text()
assert 'shellcheck -x scripts/restore-local-gitops-baseline.sh' in guard

quality_gates = Path('scripts/validate-ci-quality-gates.sh').read_text()
assert 'validate-v0.11.9.2.2.3.3.1-shellcheck-ci-parity.sh' in quality_gates

for validator_path in (
    'scripts/validate-v0.11.3-local-feature-gitops.sh',
    'scripts/validate-v0.11.3.1-local-feature-gitops-recovery.sh',
    'scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh',
    'scripts/validate-v0.11.3.5-pre-merge-baseline-restoration.sh',
):
    validator = Path(validator_path).read_text()
    assert 'GIT_TARGET_REVISION="${resolved_target_revision}"' in validator
    assert 'GIT_TARGET_REVISION="${TARGET_REVISION}"' not in validator
PY

bash -n scripts/restore-local-gitops-baseline.sh
bash -n scripts/run-local-baseline-restoration-analysis.sh
bash -n scripts/validate-v0.11.9.2.2.2-baseline-restoration-traffic-guard.sh

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x scripts/restore-local-gitops-baseline.sh \
    scripts/run-local-baseline-restoration-analysis.sh
else
  echo "SKIP: shellcheck unavailable; CI and the operator workstation must run it."
fi

bash scripts/validate-v0.11.9.2.2.3.3-request-series-image-compatibility.sh
echo "v0.11.9.2.2.3.3.1 ShellCheck CI parity repair passed; no live operation was executed."

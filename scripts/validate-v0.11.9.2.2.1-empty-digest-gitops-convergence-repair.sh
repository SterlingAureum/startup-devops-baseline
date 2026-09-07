#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT

bash "${ROOT_DIR}/scripts/test-root-application-sync-convergence.sh"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-local-failure-recovery-rehearsal.py"

python3 - "${ROOT_DIR}" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
read = lambda relative: (root / relative).read_text()
contract = json.loads(read('delivery/contracts/v0.11.9.2.2.1-empty-digest-gitops-convergence-repair.json'))
assert contract['version'] == 'v0.11.9.2.2.1'
assert contract['predecessor'] == 'v0.11.9.2.2'
assert contract['incident']['root_sync_status'] == 'persistent-OutOfSync'
assert contract['incident']['runtime_fault_enabled'] is False
assert contract['repair']['ignore_differences_added'] is False
assert contract['producer_live_executed'] is False
assert contract['runtime_qualified'] is False
for action in ('automatic_promote', 'automatic_retry', 'automatic_abort',
               'automatic_rollback', 'aws_mutation'):
    assert contract[action] is False, action

template = read('clusters/local/platform/templates/demo-api.yaml')
assert '{{ if .Values.demoApi.rehearsalFault.tokenSha256 }}' in template
assert template.count('name: rehearsalFault.tokenSha256') == 1

deploy = read('scripts/deploy-local-feature-gitops.sh')
for required in ('if [ -n "${REHEARSAL_FAULT_TOKEN_SHA256}" ]',
                 'wait_for_application_sync_identity "${ROOT_APP_NAME}"',
                 'Waiting for Root declarative feature ownership to converge'):
    assert required in deploy, required

helper = read('scripts/lib/argocd-operation.sh')
for required in ('wait_for_application_sync_identity()', 'APPLICATION_SYNC_POLL_SECONDS',
                 'did not converge to Synced revision'):
    assert required in helper, required

runner = read('scripts/local-failure-recovery-rehearsal.py')
assert runner.count("item.get('value', '')") == 2

historical = read('scripts/validate-v0.11.3.4-unified-feature-revision-rendering.sh')
assert 'fault_parameters = ["rehearsalFault.mode"]' in historical
fixture = read('scripts/validate-v0.11.4.0.1-helm-successor-coverage.sh')
assert fixture.count('name: rehearsalFault.tokenSha256') == 0
PY

if command -v helm >/dev/null 2>&1; then
  common=(
    --set-string git.targetRevision=0123456789abcdef0123456789abcdef01234567
    --set demoApi.localImage.enabled=true
    --set-string demoApi.localImage.repository=startup-devops-baseline/demo-api
    --set-string demoApi.localImage.tag=v0.11.9.2.2-local
    --set-string demoApi.localImage.pullPolicy=Never
    --set-string demoApi.localImage.applicationVersion=v0.11.9.2.2-local
  )
  helm template local-platform "${ROOT_DIR}/clusters/local/platform" \
    "${common[@]}" >"${WORK_DIR}/disabled.yaml"
  helm template local-platform "${ROOT_DIR}/clusters/local/platform" \
    "${common[@]}" \
    --set-string demoApi.rehearsalFault.mode=availability-503 \
    --set-string demoApi.rehearsalFault.tokenSha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
    >"${WORK_DIR}/armed.yaml"
  python3 - "${WORK_DIR}/disabled.yaml" "${WORK_DIR}/armed.yaml" <<'PY'
from pathlib import Path
import re
import sys

def demo(text):
    documents = re.split(r'^---\s*$', text, flags=re.MULTILINE)
    return next(item for item in documents if 'kind: Application' in item and
                re.search(r'^  name: demo-api$', item, re.MULTILINE))

disabled = demo(Path(sys.argv[1]).read_text())
armed = demo(Path(sys.argv[2]).read_text())
assert 'name: rehearsalFault.mode' in disabled
assert 'name: rehearsalFault.tokenSha256' not in disabled
assert 'name: rehearsalFault.tokenSha256' in armed
assert 'a' * 64 in armed
print('Disabled and armed Helm parameter normalization passed.')
PY
else
  echo 'SKIP: helm unavailable; CI must run disabled and armed render checks.'
fi

bash "${ROOT_DIR}/scripts/validate-v0.11.9.2.2-local-failure-recovery-live-qualification.sh"
echo 'v0.11.9.2.2.1 empty-digest GitOps convergence repair passed; no live operation was executed.'

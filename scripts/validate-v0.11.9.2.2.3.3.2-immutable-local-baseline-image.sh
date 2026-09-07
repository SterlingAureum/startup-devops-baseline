#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

python3 - <<'PY'
import json
from pathlib import Path
import re

contract = json.loads(Path(
    'delivery/contracts/v0.11.9.2.2.3.3.2-immutable-local-baseline-image.json'
).read_text())
assert contract['version'] == 'v0.11.9.2.2.3.3.2'
assert contract['predecessor'] == 'v0.11.9.2.2.3.3.1'
assert contract['build']['workflowRunId'] == '34070524953'
assert contract['build']['conclusion'] == 'success'
assert contract['scope']['localDefaultValuesOnly'] is True
assert contract['scope']['awsReleaseValuesChanged'] is False
assert contract['scope']['revision69RetainedAsEvidence'] is True
assert contract['scope']['freshRolloutRevisionRequired'] is True
for field in ('automaticRestore', 'automaticPromote', 'automaticRetry',
              'clusterMutationDuringValidation', 'awsMutationDuringValidation'):
    assert contract[field] is False, field

expected = {
    ('image', 'repository'): contract['image']['repository'],
    ('image', 'tag'): contract['image']['tag'],
    ('image', 'digest'): contract['image']['digest'],
    ('release', 'applicationVersion'): contract['release']['applicationVersion'],
    ('delivery', 'sourceRepository'): contract['source']['repository'],
    ('delivery', 'sourceCommit'): contract['source']['commit'],
    ('delivery', 'workflowRunId'): contract['build']['workflowRunId'],
}

section = None
actual = {}
for raw in Path('apps/demo-api/helm/values.yaml').read_text().splitlines():
    if raw and not raw.startswith(' ') and raw.endswith(':'):
        section = raw[:-1]
        continue
    match = re.fullmatch(r'  ([A-Za-z][A-Za-z0-9]*):\s*(.+)', raw)
    if section is None or match is None:
        continue
    key, encoded = match.groups()
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError:
        value = encoded.strip()
    actual[(section, key)] = value
for key, value in expected.items():
    assert actual.get(key) == value, (key, actual.get(key), value)

assert contract['image']['reference'] == (
    f"{contract['image']['repository']}@{contract['image']['digest']}"
)
assert contract['image']['tag'] == f"sha-{contract['source']['commit'][:7]}"
assert contract['release']['releaseId'] == (
    f"demo-api-{contract['source']['commit'][:12]}-"
    f"{contract['image']['digest'].removeprefix('sha256:')[:12]}"
)

restore = Path('scripts/restore-local-feature-baseline.sh').read_text()
for marker in (
    'derive-demo-api-release-id.py',
    '--format json',
    'declarative local baseline image identity is invalid',
    'Validated baseline release:',
    'No Kubernetes restoration operation was started',
):
    assert marker in restore, marker
assert restore.index('derive-demo-api-release-id.py') < restore.index(
    'exec "${ROOT_DIR}/scripts/restore-local-gitops-baseline.sh"')

for release_file in (
    'apps/demo-api/helm/values/releases/aws-dev.yaml',
    'apps/demo-api/helm/values/releases/aws-test.yaml',
    'apps/demo-api/helm/values/releases/aws-prod.yaml',
):
    text = Path(release_file).read_text()
    assert contract['image']['digest'] not in text, release_file
    assert contract['source']['commit'] not in text, release_file
PY

release_id="$(
  python3 scripts/derive-demo-api-release-id.py \
    --release-file apps/demo-api/helm/values.yaml
)"
if [ "${release_id}" != "demo-api-cf0a6bcbc466-cdffd3d71763" ]; then
  echo "Unexpected local baseline release ID: ${release_id}" >&2
  exit 1
fi

bash -n scripts/restore-local-feature-baseline.sh
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x scripts/restore-local-feature-baseline.sh
else
  echo "SKIP: shellcheck unavailable; CI and the operator workstation must run it."
fi

if command -v helm >/dev/null 2>&1; then
  helm lint apps/demo-api/helm >/dev/null
  rendered="$(helm template demo-api apps/demo-api/helm --namespace startup-apps)"
  grep -Fq 'ghcr.io/sterlingaureum/startup-devops-baseline/demo-api@sha256:cdffd3d71763540976570da1f201661d24c641ec459be812b20f1517f3fd2623' <<<"${rendered}"
  grep -Fq 'platform.startup.dev/application-version: "sha-cf0a6bc"' <<<"${rendered}"
  grep -Fq 'platform.startup.dev/release-id: "demo-api-cf0a6bcbc466-cdffd3d71763"' <<<"${rendered}"
else
  echo "SKIP: helm unavailable; CI and the operator workstation must render the baseline."
fi

bash scripts/validate-v0.11.9.2.2.3.3.1-shellcheck-ci-parity.sh
echo "v0.11.9.2.2.3.3.2 immutable local baseline image identity passed; no live operation was executed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.1-aws-test-successor-validation-repair.json"
CHECK="${ROOT_DIR}/scripts/check-v0.11.9.3.6.6.1-aws-test-release-successor.py"
FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "${FIXTURE_DIR}"' EXIT

python3 - "${CONTRACT}" <<'PY'
import json, pathlib, sys
c = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert c["schemaVersion"] == c["version"] == "v0.11.9.3.6.6.1"
assert c["predecessor"] == "v0.11.9.3.6.6"
assert c["implementationBaselineCommit"] == "3c14cca2b394799f3d78582e9eb31bec376edf65"
assert c["repair"]["allowedStates"] == {
    "historical-aws-test": "2817d5d1a0f728a4e88e289ca46f5259a511339924daf303fe285316ccaffa22",
    "reviewed-promoted-candidate": "5238e8bcdfb23afb882eaabda6b3f732f5a2f461cc38bd9f09d26c8fff7a5d46",
}
assert c["repair"]["unknownOrPartialIdentityRejected"] is True
assert c["repair"]["awsProdCandidateForbidden"] is True
assert all(value is False for value in c["scope"].values())
assert c["executionAuthorized"] is False
PY

historical="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-test.yaml"
promoted="${ROOT_DIR}/apps/demo-api/helm/values/releases/aws-dev.yaml"
test "$("${CHECK}" --release-file "${historical}")" = historical-aws-test
test "$("${CHECK}" --release-file "${promoted}")" = reviewed-promoted-candidate

cp "${promoted}" "${FIXTURE_DIR}/unknown.yaml"
sed -i 's/sha-cf0a6bc/sha-0000000/' "${FIXTURE_DIR}/unknown.yaml"
if "${CHECK}" --release-file "${FIXTURE_DIR}/unknown.yaml" >/dev/null 2>&1; then
  echo "Unknown or partial aws-test identity was accepted." >&2
  exit 1
fi

python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for name in (
    "validate-v0.11.9.2.2.3.3.2-immutable-local-baseline-image.sh",
    "validate-v0.11.9.3.0-remote-release-rehearsal-design.sh",
    "validate-v0.11.9.3.3.1-immutable-local-aws-successor-repair.sh",
    "validate-v0.11.9.3.3.2-remote-successor-chain-repair.sh",
):
    text = (root / "scripts" / name).read_text()
    assert "check-v0.11.9.3.6.6.1-aws-test-release-successor.py" in text, name
    assert "AWS_TEST_RELEASE_FILE" in text, name
PY

bash "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6-reviewed-live-aws-test-promotion-handoff.sh"
python3 -m py_compile "${CHECK}"
bash -n "$0"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$0"; fi

echo "v0.11.9.3.6.6.1 aws-test reviewed successor validation passed; no workflow, PR or live operation was executed."

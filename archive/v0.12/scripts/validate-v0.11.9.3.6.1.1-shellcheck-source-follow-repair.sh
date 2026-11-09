#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.1.1-shellcheck-source-follow-repair.json"
PREDECESSOR_VALIDATOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.sh"
APPLY_SCRIPT="${ROOT_DIR}/scripts/apply-eks-api-access-cidr.sh"
WORK_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${PREDECESSOR_VALIDATOR}" "${APPLY_SCRIPT}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
validator_source = Path(sys.argv[3]).read_text()
apply_source = Path(sys.argv[4]).read_text()

assert contract["schemaVersion"] == "v0.11.9.3.6.1.1"
assert contract["version"] == "v0.11.9.3.6.1.1"
assert contract["predecessor"] == "v0.11.9.3.6.1"
assert contract["status"] == "shellcheck-source-follow-parity-repaired"
assert contract["applicationBaseline"] == {
    "commit": "4ecf8515c636066a4e8e9cc640ee96473fbfd21d",
    "requiredAppliedIncrement": "v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor",
}
assert contract["diagnostic"]["code"] == "SC1091"
assert contract["diagnostic"]["checkedScript"] == "scripts/apply-eks-api-access-cidr.sh"
assert contract["diagnostic"]["controlledSource"] == "scripts/aws-environment-context.sh"
assert contract["diagnostic"]["sourceAnnotationRetained"] is True
assert contract["repair"] == {
    "validator": "scripts/validate-v0.11.9.3.6.1-aws-dev-live-rehearsal-create-executor.sh",
    "shellcheckExternalSources": True,
    "shellcheckFlag": "-x",
    "workingDirectory": "repository-root",
    "offlineInvocationRegression": "scripts/validate-v0.11.9.3.6.1.1-shellcheck-source-follow-repair.sh",
    "runtimeSemanticsChanged": False,
}
assert all(value is False for value in contract["producerExecution"].values())
assert contract["executionAuthorized"] is False
assert contract["nextCheckpoint"] == "v0.11.9.3.6.2-aws-dev-infrastructure-create-execution"

assert 'cd "${ROOT_DIR}"' in validator_source
assert "shellcheck -x \\\n" in validator_source
assert '# shellcheck source=scripts/aws-environment-context.sh' in apply_source

for relative, marker in (
    ("README.md", "v0.11.9.3.6.1.1-shellcheck-source-follow-repair"),
    ("CHANGELOG.md", "## v0.11.9.3.6.1.1"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.1.1"),
    ("docs/V0.11.9.3.6.1.1_SHELLCHECK_SOURCE_FOLLOW_REPAIR.md", "ShellCheck source-follow repair"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.1.1-shellcheck-source-follow-repair.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.1.1-shellcheck-source-follow-repair.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.1.1 static source-follow and no-runtime-change contracts passed.")
PY

cat > "${WORK_DIR}/shellcheck" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
: "${SHELLCHECK_CALL_LOG:?}"
{
  printf '%s' "$#"
  for argument in "$@"; do
    printf '\t%s' "${argument}"
  done
  printf '\n'
} >> "${SHELLCHECK_CALL_LOG}"
SH
chmod 0755 "${WORK_DIR}/shellcheck"

SHELLCHECK_CALL_LOG="${WORK_DIR}/shellcheck-calls.tsv" \
PATH="${WORK_DIR}:${PATH}" \
bash "${PREDECESSOR_VALIDATOR}" \
  > "${WORK_DIR}/predecessor.stdout" \
  2> "${WORK_DIR}/predecessor.stderr"

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${WORK_DIR}/shellcheck-calls.tsv" "${APPLY_SCRIPT}" <<'PY'
from pathlib import Path
import sys


calls = Path(sys.argv[1]).read_text().splitlines()
assert calls, "predecessor validator did not invoke ShellCheck"
fields = calls[-1].split("\t")
assert fields[0] == "4", fields
assert fields[1] == "-x", fields
assert fields[2] == sys.argv[2], fields
print("v0.11.9.3.6.1.1 recorded ShellCheck invocation passed with -x.")
PY

bash -n "${PREDECESSOR_VALIDATOR}"
bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.1.1-shellcheck-source-follow-repair.sh"

if command -v shellcheck >/dev/null 2>&1; then
  (
    cd "${ROOT_DIR}"
    shellcheck -x \
      "${APPLY_SCRIPT}" \
      "${PREDECESSOR_VALIDATOR}" \
      "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.1.1-shellcheck-source-follow-repair.sh"
  )
else
  echo "SKIP: shellcheck unavailable; offline invocation regression passed."
fi

echo "v0.11.9.3.6.1.1 ShellCheck source-follow repair validation passed; no live operation was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.json"
PREFLIGHT="${ROOT_DIR}/scripts/preflight-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py"
EXECUTOR="${ROOT_DIR}/scripts/execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py"
TESTS="${ROOT_DIR}/scripts/test-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py"
PREDECESSOR="${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.sh"
LEGACY_LIFECYCLE="${ROOT_DIR}/scripts/validate-v0.9-lifecycle-contracts.sh"

for command_name in bash python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

PYTHONDONTWRITEBYTECODE=1 python3 - \
  "${ROOT_DIR}" "${CONTRACT}" "${PREFLIGHT}" "${EXECUTOR}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


root = Path(sys.argv[1])
contract = json.loads(Path(sys.argv[2]).read_text())
preflight = Path(sys.argv[3]).read_text()
executor = Path(sys.argv[4]).read_text()

version = "v0.11.9.3.6.6.6"
assert contract["schemaVersion"] == contract["version"] == version
assert contract["predecessor"] == "v0.11.9.3.6.6.5.2"
assert contract["implementationBaselineCommit"] == "c876331f1191d489d2bf369047ec68990dac3885"
assert contract["status"] == "guarded-aws-dev-residual-cost-audit-implemented-not-executed"
assert contract["nextAction"] == "merge-run-fresh-preflight-review-verify-and-obtain-separate-read-only-audit-approval"

assert contract["entrypoints"] == {
    "preflight": "scripts/preflight-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py",
    "executor": "scripts/execute-v0.11.9.3.6.6.6-aws-dev-residual-cost-audit.py",
    "existingAudit": "scripts/validate-aws-cost-cleanup.sh",
}

fingerprints = contract["inputFingerprints"]
assert fingerprints == {
    "teardownExecutionEvidenceSha256": "85a4eed6b50b75883cfeccd11081f915591ea28c5aa1a03d97c34fbcd9067b4b",
    "existingAuditSha256": "ab0bad09b228d09e9451863c047c8da3e4ebf77198f277ad78117b99383f3df7",
}
for relative, digest in (
    ("delivery/contracts/v0.11.9.3.6.6.5.2-aws-dev-teardown-execution-evidence.json", fingerprints["teardownExecutionEvidenceSha256"]),
    ("scripts/validate-aws-cost-cleanup.sh", fingerprints["existingAuditSha256"]),
):
    assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest

assert contract["confirmations"] == {
    "preflight": "observe-reviewed-aws-dev-residual-cost-audit-preflight",
    "execute": "execute-reviewed-aws-dev-residual-cost-audit",
}

controls = contract["controls"]
for key in (
    "exactProtectedMainRequired",
    "expectedAwsAccountRequired",
    "noActiveRehearsalEksEnvironmentRequired",
    "terraformBackendMustBeReadable",
    "terraformStateMustBeEmpty",
    "authoritativeBucketListMustProveAbsence",
    "secretMustBeAbsentOrRecoveryWindowTombstone",
    "freshReviewedPreflightRequired",
    "immediatePreflightMustMatchReviewedResult",
    "publicResultRedacted",
):
    assert controls[key] is True, key
assert controls["targetEnvironment"] == "aws-dev"
assert controls["maximumWindowSeconds"] == 14400
assert controls["minimumRemainingSeconds"] == 900
assert controls["fullAuditMaximumExecutions"] == 1
assert controls["automaticRetryAllowed"] is False
assert controls["privateOutputDirectoryMode"] == "0700"
assert controls["privateOutputFileMode"] == "0600"

assert contract["boundaries"] == {
    "auditExecuted": False,
    "mutationExecuted": False,
    "awsTestCreated": False,
    "executionAuthorized": False,
}
assert all(value is False for value in contract["packageProducer"].values())

for marker in (
    "EXPECTED_AWS_ACCOUNT_ID",
    'AWS_ENVIRONMENT") != "aws-dev"',
    "require_exact_git(expected, runner)",
    "TEARDOWN_EVIDENCE_SHA256",
    "AUDIT_SHA256",
    '"eks",',
    '"list-clusters",',
    '"s3api", "list-buckets"',
    '"secretsmanager",',
    '"list-secrets",',
    '"--include-planned-deletion",',
    '"state", "list"',
    "terraform_backend_readable",
    "terraform_state_resource_count",
    "backup_bucket_absent",
    "secret_live_value_absent",
    "secret_tombstone_present",
    "account_id_emitted",
):
    assert marker in preflight, marker
for forbidden in (
    '"terraform", "destroy"',
    '"terraform", "apply"',
    '"aws", "ec2", "delete',
    '"kubectl"',
):
    assert forbidden not in preflight, forbidden

for marker in (
    "EXECUTION_CONFIRMATION",
    "immediate != reviewed",
    "MAXIMUM_WINDOW_SECONDS",
    "MINIMUM_REMAINING_SECONDS",
    "capture_output=True",
    "os.O_EXCL",
    "os.O_NOFOLLOW",
    'env["AWS_ENVIRONMENT"] = "aws-dev"',
    "automatic_retry_performed",
    "mutation_executed",
    "private_stdout_sha256",
    "private_stderr_sha256",
    "private_resource_id_output_committed",
):
    assert marker in executor, marker
assert "while True" not in executor
assert "-auto-approve" not in executor
assert "stdout=sys.stderr" not in executor

serialized = json.dumps(contract, sort_keys=True)
assert not re.search(r"\b[0-9]{12}\b", serialized)
assert "arn:aws:" not in serialized
assert "/tmp/" not in serialized
assert not re.search(r"\b(?:vpc|subnet|sg|eni|vol|fleet)-[0-9a-f-]+\b", serialized)

for relative, marker in (
    ("README.md", "v0.11.9.3.6.6.6 guarded aws-dev residual-cost audit"),
    ("CHANGELOG.md", "## v0.11.9.3.6.6.6"),
    ("docs/ROADMAP.md", "v0.11.9.3.6.6.6"),
    ("docs/V0.11.9.3.6.6.6_GUARDED_AWS_DEV_RESIDUAL_COST_AUDIT.md", "execute-reviewed-aws-dev-residual-cost-audit"),
    ("scripts/validate-ci-quality-gates.sh", "validate-v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.sh"),
    (".github/CODEOWNERS", "/delivery/contracts/v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.json"),
):
    assert marker in (root / relative).read_text(), relative

print("v0.11.9.3.6.6.6 exact-main, strict-state, redaction and no-mutation contracts passed.")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "${TESTS}"
python3 -m py_compile "${PREFLIGHT}" "${EXECUTOR}" "${TESTS}"
python3 -m json.tool "${CONTRACT}" >/dev/null

bash "${PREDECESSOR}"
bash "${LEGACY_LIFECYCLE}"

bash -n "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.sh"

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck "${ROOT_DIR}/scripts/validate-v0.11.9.3.6.6.6-guarded-aws-dev-residual-cost-audit.sh"
else
  echo "SKIP: shellcheck unavailable; CI must run it."
fi

echo "v0.11.9.3.6.6.6 guarded aws-dev residual-cost audit passed; no live audit was executed."

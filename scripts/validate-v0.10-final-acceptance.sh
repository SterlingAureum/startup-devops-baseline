#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT="${ROOT_DIR}/delivery/contracts/v0.10-final-acceptance.json"
SCHEMA="${ROOT_DIR}/delivery/contracts/v0.10-final-evidence.schema.json"
EXAMPLE="${ROOT_DIR}/delivery/contracts/examples/v0.10-final-evidence-input.example.json"
RUNBOOK="${ROOT_DIR}/docs/V0.10_FINAL_ACCEPTANCE_RUNBOOK.md"

for command in bash git jq python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Validating final acceptance contract"
jq --exit-status '
  .schemaVersion == "v0.10.8" and
  .version == "v0.10" and
  .repository == "SterlingAureum/startup-devops-baseline" and
  .protectedRef == "refs/heads/main" and
  .acceptanceMode == "clean-room-dev-test-prod-static" and
  .liveCheckpoints == [
    "status-read-only",
    "release-supersede",
    "environment-absent-resume",
    "interrupted-run-resume",
    "aws-dev-qualification",
    "aws-dev-to-aws-test-promotion",
    "aws-test-reviewed-canary-completion",
    "aws-test-qualification",
    "aws-test-to-aws-prod-static-promotion",
    "manual-rollback-workflow-boundary",
    "aws-test-cost-cleanup",
    "aws-dev-cost-cleanup"
  ] and
  .deterministicCheckpoints == [
    "exact-failed-attempt-retry",
    "bundle-expiring-classification",
    "bundle-expired-classification",
    "bundle-scope-drift-classification",
    "bundle-release-drift-classification",
    "dev-test-rollback-handoff-resolution"
  ] and
  .activationVariables == [
    "DEMO_API_AWS_DEV_QUALIFICATION_ENABLED",
    "DEMO_API_AWS_TEST_PROMOTION_ENABLED",
    "DEMO_API_AWS_TEST_QUALIFICATION_ENABLED",
    "DEMO_API_AWS_PROD_PROMOTION_ENABLED"
  ] and
  .requiredChecks == [
    "validate / quality-gates",
    "validate / demo-api release currentness"
  ] and
  .runtimeEnvironments == ["aws-dev", "aws-test"] and
  .productionBoundary == {
    "mode": "prod-static",
    "environmentApprovalRequired": true,
    "releaseOnlyPullRequestRequired": true,
    "runtimeQualification": false,
    "clusterCreation": false,
    "kubernetesWrites": false,
    "automaticMerge": false,
    "automaticRollback": false
  } and
  .cleanup.environments == ["aws-test", "aws-dev"] and
  .cleanup.validator == "scripts/validate-aws-cost-cleanup.sh" and
  .cleanup.ephemeralRunnersMustStop == true and
  .cleanup.activationVariablesMustBeDisabled == true and
  .closure.evidenceOnlyPullRequest == true and
  .closure.tagAfterEvidenceMerge == "v0.10.8" and
  (.acceptanceScopePatterns | type == "array" and length > 10)
' "${CONTRACT}" >/dev/null

echo "==> Parsing final evidence schema and operator template"
jq --exit-status '
  .properties.production["$ref"] == "#/$defs/production" and
  .["$defs"].production.properties.mode.const == "prod-static" and
  .["$defs"].production.properties.runtimeQualificationPerformed.const == false and
  .["$defs"].production.properties.clusterCreated.const == false and
  .["$defs"].production.properties.kubernetesWritesPerformed.const == false and
  .["$defs"].recovery.properties.rollbackAutomaticallyDispatched.const == false and
  .["$defs"].recovery.properties.rollbackPullRequestMerged.const == false
' "${SCHEMA}" >/dev/null

jq --exit-status '
  .schemaVersion == "v0.10.8-input" and
  .validatedControlPlaneSha == "REPLACE_WITH_40_CHARACTER_MAIN_SHA" and
  .github.pullRequests.prodPromotion == 0 and
  .production.mode == "prod-static" and
  .production.runtimeQualificationPerformed == false
' "${EXAMPLE}" >/dev/null

echo "==> Compiling final evidence tools"
python3 -m py_compile \
  "${ROOT_DIR}/scripts/v010_final_evidence.py" \
  "${ROOT_DIR}/scripts/write-v0.10-final-evidence.py" \
  "${ROOT_DIR}/scripts/validate-v0.10-final-evidence.py"

echo "==> Exercising final evidence positive and negative structure"
python3 - "${ROOT_DIR}" <<'PY'
from copy import deepcopy
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
from v010_final_evidence import acceptance_scope, validate_structure

source = "a" * 40
digest = "sha256:" + "b" * 64
release_id = f"demo-api-{source[:12]}-{digest.removeprefix('sha256:')[:12]}"
document = {
    "schemaVersion": "v0.10.8",
    "version": "v0.10",
    "status": "accepted",
    "recordedAt": "2026-08-13T12:00:00Z",
    "repository": "SterlingAureum/startup-devops-baseline",
    "protectedRef": "refs/heads/main",
    "validatedControlPlaneSha": "c" * 40,
    "release": {
        "releaseId": release_id,
        "sourceCommit": source,
        "imageDigest": digest,
        "environmentReleaseSha256": {environment: "d" * 64 for environment in ("aws-dev", "aws-test", "aws-prod")},
    },
    "qualificationBundles": {
        environment: {
            "path": f"evidence/demo-api/qualification/{environment}/{release_id}/123-1.json",
            "sha256": "e" * 64,
        }
        for environment in ("aws-dev", "aws-test")
    },
    "github": {
        "runs": {
            key: str(index)
            for index, key in enumerate((
                "statusReadOnly", "supersedeStatus", "environmentAbsent", "interrupted",
                "resumed", "devQualification", "testPromotion", "testQualification",
                "prodPromotion", "rollbackBoundary",
            ), start=1)
        },
        "pullRequests": {
            key: index
            for index, key in enumerate((
                "supersededRelease", "devQualification", "testPromotion",
                "testQualification", "prodPromotion", "rollbackBoundary",
            ), start=1)
        },
    },
    "recovery": {
        "statusReadOnlyNoDispatch": True,
        "environmentAbsentResumed": True,
        "interruptedRunRecovered": True,
        "duplicatePullRequestCreated": False,
        "supersededReleaseBlocked": True,
        "supersededPullRequestClosedByHuman": True,
        "expiryValidationMode": "deterministic-time-shift",
        "requalificationBehaviorValidated": True,
        "rollbackHandoffMode": "deterministic-handoff-plus-live-manual-pr",
        "rollbackAutomaticallyDispatched": False,
        "rollbackPullRequestMerged": False,
    },
    "production": {
        "mode": "prod-static",
        "environmentApprovalPassed": True,
        "releaseOnlyPullRequestMerged": True,
        "runtimeQualificationPerformed": False,
        "clusterCreated": False,
        "kubernetesWritesPerformed": False,
        "automaticMerge": False,
        "automaticRollback": False,
    },
    "cleanup": {
        "aws-dev": {"status": "residual-cost-audit-passed", "completedAt": "2026-08-13T11:00:00Z"},
        "aws-test": {"status": "residual-cost-audit-passed", "completedAt": "2026-08-13T10:00:00Z"},
        "ephemeralRunnersStopped": True,
        "activationVariablesDisabled": True,
    },
    "verification": {
        "acceptanceContractSha256": "f" * 64,
        "acceptanceScopeSha256": "1" * 64,
        "acceptanceScopeFileCount": 1,
        "offlineGate": "scripts/validate-v0.10-final-acceptance.sh",
    },
}
validate_structure(document)

mutations = [
    ("status dispatch", lambda d: d["recovery"].__setitem__("statusReadOnlyNoDispatch", False)),
    ("duplicate PR", lambda d: d["recovery"].__setitem__("duplicatePullRequestCreated", True)),
    ("automatic rollback", lambda d: d["production"].__setitem__("automaticRollback", True)),
    ("prod runtime", lambda d: d["production"].__setitem__("runtimeQualificationPerformed", True)),
    ("prod cluster", lambda d: d["production"].__setitem__("clusterCreated", True)),
    ("rollback merge", lambda d: d["recovery"].__setitem__("rollbackPullRequestMerged", True)),
    ("cleanup residual", lambda d: d["cleanup"]["aws-test"].__setitem__("status", "residual-found")),
    ("runner leak", lambda d: d["cleanup"].__setitem__("ephemeralRunnersStopped", False)),
    ("placeholder run", lambda d: d["github"]["runs"].__setitem__("statusReadOnly", "REPLACE_ME")),
    ("placeholder PR", lambda d: d["github"]["pullRequests"].__setitem__("prodPromotion", 0)),
]
for label, mutate in mutations:
    candidate = deepcopy(document)
    mutate(candidate)
    try:
        validate_structure(candidate)
    except (ValueError, TypeError):
        continue
    raise SystemExit(f"Unsafe final evidence mutation was accepted: {label}")

contract = json.loads((root / "delivery/contracts/v0.10-final-acceptance.json").read_text())
scope_hash, scope_count = acceptance_scope(root, contract)
if len(scope_hash) != 64 or scope_count < 20:
    raise SystemExit("Final acceptance Scope is unexpectedly small")
PY

echo "==> Validating Runbook command and safety coverage"
python3 - "${RUNBOOK}" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text()
required = [
    "operation=status",
    "operation=resume",
    "Release supersede",
    "environment_absent",
    "DEMO_API_AWS_DEV_QUALIFICATION_ENABLED",
    "DEMO_API_AWS_TEST_PROMOTION_ENABLED",
    "DEMO_API_AWS_TEST_QUALIFICATION_ENABLED",
    "DEMO_API_AWS_PROD_PROMOTION_ENABLED",
    "complete-aws-test-rollout.sh",
    "demo-api-rollback.yaml",
    "destroy-aws-test.sh",
    "destroy-aws-dev.sh",
    "validate-aws-cost-cleanup.sh",
    "write-v0.10-final-evidence.py",
    "validate-v0.10-final-evidence.py",
    "prod-static",
    "git tag -a v0.10.8",
]
for marker in required:
    if marker not in text:
        raise SystemExit(f"Final Runbook is missing: {marker}")

for forbidden in (
    "terraform -chdir=infra/terraform/aws/environments/prod apply",
    "kubectl --context aws-prod",
    "DEMO_API_AWS_PROD_RUNTIME",
):
    if forbidden in text:
        raise SystemExit(f"Final Runbook violates prod-static boundary: {forbidden}")

if text.index("evidence PR is merged") > text.index("git tag -a v0.10.8"):
    raise SystemExit("Final tag appears before evidence merge")
PY

echo "==> Checking final evidence directory remains unclaimed before live acceptance"
if find "${ROOT_DIR}/evidence/v0.10/final" -type f -name '*.json' -print -quit 2>/dev/null | grep -q .; then
  echo "A final v0.10 success record exists before live acceptance." >&2
  exit 1
fi

echo "v0.10.8 final acceptance contracts and offline behavior passed."

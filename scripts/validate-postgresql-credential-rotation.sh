#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - \
  "${ROOT_DIR}/scripts/stage-demo-api-postgresql-credential.sh" \
  "${ROOT_DIR}/scripts/discard-demo-api-postgresql-credential.sh" \
  "${ROOT_DIR}/scripts/activate-demo-api-postgresql-credential.sh" \
  "${ROOT_DIR}/scripts/reload-demo-api-postgresql-workload.sh" \
  "${ROOT_DIR}/scripts/validate-postgresql-credential-rotation-aws.sh" \
  "${ROOT_DIR}/scripts/validate-postgresql-credential-activation-aws.sh" \
  "${ROOT_DIR}/scripts/run-demo-api-postgresql-credential-rollback-drill.sh" \
  "${ROOT_DIR}/scripts/validate-postgresql-credential-rollback-aws.sh" \
  "${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh" \
  "${ROOT_DIR}/docs/archive/V0.8.5_POSTGRESQL_CREDENTIAL_ROTATION.md" \
  "${ROOT_DIR}/docs/ROADMAP.md" \
  "${ROOT_DIR}/CHANGELOG.md" <<'PY'
from pathlib import Path
import sys

(
    stage_path,
    discard_path,
    activate_path,
    reload_path,
    staging_runtime_path,
    activation_runtime_path,
    rollback_path,
    rollback_runtime_path,
    database_runtime_path,
    doc_path,
    roadmap_path,
    changelog_path,
) = (Path(value) for value in sys.argv[1:])

paths = (
    stage_path,
    discard_path,
    activate_path,
    reload_path,
    staging_runtime_path,
    activation_runtime_path,
    rollback_path,
    rollback_runtime_path,
    database_runtime_path,
    doc_path,
    roadmap_path,
    changelog_path,
)
for path in paths:
    if not path.is_file():
        raise SystemExit(f"Required v0.8.5 file is missing: {path}")

stage = stage_path.read_text()
discard = discard_path.read_text()
activate = activate_path.read_text()
reload = reload_path.read_text()
staging_runtime = staging_runtime_path.read_text()
activation_runtime = activation_runtime_path.read_text()
rollback = rollback_path.read_text()
rollback_runtime = rollback_runtime_path.read_text()
database_runtime = database_runtime_path.read_text()
doc = doc_path.read_text()
roadmap = roadmap_path.read_text()
changelog = changelog_path.read_text()


def require(text: str, marker: str, context: str) -> None:
    if marker not in text:
        raise SystemExit(f"Missing {context}: {marker}")


for marker in (
    'CONFIRM_POSTGRESQL_CREDENTIAL_STAGE:-}" != "stage-awspending"',
    '--version-stage AWSCURRENT',
    '--version-stages AWSPENDING',
    'secrets.token_urlsafe(48)',
    'file:///dev/stdin',
    'ExternalSecret is not Ready or is not pinned to AWSCURRENT.',
    'AWSCURRENT, PostgreSQL, ExternalSecret, Kubernetes Secret, and demo-api were not changed.',
):
    require(stage, marker, "safe candidate-staging contract")

for forbidden in (
    "SOURCE_SECRET",
    "SOURCE_DIGEST",
    "ALTER ROLE",
    "rollout restart",
    "kubectl delete pod",
    "force-sync=",
    "--move-to-version-id",
):
    if forbidden in stage:
        raise SystemExit(f"Candidate staging contains forbidden action or legacy dependency: {forbidden}")

for marker in (
    'CONFIRM_POSTGRESQL_CREDENTIAL_DISCARD:-}" != "discard-awspending"',
    '--version-stage AWSPENDING',
    '--remove-from-version-id "${PENDING_VERSION_ID}"',
    'AWSCURRENT was not moved.',
):
    require(discard, marker, "guarded candidate-discard contract")

for forbidden in ("delete-secret", "--move-to-version-id"):
    if forbidden in discard:
        raise SystemExit(f"Discard script contains destructive stage operation: {forbidden}")

for marker in (
    'CONFIRM_POSTGRESQL_CREDENTIAL_ACTIVATION:-}" != "activate-awspending"',
    'write_postgres_role_password "${PENDING_VERSION_ID}"',
    "SET log_statement = 'none';",
    'credential_connects "${PENDING_VERSION_ID}"',
    '--version-stage AWSCURRENT',
    '--move-to-version-id "${PENDING_VERSION_ID}"',
    '--remove-from-version-id "${CURRENT_VERSION_ID}"',
    '--version-stage AWSPENDING',
    'sync_external_secret_to_digest "${PENDING_DIGEST}"',
    'EXPECTED_DATABASE_URL_SHA256="${PENDING_DIGEST}"',
    'POSTGRESQL_WORKLOAD_RELOAD_MODE=credential-transition',
    'compensate_cutover',
    'restore_version_stages',
    'EXPECTED_DATABASE_URL_SHA256="${CURRENT_DIGEST}"',
    'The candidate is AWSCURRENT; the original version is retained as AWSPREVIOUS.',
):
    require(activate, marker, "guarded credential-activation contract")

if activate.count('POSTGRESQL_WORKLOAD_RELOAD_MODE=credential-transition') != 2:
    raise SystemExit("Activation and compensation must both use credential-transition reload mode.")

for forbidden in (
    "put-secret-value",
    "secrets.token_urlsafe",
    "kubectl rollout restart",
    "kubectl patch deployment",
    "kubectl set env",
    "set -x",
):
    if forbidden in activate:
        raise SystemExit(f"Activation script contains forbidden mutation or logging action: {forbidden}")

if activate.rfind('write_postgres_role_password "${PENDING_VERSION_ID}"') > activate.rfind(
    '--move-to-version-id "${PENDING_VERSION_ID}"'
):
    raise SystemExit("PostgreSQL must change and validate before AWSCURRENT moves.")
if activate.rfind('sync_external_secret_to_digest "${PENDING_DIGEST}"') > activate.rfind(
    'EXPECTED_DATABASE_URL_SHA256="${PENDING_DIGEST}"'
):
    raise SystemExit("ESO must converge before the workload reload begins.")

for marker in (
    'CONFIRM_POSTGRESQL_WORKLOAD_RELOAD:-}" != "reload-current-secret"',
    'EXPECTED_DATABASE_URL_SHA256',
    'RELOAD_MODE="${POSTGRESQL_WORKLOAD_RELOAD_MODE:-healthy}"',
    'healthy|credential-transition',
    'select(. >= 2)',
    'updated_replicas != desired_replicas',
    'RELOAD_MODE}" == "healthy"',
    'verified_replacement_uids',
    'A previously verified replacement Pod lost readiness during credential transition.',
    'kubectl delete pod "${old_pod}"',
    '--wait=false',
    'current_available < desired_replicas - 1',
    'pod_environment_digest "${replacement_pod}"',
    'pod_database_health "${replacement_pod}"',
    'Every original Pod was replaced one at a time without changing the Deployment template.',
):
    require(reload, marker, "one-at-a-time workload-reload contract")

for forbidden in (
    "rollout restart",
    "patch deployment",
    "set env",
    "scale deployment",
    "delete deployment",
):
    if forbidden in reload:
        raise SystemExit(f"Reload helper mutates the GitOps Deployment contract: {forbidden}")

for marker in (
    'Expected distinct, singular AWSCURRENT and AWSPENDING versions.',
    'len(pending_password) < 48',
    '.spec.data[0].remoteRef.version == "AWSCURRENT"',
    '.metadata.annotations["force-sync"] == null',
    'PostgreSQL credential rotation Checkpoint 1 AWS validation passed.',
):
    require(staging_runtime, marker, "AWS candidate-isolation validation")

if "SOURCE_DIGEST" in staging_runtime or "SOURCE_SECRET" in staging_runtime:
    raise SystemExit("Future staging must not depend on the legacy CNPG Secret.")

for marker in (
    'Expected distinct AWSCURRENT/AWSPREVIOUS versions and no AWSPENDING.',
    '"${CURRENT_DIGEST}" == "${LEGACY_SOURCE_DIGEST}"',
    'AWSPREVIOUS unexpectedly authenticates after activation.',
    '.metadata.annotations["force-sync"] == null',
    'Proving every Pod loaded AWSCURRENT',
    'validate-demo-api-postgresql.sh',
    'PostgreSQL credential rotation Checkpoint 2 AWS validation passed.',
):
    require(activation_runtime, marker, "AWS activation validation")

for marker in (
    'CONFIRM_POSTGRESQL_CREDENTIAL_ROLLBACK_DRILL:-}" !=',
    '"run-awsprevious-round-trip"',
    '"${PRECHECK_SCRIPT}"',
    'transition_to_version',
    '"${ORIGINAL_PREVIOUS_VERSION_ID}"',
    '"${ORIGINAL_CURRENT_VERSION_ID}"',
    'AWSPREVIOUS rollback validation passed.',
    '"forward recovery"',
    'restore_checkpoint2_state',
    'if credential_connects "${ORIGINAL_CURRENT_VERSION_ID}"; then',
    'database_recovered == 1 && stages_recovered == 1',
    'Skipping ESO and workload recovery until database and version stages are both restored.',
    'Automatic forward recovery passed; the original Checkpoint 2 state is active again.',
    'AUTOMATIC FORWARD RECOVERY DID NOT COMPLETE.',
    'POSTGRESQL_WORKLOAD_RELOAD_MODE=credential-transition',
    'validate_phase',
    'PostgreSQL credential rollback and forward-recovery drill passed.',
    'No AWSPENDING stage or temporary force-sync annotation remains.',
):
    require(rollback, marker, "guarded AWSPREVIOUS round-trip contract")

if rollback.count('transition_to_version \\') != 2:
    raise SystemExit("Rollback drill must perform exactly one rollback and one forward transition.")
if rollback.find('"${ORIGINAL_PREVIOUS_VERSION_ID}"') > rollback.find(
    '"forward recovery"'
):
    raise SystemExit("AWSPREVIOUS rollback must occur before forward recovery.")
if rollback.rfind('RESTORE_REQUIRED=0') < rollback.rfind('"forward recovery"'):
    raise SystemExit("Automatic recovery protection must remain armed through forward recovery.")

for forbidden in (
    "put-secret-value",
    "delete-secret",
    "secrets.token_urlsafe",
    "kubectl rollout restart",
    "kubectl patch deployment",
    "kubectl set env",
    "set -x",
    "--version-stage AWSPENDING",
):
    if forbidden in rollback:
        raise SystemExit(f"Rollback drill contains forbidden mutation or logging action: {forbidden}")

for marker in (
    'validate-postgresql-credential-activation-aws.sh',
    'PostgreSQL credential rotation Checkpoint 3 final-state validation passed.',
    'The forward recovery target is AWSCURRENT',
):
    require(rollback_runtime, marker, "Checkpoint 3 final-state validation")

for forbidden in ("SOURCE_VALUE", "SOURCE_JSON", '"${TARGET_VALUE}" != "${SOURCE_VALUE}"'):
    if forbidden in database_runtime:
        raise SystemExit(f"Active database validation still requires the legacy CNPG Secret: {forbidden}")

for marker in (
    "Checkpoint 1: Candidate Credential Staging",
    "Activate the Candidate",
    "Validate the Activated State",
    "bounded cutover, not a zero-downtime rotation claim",
    "Automatic compensation passed",
    "AUTOMATIC COMPENSATION DID NOT COMPLETE",
    "Run the AWSPREVIOUS Rollback Drill",
    "AWSPREVIOUS rollback validation passed.",
    "PostgreSQL credential rollback and forward-recovery drill passed.",
    "AUTOMATIC FORWARD RECOVERY DID NOT COMPLETE",
    "Validate the Post-Drill State",
    "Never enable shell xtrace",
):
    require(doc, marker, "v0.8.5 credential-rotation operating model")

require(
    roadmap,
    "rollback and forward-recovery implementation",
    "v0.8.5 roadmap status",
)
require(changelog, "## v0.8.5 (Unreleased)", "unreleased v0.8.5 changelog")
require(changelog, "Automatic partial-cutover compensation", "Checkpoint 2 changelog")
require(changelog, "Guarded `AWSPREVIOUS` rollback and forward-recovery drill", "Checkpoint 3 changelog")
PY

echo "PostgreSQL credential rotation Checkpoint 3 contract validation passed."

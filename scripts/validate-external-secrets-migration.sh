#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

readonly ACTIVE_EXTERNAL_SECRET="${ROOT_DIR}/clusters/aws-dev/security/external-secrets/startup-apps/demo-api-postgresql.yaml"
readonly STAGED_EXTERNAL_SECRET="${ROOT_DIR}/clusters/aws-dev/security/external-secrets/staged/demo-api-postgresql.yaml"
readonly MIGRATION_SCRIPT="${ROOT_DIR}/scripts/migrate-demo-api-postgresql-secret.sh"
readonly DEPLOY_SCRIPT="${ROOT_DIR}/scripts/deploy-aws-dev-root-app.sh"
readonly LEGACY_SCRIPT="${ROOT_DIR}/scripts/sync-demo-api-postgresql-secret.sh"
readonly DATABASE_VALIDATOR="${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"
readonly RUNTIME_SCRIPT="${ROOT_DIR}/scripts/validate-external-secrets-migration-aws.sh"
readonly ARCHIVE_DOC="${ROOT_DIR}/docs/archive/V0.8.4_EXTERNAL_SECRETS_MIGRATION.md"
readonly GITIGNORE="${ROOT_DIR}/.gitignore"

for path in \
  "${ACTIVE_EXTERNAL_SECRET}" \
  "${MIGRATION_SCRIPT}" \
  "${DEPLOY_SCRIPT}" \
  "${LEGACY_SCRIPT}" \
  "${DATABASE_VALIDATOR}" \
  "${RUNTIME_SCRIPT}" \
  "${ARCHIVE_DOC}" \
  "${GITIGNORE}"; do
  [[ -f "${path}" ]] || {
    echo "Required External Secrets migration file is missing: ${path}" >&2
    exit 1
  }
done

[[ ! -e "${STAGED_EXTERNAL_SECRET}" ]] || {
  echo "The staged ExternalSecret must be removed after activation." >&2
  exit 1
}

python3 - \
  "${ACTIVE_EXTERNAL_SECRET}" \
  "${MIGRATION_SCRIPT}" \
  "${DEPLOY_SCRIPT}" \
  "${LEGACY_SCRIPT}" \
  "${DATABASE_VALIDATOR}" \
  "${RUNTIME_SCRIPT}" \
  "${ARCHIVE_DOC}" \
  "${GITIGNORE}" <<'PY'
from pathlib import Path
import sys

(
    external_secret_path,
    migration_path,
    deploy_path,
    legacy_path,
    database_validator_path,
    runtime_path,
    archive_path,
    gitignore_path,
) = map(Path, sys.argv[1:])

external_secret = external_secret_path.read_text()
migration = migration_path.read_text()
deploy = deploy_path.read_text()
legacy = legacy_path.read_text()
database_validator = database_validator_path.read_text()
runtime = runtime_path.read_text()
archive = archive_path.read_text()
gitignore = gitignore_path.read_text()


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise SystemExit(f"{label} is missing: {marker}")


for marker in (
    "apiVersion: external-secrets.io/v1",
    "kind: ExternalSecret",
    "name: demo-api-postgresql",
    "namespace: startup-apps",
    "refreshInterval: 1h",
    "name: aws-secrets-manager",
    "kind: SecretStore",
    "creationPolicy: CreateOrMerge",
    "deletionPolicy: Retain",
    "platform.startup.dev/managed-by: external-secrets",
    "secretKey: DATABASE_URL",
    "key: startup-devops-baseline-dev/demo-api/postgresql",
    "property: DATABASE_URL",
    "version: AWSCURRENT",
):
    require(external_secret, marker, "active ExternalSecret contract")

for forbidden in ("secretStoreRef:\n    kind: ClusterSecretStore", "accessKey", "secretAccessKey"):
    if forbidden in external_secret:
        raise SystemExit(f"ExternalSecret contains forbidden auth/store field: {forbidden}")

for marker in (
    "CONFIRM_EXTERNAL_SECRETS_MIGRATION",
    "seed-from-cnpg",
    'if [[ "$-" == *x* ]]',
    "aws eks update-kubeconfig",
    "external_secrets_secret_arn",
    "describe-secret",
    "VersionIdsToStages",
    "AWSCURRENT differs",
    "refusing to overwrite",
    "--secret-string file:///dev/stdin",
    "Credential rotation belongs to v0.8.5",
    "The credential value was not printed, committed to Git, or written to Terraform state.",
):
    require(migration, marker, "guarded credential migration contract")

for forbidden in (
    "--secret-string \"${SOURCE_VALUE}\"",
    "--arg value \"${SOURCE_VALUE}\"",
    "aws_secretsmanager_secret_version",
):
    if forbidden in migration:
        raise SystemExit(f"Migration script contains forbidden secret handling: {forbidden}")

for marker in (
    "migrate-demo-api-postgresql-secret.sh",
    "CONFIRM_EXTERNAL_SECRETS_MIGRATION=seed-from-cnpg",
    "Waiting for ExternalSecret/",
    "force-sync=",
    "--for=condition=Ready",
):
    require(deploy, marker, "ESO deployment cutover contract")

if "SYNC_DATABASE_SECRET_SCRIPT" in deploy or "sync-demo-api-postgresql-secret.sh" in deploy:
    raise SystemExit("The deployment path must not invoke the legacy Kubernetes Secret copy.")

for marker in (
    "CONFIRM_LEGACY_SECRET_SYNC",
    "external-secret-suspended",
    "Refusing to create a second writer",
    "Break-glass demo-api PostgreSQL credential synchronization passed.",
):
    require(legacy, marker, "legacy synchronization break-glass contract")

for marker in (
    "ExternalSecret/${EXTERNAL_SECRET}",
    "platform.startup.dev/managed-by",
    '"external-secrets"',
):
    require(database_validator, marker, "database ExternalSecret consumption contract")

for marker in (
    "CONFIRM_EXTERNAL_SECRET_REBUILD",
    "delete-and-recreate",
    "simulate-principal-policy",
    "implicitDeny",
    "force-sync=",
    "External Secrets migration runtime validation passed.",
):
    require(runtime, marker, "External Secrets runtime migration matrix")

for marker in (
    "Checkpoint 3 implementation complete; EKS runtime validation pending.",
    "No plaintext credential enters Git, logs, command arguments, or Terraform state.",
    "External Secrets migration runtime validation passed.",
):
    require(archive, marker, "v0.8.4 checkpoint 3 status and operating model")

for marker in (
    "!clusters/aws-dev/platform/external-secrets.yaml",
    "!clusters/aws-dev/platform/external-secrets-startup-apps.yaml",
    "!clusters/aws-dev/security/external-secrets/**/*.yaml",
):
    require(gitignore, marker, "External Secrets GitOps ignore exception")
PY

echo "External Secrets migration contract validation passed."

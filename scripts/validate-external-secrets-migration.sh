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
readonly ROADMAP="${ROOT_DIR}/docs/ROADMAP.md"
readonly GITIGNORE="${ROOT_DIR}/.gitignore"

for path in \
  "${ACTIVE_EXTERNAL_SECRET}" \
  "${MIGRATION_SCRIPT}" \
  "${DEPLOY_SCRIPT}" \
  "${LEGACY_SCRIPT}" \
  "${DATABASE_VALIDATOR}" \
  "${RUNTIME_SCRIPT}" \
  "${ARCHIVE_DOC}" \
  "${ROADMAP}" \
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
  "${ROADMAP}" \
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
    roadmap_path,
    gitignore_path,
) = map(Path, sys.argv[1:])

external_secret = external_secret_path.read_text()
migration = migration_path.read_text()
deploy = deploy_path.read_text()
legacy = legacy_path.read_text()
database_validator = database_validator_path.read_text()
runtime = runtime_path.read_text()
archive = archive_path.read_text()
roadmap = roadmap_path.read_text()
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
    "engineVersion: v2",
    "mergePolicy: Replace",
    "platform.startup.dev/managed-by: external-secrets",
    "secretKey: DATABASE_URL",
    "key: startup-devops-baseline-dev/demo-api/postgresql",
    "property: DATABASE_URL",
    "version: AWSCURRENT",
    "conversionStrategy: Default",
    "decodingStrategy: None",
    "metadataPolicy: None",
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
    "credential_authenticates",
    "psycopg.connect",
    "preserving the rotated credential without overwriting it",
    "cannot authenticate",
    "Refusing to overwrite or accept an unverified database credential",
    "--secret-string file:///dev/stdin",
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
    "FORCE_SYNC_ANNOTATION_SET=true",
    "--for=condition=Ready",
    "force-sync-",
    '.metadata.annotations["force-sync"] == null',
    "FORCE_SYNC_ANNOTATION_SET=false",
    'POSTGRES_WAIT_SECONDS="${POSTGRES_WAIT_SECONDS:-1800}"',
    "Waiting for the CloudNativePG Cluster",
    '"cluster/${POSTGRES_CLUSTER}"',
    "Waiting for the PostgreSQL Argo CD Application",
    "deployment_diagnostics",
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
    "kubectl get endpointslice",
    "kubernetes.io/service-name=${POSTGRES_CLUSTER}-rw",
    "select(.conditions.ready != false)",
):
    require(database_validator, marker, "database ExternalSecret consumption contract")

deprecated_endpoints_command = "kubectl get " + 'endpoints "'
if deprecated_endpoints_command in database_validator:
    raise SystemExit("The database validator must not use the deprecated Endpoints API.")

for marker in (
    "CONFIRM_EXTERNAL_SECRET_REBUILD",
    "delete-and-recreate",
    "simulate-principal-policy",
    "implicitDeny",
    "force-sync=",
    "FORCE_SYNC_ANNOTATION_SET=true",
    "force-sync-",
    '.metadata.annotations["force-sync"] == null',
    "FORCE_SYNC_ANNOTATION_SET=false",
    '.spec.target.template.engineVersion == "v2"',
    '.spec.target.template.mergePolicy == "Replace"',
    '.spec.data[0].remoteRef.conversionStrategy == "Default"',
    '.spec.data[0].remoteRef.decodingStrategy == "None"',
    '.spec.data[0].remoteRef.metadataPolicy == "None"',
    "External Secrets migration runtime validation passed.",
):
    require(runtime, marker, "External Secrets runtime migration matrix")

deploy_trigger = deploy.index("force-sync=")
deploy_wait = deploy.index("--for=condition=Ready", deploy_trigger)
deploy_cleanup = deploy.index("force-sync-", deploy_wait)
deploy_verify = deploy.index('.metadata.annotations["force-sync"] == null', deploy_cleanup)
if not deploy_trigger < deploy_wait < deploy_cleanup < deploy_verify:
    raise SystemExit("Deployment force-sync cleanup order is invalid.")

cluster_wait = deploy.index("Waiting for the CloudNativePG Cluster", deploy_verify)
cluster_ready = deploy.index('"cluster/${POSTGRES_CLUSTER}"', cluster_wait)
postgres_application_wait = deploy.index(
    "Waiting for the PostgreSQL Argo CD Application", cluster_ready
)
demo_application_wait = deploy.index(
    "Waiting for the demo-api Argo CD Application", postgres_application_wait
)
dns_reconcile = deploy.index(
    "Reconciling the stable demo-api hostname", demo_application_wait
)
if not (
    deploy_verify
    < cluster_wait
    < cluster_ready
    < postgres_application_wait
    < demo_application_wait
    < dns_reconcile
):
    raise SystemExit("Database-dependent rebuild readiness order is invalid.")

runtime_trigger = runtime.index("force-sync=")
runtime_recheck = runtime.index("Rechecking all three protected values", runtime_trigger)
runtime_cleanup = runtime.index("force-sync-", runtime_recheck)
runtime_verify = runtime.index('.metadata.annotations["force-sync"] == null', runtime_cleanup)
if not runtime_trigger < runtime_recheck < runtime_cleanup < runtime_verify:
    raise SystemExit("Runtime rebuild force-sync cleanup order is invalid.")

for marker in (
    "Checkpoint 3 validated. v0.8.4 is ready for release.",
    "No plaintext credential enters Git, logs, command arguments, or Terraform state.",
    "The EKS runtime validation completed successfully on 2026-08-01.",
    "External Secrets migration runtime validation passed.",
):
    require(archive, marker, "v0.8.4 checkpoint 3 status and operating model")

for marker in (
    "ExternalSecret cutover - delivered",
    "v0.8.5 - PostgreSQL application credential rotation and workload reload",
):
    require(roadmap, marker, "v0.8 roadmap status")

for marker in (
    "!clusters/aws-dev/platform/external-secrets.yaml",
    "!clusters/aws-dev/platform/external-secrets-startup-apps.yaml",
    "!clusters/aws-dev/security/external-secrets/**/*.yaml",
):
    require(gitignore, marker, "External Secrets GitOps ignore exception")
PY

echo "External Secrets migration contract validation passed."

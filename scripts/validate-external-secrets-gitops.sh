#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

readonly OPERATOR_APP="${ROOT_DIR}/clusters/aws-dev/platform/external-secrets.yaml"
readonly RESOURCES_APP="${ROOT_DIR}/clusters/aws-dev/platform/external-secrets-startup-apps.yaml"
readonly STORE="${ROOT_DIR}/clusters/aws-dev/security/external-secrets/startup-apps/secret-store.yaml"
readonly STAGED_EXTERNAL_SECRET="${ROOT_DIR}/clusters/aws-dev/security/external-secrets/staged/demo-api-postgresql.yaml"
readonly DEPLOY_SCRIPT="${ROOT_DIR}/scripts/deploy-aws-dev-root-app.sh"
readonly RUNTIME_SCRIPT="${ROOT_DIR}/scripts/validate-external-secrets-gitops-aws.sh"
readonly ARCHIVE_DOC="${ROOT_DIR}/docs/archive/V0.8.3_EXTERNAL_SECRETS_GITOPS.md"

for path in \
  "${OPERATOR_APP}" \
  "${RESOURCES_APP}" \
  "${STORE}" \
  "${STAGED_EXTERNAL_SECRET}" \
  "${DEPLOY_SCRIPT}" \
  "${RUNTIME_SCRIPT}" \
  "${ARCHIVE_DOC}"; do
  [[ -f "${path}" ]] || {
    echo "Required External Secrets GitOps file is missing: ${path}" >&2
    exit 1
  }
done

python3 - \
  "${OPERATOR_APP}" \
  "${RESOURCES_APP}" \
  "${STORE}" \
  "${STAGED_EXTERNAL_SECRET}" \
  "${DEPLOY_SCRIPT}" \
  "${RUNTIME_SCRIPT}" \
  "${ARCHIVE_DOC}" <<'PY'
from pathlib import Path
import sys

(
    operator_path,
    resources_app_path,
    store_path,
    staged_path,
    deploy_path,
    runtime_path,
    archive_path,
) = map(Path, sys.argv[1:])

operator = operator_path.read_text()
resources_app = resources_app_path.read_text()
store = store_path.read_text()
staged = staged_path.read_text()
deploy = deploy_path.read_text()
runtime = runtime_path.read_text()
archive = archive_path.read_text()


def require(text: str, marker: str, label: str) -> None:
    if marker not in text:
        raise SystemExit(f"{label} is missing: {marker}")


for marker in (
    "name: external-secrets",
    "repoURL: https://charts.external-secrets.io",
    "chart: external-secrets",
    "targetRevision: 2.8.0",
    "installCRDs: true",
    "createClusterExternalSecret: false",
    "createClusterSecretStore: false",
    "createClusterGenerator: false",
    "createClusterPushSecret: false",
    "createPushSecret: false",
    "createSecretStore: true",
    "leaderElect: true",
    "scopedRBAC: true",
    "scopedNamespace: startup-apps",
    "processClusterExternalSecret: false",
    "processClusterPushSecret: false",
    "processClusterStore: false",
    "processClusterGenerator: false",
    "processPushSecret: false",
    "serviceAccountTokenCreate: false",
    "aggregateToView: false",
    "aggregateToEdit: false",
    "aggregateToAdmin: false",
    "create: false",
    "namespace: external-secrets",
    "ServerSideApply=true",
):
    require(operator, marker, "ESO pinned and namespace-scoped Helm contract")

if "latest" in operator.lower():
    raise SystemExit("The ESO Application must not use a floating latest release.")
if "eks.amazonaws.com/role-arn" in operator:
    raise SystemExit("The Terraform-derived IRSA ARN must not be committed in Helm values.")

for marker in (
    "name: external-secrets-startup-apps",
    "targetRevision: feature/v0.8-production-security-baseline",
    "path: clusters/aws-dev/security/external-secrets/startup-apps",
    "namespace: startup-apps",
    "SkipDryRunOnMissingResource=true",
):
    require(resources_app, marker, "namespaced SecretStore Application contract")

for marker in (
    "apiVersion: external-secrets.io/v1",
    "kind: SecretStore",
    "name: aws-secrets-manager",
    "namespace: startup-apps",
    "service: SecretsManager",
    "region: us-east-1",
):
    require(store, marker, "AWS namespaced SecretStore contract")

for forbidden in ("ClusterSecretStore", "accessKeyIDSecretRef", "secretAccessKeySecretRef"):
    if forbidden in store:
        raise SystemExit(f"SecretStore contains forbidden broad/static auth field: {forbidden}")

for marker in (
    "Staged only",
    "apiVersion: external-secrets.io/v1",
    "kind: ExternalSecret",
    "name: demo-api-postgresql",
    "creationPolicy: CreateOrMerge",
    "deletionPolicy: Retain",
    "secretKey: DATABASE_URL",
    "key: startup-devops-baseline-dev/demo-api/postgresql",
    "property: DATABASE_URL",
    "version: AWSCURRENT",
):
    require(staged, marker, "staged ExternalSecret cutover contract")

if "kind: ExternalSecret" in store_path.parent.joinpath("secret-store.yaml").read_text():
    raise SystemExit("Checkpoint 2 must not activate an ExternalSecret before a remote value exists.")
if "clusters/aws-dev/security/external-secrets/staged" in resources_app:
    raise SystemExit("The staged ExternalSecret directory must remain outside Argo CD scope.")

for marker in (
    "external_secrets_role_arn",
    'EXTERNAL_SECRETS_NAMESPACE="${EXTERNAL_SECRETS_NAMESPACE:-external-secrets}"',
    'EXTERNAL_SECRETS_SERVICE_ACCOUNT="${EXTERNAL_SECRETS_SERVICE_ACCOUNT:-external-secrets}"',
    'eks.amazonaws.com/role-arn="${EXTERNAL_SECRETS_ROLE_ARN}"',
    "pod-security.kubernetes.io/enforce=restricted",
):
    require(deploy, marker, "ESO IRSA bootstrap contract")

for marker in (
    "SecretStore/aws-secrets-manager",
    "External Secrets GitOps runtime validation passed.",
    "serviceaccounts/token",
    "external_secrets_role_arn",
):
    require(runtime, marker, "ESO AWS runtime matrix")

for marker in (
    "Checkpoint 2 implementation complete; EKS runtime validation pending.",
    "The staged ExternalSecret is not applied by Argo CD.",
    "Checkpoint 3 must not begin until the runtime validation passes.",
):
    require(archive, marker, "v0.8.3 checkpoint 2 status and boundary")
PY

echo "External Secrets GitOps contract validation passed."

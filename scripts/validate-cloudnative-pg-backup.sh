#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_APPLICATION="${POSTGRES_APPLICATION:-postgresql-baseline}"
POSTGRES_SERVICE_ACCOUNT="${POSTGRES_SERVICE_ACCOUNT:-postgresql-baseline}"
OBJECT_STORE="${OBJECT_STORE:-postgresql-baseline-backup}"
SCHEDULED_BACKUP="${SCHEDULED_BACKUP:-postgresql-baseline-daily}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

terraform_output() {
  local value
  value="$(terraform -chdir="${TF_DIR}" output -raw "$1")"
  if [[ -z "${value}" ]]; then
    echo "Terraform output $1 is empty." >&2
    exit 1
  fi
  printf '%s' "${value}"
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"

BACKUP_BUCKET="$(terraform_output cnpg_backup_bucket_name)"
BACKUP_ROLE_ARN="$(terraform_output cnpg_backup_role_arn)"
BACKUP_ROLE_NAME="${BACKUP_ROLE_ARN##*/}"
EXPECTED_DESTINATION="s3://${BACKUP_BUCKET}/postgresql-baseline"

echo "==> Checking S3 backup infrastructure"
aws s3api head-bucket --bucket "${BACKUP_BUCKET}"

PUBLIC_ACCESS="$(
  aws s3api get-public-access-block \
    --bucket "${BACKUP_BUCKET}" \
    --query 'PublicAccessBlockConfiguration.[BlockPublicAcls,IgnorePublicAcls,BlockPublicPolicy,RestrictPublicBuckets]' \
    --output text
)"
VERSIONING="$(
  aws s3api get-bucket-versioning \
    --bucket "${BACKUP_BUCKET}" \
    --query Status \
    --output text
)"
ENCRYPTION="$(
  aws s3api get-bucket-encryption \
    --bucket "${BACKUP_BUCKET}" \
    --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
    --output text
)"
BUCKET_PUBLIC="$(
  aws s3api get-bucket-policy-status \
    --bucket "${BACKUP_BUCKET}" \
    --query 'PolicyStatus.IsPublic' \
    --output text
)"

if [[ "${PUBLIC_ACCESS}" != $'True\tTrue\tTrue\tTrue' || \
      "${VERSIONING}" != "Enabled" || \
      "${ENCRYPTION}" != "AES256" || \
      "${BUCKET_PUBLIC}" != "False" ]]; then
  echo "The S3 backup bucket does not match the v0.6.3 security contract." >&2
  exit 1
fi

echo "==> Checking CloudNativePG backup IRSA"
ROLE_JSON="$(aws iam get-role --role-name "${BACKUP_ROLE_NAME}" --output json)"
if ! grep -q "system:serviceaccount:${POSTGRES_NAMESPACE}:${POSTGRES_SERVICE_ACCOUNT}" \
  <<<"${ROLE_JSON}"; then
  echo "The backup IAM role trust does not match the PostgreSQL ServiceAccount." >&2
  exit 1
fi

SERVICE_ACCOUNT_ROLE="$(
  kubectl get serviceaccount "${POSTGRES_SERVICE_ACCOUNT}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}'
)"
if [[ "${SERVICE_ACCOUNT_ROLE}" != "${BACKUP_ROLE_ARN}" ]]; then
  echo "The PostgreSQL ServiceAccount is not annotated with the Terraform backup role." >&2
  exit 1
fi

echo "==> Checking cert-manager and Barman Cloud Applications"
for application in cert-manager cloudnative-pg barman-cloud-plugin "${POSTGRES_APPLICATION}"; do
  kubectl wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}"
  kubectl wait \
    --for=jsonpath='{.status.health.status}'=Healthy \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}"
done

kubectl rollout status deployment/cert-manager \
  --namespace cert-manager \
  --timeout="${WAIT_TIMEOUT}"
kubectl rollout status deployment/cert-manager-webhook \
  --namespace cert-manager \
  --timeout="${WAIT_TIMEOUT}"
kubectl rollout status deployment/barman-cloud-plugin-barman-cloud \
  --namespace cnpg-system \
  --timeout="${WAIT_TIMEOUT}"
kubectl get crd objectstores.barmancloud.cnpg.io >/dev/null

EXPECTED_BARMAN_IMAGE="ghcr.io/cloudnative-pg/plugin-barman-cloud:v0.13.0"

BARMAN_IMAGE="$(
  kubectl get deployment barman-cloud-plugin-barman-cloud \
    --namespace cnpg-system \
    --output jsonpath='{.spec.template.spec.containers[0].image}'
)"

if [[ "${BARMAN_IMAGE}" != "${EXPECTED_BARMAN_IMAGE}" ]]; then
  echo "Unexpected Barman Cloud plugin image." >&2
  echo "Expected: ${EXPECTED_BARMAN_IMAGE}" >&2
  echo "Actual:   ${BARMAN_IMAGE}" >&2
  exit 1
fi

echo "==> Checking ObjectStore and scheduled backup"
LIVE_DESTINATION="$(
  kubectl get objectstore "${OBJECT_STORE}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.configuration.destinationPath}'
)"
OBJECT_STORE_CONTRACT="$(
  kubectl get objectstore "${OBJECT_STORE}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.configuration.s3Credentials.inheritFromIAMRole}:{.spec.configuration.wal.compression}:{.spec.configuration.wal.maxParallel}:{.spec.configuration.data.compression}:{.spec.configuration.data.jobs}:{.spec.retentionPolicy}'
)"
SIDECAR_RESOURCES="$(
  kubectl get objectstore "${OBJECT_STORE}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.instanceSidecarConfiguration.resources.requests.cpu}:{.spec.instanceSidecarConfiguration.resources.limits.cpu}:{.spec.instanceSidecarConfiguration.resources.requests.memory}:{.spec.instanceSidecarConfiguration.resources.limits.memory}'
)"

if [[ "${LIVE_DESTINATION}" != "${EXPECTED_DESTINATION}" || \
      "${LIVE_DESTINATION}" == *"__CNPG_BACKUP_BUCKET__"* || \
      "${OBJECT_STORE_CONTRACT}" != "true:lz4:2:lz4:1:7d" || \
      "${SIDECAR_RESOURCES}" != "100m:500m:256Mi:512Mi" ]]; then
  echo "The live ObjectStore does not match the v0.6.3 contract." >&2
  exit 1
fi

SCHEDULE_CONTRACT="$(
  kubectl get scheduledbackup "${SCHEDULED_BACKUP}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.schedule}:{.spec.backupOwnerReference}:{.spec.cluster.name}:{.spec.method}:{.spec.pluginConfiguration.name}:{.spec.target}:{.spec.immediate}:{.spec.suspend}'
)"
if [[ "${SCHEDULE_CONTRACT}" != \
      "0 0 2 * * *:cluster:${POSTGRES_CLUSTER}:plugin:barman-cloud.cloudnative-pg.io:prefer-standby:false:false" ]]; then
  echo "The ScheduledBackup does not match the v0.6.3 contract." >&2
  exit 1
fi

CLUSTER_PLUGIN="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.plugins[0].name}:{.spec.plugins[0].isWALArchiver}:{.spec.plugins[0].parameters.barmanObjectName}:{.spec.backup.target}'
)"
if [[ "${CLUSTER_PLUGIN}" != \
      "barman-cloud.cloudnative-pg.io:true:${OBJECT_STORE}:prefer-standby" ]]; then
  echo "The PostgreSQL Cluster is not configured for plugin-based WAL archiving." >&2
  exit 1
fi

echo "==> Checking continuous WAL archiving"
kubectl wait \
  --for=jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'=True \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Checking completed base backup and S3 objects"
COMPLETED_BACKUPS="$(
  kubectl get backup \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{range .items[?(@.status.phase=="completed")]}{.metadata.name}{"\n"}{end}'
)"
if [[ -z "${COMPLETED_BACKUPS}" ]]; then
  echo "No completed CloudNativePG base backup was found." >&2
  echo "Run ./scripts/run-cloudnative-pg-backup-test.sh first." >&2
  exit 1
fi

S3_KEYS="$(
  aws s3api list-objects-v2 \
    --bucket "${BACKUP_BUCKET}" \
    --prefix "postgresql-baseline/" \
    --query 'Contents[].Key' \
    --output text
)"
if [[ -z "${S3_KEYS}" || \
      "${S3_KEYS}" != *"/base/"* || \
      "${S3_KEYS}" != *"/wals/"* ]]; then
  echo "Expected both base-backup and WAL objects under the PostgreSQL S3 prefix." >&2
  exit 1
fi

echo "CloudNativePG S3 base backup and WAL archiving validation passed."

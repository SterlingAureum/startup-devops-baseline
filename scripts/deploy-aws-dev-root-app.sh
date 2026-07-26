#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
TARGET_REVISION="${TARGET_REVISION:-feature/v0.6-cloudnativepg-data-platform}"
SOURCE_FILE="${SOURCE_FILE:-${ROOT_DIR}/clusters/aws-dev/root-app.yaml}"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
POSTGRES_APPLICATION="${POSTGRES_APPLICATION:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_SERVICE_ACCOUNT="${POSTGRES_SERVICE_ACCOUNT:-postgresql-baseline}"
BACKUP_OBJECT_STORE="${BACKUP_OBJECT_STORE:-postgresql-baseline-backup}"
BACKUP_WAIT_SECONDS="${BACKUP_WAIT_SECONDS:-900}"

for command in kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

kubectl get namespace argocd >/dev/null

terraform_output() {
  local output_name="$1"
  local value

  value="$(terraform -chdir="${TF_DIR}" output -raw "${output_name}")"
  if [[ -z "${value}" ]]; then
    echo "Terraform output ${output_name} is empty." >&2
    exit 1
  fi

  printf '%s' "${value}"
}

BACKUP_BUCKET="$(terraform_output cnpg_backup_bucket_name)"
BACKUP_ROLE_ARN="$(terraform_output cnpg_backup_role_arn)"

if [[ ! "${BACKUP_BUCKET}" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "Terraform output cnpg_backup_bucket_name is not a valid S3 bucket name." >&2
  exit 1
fi

if [[ ! "${BACKUP_ROLE_ARN}" =~ ^arn:[^:]+:iam::[0-9]{12}:role/.+ ]]; then
  echo "Terraform output cnpg_backup_role_arn is not a valid IAM role ARN." >&2
  exit 1
fi

echo "==> Configuring the CloudNativePG backup ServiceAccount"
kubectl create namespace "${POSTGRES_NAMESPACE}" \
  --dry-run=client \
  --output yaml | kubectl apply -f -
kubectl create serviceaccount "${POSTGRES_SERVICE_ACCOUNT}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --dry-run=client \
  --output yaml | kubectl apply -f -
kubectl annotate serviceaccount "${POSTGRES_SERVICE_ACCOUNT}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  eks.amazonaws.com/role-arn="${BACKUP_ROLE_ARN}" \
  --overwrite

TEMP_FILE="$(mktemp)"
trap 'rm -f "${TEMP_FILE}"' EXIT

sed \
  -e "s#repoURL: .*startup-devops-baseline.git#repoURL: ${REPO_URL}#" \
  -e "s#targetRevision: .*#targetRevision: ${TARGET_REVISION}#" \
  "${SOURCE_FILE}" > "${TEMP_FILE}"

kubectl apply -f "${TEMP_FILE}"

echo "==> Waiting for the GitOps backup destination contract"
deadline=$((SECONDS + BACKUP_WAIT_SECONDS))
while true; do
  application_yaml="$(
    kubectl get application "${POSTGRES_APPLICATION}" \
      --namespace argocd \
      --output yaml 2>/dev/null || true
  )"

  if grep -q -- "/spec/configuration/destinationPath" <<<"${application_yaml}" && \
     kubectl get objectstore "${BACKUP_OBJECT_STORE}" \
       --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the PostgreSQL backup ObjectStore and Argo CD ignore rule." >&2
    exit 1
  fi

  sleep 10
done

echo "==> Applying the Terraform S3 destination to the live ObjectStore"
kubectl patch objectstore "${BACKUP_OBJECT_STORE}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --type merge \
  --patch "{\"spec\":{\"configuration\":{\"destinationPath\":\"s3://${BACKUP_BUCKET}/postgresql-baseline\"}}}"

kubectl annotate serviceaccount "${POSTGRES_SERVICE_ACCOUNT}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  eks.amazonaws.com/role-arn="${BACKUP_ROLE_ARN}" \
  --overwrite

kubectl annotate application "${POSTGRES_APPLICATION}" \
  --namespace argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite

echo "Applied aws-dev root application"
echo "Repository: ${REPO_URL}"
echo "Revision:   ${TARGET_REVISION}"
echo "Backup S3:  s3://${BACKUP_BUCKET}/postgresql-baseline"

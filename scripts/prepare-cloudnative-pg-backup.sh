#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_SERVICE_ACCOUNT="${POSTGRES_SERVICE_ACCOUNT:-postgresql-baseline}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

BACKUP_ROLE_ARN="$(
  terraform -chdir="${TF_DIR}" output -raw cnpg_backup_role_arn
)"
if [[ ! "${BACKUP_ROLE_ARN}" =~ ^arn:[^:]+:iam::[0-9]{12}:role/.+ ]]; then
  echo "Terraform output cnpg_backup_role_arn is not a valid IAM role ARN." >&2
  exit 1
fi

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"

echo "==> Preparing the PostgreSQL ServiceAccount for backup IRSA"
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

echo "CloudNativePG backup IRSA preparation passed."
echo "It is now safe to push the v0.6.3 GitOps changes."

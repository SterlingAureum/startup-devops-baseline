#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
TARGET_REVISION="${TARGET_REVISION:-main}"
SOURCE_FILE="${SOURCE_FILE:-${ROOT_DIR}/clusters/aws-dev/root-app.yaml}"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
POSTGRES_APPLICATION="${POSTGRES_APPLICATION:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_SERVICE_ACCOUNT="${POSTGRES_SERVICE_ACCOUNT:-postgresql-baseline}"
BACKUP_OBJECT_STORE="${BACKUP_OBJECT_STORE:-postgresql-baseline-backup}"
BACKUP_WAIT_SECONDS="${BACKUP_WAIT_SECONDS:-900}"
DEMO_APPLICATION="${DEMO_APPLICATION:-demo-api-aws-dev}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_DATABASE_SECRET="${DEMO_DATABASE_SECRET:-demo-api-postgresql}"
DEMO_WAIT_SECONDS="${DEMO_WAIT_SECONDS:-900}"
EXTERNAL_SECRETS_NAMESPACE="${EXTERNAL_SECRETS_NAMESPACE:-external-secrets}"
EXTERNAL_SECRETS_SERVICE_ACCOUNT="${EXTERNAL_SECRETS_SERVICE_ACCOUNT:-external-secrets}"
EXTERNAL_SECRETS_APPLICATION="${EXTERNAL_SECRETS_APPLICATION:-external-secrets}"
EXTERNAL_SECRETS_RESOURCES_APPLICATION="${EXTERNAL_SECRETS_RESOURCES_APPLICATION:-external-secrets-startup-apps}"
EXTERNAL_SECRETS_STORE="${EXTERNAL_SECRETS_STORE:-aws-secrets-manager}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-demo-api-postgresql}"
EXTERNAL_SECRETS_WAIT_SECONDS="${EXTERNAL_SECRETS_WAIT_SECONDS:-900}"
MIGRATE_DATABASE_SECRET_SCRIPT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")" &&
    pwd
)/migrate-demo-api-postgresql-secret.sh"
RECONCILE_DEMO_API_DNS_SCRIPT="$(
  cd "$(dirname "${BASH_SOURCE[0]}")" &&
    pwd
)/reconcile-demo-api-dns.sh"
FORCE_SYNC_ANNOTATION_SET=false

for command in aws kubectl terraform jq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

[[ -x "${RECONCILE_DEMO_API_DNS_SCRIPT}" ]] || {
  echo "Required executable is missing: ${RECONCILE_DEMO_API_DNS_SCRIPT}" >&2
  exit 1
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Verifying Kubernetes API access"
kubectl --request-timeout=30s get --raw=/readyz >/dev/null
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
EXTERNAL_SECRETS_ROLE_ARN="$(terraform_output external_secrets_role_arn)"

if [[ ! "${BACKUP_BUCKET}" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]; then
  echo "Terraform output cnpg_backup_bucket_name is not a valid S3 bucket name." >&2
  exit 1
fi

if [[ ! "${BACKUP_ROLE_ARN}" =~ ^arn:[^:]+:iam::[0-9]{12}:role/.+ ]]; then
  echo "Terraform output cnpg_backup_role_arn is not a valid IAM role ARN." >&2
  exit 1
fi

if [[ ! "${EXTERNAL_SECRETS_ROLE_ARN}" =~ ^arn:[^:]+:iam::[0-9]{12}:role/.+ ]]; then
  echo "Terraform output external_secrets_role_arn is not a valid IAM role ARN." >&2
  exit 1
fi

echo "==> Configuring the External Secrets Operator ServiceAccount"
kubectl create namespace "${EXTERNAL_SECRETS_NAMESPACE}" \
  --dry-run=client \
  --output yaml | kubectl apply -f -
kubectl label namespace "${EXTERNAL_SECRETS_NAMESPACE}" \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=v1.30 \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted \
  --overwrite
kubectl create serviceaccount "${EXTERNAL_SECRETS_SERVICE_ACCOUNT}" \
  --namespace "${EXTERNAL_SECRETS_NAMESPACE}" \
  --dry-run=client \
  --output yaml | kubectl apply -f -
kubectl annotate serviceaccount "${EXTERNAL_SECRETS_SERVICE_ACCOUNT}" \
  --namespace "${EXTERNAL_SECRETS_NAMESPACE}" \
  eks.amazonaws.com/role-arn="${EXTERNAL_SECRETS_ROLE_ARN}" \
  --overwrite

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
cleanup_deployment() {
  rm -f "${TEMP_FILE}"
  if [[ "${FORCE_SYNC_ANNOTATION_SET}" == "true" ]]; then
    kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
      --namespace "${DEMO_NAMESPACE}" \
      force-sync- >/dev/null 2>&1 || true
  fi
}
trap cleanup_deployment EXIT

sed \
  -e "s#repoURL: .*startup-devops-baseline.git#repoURL: ${REPO_URL}#" \
  -e "s#targetRevision: .*#targetRevision: ${TARGET_REVISION}#" \
  "${SOURCE_FILE}" > "${TEMP_FILE}"

kubectl apply -f "${TEMP_FILE}"

echo "==> Waiting for the External Secrets Operator GitOps applications"
deadline=$((SECONDS + EXTERNAL_SECRETS_WAIT_SECONDS))
for application in \
  "${EXTERNAL_SECRETS_APPLICATION}" \
  "${EXTERNAL_SECRETS_RESOURCES_APPLICATION}"; do
  while ! kubectl get application "${application}" \
    --namespace argocd >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for Argo CD Application ${application}." >&2
      exit 1
    fi
    sleep 10
  done

  kubectl annotate application "${application}" \
    --namespace argocd \
    argocd.argoproj.io/refresh=hard \
    --overwrite

  kubectl wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${application}" \
    --namespace argocd \
    --timeout="${EXTERNAL_SECRETS_WAIT_SECONDS}s"
done

kubectl wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${EXTERNAL_SECRETS_APPLICATION}" \
  --namespace argocd \
  --timeout="${EXTERNAL_SECRETS_WAIT_SECONDS}s"

kubectl wait \
  --for=condition=Ready \
  "SecretStore/${EXTERNAL_SECRETS_STORE}" \
  --namespace "${DEMO_NAMESPACE}" \
  --timeout="${EXTERNAL_SECRETS_WAIT_SECONDS}s"

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

echo "==> Waiting for the CloudNativePG application credential"
deadline=$((SECONDS + DEMO_WAIT_SECONDS))
while ! kubectl get secret "${POSTGRES_APPLICATION}-app" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the CloudNativePG application credential." >&2
    exit 1
  fi
  sleep 10
done

echo "==> Ensuring the database credential is present in AWS Secrets Manager"
CONFIRM_EXTERNAL_SECRETS_MIGRATION=seed-from-cnpg \
  "${MIGRATE_DATABASE_SECRET_SCRIPT}"

echo "==> Waiting for ExternalSecret/${EXTERNAL_SECRET}"
kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
  --namespace "${DEMO_NAMESPACE}" \
  force-sync="$(date +%s)" \
  --overwrite
FORCE_SYNC_ANNOTATION_SET=true
kubectl wait \
  --for=condition=Ready \
  "ExternalSecret/${EXTERNAL_SECRET}" \
  --namespace "${DEMO_NAMESPACE}" \
  --timeout="${EXTERNAL_SECRETS_WAIT_SECONDS}s"
kubectl get secret "${DEMO_DATABASE_SECRET}" \
  --namespace "${DEMO_NAMESPACE}" >/dev/null

echo "==> Removing the temporary ExternalSecret force-sync annotation"
kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
  --namespace "${DEMO_NAMESPACE}" \
  force-sync- >/dev/null
external_secret_json="$(
  kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"
jq --exit-status '
  (.metadata.annotations["force-sync"] == null) and
  any(.status.conditions[]?; .type == "Ready" and .status == "True")
' <<<"${external_secret_json}" >/dev/null || {
  echo "ExternalSecret is not Ready and clean after forced synchronization." >&2
  exit 1
}
FORCE_SYNC_ANNOTATION_SET=false

echo "==> Waiting for the demo-api Argo CD Application"
deadline=$((SECONDS + DEMO_WAIT_SECONDS))
while ! kubectl get application "${DEMO_APPLICATION}" \
  --namespace argocd >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for the demo-api Argo CD Application." >&2
    exit 1
  fi
  sleep 10
done

kubectl annotate application "${POSTGRES_APPLICATION}" \
  --namespace argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite

kubectl annotate application "${DEMO_APPLICATION}" \
  --namespace argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite

kubectl wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/${DEMO_APPLICATION}" \
  --namespace argocd \
  --timeout="${DEMO_WAIT_SECONDS}s"
kubectl wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${DEMO_APPLICATION}" \
  --namespace argocd \
  --timeout="${DEMO_WAIT_SECONDS}s"

echo "==> Reconciling the stable demo-api hostname to the live ALB"
AWS_REGION="${AWS_REGION}" \
CLUSTER_NAME="${CLUSTER_NAME}" \
APP_NAMESPACE="${DEMO_NAMESPACE}" \
  "${RECONCILE_DEMO_API_DNS_SCRIPT}"

echo "Applied aws-dev root application"
echo "Repository: ${REPO_URL}"
echo "Revision:   ${TARGET_REVISION}"
echo "Backup S3:  s3://${BACKUP_BUCKET}/postgresql-baseline"
echo "Database:   ${DEMO_NAMESPACE}/${DEMO_DATABASE_SECRET}"
echo "SecretStore:${DEMO_NAMESPACE}/${EXTERNAL_SECRETS_STORE}"

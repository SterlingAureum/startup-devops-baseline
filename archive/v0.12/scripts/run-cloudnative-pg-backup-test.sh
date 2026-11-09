#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
BACKUP_TIMEOUT_SECONDS="${BACKUP_TIMEOUT_SECONDS:-1200}"
S3_TIMEOUT_SECONDS="${S3_TIMEOUT_SECONDS:-300}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"

BACKUP_BUCKET="$(
  terraform -chdir="${TF_DIR}" output -raw cnpg_backup_bucket_name
)"
if [[ -z "${BACKUP_BUCKET}" ]]; then
  echo "Terraform output cnpg_backup_bucket_name is empty." >&2
  exit 1
fi

echo "==> Waiting for PostgreSQL and continuous archiving"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout=20m
kubectl wait \
  --for=jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'=True \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout=20m

PRIMARY_POD="$(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --output jsonpath='{.items[0].metadata.name}'
)"
if [[ -z "${PRIMARY_POD}" ]]; then
  echo "Unable to resolve the current PostgreSQL primary Pod." >&2
  exit 1
fi

echo "==> Forcing a WAL switch before the base backup"
kubectl exec "${PRIMARY_POD}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --container postgres \
  -- psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -Atqc "SELECT pg_switch_wal();" >/dev/null

BACKUP_NAME="postgresql-baseline-manual-$(date -u +%Y%m%d%H%M%S)"
echo "==> Creating plugin-based base backup ${BACKUP_NAME}"
kubectl create --namespace "${POSTGRES_NAMESPACE}" -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: ${BACKUP_NAME}
  labels:
    app.kubernetes.io/part-of: startup-devops-baseline
    platform.startup.dev/test: v0.6.3
spec:
  cluster:
    name: ${POSTGRES_CLUSTER}
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
  target: prefer-standby
EOF

deadline=$((SECONDS + BACKUP_TIMEOUT_SECONDS))
while true; do
  phase="$(
    kubectl get backup "${BACKUP_NAME}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.status.phase}'
  )"

  case "${phase}" in
    completed)
      break
      ;;
    failed)
      kubectl describe backup "${BACKUP_NAME}" \
        --namespace "${POSTGRES_NAMESPACE}" >&2
      echo "CloudNativePG base backup failed." >&2
      exit 1
      ;;
  esac

  if (( SECONDS >= deadline )); then
    kubectl describe backup "${BACKUP_NAME}" \
      --namespace "${POSTGRES_NAMESPACE}" >&2
    echo "Timed out waiting for the CloudNativePG base backup." >&2
    exit 1
  fi

  sleep 10
done

echo "==> Forcing a WAL switch after the base backup"
PRIMARY_POD="$(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --output jsonpath='{.items[0].metadata.name}'
)"
kubectl exec "${PRIMARY_POD}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --container postgres \
  -- psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -Atqc "SELECT pg_switch_wal();" >/dev/null

echo "==> Waiting for base-backup and WAL objects in S3"
deadline=$((SECONDS + S3_TIMEOUT_SECONDS))
while true; do
  s3_keys="$(
    aws s3api list-objects-v2 \
      --bucket "${BACKUP_BUCKET}" \
      --prefix "postgresql-baseline/" \
      --query 'Contents[].Key' \
      --output text
  )"

  if [[ "${s3_keys}" == *"/base/"* && "${s3_keys}" == *"/wals/"* ]]; then
    break
  fi

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for base-backup and WAL objects in S3." >&2
    exit 1
  fi

  sleep 10
done

echo "CloudNativePG S3 base backup and WAL archiving test passed."
echo "Backup resource: ${POSTGRES_NAMESPACE}/${BACKUP_NAME}"

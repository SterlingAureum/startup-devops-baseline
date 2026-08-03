#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
RESOURCES_APPLICATION="${RESOURCES_APPLICATION:-external-secrets-startup-apps}"
SOURCE_NAMESPACE="${SOURCE_NAMESPACE:-data-platform}"
SOURCE_SECRET="${SOURCE_SECRET:-postgresql-baseline-app}"
SOURCE_KEY="${SOURCE_KEY:-fqdn-uri}"
TARGET_NAMESPACE="${TARGET_NAMESPACE:-startup-apps}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
TARGET_KEY="${TARGET_KEY:-DATABASE_URL}"
EXTERNAL_SECRET="${EXTERNAL_SECRET:-demo-api-postgresql}"
WAIT_SECONDS="${WAIT_SECONDS:-600}"
FORCE_SYNC_ANNOTATION_SET=false

for command in aws base64 jq kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

cleanup_force_sync_annotation() {
  if [[ "${FORCE_SYNC_ANNOTATION_SET}" == "true" ]]; then
    kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
      --namespace "${TARGET_NAMESPACE}" \
      force-sync- >/dev/null 2>&1 || true
  fi
}
trap cleanup_force_sync_annotation EXIT

tf_output() {
  local output_name="$1"
  local value

  value="$(terraform -chdir="${TF_DIR}" output -raw "${output_name}")"
  [[ -n "${value}" ]] || {
    echo "Terraform output ${output_name} is empty." >&2
    exit 1
  }
  printf '%s' "${value}"
}

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}" >/dev/null

SECRET_ARN="$(tf_output external_secrets_secret_arn)"
ROLE_ARN="$(tf_output external_secrets_role_arn)"

echo "==> Verifying the GitOps and ExternalSecret state"
kubectl wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/${RESOURCES_APPLICATION}" \
  --namespace argocd \
  --timeout="${WAIT_SECONDS}s"
kubectl wait \
  --for=condition=Ready \
  "ExternalSecret/${EXTERNAL_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" \
  --timeout="${WAIT_SECONDS}s"

EXTERNAL_SECRET_JSON="$(
  kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json
)"
jq --exit-status '
  .apiVersion == "external-secrets.io/v1" and
  .spec.secretStoreRef.name == "aws-secrets-manager" and
  .spec.secretStoreRef.kind == "SecretStore" and
  .spec.target.name == "demo-api-postgresql" and
  .spec.target.creationPolicy == "CreateOrMerge" and
  .spec.target.deletionPolicy == "Retain" and
  .spec.target.template.engineVersion == "v2" and
  .spec.target.template.mergePolicy == "Replace" and
  (.spec.data | length) == 1 and
  .spec.data[0].secretKey == "DATABASE_URL" and
  .spec.data[0].remoteRef.key == "startup-devops-baseline-dev/demo-api/postgresql" and
  .spec.data[0].remoteRef.property == "DATABASE_URL" and
  .spec.data[0].remoteRef.version == "AWSCURRENT" and
  .spec.data[0].remoteRef.conversionStrategy == "Default" and
  .spec.data[0].remoteRef.decodingStrategy == "None" and
  .spec.data[0].remoteRef.metadataPolicy == "None" and
  any(.status.conditions[]?; .type == "Ready" and .status == "True") and
  ((.status.refreshTime // "") | length > 0) and
  ((.status.syncedResourceVersion // "") | length > 0)
' <<<"${EXTERNAL_SECRET_JSON}" >/dev/null || {
  echo "The active ExternalSecret does not match its ready synchronization contract." >&2
  exit 1
}

read_values() {
  SOURCE_BASE64="$(
    kubectl get secret "${SOURCE_SECRET}" \
      --namespace "${SOURCE_NAMESPACE}" \
      --output json |
      jq -er --arg key "${SOURCE_KEY}" '.data[$key] | select(length > 0)'
  )"
  TARGET_JSON="$(
    kubectl get secret "${TARGET_SECRET}" \
      --namespace "${TARGET_NAMESPACE}" \
      --output json
  )"
  TARGET_BASE64="$(
    jq -er --arg key "${TARGET_KEY}" '.data[$key] | select(length > 0)' \
      <<<"${TARGET_JSON}"
  )"
  TARGET_KEYS="$(jq -r '.data | keys | join(",")' <<<"${TARGET_JSON}")"
  TARGET_MANAGER="$(
    jq -r '.metadata.labels["platform.startup.dev/managed-by"] // empty' \
      <<<"${TARGET_JSON}"
  )"
  REMOTE_DOCUMENT="$(
    aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${SECRET_ARN}" \
      --version-stage AWSCURRENT \
      --query SecretString \
      --output text
  )"
  REMOTE_VALUE="$(
    jq -er --arg key "${TARGET_KEY}" '.[$key] | select(type == "string" and length > 0)' \
      <<<"${REMOTE_DOCUMENT}"
  )"
  REMOTE_BASE64="$(printf '%s' "${REMOTE_VALUE}" | base64 | tr -d '\n')"
}

echo "==> Comparing CNPG, Secrets Manager, and Kubernetes values without printing them"
read_values
if [[ "${SOURCE_BASE64}" != "${REMOTE_BASE64}" || \
      "${SOURCE_BASE64}" != "${TARGET_BASE64}" || \
      "${TARGET_KEYS}" != "${TARGET_KEY}" || \
      "${TARGET_MANAGER}" != "external-secrets" ]]; then
  echo "CNPG, Secrets Manager, and the ESO-managed target are not identical." >&2
  exit 1
fi

if jq -e '
  any(.metadata.ownerReferences[]?; .kind == "ExternalSecret")
' <<<"${TARGET_JSON}" >/dev/null; then
  echo "CreateOrMerge unexpectedly added an ExternalSecret ownerReference." >&2
  exit 1
fi

echo "==> Verifying the ESO role is denied on an unrelated Secret ARN"
PARTITION="$(cut -d: -f2 <<<"${SECRET_ARN}")"
ACCOUNT_ID="$(cut -d: -f5 <<<"${SECRET_ARN}")"
DENIED_SECRET_ARN="arn:${PARTITION}:secretsmanager:${AWS_REGION}:${ACCOUNT_ID}:secret:external-secrets-denied-*"
DENIED_DECISION="$(
  aws iam simulate-principal-policy \
    --policy-source-arn "${ROLE_ARN}" \
    --action-names secretsmanager:GetSecretValue \
    --resource-arns "${DENIED_SECRET_ARN}" \
    --query 'EvaluationResults[0].EvalDecision' \
    --output text
)"
[[ "${DENIED_DECISION}" == "implicitDeny" ]] || {
  echo "ESO role decision for an unrelated Secret was ${DENIED_DECISION}, not implicitDeny." >&2
  exit 1
}

if [[ "${CONFIRM_EXTERNAL_SECRET_REBUILD:-}" != "delete-and-recreate" ]]; then
  cat >&2 <<'EOF'
Non-destructive External Secrets checks passed.

To prove automatic recovery, re-run with:
  CONFIRM_EXTERNAL_SECRET_REBUILD=delete-and-recreate \
    ./scripts/validate-external-secrets-migration-aws.sh

This deletes only startup-apps/demo-api-postgresql. Existing Pods retain their
current environment, and ESO must recreate the Secret before validation ends.
EOF
  exit 1
fi

ORIGINAL_TARGET_UID="$(jq -r '.metadata.uid' <<<"${TARGET_JSON}")"
[[ -n "${ORIGINAL_TARGET_UID}" ]] || {
  echo "The target Secret UID is empty." >&2
  exit 1
}

echo "==> Deleting and rebuilding only ${TARGET_NAMESPACE}/${TARGET_SECRET}"
kubectl delete secret "${TARGET_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" \
  --wait=true \
  --timeout=60s >/dev/null
kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" \
  force-sync="$(date +%s)" \
  --overwrite >/dev/null
FORCE_SYNC_ANNOTATION_SET=true

deadline=$((SECONDS + WAIT_SECONDS))
while true; do
  if kubectl get secret "${TARGET_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" >/dev/null 2>&1; then
    REBUILT_UID="$(
      kubectl get secret "${TARGET_SECRET}" \
        --namespace "${TARGET_NAMESPACE}" \
        --output jsonpath='{.metadata.uid}'
    )"
    if [[ -n "${REBUILT_UID}" && "${REBUILT_UID}" != "${ORIGINAL_TARGET_UID}" ]]; then
      break
    fi
  fi

  if (( SECONDS >= deadline )); then
    kubectl describe externalsecret "${EXTERNAL_SECRET}" \
      --namespace "${TARGET_NAMESPACE}" >&2 || true
    echo "Timed out waiting for ESO to recreate the target Secret." >&2
    exit 1
  fi
  sleep 5
done

kubectl wait \
  --for=condition=Ready \
  "ExternalSecret/${EXTERNAL_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" \
  --timeout="${WAIT_SECONDS}s"

echo "==> Rechecking all three protected values after recreation"
read_values
if [[ "${SOURCE_BASE64}" != "${REMOTE_BASE64}" || \
      "${SOURCE_BASE64}" != "${TARGET_BASE64}" || \
      "${TARGET_KEYS}" != "${TARGET_KEY}" || \
      "${TARGET_MANAGER}" != "external-secrets" ]]; then
  echo "The recreated Secret does not match CNPG and Secrets Manager." >&2
  exit 1
fi

echo "==> Removing the temporary ExternalSecret force-sync annotation"
kubectl annotate externalsecret "${EXTERNAL_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" \
  force-sync- >/dev/null
EXTERNAL_SECRET_JSON="$(
  kubectl get externalsecret "${EXTERNAL_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json
)"
jq --exit-status '
  (.metadata.annotations["force-sync"] == null) and
  any(.status.conditions[]?; .type == "Ready" and .status == "True")
' <<<"${EXTERNAL_SECRET_JSON}" >/dev/null || {
  echo "ExternalSecret is not Ready and clean after target reconstruction." >&2
  exit 1
}
FORCE_SYNC_ANNOTATION_SET=false

unset SOURCE_BASE64 TARGET_BASE64 REMOTE_BASE64 REMOTE_DOCUMENT REMOTE_VALUE TARGET_JSON

"${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"

echo "External Secrets migration runtime validation passed."

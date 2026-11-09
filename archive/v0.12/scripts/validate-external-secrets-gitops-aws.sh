#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
OPERATOR_APPLICATION="${OPERATOR_APPLICATION:-external-secrets}"
RESOURCES_APPLICATION="${RESOURCES_APPLICATION:-external-secrets-startup-apps}"
ESO_NAMESPACE="${ESO_NAMESPACE:-external-secrets}"
ESO_SERVICE_ACCOUNT="${ESO_SERVICE_ACCOUNT:-external-secrets}"
TARGET_NAMESPACE="${TARGET_NAMESPACE:-startup-apps}"
STORE_NAME="${STORE_NAME:-aws-secrets-manager}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"

for command in jq kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

terraform_output() {
  local output_name="$1"
  local value

  value="$(terraform -chdir="${TF_DIR}" output -raw "${output_name}")"
  [[ -n "${value}" ]] || {
    echo "Terraform output ${output_name} is empty." >&2
    exit 1
  }
  printf '%s' "${value}"
}

EXPECTED_ROLE_ARN="$(terraform_output external_secrets_role_arn)"
if [[ ! "${EXPECTED_ROLE_ARN}" =~ ^arn:[^:]+:iam::[0-9]{12}:role/.+ ]]; then
  echo "Terraform output external_secrets_role_arn is not a valid IAM role ARN." >&2
  exit 1
fi

echo "==> Verifying Argo CD application state"
for application in "${OPERATOR_APPLICATION}" "${RESOURCES_APPLICATION}"; do
  kubectl wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${application}" \
    --namespace argocd \
    --timeout=300s
done

kubectl wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${OPERATOR_APPLICATION}" \
  --namespace argocd \
  --timeout=300s

OPERATOR_REVISION="$({
  kubectl get application "${OPERATOR_APPLICATION}" \
    --namespace argocd \
    --output jsonpath='{.spec.source.targetRevision}'
})"
[[ "${OPERATOR_REVISION}" == "2.8.0" ]] || {
  echo "ESO Application is not pinned to 2.8.0: ${OPERATOR_REVISION}" >&2
  exit 1
}

echo "==> Verifying ESO workload identity"
ACTUAL_ROLE_ARN="$({
  kubectl get serviceaccount "${ESO_SERVICE_ACCOUNT}" \
    --namespace "${ESO_NAMESPACE}" \
    --output jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}'
})"
[[ "${ACTUAL_ROLE_ARN}" == "${EXPECTED_ROLE_ARN}" ]] || {
  echo "ESO ServiceAccount IRSA annotation does not match Terraform output." >&2
  exit 1
}

PODS_JSON="$({
  kubectl get pods \
    --namespace "${ESO_NAMESPACE}" \
    --output json
})"
jq -e \
  --arg role "${EXPECTED_ROLE_ARN}" \
  --arg service_account "${ESO_SERVICE_ACCOUNT}" '
  any(.items[];
    .spec.serviceAccountName == $service_account and
    any(.spec.containers[].env[]?;
      .name == "AWS_ROLE_ARN" and .value == $role) and
    any(.spec.containers[].env[]?;
      .name == "AWS_WEB_IDENTITY_TOKEN_FILE"))
' <<<"${PODS_JSON}" >/dev/null || {
  echo "A running ESO controller Pod does not contain the expected IRSA environment." >&2
  exit 1
}

echo "==> Verifying ESO components"
for deployment in \
  external-secrets \
  external-secrets-webhook \
  external-secrets-cert-controller; do
  kubectl rollout status \
    "deployment/${deployment}" \
    --namespace "${ESO_NAMESPACE}" \
    --timeout=300s
done

for crd in externalsecrets.external-secrets.io secretstores.external-secrets.io; do
  kubectl get customresourcedefinition "${crd}" >/dev/null
done

echo "==> Verifying namespace-scoped Kubernetes permissions"
ESO_SUBJECT="system:serviceaccount:${ESO_NAMESPACE}:${ESO_SERVICE_ACCOUNT}"
kubectl auth can-i list secrets \
  --as="${ESO_SUBJECT}" \
  --namespace "${TARGET_NAMESPACE}" | grep -qx yes || {
  echo "ESO cannot reconcile Secrets in ${TARGET_NAMESPACE}." >&2
  exit 1
}

if kubectl auth can-i list secrets \
  --as="${ESO_SUBJECT}" \
  --namespace data-platform | grep -qx yes; then
  echo "ESO unexpectedly has Secret list access in data-platform." >&2
  exit 1
fi

if kubectl auth can-i create serviceaccounts/token \
  --as="${ESO_SUBJECT}" \
  --namespace "${TARGET_NAMESPACE}" | grep -qx yes; then
  echo "ESO unexpectedly has ServiceAccount token creation permission." >&2
  exit 1
fi

echo "==> Verifying SecretStore/aws-secrets-manager readiness"
kubectl wait \
  --for=condition=Ready \
  "SecretStore/${STORE_NAME}" \
  --namespace "${TARGET_NAMESPACE}" \
  --timeout=300s

STORE_JSON="$({
  kubectl get secretstore "${STORE_NAME}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json
})"
jq -e '
  .apiVersion == "external-secrets.io/v1" and
  .spec.provider.aws.service == "SecretsManager" and
  .spec.provider.aws.region == "us-east-1" and
  (.spec.provider.aws.auth == null)
' <<<"${STORE_JSON}" >/dev/null || {
  echo "The namespaced AWS SecretStore contract is not correct." >&2
  exit 1
}

echo "==> Verifying Checkpoint 2 cutover boundary"
if kubectl get externalsecret "${TARGET_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" >/dev/null 2>&1; then
  echo "The staged ExternalSecret was activated before Checkpoint 3." >&2
  exit 1
fi

kubectl get secret "${TARGET_SECRET}" \
  --namespace "${TARGET_NAMESPACE}" >/dev/null

echo "External Secrets GitOps runtime validation passed."

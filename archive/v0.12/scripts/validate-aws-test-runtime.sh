#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="aws-test"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

for command in aws curl jq kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring the exact aws-test Kubernetes context"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}" >/dev/null
kubectl --request-timeout=30s get --raw=/readyz >/dev/null
[[ "$(kubectl config current-context)" == *"${CLUSTER_NAME}"* ]] || {
  echo "Current context does not identify ${CLUSTER_NAME}." >&2
  exit 1
}

echo "==> Validating GitOps convergence"
for application in "${ROOT_APPLICATION}" "${DEMO_APPLICATION}" postgresql-baseline; do
  kubectl get application "${application}" -n argocd -o json |
    jq --exit-status '.status.sync.status == "Synced" and .status.health.status == "Healthy"' >/dev/null
done

echo "==> Validating database and application runtime"
AWS_REGION="${AWS_REGION}" CLUSTER_NAME="${CLUSTER_NAME}" TF_DIR="${TF_DIR}" \
  "${ROOT_DIR}/scripts/validate-cloudnative-pg-backup.sh"
"${ROOT_DIR}/scripts/validate-cloudnative-pg-persistence.sh"
APPLICATION_NAME="${DEMO_APPLICATION}" DEMO_WORKLOAD_KIND="Rollout" \
  "${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"

curl --fail --silent --show-error "https://${DEMO_HOSTNAME}/ready" |
  jq --exit-status '.status == "ready" and .database == "ok"' >/dev/null
curl --fail --silent --show-error "https://${DEMO_HOSTNAME}/version" |
  jq --exit-status '.environment == "aws-test" and (.version | length > 0)' >/dev/null

if [[ -n "${EVIDENCE_ACTOR:-}" ]]; then
  echo "==> Recording release-bound aws-test runtime evidence"
  ENVIRONMENT="aws-test" EVIDENCE_ACTOR="${EVIDENCE_ACTOR}" \
    "${ROOT_DIR}/scripts/record-demo-api-runtime-evidence-aws.sh"
else
  echo "EVIDENCE_ACTOR is unset; runtime evidence recording was intentionally skipped."
fi

echo "aws-test runtime validation passed."

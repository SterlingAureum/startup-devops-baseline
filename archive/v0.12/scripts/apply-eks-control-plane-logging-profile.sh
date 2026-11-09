#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

PROFILE="${EKS_CONTROL_PLANE_LOGGING_PROFILE:-}"
PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/v097-eks-logging.XXXXXX.tfplan")"
trap 'rm -f -- "${PLAN_FILE}"' EXIT

for command in aws jq terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

case "${PROFILE}" in
  off)
    if [[ "${AWS_ENVIRONMENT}" == "aws-prod" ]]; then
      echo "The production Terraform root refuses the off logging profile." >&2
      exit 1
    fi
    LOG_TYPES_JSON='[]'
    ;;
  production-parity)
    LOG_TYPES_JSON='["api","audit","authenticator","controllerManager","scheduler"]'
    ;;
  *)
    cat >&2 <<'EOF'
EKS_CONTROL_PLANE_LOGGING_PROFILE must be one of:
  off                - no new control-plane log ingestion (aws-dev/aws-test only)
  production-parity  - all five EKS control-plane log types
EOF
    exit 1
    ;;
esac

if [[ "${CONFIRM_EKS_LOGGING_PROFILE:-}" != "apply-eks-logging-profile" ]]; then
  cat >&2 <<EOF
This will update ${CLUSTER_NAME} to the ${PROFILE} EKS control-plane logging
profile through Terraform. Re-run with:

  CONFIRM_EKS_LOGGING_PROFILE=apply-eks-logging-profile

Disabling ingestion does not delete existing CloudWatch log events or reverse
usage already recorded for the current billing month.
EOF
  exit 1
fi

echo "==> Verifying AWS identity and live EKS endpoint configuration"
aws sts get-caller-identity >/dev/null
CLUSTER_JSON="$(aws eks describe-cluster \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" \
  --output json)"
PUBLIC_ACCESS_CIDRS_JSON="$(
  jq -c '.cluster.resourcesVpcConfig.publicAccessCidrs' <<<"${CLUSTER_JSON}"
)"
jq --exit-status '
  type == "array" and length > 0 and
  all(.[]; test("^[0-9A-Fa-f:./]+$") and . != "0.0.0.0/0")
' <<<"${PUBLIC_ACCESS_CIDRS_JSON}" >/dev/null || {
  echo "The live EKS public endpoint allowlist is empty, open, or invalid." >&2
  exit 1
}

echo "==> Planning ${PROFILE} logging for ${AWS_ENVIRONMENT}"
terraform -chdir="${TF_DIR}" init -input=false
terraform -chdir="${TF_DIR}" plan \
  -input=false \
  -out="${PLAN_FILE}" \
  -var="eks_public_access_cidrs=${PUBLIC_ACCESS_CIDRS_JSON}" \
  -var="eks_enabled_cluster_log_types=${LOG_TYPES_JSON}" \
  -var="eks_cluster_log_retention_days=${EKS_CLUSTER_LOG_RETENTION_DAYS}"

echo "==> Applying the reviewed logging profile"
terraform -chdir="${TF_DIR}" apply -input=false "${PLAN_FILE}"
aws eks wait cluster-active --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

ACTUAL_LOG_TYPES_JSON="$(
  aws eks describe-cluster \
    --region "${AWS_REGION}" \
    --name "${CLUSTER_NAME}" \
    --output json |
    jq -c '[.cluster.logging.clusterLogging[]? | select(.enabled == true) | .types[]] | unique | sort'
)"
EXPECTED_LOG_TYPES_JSON="$(jq -c 'sort' <<<"${LOG_TYPES_JSON}")"
if [[ "${ACTUAL_LOG_TYPES_JSON}" != "${EXPECTED_LOG_TYPES_JSON}" ]]; then
  echo "Unexpected live EKS log types: ${ACTUAL_LOG_TYPES_JSON}" >&2
  exit 1
fi

LOG_RETENTION="$(aws logs describe-log-groups \
  --region "${AWS_REGION}" \
  --log-group-name-prefix "/aws/eks/${CLUSTER_NAME}/cluster" \
  --output json |
  jq -r --arg name "/aws/eks/${CLUSTER_NAME}/cluster" '
    [.logGroups[] | select(.logGroupName == $name)] |
    if length == 1 then .[0].retentionInDays else empty end
  ')"
if [[ "${LOG_RETENTION}" != "${EKS_CLUSTER_LOG_RETENTION_DAYS}" ]]; then
  echo "Unexpected EKS log retention: ${LOG_RETENTION:-missing}" >&2
  exit 1
fi

echo "EKS control-plane logging profile passed: ${AWS_ENVIRONMENT}/${PROFILE}."
echo "Enabled types: ${ACTUAL_LOG_TYPES_JSON}; retention: ${LOG_RETENTION} days."

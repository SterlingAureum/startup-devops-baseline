#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
REQUESTED_LOG_TYPES_JSON="${EKS_CLUSTER_LOG_TYPES_JSON-}"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context
EKS_ACCESS_MODE="${EKS_ACCESS_MODE:-maintain}"
[[ "${EKS_ACCESS_MODE}" == maintain || "${EKS_ACCESS_MODE}" == create-dev ]] || exit 1
if [[ "${EKS_ACCESS_MODE}" == create-dev ]]; then
  [[ "${AWS_ENVIRONMENT}" == aws-dev &&
     "${CONFIRM_AWS_DEV_APPLY:-}" == create-ephemeral-aws-dev &&
     "${EXPECTED_AWS_ACCOUNT_ID:-}" =~ ^[0-9]{12}$ ]] || {
    echo 'Creation requires aws-dev confirmation and EXPECTED_AWS_ACCOUNT_ID.' >&2; exit 1;
  }
  [[ "${TF_DIR}" == "${ROOT_DIR}/infra/terraform/aws/environments/dev" &&
     "${CLUSTER_NAME}" == startup-devops-baseline-dev ]] || {
    echo 'Creation refuses custom Terraform roots or cluster names.' >&2; exit 1;
  }
fi

IP_DISCOVERY_URL="${IP_DISCOVERY_URL:-https://checkip.amazonaws.com}"

for command in aws curl jq kubectl python3 terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "${CONFIRM_EKS_API_CIDR_UPDATE:-}" != "restrict-current-ip" ]]; then
  cat >&2 <<'EOF'
Set CONFIRM_EKS_API_CIDR_UPDATE=restrict-current-ip to update the EKS public
endpoint allowlist. The detected address is passed directly to Terraform and
is never written to a repository file.
EOF
  exit 1
fi

PUBLIC_IP="${MANAGEMENT_PUBLIC_IP:-}"
if [[ -z "${PUBLIC_IP}" ]]; then
  PUBLIC_IP="$(curl --proto '=https' --tlsv1.2 --fail --silent --show-error "${IP_DISCOVERY_URL}")"
fi

PUBLIC_IP="$(
  python3 - "${PUBLIC_IP}" <<'PY'
import ipaddress
import sys

try:
    address = ipaddress.ip_address(sys.argv[1].strip())
except ValueError as error:
    raise SystemExit(f"Invalid management public IP: {error}")

if address.version != 4 or not address.is_global:
    raise SystemExit("The management address must be a globally routable IPv4 address.")

print(address)
PY
)"
MANAGEMENT_CIDR="${PUBLIC_IP}/32"
PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/v086-eks-access.XXXXXX.tfplan")"
trap 'rm -f -- "${PLAN_FILE}"' EXIT

echo "==> AWS identity"
aws sts get-caller-identity >/dev/null

if [[ "${EKS_ACCESS_MODE}" == create-dev ]]; then
  ACTUAL_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
  [[ "${ACTUAL_ACCOUNT}" == "${EXPECTED_AWS_ACCOUNT_ID}" ]] || {
    echo 'AWS account mismatch; no Terraform operation performed.' >&2; exit 1;
  }
fi
DISCOVERY_ERROR="$(mktemp)"
trap 'rm -f -- "${PLAN_FILE}" "${DISCOVERY_ERROR}"' EXIT
if CLUSTER_JSON="$(aws eks describe-cluster --region "${AWS_REGION}" --name "${CLUSTER_NAME}" --output json 2>"${DISCOVERY_ERROR}")"; then
  [[ "${EKS_ACCESS_MODE}" == maintain ]] || {
    echo 'Cluster already exists; use the maintenance entrypoint after reviewing Terraform state.' >&2; exit 1;
  }
else
  if ! grep -q '(ResourceNotFoundException)' "${DISCOVERY_ERROR}"; then
    cat "${DISCOVERY_ERROR}" >&2
    echo 'EKS discovery failed; this is not proof of an absent cluster.' >&2; exit 1
  fi
  [[ "${EKS_ACCESS_MODE}" == create-dev ]] || {
    echo 'Cluster not found. Verify AWS account/region; for initial dev creation use scripts/apply-aws-dev.sh.' >&2; exit 1;
  }
fi

# Endpoint allowlist maintenance must not silently change the logging cost
# profile. Preserve the live EKS setting unless the operator explicitly passes
# EKS_CLUSTER_LOG_TYPES_JSON.
if [[ -z "${REQUESTED_LOG_TYPES_JSON}" ]]; then
  EKS_CLUSTER_LOG_TYPES_JSON="$(
    printf '%s' "${CLUSTER_JSON}" |
      jq -c '[.cluster.logging.clusterLogging[]? | select(.enabled == true) | .types[]] | unique'
  )"
else
  EKS_CLUSTER_LOG_TYPES_JSON="${REQUESTED_LOG_TYPES_JSON}"
fi
EKS_CLUSTER_LOG_TYPES_JSON="$(
  jq -ce '
    type == "array" and
    length == (unique | length) and
    all(.[]; IN("api", "audit", "authenticator", "controllerManager", "scheduler"))
  ' <<<"${EKS_CLUSTER_LOG_TYPES_JSON}" >/dev/null &&
  jq -c 'sort' <<<"${EKS_CLUSTER_LOG_TYPES_JSON}"
)" || {
  echo "EKS_CLUSTER_LOG_TYPES_JSON must be a unique array of supported EKS control-plane log types." >&2
  exit 1
}

echo "==> Restricting ${CLUSTER_NAME} public endpoint to the current workstation /32"
echo "The address is runtime-only and will not be written to Git."
echo "Preserving EKS control-plane log types: ${EKS_CLUSTER_LOG_TYPES_JSON}"

terraform -chdir="${TF_DIR}" init -input=false
if [[ "${EKS_ACCESS_MODE}" == create-dev ]]; then
  STATE_JSON="$(terraform -chdir="${TF_DIR}" show -json)" || {
    echo 'Cannot inspect Terraform state; stopping.' >&2; exit 1;
  }
  jq -e '[.. | objects | .resources? // empty | .[]] | length == 0' <<<"${STATE_JSON}" >/dev/null || {
    echo 'Nonempty dev state: review partial/existing infrastructure; do not delete state.' >&2; exit 1;
  }
fi
terraform -chdir="${TF_DIR}" plan \
  -input=false \
  -out="${PLAN_FILE}" \
  -var="eks_public_access_cidrs=[\"${MANAGEMENT_CIDR}\"]" \
  -var="eks_enabled_cluster_log_types=${EKS_CLUSTER_LOG_TYPES_JSON}" \
  -var="eks_cluster_log_retention_days=${EKS_CLUSTER_LOG_RETENTION_DAYS}"
if [[ "${EKS_ACCESS_MODE}" == create-dev ]]; then
  read -r -p 'Review the plan above. Type apply-aws-dev to apply: ' PLAN_CONFIRMATION
  [[ "${PLAN_CONFIRMATION}" == apply-aws-dev ]] || exit 1
fi
terraform -chdir="${TF_DIR}" apply -input=false "${PLAN_FILE}"

echo "==> Waiting for ${CLUSTER_NAME} to report Active"
aws eks wait cluster-active \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"

ACTUAL_CIDRS="$(
  aws eks describe-cluster \
    --region "${AWS_REGION}" \
    --name "${CLUSTER_NAME}" \
    --query 'cluster.resourcesVpcConfig.publicAccessCidrs' \
    --output text
)"
if [[ "${ACTUAL_CIDRS}" != "${MANAGEMENT_CIDR}" ]]; then
  echo "EKS returned an unexpected public endpoint allowlist: ${ACTUAL_CIDRS}" >&2
  exit 1
fi

echo "==> Refreshing kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Verifying Kubernetes API access from this workstation"
if ! kubectl --request-timeout=30s get --raw=/readyz >/dev/null; then
  cat >&2 <<EOF
EKS saved ${MANAGEMENT_CIDR}, but this terminal could not reach the Kubernetes
API after kubeconfig was refreshed. Keep the current VPN or network route
stable, verify the terminal's actual egress path, and rerun this guarded script.
AWS Console or the EKS management API remains available for endpoint recovery.
EOF
  exit 1
fi

echo "EKS public endpoint restriction passed."
echo "Re-run this script whenever the workstation public IP changes."

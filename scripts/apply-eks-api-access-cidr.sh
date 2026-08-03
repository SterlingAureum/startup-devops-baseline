#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
IP_DISCOVERY_URL="${IP_DISCOVERY_URL:-https://checkip.amazonaws.com}"
EKS_CLUSTER_LOG_TYPES_JSON="${EKS_CLUSTER_LOG_TYPES_JSON:-[\"api\",\"audit\",\"authenticator\"]}"
EKS_CLUSTER_LOG_RETENTION_DAYS="${EKS_CLUSTER_LOG_RETENTION_DAYS:-14}"

for command in aws curl kubectl python3 terraform; do
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

echo "==> Restricting ${CLUSTER_NAME} public endpoint to the current workstation /32"
echo "The address is runtime-only and will not be written to Git."

terraform -chdir="${TF_DIR}" init -input=false
terraform -chdir="${TF_DIR}" plan \
  -input=false \
  -out="${PLAN_FILE}" \
  -var="eks_public_access_cidrs=[\"${MANAGEMENT_CIDR}\"]" \
  -var="eks_enabled_cluster_log_types=${EKS_CLUSTER_LOG_TYPES_JSON}" \
  -var="eks_cluster_log_retention_days=${EKS_CLUSTER_LOG_RETENTION_DAYS}"
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

#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="aws-test"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

IP_DISCOVERY_URL="${IP_DISCOVERY_URL:-https://checkip.amazonaws.com}"
APPLY_MODE="${AWS_TEST_APPLY_MODE:-create}"
PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/v096-aws-test.XXXXXX.tfplan")"
trap 'rm -f -- "${PLAN_FILE}"' EXIT

for command in aws curl git python3 terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "${APPLY_MODE}" != "create" && "${APPLY_MODE}" != "resume" ]]; then
  echo "AWS_TEST_APPLY_MODE must be create or resume." >&2
  exit 1
fi
if [[ "$(git -C "${ROOT_DIR}" branch --show-current)" != "main" ]] ||
   [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
  echo "Run the aws-test clean-room apply from a clean main worktree." >&2
  exit 1
fi

if [[ "${CONFIRM_AWS_TEST_APPLY:-}" != "apply-ephemeral-aws-test" ]]; then
  cat >&2 <<'EOF'
This creates billable aws-test resources: EKS, EC2, NAT Gateway, EBS, S3,
Secrets Manager, CloudWatch, and related networking. The environment is
ephemeral and must be destroyed after evidence collection.

Re-run with CONFIRM_AWS_TEST_APPLY=apply-ephemeral-aws-test.
EOF
  exit 1
fi

PUBLIC_IP="${MANAGEMENT_PUBLIC_IP:-}"
if [[ -z "${PUBLIC_IP}" ]]; then
  PUBLIC_IP="$(curl --proto '=https' --tlsv1.2 --fail --silent --show-error "${IP_DISCOVERY_URL}")"
fi
PUBLIC_IP="$(python3 - "${PUBLIC_IP}" <<'PY'
import ipaddress
import sys

address = ipaddress.ip_address(sys.argv[1].strip())
if address.version != 4 or not address.is_global:
    raise SystemExit("The management address must be a globally routable IPv4 address.")
print(address)
PY
)"
MANAGEMENT_CIDR="${PUBLIC_IP}/32"

echo "==> Verifying AWS identity"
aws sts get-caller-identity >/dev/null

echo "==> Initializing the independent aws-test Terraform root"
terraform -chdir="${TF_DIR}" init -input=false

STATE_LIST="$(terraform -chdir="${TF_DIR}" state list 2>/dev/null || true)"
STATE_COUNT="$(sed '/^$/d' <<<"${STATE_LIST}" | wc -l | tr -d ' ')"
if [[ "${APPLY_MODE}" == "create" && "${STATE_COUNT}" != "0" ]]; then
  echo "aws-test Terraform state is not empty; use AWS_TEST_APPLY_MODE=resume only after reviewing the existing state." >&2
  exit 1
fi

if [[ "${APPLY_MODE}" == "create" ]] &&
   aws eks describe-cluster --region "${AWS_REGION}" --name "${CLUSTER_NAME}" >/dev/null 2>&1; then
  echo "${CLUSTER_NAME} already exists; refusing a create-mode apply." >&2
  exit 1
fi

echo "==> Planning aws-test with a runtime-only EKS management /32"
terraform -chdir="${TF_DIR}" plan \
  -input=false \
  -out="${PLAN_FILE}" \
  -var="eks_public_access_cidrs=[\"${MANAGEMENT_CIDR}\"]"

echo "==> Applying reviewed aws-test plan"
terraform -chdir="${TF_DIR}" apply -input=false "${PLAN_FILE}"
aws eks wait cluster-active --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

ACTUAL_CIDRS="$(aws eks describe-cluster \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" \
  --query 'cluster.resourcesVpcConfig.publicAccessCidrs' \
  --output text)"
if [[ "${ACTUAL_CIDRS}" != "${MANAGEMENT_CIDR}" ]]; then
  echo "EKS returned an unexpected endpoint allowlist: ${ACTUAL_CIDRS}" >&2
  exit 1
fi

echo "aws-test Terraform apply passed. The management address remained runtime-only."
echo "Next: ./scripts/bootstrap-aws-test.sh"

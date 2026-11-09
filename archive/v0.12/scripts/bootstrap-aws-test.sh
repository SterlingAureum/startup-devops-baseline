#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="aws-test"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

if [[ "${CONFIRM_AWS_TEST_BOOTSTRAP:-}" != "bootstrap-ephemeral-aws-test" ]]; then
  cat >&2 <<'EOF'
This bootstraps Argo CD and applies the aws-test root Application to the
ephemeral EKS cluster. Run only after reviewing the aws-test Terraform apply.

Re-run with CONFIRM_AWS_TEST_BOOTSTRAP=bootstrap-ephemeral-aws-test.
EOF
  exit 1
fi

if [[ "$(git -C "${ROOT_DIR}" branch --show-current)" != "main" ]] ||
   [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
  echo "Run aws-test bootstrap from a clean main worktree." >&2
  exit 1
fi

AWS_REGION="${AWS_REGION}" \
CLUSTER_NAME="${CLUSTER_NAME}" \
TF_DIR="${TF_DIR}" \
  "${ROOT_DIR}/scripts/bootstrap-eks-argocd.sh"

AWS_REGION="${AWS_REGION}" \
CLUSTER_NAME="${CLUSTER_NAME}" \
TF_DIR="${TF_DIR}" \
ROOT_APPLICATION="${ROOT_APPLICATION}" \
DEMO_APPLICATION="${DEMO_APPLICATION}" \
DEMO_HOSTNAME="${DEMO_HOSTNAME}" \
SOURCE_FILE="${SOURCE_FILE}" \
DEMO_ACCEPTED_HEALTH_STATUSES="Healthy,Suspended,Progressing" \
TARGET_REVISION="main" \
  "${ROOT_DIR}/scripts/deploy-aws-dev-root-app.sh"

echo "aws-test GitOps bootstrap reached a reviewable runtime state."
echo "Promote aws-dev -> aws-test through the governed workflow, then complete the canary."

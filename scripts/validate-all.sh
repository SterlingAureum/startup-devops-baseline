#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_step() {
  local label="$1"
  local script="$2"
  printf '
==> %s
' "${label}"
  if [[ ! -x "${script}" ]]; then
    printf 'ERROR: required executable not found: %s
' "${script}" >&2
    exit 1
  fi
  "${script}"
}

printf '%s
'   '============================================'   ' startup-devops-baseline full validation'   '============================================'

run_step "Terraform configuration" "${ROOT_DIR}/scripts/validate-terraform.sh"
run_step "EKS infrastructure baseline" "${ROOT_DIR}/scripts/validate-eks-baseline.sh"
run_step "Karpenter AWS foundation" "${ROOT_DIR}/scripts/validate-karpenter-foundation.sh"
run_step "Karpenter controller" "${ROOT_DIR}/scripts/validate-karpenter-controller.sh"
run_step "Karpenter EC2NodeClass" "${ROOT_DIR}/scripts/validate-karpenter-nodeclass.sh"
run_step "AWS GitOps and application baseline" "${ROOT_DIR}/scripts/validate-aws-dev.sh"

printf '
%s
'   '============================================'   ' Validation completed successfully'   '============================================'

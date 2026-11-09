#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_step() {
  local label="$1"
  local script="$2"
  printf '\n==> %s\n' "${label}"
  "${script}"
}

run_step "TLS, DNS, endpoint, logging, and IP privacy static contracts" \
  "${ROOT_DIR}/scripts/validate-tls-dns-security.sh"
run_step "TLS, DNS, endpoint, logging, and HTTPS AWS runtime" \
  "${ROOT_DIR}/scripts/validate-tls-dns-security-aws.sh"
run_step "Namespace guardrail contracts" \
  "${ROOT_DIR}/scripts/validate-namespace-guardrails.sh"
run_step "Application admission-policy contracts" \
  "${ROOT_DIR}/scripts/validate-application-admission-policies.sh"
run_step "EKS NetworkPolicy contracts" \
  "${ROOT_DIR}/scripts/validate-eks-network-policy.sh"
run_step "startup-apps NetworkPolicy contracts" \
  "${ROOT_DIR}/scripts/validate-startup-apps-network-policy.sh"
run_step "data-platform NetworkPolicy contracts" \
  "${ROOT_DIR}/scripts/validate-data-platform-network-policy.sh"
run_step "External Secrets foundation contracts" \
  "${ROOT_DIR}/scripts/validate-external-secrets-foundation.sh"
run_step "External Secrets GitOps contracts" \
  "${ROOT_DIR}/scripts/validate-external-secrets-gitops.sh"
run_step "External Secrets migration contracts" \
  "${ROOT_DIR}/scripts/validate-external-secrets-migration.sh"
run_step "PostgreSQL credential rotation contracts" \
  "${ROOT_DIR}/scripts/validate-postgresql-credential-rotation.sh"
run_step "PostgreSQL rollback final state" \
  "${ROOT_DIR}/scripts/validate-postgresql-credential-rollback-aws.sh"

echo
echo "v0.8 Production Security Baseline final validation passed."

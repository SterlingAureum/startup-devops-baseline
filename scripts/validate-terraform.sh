#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly TF_ROOT="${ROOT_DIR}/infra/terraform/aws"
readonly ROOTS=(runtime-identities environments/dev environments/test environments/prod)

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform was not found in PATH" >&2
  exit 1
fi

echo "==> Checking Terraform formatting"
terraform fmt -check -recursive "${TF_ROOT}"

for root in "${ROOTS[@]}"; do
  tf_dir="${TF_ROOT}/${root}"
  echo "==> Initializing Terraform root ${root} without backend configuration"
  terraform -chdir="${tf_dir}" init -backend=false -input=false

  echo "==> Validating Terraform configuration for ${root}"
  terraform -chdir="${tf_dir}" validate
done

echo "Terraform runtime-identities/dev/test/prod validation passed"

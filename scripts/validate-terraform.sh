#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly TF_ROOT="${ROOT_DIR}/infra/terraform/aws"
readonly ENVIRONMENTS=(dev test prod)

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform was not found in PATH" >&2
  exit 1
fi

echo "==> Checking Terraform formatting"
terraform fmt -check -recursive "${TF_ROOT}"

for environment in "${ENVIRONMENTS[@]}"; do
  tf_dir="${TF_ROOT}/environments/${environment}"
  echo "==> Initializing Terraform for ${environment} without backend configuration"
  terraform -chdir="${tf_dir}" init -backend=false -input=false

  echo "==> Validating Terraform configuration for ${environment}"
  terraform -chdir="${tf_dir}" validate
done

echo "Terraform dev/test/prod validation passed"

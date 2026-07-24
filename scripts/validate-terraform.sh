#!/usr/bin/env bash
set -euo pipefail

readonly TF_DIR="infra/terraform/aws/environments/dev"

if ! command -v terraform >/dev/null 2>&1; then
  echo "terraform was not found in PATH" >&2
  exit 1
fi

echo "==> Checking Terraform formatting"
terraform -chdir="${TF_DIR}" fmt -check -recursive

echo "==> Initializing Terraform without backend configuration"
terraform -chdir="${TF_DIR}" init -backend=false -input=false

echo "==> Validating Terraform configuration"
terraform -chdir="${TF_DIR}" validate

echo "Terraform validation passed"

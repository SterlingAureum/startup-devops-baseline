#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_BIN="${TERRAFORM_BIN:-terraform}"
optional=false

if [[ "${1:-}" == "--optional" ]]; then
  optional=true
  shift
fi
if (( $# != 0 )); then
  echo "Usage: $0 [--optional]" >&2
  exit 2
fi

if ! command -v "${TERRAFORM_BIN}" >/dev/null 2>&1; then
  if [[ "${optional}" == "true" ]]; then
    echo "SKIP: terraform unavailable; tracked Terraform formatting remains required in terraform-validate CI."
    exit 0
  fi
  echo "terraform was not found in PATH" >&2
  exit 1
fi

mapfile -d '' -t repository_paths < <(
  git -C "${ROOT_DIR}" ls-files -z -- infra/terraform/aws
)

tracked_terraform_files=()
for relative_path in "${repository_paths[@]}"; do
  case "${relative_path}" in
    *.tf|*.tfvars|*.tfvars.json)
      tracked_terraform_files+=("${relative_path}")
      ;;
  esac
done

if (( ${#tracked_terraform_files[@]} == 0 )); then
  echo "No tracked Terraform files were found under infra/terraform/aws" >&2
  exit 1
fi

(
  cd "${ROOT_DIR}"
  "${TERRAFORM_BIN}" fmt -check -no-color "${tracked_terraform_files[@]}"
)

echo "Tracked Terraform formatting passed; tracked_file_count=${#tracked_terraform_files[@]}; ignored private tfvars were not inspected."

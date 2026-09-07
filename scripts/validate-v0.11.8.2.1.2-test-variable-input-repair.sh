#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-aws-test-variable-inputs.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.2.1-aws-test-feature-qualification.sh"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.2.1.1-active-gitops-preview-registration.sh"
echo 'v0.11.8.2.1.2 offline variable/review guards passed; live acceptance remains separate.'

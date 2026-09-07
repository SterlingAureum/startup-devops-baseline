#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-aws-test-target-identity.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.2.1.2-test-variable-input-repair.sh"
echo 'v0.11.8.2.1.3 target identity regression passed; live qualification is separate.'

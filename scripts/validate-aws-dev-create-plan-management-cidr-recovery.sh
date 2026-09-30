#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py" \
  --root "${ROOT_DIR}"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"

python3 -m json.tool \
  "${ROOT_DIR}/delivery/contracts/v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-management-cidr-recovery.json" \
  >/dev/null

python3 -m json.tool \
  "${ROOT_DIR}/delivery/examples/v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery-request.example.json" \
  >/dev/null

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.5.0.1-aws-dev-create-plan-recovery.py"

bash -n "${ROOT_DIR}/scripts/validate-aws-dev-create-plan-management-cidr-recovery.sh"

echo "v0.12.4.1.5.0.5.0.1 management-CIDR recovery offline validation passed; no live command was executed."

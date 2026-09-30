#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.py" \
  --root "${ROOT_DIR}"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py"

python3 -m json.tool \
  "${ROOT_DIR}/delivery/contracts/v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.json" \
  >/dev/null

python3 -m json.tool \
  "${ROOT_DIR}/delivery/examples/v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply-request.example.json" \
  >/dev/null

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py" \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.6-aws-dev-recovery-saved-plan-apply.py"

bash -n "${ROOT_DIR}/scripts/validate-v0.12.4.1.5.0.6-reviewed-aws-dev-recovery-saved-plan-apply.sh"

echo "v0.12.4.1.5.0.6 reviewed aws-dev recovery saved-plan apply contract passed offline; no live command was executed."

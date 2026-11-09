#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.5-guarded-aws-dev-saved-create-plan.py" \
  --root "${ROOT_DIR}"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py"

python3 -m json.tool \
  "${ROOT_DIR}/delivery/contracts/v0.12.4.1.5.0.5-guarded-aws-dev-remote-state-saved-create-plan.json" \
  >/dev/null

python3 -m json.tool \
  "${ROOT_DIR}/delivery/examples/v0.12.4.1.5.0.5-aws-dev-clean-room-create-plan-request.example.json" \
  >/dev/null

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.5-guarded-aws-dev-saved-create-plan.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py" \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.5-aws-dev-saved-create-plan.py"

bash -n \
  "${ROOT_DIR}/scripts/validate-v0.12.4.1.5.0.5-guarded-aws-dev-saved-create-plan.sh"

echo "v0.12.4.1.5.0.5 guarded aws-dev saved create-plan offline validation passed; no live command was executed."

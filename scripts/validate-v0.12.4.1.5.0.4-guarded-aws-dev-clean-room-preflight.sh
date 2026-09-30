#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.4-guarded-aws-dev-clean-room-preflight.py" \
  --root "${ROOT_DIR}"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py"

python3 -m json.tool \
  "${ROOT_DIR}/delivery/contracts/v0.12.4.1.5.0.4-guarded-aws-dev-remote-state-clean-room-preflight.json" \
  >/dev/null

python3 -m json.tool \
  "${ROOT_DIR}/delivery/examples/v0.12.4.1.5.0.4-aws-dev-clean-room-preflight-request.example.json" \
  >/dev/null

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.4-guarded-aws-dev-clean-room-preflight.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py" \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.4-aws-dev-clean-room-preflight.py"

bash -n \
  "${ROOT_DIR}/scripts/validate-v0.12.4.1.5.0.4-guarded-aws-dev-clean-room-preflight.sh"

echo "v0.12.4.1.5.0.4 guarded aws-dev clean-room preflight offline validation passed; no live command was executed."

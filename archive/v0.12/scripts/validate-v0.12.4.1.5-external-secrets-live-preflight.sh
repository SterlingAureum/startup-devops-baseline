#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5-external-secrets-live-preflight-contract.py" \
  --root "${ROOT_DIR}"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5-external-secrets-live-preflight.py"

python3 -m json.tool \
  "${ROOT_DIR}/delivery/contracts/v0.12.4.1.5-external-secrets-live-preflight.json" \
  >/dev/null

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5-external-secrets-live-preflight-contract.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.4.1.5-external-secrets-live-preflight.py" \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5-external-secrets-live-preflight.py"

bash -n \
  "${ROOT_DIR}/scripts/validate-v0.12.4.1.5-external-secrets-live-preflight.sh"

echo "v0.12.4.1.5 External Secrets live-preflight offline validation passed; no live command was executed."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py" \
  --root "${ROOT_DIR}"

PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"

python3 -m json.tool \
  "${ROOT_DIR}/delivery/contracts/v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.json" \
  >/dev/null

python3 -m json.tool \
  "${ROOT_DIR}/delivery/examples/v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery-request.example.json" \
  >/dev/null

python3 -m py_compile \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py" \
  "${ROOT_DIR}/scripts/execute-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py" \
  "${ROOT_DIR}/scripts/test-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.py"

bash -n "${ROOT_DIR}/scripts/validate-v0.12.4.1.5.0.6.0.1-aws-dev-post-apply-read-only-recovery.sh"

echo "v0.12.4.1.5.0.6.0.1 aws-dev post-apply read-only recovery passed offline; no live command was executed."

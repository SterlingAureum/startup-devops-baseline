#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-aws-test-secret-preflight.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.2.1.3-test-target-identity.sh"
echo 'v0.11.8.2.2 offline closure/rebuild checks passed; no cloud operations executed.'

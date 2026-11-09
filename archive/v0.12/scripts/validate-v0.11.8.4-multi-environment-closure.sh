#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-observability-evidence-archive.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.3-prod-read-only-qualification.sh"
echo 'v0.11.8.4 offline evidence-management checks passed; no new runtime qualification claimed.'

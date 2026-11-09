#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-local-release-rehearsal.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.9.0-release-rehearsal-design.sh"
echo 'v0.11.9.1 offline checks passed; local live rehearsal remains operator-run.'

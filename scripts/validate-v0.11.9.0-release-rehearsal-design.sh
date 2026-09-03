#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-release-rehearsal-plan.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.4-multi-environment-closure.sh"
echo 'v0.11.9.0 offline design checks passed; runtime unverified, execution not authorized.'

#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-aws-prod-observability.py"
bash "${ROOT_DIR}/scripts/validate-v0.11.8.2.2-test-closure-and-rebuild.sh"
echo 'v0.11.8.3 offline checks passed; real prod acceptance remains deferred to the v0.11 tail.'

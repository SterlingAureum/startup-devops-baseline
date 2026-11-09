#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="v0.12.4.1.5.0.7.1.6.3-shared-dev-test-two-wave-teardown-private-preflight"

PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/check-${PREFIX}.py" --root "${ROOT_DIR}"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-${PREFIX}.py"
bash -n "${ROOT_DIR}/scripts/validate-${PREFIX}.sh"

echo "v0.12.4.1.5.0.7.1.6.3 private teardown preflight passed offline validation; no live command was executed."

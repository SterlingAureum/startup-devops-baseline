#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${ROOT_DIR}/scripts/check-v0.12.4.1.5.0.3-aws-dev-remote-state-clean-room-reconstruction-design.py" \
  --root "${ROOT_DIR}"

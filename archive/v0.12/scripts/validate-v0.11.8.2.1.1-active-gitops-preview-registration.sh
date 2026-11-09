#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${ROOT_DIR}/scripts/validate-active-gitops-revisions.sh"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-active-gitops-preview-registration.py"
echo 'v0.11.8.2.1.1 exact preview registration and negative boundaries passed.'

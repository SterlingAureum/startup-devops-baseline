#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "${ROOT_DIR}/scripts/test-aws-test-feature.py"
"${ROOT_DIR}/scripts/validate-v0.11.8.2.0.1-barman-chart-identity-render-coverage-repair.sh"
"${ROOT_DIR}/scripts/validate-active-gitops-revisions.sh"
echo 'v0.11.8.2.1 offline safety checks passed; live AWS/test acceptance is separate.'

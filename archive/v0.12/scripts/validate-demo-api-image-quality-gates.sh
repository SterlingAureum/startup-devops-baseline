#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh" --structure-only
bash "${ROOT_DIR}/scripts/validate-demo-api-security-supply-chain.sh"
IMAGE_NAME="demo-api-image-quality-gate:runtime" \
  bash "${ROOT_DIR}/scripts/validate-demo-api-workload-security.sh"

echo "Demo-api image quality gates passed without replaying historical repository validators."

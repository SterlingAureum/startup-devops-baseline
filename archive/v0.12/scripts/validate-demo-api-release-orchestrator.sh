#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"${ROOT_DIR}/scripts/validate-demo-api-aws-dev-orchestration.sh"
"${ROOT_DIR}/scripts/validate-demo-api-aws-test-orchestration.sh"
"${ROOT_DIR}/scripts/validate-demo-api-aws-prod-orchestration.sh"
"${ROOT_DIR}/scripts/validate-demo-api-orchestration-recovery.sh"

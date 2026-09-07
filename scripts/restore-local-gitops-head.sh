#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# This wrapper is deliberately post-merge only. deploy-root-app.sh verifies that
# remote HEAD contains clusters/local/platform/Chart.yaml before Kubernetes is
# contacted, so an old main branch cannot receive a Helm-shaped Root source.
TARGET_REVISION=HEAD \
BASELINE_LABEL="Post-merge HEAD baseline" \
  exec "${ROOT_DIR}/scripts/restore-local-gitops-baseline.sh"

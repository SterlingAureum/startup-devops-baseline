#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${ROOT_DIR}/scripts/test-aws-test-qualification-prerequisites.py"
if command -v kustomize >/dev/null 2>&1 || command -v kubectl >/dev/null 2>&1; then
  "${ROOT_DIR}/scripts/check-aws-test-qualification-preview.sh"
  "${ROOT_DIR}/scripts/check-aws-gitops-revision-boundary.sh"
else
  echo 'SKIP: real Kustomize rendering; install kustomize or kubectl and run check-aws-test-qualification-preview.sh.'
fi
echo 'v0.11.8.2.0 prerequisite contract checks passed; no live qualification claimed.'

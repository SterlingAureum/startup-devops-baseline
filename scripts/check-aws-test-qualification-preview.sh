#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
if command -v kustomize >/dev/null 2>&1; then
  render() { kustomize build "$1"; }
elif command -v kubectl >/dev/null 2>&1; then
  render() { kubectl kustomize "$1"; }
else
  echo 'kustomize or kubectl required; no live requests are made.' >&2
  exit 1
fi
render "${ROOT_DIR}/clusters/aws/overlays/test" >"${WORK_DIR}/stable.yaml"
render "${ROOT_DIR}/clusters/aws/overlays/test-feature-qualification" >"${WORK_DIR}/preview.yaml"
python3 "${ROOT_DIR}/scripts/check-aws-test-qualification-preview.py" \
  --stable "${WORK_DIR}/stable.yaml" --preview "${WORK_DIR}/preview.yaml"

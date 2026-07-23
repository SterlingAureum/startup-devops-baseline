#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
TARGET_REVISION="${TARGET_REVISION:-feature/v0.5-karpenter-autoscaling}"
SOURCE_FILE="${SOURCE_FILE:-${ROOT_DIR}/clusters/aws-dev/root-app.yaml}"

command -v kubectl >/dev/null 2>&1 || {
  echo "Required command not found: kubectl" >&2
  exit 1
}

kubectl get namespace argocd >/dev/null

TEMP_FILE="$(mktemp)"
trap 'rm -f "${TEMP_FILE}"' EXIT

sed \
  -e "s#repoURL: .*startup-devops-baseline.git#repoURL: ${REPO_URL}#" \
  -e "s#targetRevision: .*#targetRevision: ${TARGET_REVISION}#" \
  "${SOURCE_FILE}" > "${TEMP_FILE}"

kubectl apply -f "${TEMP_FILE}"

echo "Applied aws-dev root application"
echo "Repository: ${REPO_URL}"
echo "Revision:   ${TARGET_REVISION}"

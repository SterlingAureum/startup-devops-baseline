#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for command in bash git helm; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

bash "${ROOT_DIR}/scripts/validate-demo-api-values-separation.sh"
bash "${ROOT_DIR}/scripts/validate-demo-api-promotion.sh"
bash "${ROOT_DIR}/scripts/validate-demo-api-promotion-governance.sh"

for environment in aws-dev aws-test aws-prod; do
  helm lint "${ROOT_DIR}/apps/demo-api/helm" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/${environment}.yaml" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/${environment}.yaml"
  helm template demo-api "${ROOT_DIR}/apps/demo-api/helm" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/environments/${environment}.yaml" \
    --values "${ROOT_DIR}/apps/demo-api/helm/values/releases/${environment}.yaml" \
    >/dev/null
done

git -C "${ROOT_DIR}" diff --check
echo "Demo-api release quality gates passed without replaying historical repository validators."

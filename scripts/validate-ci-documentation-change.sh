#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${CI_CHANGE_EVENT:?CI_CHANGE_EVENT is required}"
: "${CI_BASE_SHA:?CI_BASE_SHA is required}"
: "${CI_HEAD_SHA:?CI_HEAD_SHA is required}"

python3 "${ROOT_DIR}/scripts/classify-ci-change-impact.py" \
  --root "${ROOT_DIR}" \
  --requested-mode auto \
  --event "${CI_CHANGE_EVENT}" \
  --base "${CI_BASE_SHA}" \
  --head "${CI_HEAD_SHA}" \
  --require-mode documentation

if [[ "${CI_CHANGE_EVENT}" == "pull_request" ]]; then
  git -C "${ROOT_DIR}" diff --check "${CI_BASE_SHA}...${CI_HEAD_SHA}"
else
  git -C "${ROOT_DIR}" diff --check "${CI_BASE_SHA}..${CI_HEAD_SHA}"
fi

bash "${ROOT_DIR}/scripts/validate-v0.12.3.1-ci-change-impact-routing.sh" --structure-only
echo "Documentation-only CI quality gate passed; full historical execution was not required."

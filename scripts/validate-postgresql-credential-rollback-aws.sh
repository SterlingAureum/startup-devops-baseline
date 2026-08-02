#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTIVATION_VALIDATOR="${ROOT_DIR}/scripts/validate-postgresql-credential-activation-aws.sh"

[[ -x "${ACTIVATION_VALIDATOR}" ]] || {
  echo "Required executable is missing: ${ACTIVATION_VALIDATOR}" >&2
  exit 1
}

if [[ "$-" == *x* ]]; then
  echo "Disable shell xtrace before validating credentials." >&2
  exit 1
fi

echo "==> Revalidating the required post-drill Checkpoint 2 state"
"${ACTIVATION_VALIDATOR}"

echo "PostgreSQL credential rotation Checkpoint 3 final-state validation passed."
echo "The forward recovery target is AWSCURRENT, AWSPREVIOUS is inactive, and all credential consumers have converged."

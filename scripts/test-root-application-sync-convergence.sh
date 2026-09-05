#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
mkdir -p "${WORK_DIR}/bin"

cat >"${WORK_DIR}/bin/kubectl" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
output="${*: -1}"
if [[ "${output}" == *'.status.sync.status}'* ]]; then
  count=0
  [ ! -f "${SYNC_COUNT_FILE}" ] || count="$(<"${SYNC_COUNT_FILE}")"
  count=$((count + 1))
  printf '%s' "${count}" >"${SYNC_COUNT_FILE}"
  if [ "${SYNC_MODE}" = transient ] && [ "${count}" -ge 3 ]; then
    printf '%s' Synced
  else
    printf '%s' OutOfSync
  fi
elif [[ "${output}" == *'.status.sync.revision}'* ]]; then
  printf '%s' "${EXPECTED_SHA}"
else
  exit 0
fi
SH
chmod +x "${WORK_DIR}/bin/kubectl"

export PATH="${WORK_DIR}/bin:${PATH}"
export ARGOCD_NAMESPACE=argocd
export WAIT_TIMEOUT_SECONDS=2
export APPLICATION_SYNC_POLL_SECONDS=0
export EXPECTED_SHA=0123456789abcdef0123456789abcdef01234567
export SYNC_COUNT_FILE="${WORK_DIR}/count"

# shellcheck source=scripts/lib/argocd-operation.sh
source "${ROOT_DIR}/scripts/lib/argocd-operation.sh"
validate_argocd_operation_settings

echo '==> Accepting bounded transient Root OutOfSync convergence'
export SYNC_MODE=transient
wait_for_application_sync_identity startup-devops-root "${EXPECTED_SHA}"
[ "$(<"${SYNC_COUNT_FILE}")" -eq 3 ]

echo '==> Rejecting permanent Root OutOfSync'
printf '%s' 0 >"${SYNC_COUNT_FILE}"
export SYNC_MODE=permanent
if wait_for_application_sync_identity startup-devops-root "${EXPECTED_SHA}" \
  >"${WORK_DIR}/permanent.out" 2>"${WORK_DIR}/permanent.err"; then
  echo 'Permanent Root OutOfSync was accepted.' >&2
  exit 1
fi
grep -q 'did not converge to Synced revision' "${WORK_DIR}/permanent.err"

echo 'Root Application sync identity convergence tests passed.'

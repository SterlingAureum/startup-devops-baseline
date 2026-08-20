#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
ROOT_APP_FILE="clusters/local/root-app.yaml"
DEFAULT_REPO_URL="https://github.com/SterlingAureum/startup-devops-baseline.git"
REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"
TARGET_REVISION="${TARGET_REVISION:-HEAD}"
ROOT_SYNC_MODE="${ROOT_SYNC_MODE:-}"

if [ -z "${ROOT_SYNC_MODE}" ]; then
  if [ "${TARGET_REVISION}" = "HEAD" ]; then
    ROOT_SYNC_MODE="automated"
  else
    ROOT_SYNC_MODE="manual"
  fi
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl

if ! [[ "${TARGET_REVISION}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]; then
  echo "ERROR: TARGET_REVISION contains unsupported characters: ${TARGET_REVISION}" >&2
  exit 1
fi

case "${ROOT_SYNC_MODE}" in
  automated|manual) ;;
  *)
    echo "ERROR: ROOT_SYNC_MODE must be automated or manual." >&2
    exit 1
    ;;
esac

if [[ "${REPO_URL}" == *$'\n'* || "${REPO_URL}" == *$'\r'* || "${REPO_URL}" == *'#'* ]]; then
  echo "ERROR: REPO_URL contains unsupported characters." >&2
  exit 1
fi

if [ ! -f "$ROOT_APP_FILE" ]; then
  echo "ERROR: root app file not found: $ROOT_APP_FILE" >&2
  echo "Run this script from the repository root." >&2
  exit 1
fi

kubectl get namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 || {
  echo "ERROR: namespace not found: $ARGOCD_NAMESPACE" >&2
  echo "Run ./scripts/install-argocd.sh first." >&2
  exit 1
}

TMP_FILE="$(mktemp)"
SYNC_MODE_FILE=""
trap 'rm -f "$TMP_FILE" "${SYNC_MODE_FILE:-}"' EXIT

echo "Using repository URL: ${REPO_URL}"
echo "Using target revision: ${TARGET_REVISION}"
echo "Using root sync mode: ${ROOT_SYNC_MODE}"
sed \
  -e "s#^[[:space:]]*repoURL: .*\$#    repoURL: ${REPO_URL}#" \
  -e "s#^[[:space:]]*targetRevision: .*\$#    targetRevision: ${TARGET_REVISION}#" \
  "${ROOT_APP_FILE}" >"${TMP_FILE}"

if [ "${ROOT_SYNC_MODE}" = "manual" ]; then
  SYNC_MODE_FILE="$(mktemp)"
  sed '/^    automated:/,/^    syncOptions:/ {
    /^    syncOptions:/!d
  }' "${TMP_FILE}" >"${SYNC_MODE_FILE}"
  mv "${SYNC_MODE_FILE}" "${TMP_FILE}"
  SYNC_MODE_FILE=""
fi

echo "Applying Argo CD root application..."
kubectl apply -f "${TMP_FILE}"

if [ "${ROOT_SYNC_MODE}" = "manual" ]; then
  kubectl -n "${ARGOCD_NAMESPACE}" patch application "${ROOT_APP_NAME}" \
    --type merge \
    -p '{"spec":{"syncPolicy":{"automated":null}}}' >/dev/null
fi

echo "Root application status:"
kubectl -n "${ARGOCD_NAMESPACE}" get applications.argoproj.io "${ROOT_APP_NAME}" || true

echo "Root app deployment completed."

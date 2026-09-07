#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
ROOT_APP_FILE="clusters/local/root-app.yaml"
DEFAULT_REPO_URL="https://github.com/SterlingAureum/startup-devops-baseline.git"
REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"
TARGET_REVISION="${TARGET_REVISION:-HEAD}"
GIT_TARGET_REVISION="${GIT_TARGET_REVISION:-${TARGET_REVISION}}"
LOCAL_IMAGE_ENABLED="${LOCAL_IMAGE_ENABLED:-false}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-Never}"
APPLICATION_VERSION="${APPLICATION_VERSION:-${IMAGE_TAG}}"
REHEARSAL_FAULT_MODE="${REHEARSAL_FAULT_MODE:-disabled}"
REHEARSAL_FAULT_TOKEN_SHA256="${REHEARSAL_FAULT_TOKEN_SHA256:-}"
ROOT_SYNC_MODE="${ROOT_SYNC_MODE:-}"
REQUIRED_ROOT_SOURCE_PATH="${REQUIRED_ROOT_SOURCE_PATH:-clusters/local/platform/Chart.yaml}"

# shellcheck source=scripts/lib/git-revision.sh
source "${ROOT_DIR}/scripts/lib/git-revision.sh"

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

for command_name in awk git kubectl sed wc; do
  require_cmd "${command_name}"
done

if ! [[ "${TARGET_REVISION}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]; then
  echo "ERROR: TARGET_REVISION contains unsupported characters: ${TARGET_REVISION}" >&2
  exit 1
fi

if ! [[ "${GIT_TARGET_REVISION}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]]; then
  echo "ERROR: GIT_TARGET_REVISION contains unsupported characters: ${GIT_TARGET_REVISION}" >&2
  exit 1
fi

case "${LOCAL_IMAGE_ENABLED}" in
  true|false) ;;
  *)
    echo "ERROR: LOCAL_IMAGE_ENABLED must be true or false." >&2
    exit 1
    ;;
esac

if ! [[ "${IMAGE_REPOSITORY}" =~ ^[A-Za-z0-9][A-Za-z0-9._/:@-]*$ ]]; then
  echo "ERROR: IMAGE_REPOSITORY contains unsupported characters: ${IMAGE_REPOSITORY}" >&2
  exit 1
fi

if [ -n "${IMAGE_TAG}" ] && ! [[ "${IMAGE_TAG}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "ERROR: IMAGE_TAG contains unsupported characters: ${IMAGE_TAG}" >&2
  exit 1
fi

case "${IMAGE_PULL_POLICY}" in
  Always|IfNotPresent|Never) ;;
  *)
    echo "ERROR: IMAGE_PULL_POLICY must be Always, IfNotPresent, or Never." >&2
    exit 1
    ;;
esac

if [ -n "${APPLICATION_VERSION}" ] && ! [[ "${APPLICATION_VERSION}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "ERROR: APPLICATION_VERSION contains unsupported characters: ${APPLICATION_VERSION}" >&2
  exit 1
fi

if [ "${LOCAL_IMAGE_ENABLED}" = "true" ] && { [ -z "${IMAGE_TAG}" ] || [ -z "${APPLICATION_VERSION}" ]; }; then
  echo "ERROR: IMAGE_TAG and APPLICATION_VERSION are required when LOCAL_IMAGE_ENABLED=true." >&2
  exit 1
fi

case "${REHEARSAL_FAULT_MODE}" in
  disabled)
    [ -z "${REHEARSAL_FAULT_TOKEN_SHA256}" ] || {
      echo "ERROR: disabled rehearsal fault mode must not retain a token digest." >&2
      exit 1
    }
    ;;
  availability-503)
    [ "${LOCAL_IMAGE_ENABLED}" = "true" ] || {
      echo "ERROR: rehearsal fault mode is supported only for an explicit local image." >&2
      exit 1
    }
    [[ "${REHEARSAL_FAULT_TOKEN_SHA256}" =~ ^[0-9a-f]{64}$ ]] || {
      echo "ERROR: enabled rehearsal fault mode requires a lowercase SHA-256 token digest." >&2
      exit 1
    }
    ;;
  *)
    echo "ERROR: REHEARSAL_FAULT_MODE must be disabled or availability-503." >&2
    exit 1
    ;;
esac

case "${ROOT_SYNC_MODE}" in
  automated|manual) ;;
  *)
    echo "ERROR: ROOT_SYNC_MODE must be automated or manual." >&2
    exit 1
    ;;
esac

if ! [[ "${REPO_URL}" =~ ^https?://[A-Za-z0-9._~:/-]+$ ]]; then
  echo "ERROR: REPO_URL contains unsupported characters." >&2
  exit 1
fi

if [ ! -f "$ROOT_APP_FILE" ]; then
  echo "ERROR: root app file not found: $ROOT_APP_FILE" >&2
  echo "Run this script from the repository root." >&2
  exit 1
fi

resolved_root_revision="$(resolve_remote_git_revision "${REPO_URL}" "${TARGET_REVISION}")"
assert_remote_git_revision_contains_path \
  "${REPO_URL}" \
  "${TARGET_REVISION}" \
  "${resolved_root_revision}" \
  "${REQUIRED_ROOT_SOURCE_PATH}"

kubectl get namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 || {
  echo "ERROR: namespace not found: $ARGOCD_NAMESPACE" >&2
  echo "Run ./scripts/install-argocd.sh first." >&2
  exit 1
}

TMP_FILE="$(mktemp)"
SYNC_MODE_FILE=""
PARAMETER_FILE=""
trap 'rm -f "$TMP_FILE" "${SYNC_MODE_FILE:-}" "${PARAMETER_FILE:-}"' EXIT

echo "Using repository URL: ${REPO_URL}"
echo "Using root target revision: ${TARGET_REVISION}"
echo "Resolved root source commit: ${resolved_root_revision}"
echo "Using same-repository child revision: ${GIT_TARGET_REVISION}"
echo "Using local image override: ${LOCAL_IMAGE_ENABLED}"
echo "Using root sync mode: ${ROOT_SYNC_MODE}"
sed \
  -e "s#^[[:space:]]*repoURL: .*\$#    repoURL: ${REPO_URL}#" \
  -e "s#^[[:space:]]*targetRevision: .*\$#    targetRevision: ${TARGET_REVISION}#" \
  "${ROOT_APP_FILE}" >"${TMP_FILE}"

PARAMETER_FILE="$(mktemp)"
awk \
  -v repo_url="${REPO_URL}" \
  -v git_revision="${GIT_TARGET_REVISION}" \
  -v local_image_enabled="${LOCAL_IMAGE_ENABLED}" \
  -v image_repository="${IMAGE_REPOSITORY}" \
  -v image_tag="${IMAGE_TAG}" \
  -v image_pull_policy="${IMAGE_PULL_POLICY}" \
  -v application_version="${APPLICATION_VERSION}" \
  -v rehearsal_fault_mode="${REHEARSAL_FAULT_MODE}" \
  -v rehearsal_fault_token_sha256="${REHEARSAL_FAULT_TOKEN_SHA256}" '
  $0 == "        - name: git.repoURL" {
    print
    getline
    print "          value: \"" repo_url "\""
    next
  }
  $0 == "        - name: git.targetRevision" {
    print
    getline
    print "          value: \"" git_revision "\""
    next
  }
  $0 == "        - name: demoApi.localImage.enabled" {
    print
    getline
    print "          value: \"" local_image_enabled "\""
    next
  }
  $0 == "        - name: demoApi.localImage.repository" {
    print
    getline
    print "          value: \"" image_repository "\""
    next
  }
  $0 == "        - name: demoApi.localImage.tag" {
    print
    getline
    print "          value: \"" image_tag "\""
    next
  }
  $0 == "        - name: demoApi.localImage.pullPolicy" {
    print
    getline
    print "          value: \"" image_pull_policy "\""
    next
  }
  $0 == "        - name: demoApi.localImage.applicationVersion" {
    print
    getline
    print "          value: \"" application_version "\""
    next
  }
  $0 == "        - name: demoApi.rehearsalFault.mode" {
    print
    getline
    print "          value: \"" rehearsal_fault_mode "\""
    next
  }
  $0 == "        - name: demoApi.rehearsalFault.tokenSha256" {
    print
    getline
    print "          value: \"" rehearsal_fault_token_sha256 "\""
    next
  }
  { print }
' "${TMP_FILE}" >"${PARAMETER_FILE}"
mv "${PARAMETER_FILE}" "${TMP_FILE}"
PARAMETER_FILE=""

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

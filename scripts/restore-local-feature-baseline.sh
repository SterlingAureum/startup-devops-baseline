#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
TARGET_REVISION="${TARGET_REVISION:-}"

# shellcheck source=scripts/lib/git-revision.sh
source "${ROOT_DIR}/scripts/lib/git-revision.sh"

for command_name in awk git wc; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
done

if [ -z "${TARGET_REVISION}" ]; then
  echo "ERROR: TARGET_REVISION is required for pre-merge feature baseline restoration." >&2
  echo "Example: TARGET_REVISION=feature/example $0" >&2
  exit 1
fi

case "${TARGET_REVISION}" in
  HEAD|main|master)
    echo "ERROR: use restore-local-gitops-head.sh only after the platform Helm Chart has reached remote HEAD." >&2
    exit 1
    ;;
esac

cd "${ROOT_DIR}"
resolved_target_revision="$(resolve_remote_git_revision "${REPO_URL}" "${TARGET_REVISION}")"
local_commit="$(git rev-parse HEAD)"

if [ "${local_commit,,}" != "${resolved_target_revision}" ]; then
  echo "ERROR: local checkout does not match the remote feature commit." >&2
  echo "Local commit:  ${local_commit,,}" >&2
  echo "Remote commit: ${resolved_target_revision}" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: tracked repository changes must be committed before feature baseline restoration." >&2
  exit 1
fi

baseline_image_tag="$(awk '
  /^image:/ { in_image=1; next }
  in_image && /^[^[:space:]]/ { exit }
  in_image && $1 == "tag:" { gsub(/\"/, "", $2); print $2; exit }
' "${ROOT_DIR}/apps/demo-api/helm/values.yaml")"
if [ "${baseline_image_tag}" = "sha-3e50802" ]; then
  echo "ERROR: baseline image ${baseline_image_tag} was rejected by live revision 69." >&2
  echo "Its Candidate target was up, but release-scoped request metrics remained empty." >&2
  echo "Publish and declare a telemetry-compatible immutable image before restoration." >&2
  echo "No Kubernetes restoration operation was started." >&2
  exit 1
fi

echo "Requested feature revision: ${TARGET_REVISION}"
echo "Resolved feature commit:   ${resolved_target_revision}"

TARGET_REVISION="${resolved_target_revision}" \
BASELINE_LABEL="Pre-merge feature baseline" \
REPO_URL="${REPO_URL}" \
  exec "${ROOT_DIR}/scripts/restore-local-gitops-baseline.sh"

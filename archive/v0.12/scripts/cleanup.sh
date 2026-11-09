#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kind

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "Deleting kind cluster: $CLUSTER_NAME"
  kind delete cluster --name "$CLUSTER_NAME"
else
  echo "kind cluster does not exist: $CLUSTER_NAME"
fi

echo "Cleanup completed."

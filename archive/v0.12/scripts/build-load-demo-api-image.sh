#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline}"
IMAGE_NAME="${IMAGE_NAME:-startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-0.1.0}"
APP_DIR="apps/demo-api"
FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd kind

if [ ! -f "${APP_DIR}/Dockerfile" ]; then
  echo "ERROR: Dockerfile not found: ${APP_DIR}/Dockerfile" >&2
  echo "Run this script from the repository root." >&2
  exit 1
fi

if ! kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  echo "ERROR: kind cluster not found: ${CLUSTER_NAME}" >&2
  echo "Run ./scripts/bootstrap-kind.sh first, or set CLUSTER_NAME to the correct cluster." >&2
  exit 1
fi

echo "Building demo-api image: ${FULL_IMAGE}"
docker build -t "${FULL_IMAGE}" "${APP_DIR}"

echo "Loading image into kind cluster: ${CLUSTER_NAME}"
kind load docker-image "${FULL_IMAGE}" --name "${CLUSTER_NAME}"

echo "Image loaded successfully: ${FULL_IMAGE}"

#!/usr/bin/env bash
set -euo pipefail

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"

if [ -z "$IMAGE_TAG" ]; then
  echo "ERROR: IMAGE_TAG is required." >&2
  echo "Example:" >&2
  echo "  IMAGE_TAG=sha-82aa684 ./scripts/check-ghcr-demo-api-image.sh" >&2
  exit 1
fi

FULL_IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"

echo "Checking image manifest: ${FULL_IMAGE}"
docker manifest inspect "${FULL_IMAGE}" >/dev/null

echo "Image exists: ${FULL_IMAGE}"

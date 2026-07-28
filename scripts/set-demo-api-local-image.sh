#!/usr/bin/env bash
set -euo pipefail

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-startup-devops-baseline/demo-api}" \
IMAGE_TAG="${IMAGE_TAG:-0.1.1}" \
IMAGE_DIGEST="" \
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-Never}" \
APP_VERSION="${APP_VERSION:-${IMAGE_TAG:-0.1.1}}" \
REQUIRE_IMAGE_DIGEST=false \
  ./scripts/set-demo-api-image.sh

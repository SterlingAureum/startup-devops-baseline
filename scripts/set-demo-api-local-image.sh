#!/usr/bin/env bash
set -euo pipefail

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-startup-devops-baseline/demo-api}" \
IMAGE_TAG="${IMAGE_TAG:-0.1.1}" \
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-Never}" \
APP_VERSION="${APP_VERSION:-${IMAGE_TAG:-0.1.1}}" \
  ./scripts/set-demo-api-image.sh

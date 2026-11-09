#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline}"
IMAGE_NAME="${IMAGE_NAME:-startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-0.1.0}"

FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building image: ${FULL_IMAGE}"
docker build -t "${FULL_IMAGE}" apps/demo-api

echo "Loading image into kind cluster: ${CLUSTER_NAME}"
kind load docker-image "${FULL_IMAGE}" --name "${CLUSTER_NAME}"

echo "Restarting demo-api deployment if it exists"
kubectl rollout restart deployment/demo-api -n startup-apps || true

echo "Done."
echo "Image loaded: ${FULL_IMAGE}"

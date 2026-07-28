#!/usr/bin/env bash
set -euo pipefail

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE_DIGEST="${IMAGE_DIGEST:-}"

if [[ -z "${IMAGE_TAG}" || -z "${IMAGE_DIGEST}" ]]; then
  echo "ERROR: IMAGE_TAG and IMAGE_DIGEST are required." >&2
  echo "Example:" >&2
  echo "  IMAGE_TAG=sha-82aa684 \\" >&2
  echo "  IMAGE_DIGEST=sha256:<64-hex-characters> \\" >&2
  echo "    ./scripts/check-ghcr-demo-api-image.sh" >&2
  exit 1
fi

if [[ ! "${IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR: IMAGE_DIGEST must be a lowercase sha256 digest." >&2
  exit 1
fi

TAGGED_IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
DIGEST_IMAGE="${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"

echo "Checking tagged image: ${TAGGED_IMAGE}"
TAG_DIGEST="$(
  docker buildx imagetools inspect "${TAGGED_IMAGE}" |
    awk '$1 == "Digest:" { print $2; exit }'
)"

if [[ -z "${TAG_DIGEST}" ]]; then
  echo "Could not resolve the digest for ${TAGGED_IMAGE}." >&2
  exit 1
fi

if [[ "${TAG_DIGEST}" != "${IMAGE_DIGEST}" ]]; then
  echo "The tag does not resolve to the expected digest." >&2
  echo "Expected: ${IMAGE_DIGEST}" >&2
  echo "Observed: ${TAG_DIGEST}" >&2
  exit 1
fi

docker buildx imagetools inspect "${DIGEST_IMAGE}" >/dev/null

echo "Image identity verified:"
echo "  tag=${IMAGE_TAG}"
echo "  digest=${IMAGE_DIGEST}"

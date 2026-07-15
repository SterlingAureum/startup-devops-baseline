#!/usr/bin/env bash
set -euo pipefail

VALUES_FILE="${VALUES_FILE:-apps/demo-api/helm/values.yaml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-ghcr.io/sterlingaureum/startup-devops-baseline/demo-api}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-IfNotPresent}"
APP_VERSION="${APP_VERSION:-$IMAGE_TAG}"

if [ -z "$IMAGE_TAG" ]; then
  echo "ERROR: IMAGE_TAG is required." >&2
  echo "Example:" >&2
  echo "  IMAGE_TAG=sha-82aa684 ./scripts/set-demo-api-image.sh" >&2
  exit 1
fi

if [ ! -f "$VALUES_FILE" ]; then
  echo "ERROR: values file not found: $VALUES_FILE" >&2
  echo "Run this script from the repository root." >&2
  exit 1
fi

python3 - "$VALUES_FILE" "$IMAGE_REPOSITORY" "$IMAGE_TAG" "$IMAGE_PULL_POLICY" "$APP_VERSION" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
repo = sys.argv[2]
tag = sys.argv[3]
pull_policy = sys.argv[4]
app_version = sys.argv[5]

lines = path.read_text().splitlines()
out = []
section = None
for line in lines:
    stripped = line.strip()
    if line and not line.startswith(" ") and stripped.endswith(":"):
        section = stripped[:-1]

    if section == "image":
        if stripped.startswith("repository:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}repository: {repo}')
            continue
        if stripped.startswith("tag:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}tag: "{tag}"')
            continue
        if stripped.startswith("pullPolicy:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f'{indent}pullPolicy: {pull_policy}')
            continue

    if section == "env" and stripped.startswith("APP_VERSION:"):
        indent = line[: len(line) - len(line.lstrip())]
        out.append(f'{indent}APP_VERSION: "{app_version}"')
        continue

    out.append(line)

path.write_text("\n".join(out) + "\n")
PY

echo "Updated ${VALUES_FILE}:"
echo "  image.repository=${IMAGE_REPOSITORY}"
echo "  image.tag=${IMAGE_TAG}"
echo "  image.pullPolicy=${IMAGE_PULL_POLICY}"
echo "  env.APP_VERSION=${APP_VERSION}"
echo
echo "Next:"
echo "  helm lint apps/demo-api/helm"
echo "  git add ${VALUES_FILE}"
echo "  git commit -m \"release: update demo-api image to ${IMAGE_TAG}\""
echo "  git push"

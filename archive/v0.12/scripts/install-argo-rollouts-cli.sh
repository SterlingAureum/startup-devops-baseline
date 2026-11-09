#!/usr/bin/env bash
set -euo pipefail

VERSION="${ARGO_ROLLOUTS_VERSION:-v1.9.0}"
OS="${OS:-linux}"
ARCH="${ARCH:-amd64}"
BIN="kubectl-argo-rollouts"
URL="https://github.com/argoproj/argo-rollouts/releases/download/${VERSION}/kubectl-argo-rollouts-${OS}-${ARCH}"

echo "Installing ${BIN} ${VERSION} for ${OS}/${ARCH}"
curl -L -o "${BIN}" "${URL}"
chmod +x "${BIN}"
sudo mv "${BIN}" /usr/local/bin/${BIN}

kubectl argo rollouts version

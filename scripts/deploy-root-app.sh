#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_FILE="clusters/local/root-app.yaml"
DEFAULT_REPO_URL="https://github.com/SterlingAureum/startup-devops-baseline.git"
REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl

if [ ! -f "$ROOT_APP_FILE" ]; then
  echo "ERROR: root app file not found: $ROOT_APP_FILE" >&2
  echo "Run this script from the repository root." >&2
  exit 1
fi

kubectl get namespace "$ARGOCD_NAMESPACE" >/dev/null 2>&1 || {
  echo "ERROR: namespace not found: $ARGOCD_NAMESPACE" >&2
  echo "Run ./scripts/install-argocd.sh first." >&2
  exit 1
}

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

if [ -n "$REPO_URL" ]; then
  echo "Using repository URL: $REPO_URL"
  sed "s#https://github.com/YOUR_GITHUB_USERNAME/startup-devops-baseline.git#$REPO_URL#g" "$ROOT_APP_FILE" > "$TMP_FILE"
else
  echo "WARNING: REPO_URL is not set. Applying root app with placeholder repo URL."
  echo "         Sync will not work until the repoURL is updated."
  cp "$ROOT_APP_FILE" "$TMP_FILE"
fi

echo "Applying Argo CD root application..."
kubectl apply -f "$TMP_FILE"

echo "Root application status:"
kubectl -n "$ARGOCD_NAMESPACE" get applications.argoproj.io startup-devops-root || true

echo "Root app deployment completed."

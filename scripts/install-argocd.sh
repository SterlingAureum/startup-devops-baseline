#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ARGOCD_VERSION="${ARGOCD_VERSION:-v3.3.12}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl

kubectl create namespace "$ARGOCD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

if [ "$ARGOCD_VERSION" = "stable" ]; then
  INSTALL_URL="https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"
else
  INSTALL_URL="https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"
fi

echo "Installing Argo CD into namespace: $ARGOCD_NAMESPACE"
echo "Install manifest: $INSTALL_URL"
kubectl apply --server-side --force-conflicts \
	-n "$ARGOCD_NAMESPACE" \
	-f "$INSTALL_URL"

echo "Waiting for Argo CD deployments..."
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-repo-server --timeout=180s
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-server --timeout=180s
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-applicationset-controller --timeout=180s

# argocd-dex-server may not be required for every local scenario, but it is part of the standard install.
if kubectl -n "$ARGOCD_NAMESPACE" get deployment argocd-dex-server >/dev/null 2>&1; then
  kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-dex-server --timeout=180s
fi

echo "Argo CD pods:"
kubectl -n "$ARGOCD_NAMESPACE" get pods

echo "Argo CD installation completed."
echo "To access UI: kubectl -n $ARGOCD_NAMESPACE port-forward svc/argocd-server 8080:443"

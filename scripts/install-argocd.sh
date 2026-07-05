#!/usr/bin/env bash
set -euo pipefail

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ARGOCD_INSTALL_MANIFEST="${ARGOCD_INSTALL_MANIFEST:-https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300s}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd kubectl

kubectl create namespace "$ARGOCD_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

echo "Installing Argo CD into namespace: ${ARGOCD_NAMESPACE}"
echo "Install manifest: ${ARGOCD_INSTALL_MANIFEST}"
echo "Using server-side apply to avoid large CRD annotation limits."

kubectl apply --server-side --force-conflicts \
  -n "$ARGOCD_NAMESPACE" \
  -f "$ARGOCD_INSTALL_MANIFEST"

echo "Waiting for Argo CD workloads to be available..."
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-redis --timeout="$WAIT_TIMEOUT"
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-repo-server --timeout="$WAIT_TIMEOUT"
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-server --timeout="$WAIT_TIMEOUT"
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-applicationset-controller --timeout="$WAIT_TIMEOUT" || true
kubectl -n "$ARGOCD_NAMESPACE" rollout status deployment/argocd-dex-server --timeout="$WAIT_TIMEOUT" || true
kubectl -n "$ARGOCD_NAMESPACE" rollout status statefulset/argocd-application-controller --timeout="$WAIT_TIMEOUT"

echo "Argo CD pods:"
kubectl get pods -n "$ARGOCD_NAMESPACE"

echo "Argo CD installation completed."
echo "To access the UI locally, run:"
echo "  kubectl -n ${ARGOCD_NAMESPACE} port-forward svc/argocd-server 8080:443"

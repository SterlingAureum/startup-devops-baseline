#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline}"
KIND_CONTEXT="kind-${CLUSTER_NAME}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd kubectl
require_cmd kind

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running or current user cannot access Docker." >&2
  exit 1
fi

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster already exists: $CLUSTER_NAME"
else
  echo "Creating kind cluster: $CLUSTER_NAME"
  cat <<EOF | kind create cluster --name "$CLUSTER_NAME" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
EOF
fi

echo "Using kubectl context: $KIND_CONTEXT"
kubectl config use-context "$KIND_CONTEXT" >/dev/null

echo "Waiting for node readiness..."
kubectl wait --for=condition=Ready nodes --all --timeout=120s

echo "Cluster nodes:"
kubectl get nodes -o wide

echo "kind bootstrap completed."

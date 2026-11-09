#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline}"
KIND_NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.30.0}"
KIND_CONFIG_FILE="${KIND_CONFIG_FILE:-}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-180s}"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

wait_for_pods() {
  local namespace="$1"
  local selector="$2"
  local description="$3"

  echo "Waiting for ${description} to be ready..."
  if ! kubectl wait --for=condition=Ready pod -n "$namespace" -l "$selector" --timeout="$WAIT_TIMEOUT"; then
    echo "ERROR: ${description} did not become ready within ${WAIT_TIMEOUT}." >&2
    echo "Current pods in namespace ${namespace}:" >&2
    kubectl get pods -n "$namespace" -o wide >&2 || true
    echo "Recent kube-proxy logs, if available:" >&2
    kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=80 >&2 || true
    exit 1
  fi
}

require_cmd kind
require_cmd kubectl
require_cmd docker

OPEN_FILES_LIMIT="$(ulimit -n)"
echo "Current open files limit: ${OPEN_FILES_LIMIT}"
if [ "$OPEN_FILES_LIMIT" != "unlimited" ] && [ "$OPEN_FILES_LIMIT" -lt 65535 ]; then
  echo "WARNING: open files limit is lower than 65535."
  echo "         If kube-proxy fails with 'too many open files', try: ulimit -n 65535"
fi

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
  echo "kind cluster already exists: ${CLUSTER_NAME}"
else
  echo "Creating kind cluster: ${CLUSTER_NAME}"
  echo "Using kind node image: ${KIND_NODE_IMAGE}"

  TMP_CONFIG="$(mktemp)"
  trap 'rm -f "$TMP_CONFIG"' EXIT

  if [ -n "$KIND_CONFIG_FILE" ]; then
    if [ ! -f "$KIND_CONFIG_FILE" ]; then
      echo "ERROR: KIND_CONFIG_FILE not found: ${KIND_CONFIG_FILE}" >&2
      exit 1
    fi
    kind create cluster --name "$CLUSTER_NAME" --config "$KIND_CONFIG_FILE"
  else
    cat > "$TMP_CONFIG" <<KIND_CONFIG
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: ${KIND_NODE_IMAGE}
    extraPortMappings:
      - containerPort: 80
        hostPort: 80
        protocol: TCP
      - containerPort: 443
        hostPort: 443
        protocol: TCP
KIND_CONFIG
    kind create cluster --name "$CLUSTER_NAME" --config "$TMP_CONFIG"
  fi
fi

echo "Switching kubectl context..."
kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null
kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null

echo "Waiting for node readiness..."
kubectl wait --for=condition=Ready node --all --timeout="$WAIT_TIMEOUT"

echo "Checking kube-system core components..."
wait_for_pods kube-system "k8s-app=kube-proxy" "kube-proxy"
wait_for_pods kube-system "k8s-app=kube-dns" "CoreDNS"
wait_for_pods kube-system "app=kindnet" "kindnet"

echo "Cluster status:"
kubectl get nodes -o wide
kubectl get pods -n kube-system

echo "kind cluster bootstrap completed."

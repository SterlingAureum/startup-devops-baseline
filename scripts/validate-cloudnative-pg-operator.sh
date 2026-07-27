#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"
APPLICATION_NAME="cloudnative-pg"
OPERATOR_NAMESPACE="cnpg-system"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Checking CloudNativePG Argo CD Application"
kubectl get application "${APPLICATION_NAME}" -n argocd >/dev/null
kubectl wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/${APPLICATION_NAME}" \
  --namespace argocd \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${APPLICATION_NAME}" \
  --namespace argocd \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Checking CloudNativePG CRDs"
for crd in \
  clusters.postgresql.cnpg.io \
  backups.postgresql.cnpg.io \
  scheduledbackups.postgresql.cnpg.io \
  poolers.postgresql.cnpg.io; do
  kubectl wait \
    --for=condition=Established \
    "crd/${crd}" \
    --timeout="${WAIT_TIMEOUT}"
done

echo "==> Checking CloudNativePG admission webhooks"
kubectl get mutatingwebhookconfiguration \
  cnpg-mutating-webhook-configuration >/dev/null
kubectl get validatingwebhookconfiguration \
  cnpg-validating-webhook-configuration >/dev/null

echo "==> Waiting for CloudNativePG operator"
mapfile -t OPERATOR_DEPLOYMENTS < <(
  kubectl get deployments \
    --namespace "${OPERATOR_NAMESPACE}" \
    --selector app.kubernetes.io/name=cloudnative-pg \
    --output name
)

if (( ${#OPERATOR_DEPLOYMENTS[@]} != 1 )); then
  echo "Expected exactly one CloudNativePG operator Deployment, found ${#OPERATOR_DEPLOYMENTS[@]}." >&2
  exit 1
fi

OPERATOR_DEPLOYMENT="${OPERATOR_DEPLOYMENTS[0]#deployment.apps/}"
kubectl rollout status "deployment/${OPERATOR_DEPLOYMENT}" \
  --namespace "${OPERATOR_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

DESIRED_REPLICAS="$(
  kubectl get deployment "${OPERATOR_DEPLOYMENT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --output jsonpath='{.spec.replicas}'
)"
AVAILABLE_REPLICAS="$(
  kubectl get deployment "${OPERATOR_DEPLOYMENT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --output jsonpath='{.status.availableReplicas}'
)"

if [[ "${DESIRED_REPLICAS}" != "2" || "${AVAILABLE_REPLICAS}" != "2" ]]; then
  echo "Expected 2 desired and available operator replicas; found desired=${DESIRED_REPLICAS:-0}, available=${AVAILABLE_REPLICAS:-0}." >&2
  exit 1
fi

echo "==> Checking operator placement and anti-affinity"
mapfile -t OPERATOR_NODES < <(
  kubectl get pods \
    --namespace "${OPERATOR_NAMESPACE}" \
    --selector app.kubernetes.io/name=cloudnative-pg \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}'
)

if (( ${#OPERATOR_NODES[@]} != 2 )); then
  echo "Expected 2 running CloudNativePG operator pods, found ${#OPERATOR_NODES[@]}." >&2
  exit 1
fi

declare -A UNIQUE_NODES=()
for node_name in "${OPERATOR_NODES[@]}"; do
  workload_label="$(
    kubectl get node "${node_name}" \
      --output jsonpath='{.metadata.labels.workload}'
  )"
  nodepool_label="$(
    kubectl get node "${node_name}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}'
  )"

  if [[ "${workload_label}" != "system" || -n "${nodepool_label}" ]]; then
    echo "CloudNativePG operator pod is not on a stable system node: ${node_name}." >&2
    exit 1
  fi
  UNIQUE_NODES["${node_name}"]=1
done

if (( ${#UNIQUE_NODES[@]} != 2 )); then
  echo "CloudNativePG operator replicas are not spread across two nodes." >&2
  exit 1
fi

echo "==> Checking Argo CD Sync and Health"
SYNC_STATUS="$(
  kubectl get application "${APPLICATION_NAME}" -n argocd \
    --output jsonpath='{.status.sync.status}'
)"
HEALTH_STATUS="$(
  kubectl get application "${APPLICATION_NAME}" -n argocd \
    --output jsonpath='{.status.health.status}'
)"

if [[ "${SYNC_STATUS}" != "Synced" || "${HEALTH_STATUS}" != "Healthy" ]]; then
  echo "CloudNativePG Application is not ready: sync=${SYNC_STATUS:-Unknown}, health=${HEALTH_STATUS:-Unknown}." >&2
  exit 1
fi

echo "CloudNativePG operator validation passed."

#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
SOURCE_CLUSTER="${SOURCE_CLUSTER:-postgresql-baseline}"
SOURCE_OBJECT_STORE="${SOURCE_OBJECT_STORE:-postgresql-baseline-backup}"
SHARED_SERVICE_ACCOUNT="${SHARED_SERVICE_ACCOUNT:-postgresql-baseline}"
RECOVERY_NODE_POOL="${RECOVERY_NODE_POOL:-database-recovery-ondemand}"
LATEST_CLUSTER="${LATEST_CLUSTER:-postgresql-recovery-latest}"
PITR_CLUSTER="${PITR_CLUSTER:-postgresql-recovery-pitr}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}"

echo "==> Checking source PostgreSQL recovery prerequisites"
kubectl wait \
  --for=condition=Ready \
  "cluster/${SOURCE_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'=True \
  "cluster/${SOURCE_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

READY_INSTANCES="$(
  kubectl get cluster "${SOURCE_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.readyInstances}'
)"
if [[ "${READY_INSTANCES}" != "3" ]]; then
  echo "Expected three ready source PostgreSQL instances." >&2
  exit 1
fi

kubectl get objectstore "${SOURCE_OBJECT_STORE}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null
kubectl get serviceaccount "${SHARED_SERVICE_ACCOUNT}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null

COMPLETED_BACKUPS="$(
  kubectl get backup \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{range .items[?(@.status.phase=="completed")]}{.metadata.name}{"\n"}{end}'
)"
if [[ -z "${COMPLETED_BACKUPS}" ]]; then
  echo "No completed base backup is available for recovery." >&2
  exit 1
fi

echo "==> Checking isolated recovery NodePool"
kubectl wait \
  --for=condition=Ready \
  "nodepool/${RECOVERY_NODE_POOL}" \
  --timeout=10m

RECOVERY_NODE_POOL_CONTRACT="$(
  kubectl get nodepool "${RECOVERY_NODE_POOL}" \
    --output jsonpath='{.spec.template.metadata.labels.workload}:{.spec.template.metadata.labels.capacity-tier}:{.spec.template.spec.nodeClassRef.name}:{.spec.template.spec.taints[0].key}={.spec.template.spec.taints[0].value}:{.spec.template.spec.taints[0].effect}:{.spec.limits.cpu}:{.spec.limits.memory}:{.spec.limits.nodes}:{.spec.disruption.consolidationPolicy}:{.spec.disruption.consolidateAfter}'
)"
if [[ "${RECOVERY_NODE_POOL_CONTRACT}" != \
      "database-recovery:recovery:database:dedicated=database-recovery:NoSchedule:2:8Gi:1:WhenEmpty:1m" ]]; then
  echo "The recovery NodePool does not match the v0.6.4 contract." >&2
  exit 1
fi

RECOVERY_REQUIREMENTS="$(
  kubectl get nodepool "${RECOVERY_NODE_POOL}" \
    --output jsonpath='{range .spec.template.spec.requirements[*]}{.key}={.values[*]}{"\n"}{end}'
)"
for requirement in \
  "karpenter.sh/capacity-type=on-demand" \
  "topology.kubernetes.io/zone=us-east-1a us-east-1b" \
  "karpenter.k8s.aws/instance-cpu=2"; do
  if ! grep -qx "${requirement}" <<<"${RECOVERY_REQUIREMENTS}"; then
    echo "The recovery NodePool is missing ${requirement}." >&2
    exit 1
  fi
done

echo "==> Confirming recovery resources were cleaned up"
for recovery_cluster in "${LATEST_CLUSTER}" "${PITR_CLUSTER}"; do
  if kubectl get cluster "${recovery_cluster}" \
    --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
    echo "Recovery Cluster ${recovery_cluster} still exists." >&2
    exit 1
  fi
  if [[ -n "$(
    kubectl get pvc \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${recovery_cluster}" \
      --output name
  )" ]]; then
    echo "Recovery PVCs for ${recovery_cluster} still exist." >&2
    exit 1
  fi
done

if [[ -n "$(
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${RECOVERY_NODE_POOL}" \
    --output name
)" ]] || [[ -n "$(
  kubectl get nodes \
    --selector "karpenter.sh/nodepool=${RECOVERY_NODE_POOL}" \
    --output name
)" ]]; then
  echo "Temporary recovery capacity still exists." >&2
  exit 1
fi

echo "CloudNativePG recovery and PITR readiness and cleanup validation passed."

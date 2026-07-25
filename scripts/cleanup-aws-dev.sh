#!/usr/bin/env bash
set -euo pipefail

WAIT_TIMEOUT="${WAIT_TIMEOUT:-15m}"
ROOT_APP="startup-devops-aws-dev-root"
POSTGRES_APP="postgresql-baseline"
POSTGRES_CLUSTER="postgresql-baseline"
POSTGRES_NAMESPACE="data-platform"
POSTGRES_STORAGE_CLASS="gp3-cnpg"

command -v kubectl >/dev/null 2>&1 || {
  echo "Required command not found: kubectl" >&2
  exit 1
}

cat <<EOF
WARNING: this cleanup deletes the v0.6.1 PostgreSQL Cluster and its data PVC.

The gp3 StorageClass uses reclaim policy Delete, so the backing EBS volume is
also deleted. v0.6.1 has no backup or restore path.

Type 'delete-data' to continue:
EOF

if [[ "${CONFIRM_AWS_DEV_CLEANUP:-}" == "delete-data" ]]; then
  confirmation="delete-data"
else
  read -r confirmation
fi

if [[ "${confirmation}" != "delete-data" ]]; then
  echo "Cleanup cancelled."
  exit 0
fi

if kubectl get application "${ROOT_APP}" -n argocd >/dev/null 2>&1; then
  echo "==> Suspending root Application automation"
  kubectl patch application "${ROOT_APP}" \
    --namespace argocd \
    --type merge \
    --patch '{"spec":{"syncPolicy":{"automated":null}}}'
else
  echo "==> Root application is already absent"
fi

if kubectl get application "${POSTGRES_APP}" -n argocd >/dev/null 2>&1; then
  echo "==> Suspending PostgreSQL Application automation"
  kubectl patch application "${POSTGRES_APP}" \
    --namespace argocd \
    --type merge \
    --patch '{"spec":{"syncPolicy":{"automated":null}}}'
fi

if kubectl get cluster "${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
  echo "==> Deleting PostgreSQL Cluster before EKS teardown"
  kubectl delete cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --wait=true \
    --timeout="${WAIT_TIMEOUT}"
fi

kubectl delete pvc \
  --namespace "${POSTGRES_NAMESPACE}" \
  --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}" 2>/dev/null || true
kubectl delete namespace "${POSTGRES_NAMESPACE}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"
kubectl delete storageclass "${POSTGRES_STORAGE_CLASS}" \
  --ignore-not-found=true

for smoke_namespace in \
  karpenter-smoke \
  karpenter-spot-smoke \
  karpenter-fis-smoke; do
  kubectl delete namespace "${smoke_namespace}" \
    --ignore-not-found=true \
    --wait=false
done

if kubectl get crd nodepools.karpenter.sh >/dev/null 2>&1; then
  echo "==> Deleting NodePools and Karpenter-provisioned capacity"
  kubectl delete nodepool --all --wait=true --timeout="${WAIT_TIMEOUT}"
  kubectl delete nodeclaim --all --wait=true --timeout="${WAIT_TIMEOUT}"
  if [[ -n "$(kubectl get nodes --selector karpenter.sh/nodepool --output name)" ]]; then
    kubectl wait --for=delete node \
      --selector karpenter.sh/nodepool \
      --timeout="${WAIT_TIMEOUT}"
  fi
fi

if kubectl get crd ec2nodeclasses.karpenter.k8s.aws >/dev/null 2>&1; then
  echo "==> Deleting EC2NodeClasses and generated instance profiles"
  kubectl delete ec2nodeclass --all --wait=true --timeout="${WAIT_TIMEOUT}"
fi

if kubectl get application "${ROOT_APP}" -n argocd >/dev/null 2>&1; then
  echo "==> Deleting aws-dev root application with cascading cleanup"
  kubectl delete application "${ROOT_APP}" -n argocd --wait=false
fi

echo "==> Waiting for demo-api ingress to disappear"
end=$((SECONDS + 900))
while kubectl get ingress demo-api -n startup-apps >/dev/null 2>&1; do
  if (( SECONDS >= end )); then
    echo "Timed out waiting for the demo-api Ingress to be deleted." >&2
    echo "Check the AWS Load Balancer Controller and ALB finalizers before terraform destroy." >&2
    exit 1
  fi
  sleep 10
done

echo "==> Application resources removed"
echo "Verify the ALB is gone in AWS, then run:"
echo "terraform -chdir=infra/terraform/aws/environments/dev destroy"

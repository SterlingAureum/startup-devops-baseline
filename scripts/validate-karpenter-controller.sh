#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Checking Karpenter Argo CD Applications"
for application in karpenter-crd karpenter; do
  kubectl get application "${application}" -n argocd >/dev/null
done

echo "==> Checking Karpenter CRDs"
for crd in \
  nodepools.karpenter.sh \
  nodeclaims.karpenter.sh \
  ec2nodeclasses.karpenter.k8s.aws; do
  kubectl get crd "${crd}" >/dev/null
done

echo "==> Checking Karpenter IRSA service account"
KARPENTER_ROLE_ARN="$(
  kubectl get serviceaccount karpenter \
    --namespace kube-system \
    --output jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}'
)"
if [[ -z "${KARPENTER_ROLE_ARN}" ]]; then
  echo "Karpenter service account is missing its IRSA role annotation." >&2
  exit 1
fi

echo "==> Waiting for Karpenter controller"
kubectl rollout status deployment/karpenter \
  --namespace kube-system \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Checking Karpenter controller placement"
mapfile -t KARPENTER_NODES < <(
  kubectl get pods \
    --namespace kube-system \
    --selector app.kubernetes.io/name=karpenter \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}'
)

if (( ${#KARPENTER_NODES[@]} == 0 )); then
  echo "No running Karpenter controller pods were found." >&2
  exit 1
fi

for node_name in "${KARPENTER_NODES[@]}"; do
  workload_label="$(
    kubectl get node "${node_name}" \
      --output jsonpath='{.metadata.labels.workload}'
  )"
  if [[ "${workload_label}" != "system" ]]; then
    echo "Karpenter controller pod is running on non-system node ${node_name}." >&2
    exit 1
  fi
done

echo "==> Current Karpenter capacity resources"
kubectl get nodepools,nodeclaims

echo "Karpenter controller validation passed."

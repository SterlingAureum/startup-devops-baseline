#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
ROOT_APPLICATION="${ROOT_APPLICATION:-startup-devops-aws-dev-root}"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
ALB_WAIT_SECONDS="${ALB_WAIT_SECONDS:-600}"
KARPENTER_WAIT_SECONDS="${KARPENTER_WAIT_SECONDS:-600}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'ERROR: required command not found: %s
' "$1" >&2
    exit 1
  }
}

for command_name in aws kubectl terraform; do
  require_command "${command_name}"
done

cat <<EOF
WARNING: this operation will destroy the aws-dev environment.

Cluster: ${CLUSTER_NAME}
Region: ${AWS_REGION}
Terraform directory: ${TF_DIR}

Expected resources include EKS, EC2 nodes, NAT Gateway, VPC, ALB-related resources, and applications.

Type 'destroy' to continue:
EOF

read -r confirmation
if [[ "${confirmation}" != "destroy" ]]; then
  echo "Destroy cancelled."
  exit 0
fi

aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

ROOT_APPLICATION_EXISTS=false
if kubectl get application "${ROOT_APPLICATION}" -n "${ARGOCD_NAMESPACE}" >/dev/null 2>&1; then
  ROOT_APPLICATION_EXISTS=true
  echo "==> Suspending root Application automation"
  kubectl patch application "${ROOT_APPLICATION}" \
    --namespace "${ARGOCD_NAMESPACE}" \
    --type merge \
    --patch '{"spec":{"syncPolicy":{"automated":null}}}'
fi

kubectl delete namespace karpenter-smoke \
  --ignore-not-found=true \
  --wait=false

if kubectl get crd nodepools.karpenter.sh >/dev/null 2>&1; then
  echo "==> Deleting NodePools and Karpenter-provisioned capacity"
  kubectl delete nodepool --all --wait=false

  deadline=$((SECONDS + KARPENTER_WAIT_SECONDS))
  while kubectl get nodepool -o name 2>/dev/null | grep -q . || \
        kubectl get nodeclaim -o name 2>/dev/null | grep -q . || \
        kubectl get nodes --selector karpenter.sh/nodepool -o name 2>/dev/null | grep -q .; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: timed out waiting for Karpenter node cleanup." >&2
      exit 1
    fi
    kubectl get nodepools,nodeclaims || true
    sleep 15
  done
fi

if kubectl get crd ec2nodeclasses.karpenter.k8s.aws >/dev/null 2>&1; then
  echo "==> Deleting EC2NodeClasses before the Karpenter controller"
  kubectl delete ec2nodeclass --all --wait=false

  deadline=$((SECONDS + KARPENTER_WAIT_SECONDS))
  while kubectl get ec2nodeclass -o name 2>/dev/null | grep -q .; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: timed out waiting for EC2NodeClass instance-profile cleanup." >&2
      exit 1
    fi
    kubectl get ec2nodeclass || true
    sleep 15
  done
fi

if [[ "${ROOT_APPLICATION_EXISTS}" == "true" ]]; then
  kubectl delete application "${ROOT_APPLICATION}" -n "${ARGOCD_NAMESPACE}" --wait=false
else
  echo "Root Application not found; continuing."
fi

if kubectl get namespace "${APP_NAMESPACE}" >/dev/null 2>&1; then
  kubectl delete ingress --all -n "${APP_NAMESPACE}" --ignore-not-found=true --wait=false
fi

deadline=$((SECONDS + ALB_WAIT_SECONDS))
while kubectl get ingress -A -o name 2>/dev/null | grep -q .; do
  if (( SECONDS >= deadline )); then
    echo "ERROR: timed out waiting for Ingress resources to disappear." >&2
    exit 1
  fi
  kubectl get ingress -A || true
  sleep 15
done

sleep 30
kubectl get service -A --field-selector spec.type=LoadBalancer || true
terraform -chdir="${TF_DIR}" destroy

echo "Destroy completed. Review AWS for unexpected residual load balancers, NAT Gateways, or Elastic IPs."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"
ALB_APPLICATION_TEMPLATE="${ALB_APPLICATION_TEMPLATE:-${ROOT_DIR}/clusters/aws-dev/platform/aws-load-balancer-controller.yaml}"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

kubectl get nodes >/dev/null

terraform_output() {
  local output_name="$1"
  local value

  value="$(terraform -chdir="${TF_DIR}" output -raw "${output_name}")"
  if [[ -z "${value}" ]]; then
    echo "Terraform output ${output_name} is empty." >&2
    exit 1
  fi

  printf '%s' "${value}"
}

create_irsa_service_account() {
  local service_account_name="$1"
  local role_arn="$2"

  kubectl create serviceaccount "${service_account_name}" \
    --namespace kube-system \
    --dry-run=client \
    --output yaml | kubectl apply -f -

  kubectl annotate serviceaccount "${service_account_name}" \
    --namespace kube-system \
    eks.amazonaws.com/role-arn="${role_arn}" \
    --overwrite
}

ALB_ROLE_ARN="$(terraform_output aws_load_balancer_controller_role_arn)"
KARPENTER_ROLE_ARN="$(terraform_output karpenter_controller_role_arn)"
VPC_ID="$(terraform_output vpc_id)"

if [[ ! "${VPC_ID}" =~ ^vpc-[[:xdigit:]]+$ ]]; then
  echo "Terraform output vpc_id has an unexpected value: ${VPC_ID}" >&2
  exit 1
fi

echo "==> Creating AWS Load Balancer Controller service account"
create_irsa_service_account "aws-load-balancer-controller" "${ALB_ROLE_ARN}"

echo "==> Creating Karpenter service account"
create_irsa_service_account "karpenter" "${KARPENTER_ROLE_ARN}"

echo "==> Installing Argo CD (${ARGOCD_VERSION})"
kubectl create namespace argocd --dry-run=client --output yaml | kubectl apply -f -
kubectl apply --server-side --force-conflicts \
  --namespace argocd \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

kubectl rollout status deployment/argocd-server -n argocd --timeout=10m
kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=10m
kubectl rollout status statefulset/argocd-application-controller -n argocd --timeout=10m

if [[ ! -f "${ALB_APPLICATION_TEMPLATE}" ]]; then
  echo "AWS Load Balancer Controller template not found: ${ALB_APPLICATION_TEMPLATE}" >&2
  exit 1
fi

ALB_APPLICATION_RENDERED="$(mktemp)"
trap 'rm -f "${ALB_APPLICATION_RENDERED}"' EXIT

sed "s#__VPC_ID__#${VPC_ID}#g" \
  "${ALB_APPLICATION_TEMPLATE}" > "${ALB_APPLICATION_RENDERED}"

if grep -q "__VPC_ID__" "${ALB_APPLICATION_RENDERED}"; then
  echo "AWS Load Balancer Controller template still contains __VPC_ID__." >&2
  exit 1
fi

echo "==> Applying AWS Load Balancer Controller Application with Terraform VPC ID"
kubectl apply -f "${ALB_APPLICATION_RENDERED}"

echo "==> Bootstrap complete"
echo "Next: ./scripts/deploy-aws-dev-root-app.sh"

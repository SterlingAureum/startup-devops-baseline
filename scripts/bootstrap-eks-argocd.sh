#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
TF_DIR="${TF_DIR:-infra/terraform/aws/environments/dev}"
ARGOCD_VERSION="${ARGOCD_VERSION:-stable}"
SERVICE_ACCOUNT_NAME="aws-load-balancer-controller"

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

kubectl get nodes >/dev/null

ROLE_ARN="$(terraform -chdir="${TF_DIR}" output -raw aws_load_balancer_controller_role_arn)"
if [[ -z "${ROLE_ARN}" ]]; then
  echo "Terraform output aws_load_balancer_controller_role_arn is empty." >&2
  exit 1
fi

echo "==> Creating AWS Load Balancer Controller service account"
kubectl create serviceaccount "${SERVICE_ACCOUNT_NAME}" \
  --namespace kube-system \
  --dry-run=client \
  --output yaml | kubectl apply -f -

kubectl annotate serviceaccount "${SERVICE_ACCOUNT_NAME}" \
  --namespace kube-system \
  eks.amazonaws.com/role-arn="${ROLE_ARN}" \
  --overwrite

echo "==> Installing Argo CD (${ARGOCD_VERSION})"
kubectl create namespace argocd --dry-run=client --output yaml | kubectl apply -f -
kubectl apply --server-side --force-conflicts \
  --namespace argocd \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

kubectl rollout status deployment/argocd-server -n argocd --timeout=10m
kubectl rollout status deployment/argocd-repo-server -n argocd --timeout=10m
kubectl rollout status statefulset/argocd-application-controller -n argocd --timeout=10m

echo "==> Bootstrap complete"
echo "Next: ./scripts/deploy-aws-dev-root-app.sh"

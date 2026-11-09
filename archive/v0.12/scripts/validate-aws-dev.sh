#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
DEMO_HOSTNAME="${DEMO_HOSTNAME:-demo.dev.aureumstack.com}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl curl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> AWS identity"
aws sts get-caller-identity

echo "==> Configure kubeconfig"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

echo "==> Nodes"
kubectl get nodes -o wide

echo "==> Argo CD applications"
kubectl get applications.argoproj.io -n argocd

echo "==> AWS Load Balancer Controller"
kubectl rollout status deployment/aws-load-balancer-controller \
  -n kube-system --timeout="${WAIT_TIMEOUT}"

echo "==> demo-api deployment"
kubectl rollout status deployment/demo-api \
  -n startup-apps --timeout="${WAIT_TIMEOUT}"

mapfile -t DEMO_API_NODES < <(
  kubectl get pods \
    --namespace startup-apps \
    --selector app.kubernetes.io/name=demo-api \
    --output jsonpath='{range .items[*]}{.spec.nodeName}{"\n"}{end}' |
    sort -u
)
if (( ${#DEMO_API_NODES[@]} < 1 )); then
  echo "No scheduled demo-api node was found." >&2
  exit 1
fi

for demo_api_node in "${DEMO_API_NODES[@]}"; do
  scheduling_identity="$(
    kubectl get node "${demo_api_node}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}:{.metadata.labels.workload}:{.metadata.labels.capacity-tier}'
  )"
  if [[ "${scheduling_identity}" != \
        "application-ondemand:application:on-demand" ]]; then
    echo "demo-api is running outside the On-Demand application tier: ${demo_api_node}." >&2
    exit 1
  fi
done

kubectl get ingress demo-api -n startup-apps

ALB_HOSTNAME="$(kubectl get ingress demo-api -n startup-apps -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
if [[ -z "${ALB_HOSTNAME}" ]]; then
  echo "ALB hostname is not available yet." >&2
  exit 1
fi

echo "==> ALB hostname: ${ALB_HOSTNAME}"
echo "==> Public hostname: ${DEMO_HOSTNAME}"

HTTP_STATUS="$(
  curl --output /dev/null --silent --show-error \
    --connect-timeout 10 --max-time 30 \
    --write-out '%{http_code}' \
    "http://${DEMO_HOSTNAME}/health"
)"
if [[ "${HTTP_STATUS}" != "301" ]]; then
  echo "Expected HTTP 301 redirect, received ${HTTP_STATUS}." >&2
  exit 1
fi

for path in health ready version db/health; do
  echo "==> GET /${path}"
  curl --fail --show-error --silent --retry 12 --retry-delay 10 \
    "https://${DEMO_HOSTNAME}/${path}"
  echo
 done

echo "==> aws-dev validation passed"

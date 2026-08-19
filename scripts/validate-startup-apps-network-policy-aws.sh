#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
APPLICATION_NAME="${APPLICATION_NAME:-startup-apps-network-policy-aws-dev}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
APP_DEPLOYMENT="${APP_DEPLOYMENT:-demo-api}"
APP_SERVICE="${APP_SERVICE:-demo-api}"
DEMO_HOSTNAME="${DEMO_HOSTNAME:-demo.dev.aureumstack.com}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgresql-baseline-rw.data-platform.svc.cluster.local}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"
TEST_IMAGE="${TEST_IMAGE:-public.ecr.aws/docker/library/busybox:1.36.1}"
TEST_NAMESPACE="${TEST_NAMESPACE:-v082-startup-apps-netpol-test-$$}"
TEST_NAMESPACE_CREATED="false"

for command in aws curl git grep jq kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

EXPECTED_REVISION="${EXPECTED_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"

if [[ ! "${TEST_NAMESPACE}" =~ ^v082-startup-apps-netpol-test-[a-z0-9-]+$ ]]; then
  echo "TEST_NAMESPACE must use the v082-startup-apps-netpol-test- prefix." >&2
  exit 1
fi

cleanup() {
  if [[ "${TEST_NAMESPACE_CREATED}" == "true" ]]; then
    kubectl delete namespace "${TEST_NAMESPACE}" \
      --ignore-not-found \
      --wait=false >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_for_application() {
  kubectl wait \
    --for=jsonpath='{.status.sync.revision}'="${EXPECTED_REVISION}" \
    "application/${APPLICATION_NAME}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}"
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
}

wait_for_public_health() {
  local hostname="$1"
  local attempt

  for attempt in {1..60}; do
    if curl \
      --fail \
      --silent \
      --show-error \
      --connect-timeout 5 \
      --max-time 10 \
      "https://${hostname}/health" |
      jq --exit-status '.status == "ok"' >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done

  echo "The ALB health endpoint did not remain reachable." >&2
  return 1
}

assert_request_denied() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    echo "${description} was unexpectedly allowed." >&2
    exit 1
  fi
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Refreshing the startup-apps NetworkPolicy Application"
kubectl annotate application "${APPLICATION_NAME}" \
  --namespace argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite >/dev/null

echo "==> Waiting for startup-apps policies at ${EXPECTED_REVISION}"
wait_for_application

echo "==> Verifying policy resources"
for policy in \
  default-deny \
  allow-dns-egress \
  allow-alb-to-demo-api \
  allow-observability-to-demo-api \
  allow-demo-api-to-postgresql; do
  kubectl get networkpolicy "${policy}" \
    --namespace "${APP_NAMESPACE}" >/dev/null
done

if ! kubectl get policyendpoints.networking.k8s.aws \
  --namespace "${APP_NAMESPACE}" \
  --output name | grep -q .; then
  echo "No PolicyEndpoint was created for startup-apps." >&2
  exit 1
fi

echo "==> Verifying ALB subnet CIDR alignment"
ALB_HOSTNAME="$(
  kubectl get ingress "${APP_DEPLOYMENT}" \
    --namespace "${APP_NAMESPACE}" \
    --output jsonpath='{.status.loadBalancer.ingress[0].hostname}'
)"
if [[ -z "${ALB_HOSTNAME}" ]]; then
  echo "The demo-api Ingress does not have an ALB hostname." >&2
  exit 1
fi

mapfile -t ALB_SUBNET_IDS < <(
  aws elbv2 describe-load-balancers \
    --region "${AWS_REGION}" \
    --query "LoadBalancers[?DNSName=='${ALB_HOSTNAME}'].AvailabilityZones[].SubnetId" \
    --output json |
    jq -r '.[]'
)
if (( ${#ALB_SUBNET_IDS[@]} == 0 )); then
  echo "No AWS load balancer subnets were resolved for ${ALB_HOSTNAME}." >&2
  exit 1
fi

ALB_SUBNETS_JSON="$(
  aws ec2 describe-subnets \
    --region "${AWS_REGION}" \
    --subnet-ids "${ALB_SUBNET_IDS[@]}" \
    --output json
)"
if ! jq --exit-status '
  .Subnets | length > 0 and
  all(.[];
    any(.Tags[]?;
      .Key == "kubernetes.io/role/elb" and .Value == "1"
    )
  )
' <<<"${ALB_SUBNETS_JSON}" >/dev/null; then
  echo "The demo-api ALB is not using only ELB-tagged public subnets." >&2
  exit 1
fi

AWS_ALB_CIDRS="$(
  jq -c '[.Subnets[].CidrBlock] | sort' <<<"${ALB_SUBNETS_JSON}"
)"
POLICY_ALB_CIDRS="$(
  kubectl get networkpolicy allow-alb-to-demo-api \
    --namespace "${APP_NAMESPACE}" \
    --output json |
    jq -c '[.spec.ingress[].from[]?.ipBlock.cidr] | sort'
)"
if [[ "${AWS_ALB_CIDRS}" == "[]" ||
      "${POLICY_ALB_CIDRS}" != "${AWS_ALB_CIDRS}" ]]; then
  echo "The ALB NetworkPolicy CIDRs do not match the ELB-tagged subnets." >&2
  echo "AWS:    ${AWS_ALB_CIDRS}" >&2
  echo "Policy: ${POLICY_ALB_CIDRS}" >&2
  exit 1
fi

echo "==> Verifying the protected application remains healthy"
kubectl rollout status "deployment/${APP_DEPLOYMENT}" \
  --namespace "${APP_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

wait_for_public_health "${DEMO_HOSTNAME}"

mapfile -t APP_PODS < <(
  kubectl get pods \
    --namespace "${APP_NAMESPACE}" \
    --selector "app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api" \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#APP_PODS[@]} == 0 )); then
  echo "No running demo-api Pods were found." >&2
  exit 1
fi

echo "==> Verifying DNS and PostgreSQL egress"
for pod in "${APP_PODS[@]}"; do
  kubectl exec \
    --namespace "${APP_NAMESPACE}" \
    "${pod}" -- \
    python -c \
      'import socket; socket.getaddrinfo("'"${POSTGRES_SERVICE}"'", 5432)' \
    >/dev/null

  kubectl exec \
    --namespace "${APP_NAMESPACE}" \
    "${pod}" -- \
    python -c \
      'import json, urllib.request; data=json.load(urllib.request.urlopen("http://127.0.0.1:8080/db/health", timeout=15)); assert data["status"] == "ok"' \
    >/dev/null
done

echo "==> Creating isolated negative-test endpoints"
kubectl create namespace "${TEST_NAMESPACE}" >/dev/null
TEST_NAMESPACE_CREATED="true"

kubectl apply --namespace "${TEST_NAMESPACE}" -f - >/dev/null <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: netpol-server
data:
  index.html: network-policy-test
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: netpol-server
spec:
  replicas: 1
  selector:
    matchLabels:
      app: netpol-server
  template:
    metadata:
      labels:
        app: netpol-server
    spec:
      containers:
        - name: server
          image: ${TEST_IMAGE}
          command: ["httpd", "-f", "-p", "8080", "-h", "/www"]
          ports:
            - name: http
              containerPort: 8080
          volumeMounts:
            - name: content
              mountPath: /www
          resources:
            requests:
              cpu: 5m
              memory: 8Mi
            limits:
              cpu: 25m
              memory: 32Mi
      volumes:
        - name: content
          configMap:
            name: netpol-server
---
apiVersion: v1
kind: Service
metadata:
  name: netpol-server
spec:
  selector:
    app: netpol-server
  ports:
    - name: http
      port: 8080
      targetPort: http
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: netpol-client
spec:
  replicas: 1
  selector:
    matchLabels:
      app: netpol-client
  template:
    metadata:
      labels:
        app: netpol-client
    spec:
      containers:
        - name: client
          image: ${TEST_IMAGE}
          command: ["sh", "-c", "sleep 3600"]
          resources:
            requests:
              cpu: 5m
              memory: 8Mi
            limits:
              cpu: 25m
              memory: 32Mi
EOF

kubectl rollout status deployment/netpol-server \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl rollout status deployment/netpol-client \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

BASELINE_RESPONSE="$(
  kubectl exec \
    --namespace "${TEST_NAMESPACE}" \
    deployment/netpol-client -- \
    wget -q -T 5 -O - http://netpol-server:8080
)"
if [[ "${BASELINE_RESPONSE}" != "network-policy-test" ]]; then
  echo "The negative-test server is not reachable from its control client." >&2
  exit 1
fi

echo "==> Verifying unauthorized ingress is denied"
assert_request_denied \
  "Cross-namespace access to demo-api" \
  kubectl exec \
    --namespace "${TEST_NAMESPACE}" \
    deployment/netpol-client -- \
    wget -q -T 5 -O - \
      "http://${APP_SERVICE}.${APP_NAMESPACE}.svc.cluster.local/health"

echo "==> Verifying unauthorized egress is denied"
for pod in "${APP_PODS[@]}"; do
  assert_request_denied \
    "demo-api egress to ${TEST_NAMESPACE}/netpol-server from ${pod}" \
    kubectl exec \
      --namespace "${APP_NAMESPACE}" \
      "${pod}" -- \
      python -c \
        'import socket; connection=socket.create_connection(("netpol-server.'"${TEST_NAMESPACE}"'.svc.cluster.local", 8080), timeout=5); connection.close()'
done

echo "startup-apps NetworkPolicy aws-dev runtime validation passed."

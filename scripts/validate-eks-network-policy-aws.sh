#!/usr/bin/env bash
set -Eeuo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
ADDON_NAME="vpc-cni"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-5m}"
TEST_IMAGE="${TEST_IMAGE:-public.ecr.aws/docker/library/busybox:1.36.1}"
TEST_NAMESPACE="${TEST_NAMESPACE:-v082-network-policy-test-$$}"
TEST_NAMESPACE_CREATED="false"

for command in aws jq kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ ! "${TEST_NAMESPACE}" =~ ^v082-network-policy-test-[a-z0-9-]+$ ]]; then
  echo "TEST_NAMESPACE must use the v082-network-policy-test- prefix." >&2
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

request_server() {
  kubectl exec \
    --namespace "${TEST_NAMESPACE}" \
    deployment/netpol-client \
    -- wget -q -T 3 -O - http://netpol-server:8080 2>/dev/null
}

wait_for_allowed() {
  local description="$1"
  local attempt
  local output

  for attempt in {1..45}; do
    if output="$(request_server)" &&
      [[ "${output}" == "network-policy-allowed" ]]; then
      return 0
    fi
    sleep 2
  done

  echo "${description}: the client could not reach the test server." >&2
  return 1
}

wait_for_denied() {
  local description="$1"
  local attempt
  local consecutive_failures=0

  for attempt in {1..45}; do
    if request_server >/dev/null; then
      consecutive_failures=0
    else
      consecutive_failures=$((consecutive_failures + 1))
      if (( consecutive_failures >= 3 )); then
        return 0
      fi
    fi
    sleep 2
  done

  echo "${description}: traffic remained reachable after default-deny." >&2
  return 1
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Verifying the VPC CNI managed add-on configuration"
ADDON_STATUS="$(
  aws eks describe-addon \
    --region "${AWS_REGION}" \
    --cluster-name "${CLUSTER_NAME}" \
    --addon-name "${ADDON_NAME}" \
    --query 'addon.status' \
    --output text
)"
if [[ "${ADDON_STATUS}" != "ACTIVE" ]]; then
  echo "The ${ADDON_NAME} add-on is not ACTIVE: ${ADDON_STATUS}" >&2
  exit 1
fi

ADDON_CONFIGURATION="$(
  aws eks describe-addon \
    --region "${AWS_REGION}" \
    --cluster-name "${CLUSTER_NAME}" \
    --addon-name "${ADDON_NAME}" \
    --query 'addon.configurationValues' \
    --output text
)"
if ! jq --exit-status \
  '(.enableNetworkPolicy == true) or (.enableNetworkPolicy == "true")' \
  <<<"${ADDON_CONFIGURATION}" >/dev/null 2>&1; then
  echo "The VPC CNI add-on does not enable NetworkPolicy enforcement." >&2
  echo "configurationValues: ${ADDON_CONFIGURATION:-missing}" >&2
  exit 1
fi

echo "==> Verifying the VPC CNI node agent"
kubectl rollout status daemonset/aws-node \
  --namespace kube-system \
  --timeout="${WAIT_TIMEOUT}"

NODE_AGENT_ENABLED="$(
  kubectl get daemonset aws-node \
    --namespace kube-system \
    -o json |
    jq -r '
      [
        .spec.template.spec.containers[]
        | select(.name == "aws-eks-nodeagent")
        | .args[]?
      ]
      | any(. == "--enable-network-policy=true")
    '
)"
if [[ "${NODE_AGENT_ENABLED}" != "true" ]]; then
  echo "aws-eks-nodeagent is not running with --enable-network-policy=true." >&2
  exit 1
fi

ENFORCING_MODE="$(
  kubectl get daemonset aws-node \
    --namespace kube-system \
    -o json |
    jq -r '
      [
        .spec.template.spec.containers[]
        | select(.name == "aws-node")
        | .env[]?
        | select(.name == "NETWORK_POLICY_ENFORCING_MODE")
        | .value
      ]
      | last // "standard"
    '
)"
if [[ "${ENFORCING_MODE}" == "strict" ]]; then
  echo "Checkpoint 1 expects standard, not strict, enforcing mode." >&2
  exit 1
fi

kubectl get customresourcedefinition \
  policyendpoints.networking.k8s.aws >/dev/null

echo "==> Creating isolated NetworkPolicy test workloads"
kubectl create namespace "${TEST_NAMESPACE}" >/dev/null
TEST_NAMESPACE_CREATED="true"

kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: netpol-server-content
  namespace: ${TEST_NAMESPACE}
data:
  index.html: network-policy-allowed
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: netpol-server
  namespace: ${TEST_NAMESPACE}
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
      automountServiceAccountToken: false
      containers:
        - name: server
          image: ${TEST_IMAGE}
          command: ["httpd"]
          args: ["-f", "-p", "8080", "-h", "/www"]
          ports:
            - name: http
              containerPort: 8080
          resources:
            requests:
              cpu: 5m
              memory: 8Mi
            limits:
              cpu: 50m
              memory: 32Mi
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 65534
          volumeMounts:
            - name: content
              mountPath: /www
              readOnly: true
      securityContext:
        seccompProfile:
          type: RuntimeDefault
      volumes:
        - name: content
          configMap:
            name: netpol-server-content
---
apiVersion: v1
kind: Service
metadata:
  name: netpol-server
  namespace: ${TEST_NAMESPACE}
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
  namespace: ${TEST_NAMESPACE}
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
      automountServiceAccountToken: false
      containers:
        - name: client
          image: ${TEST_IMAGE}
          command: ["sh", "-c", "while true; do sleep 3600; done"]
          resources:
            requests:
              cpu: 5m
              memory: 8Mi
            limits:
              cpu: 50m
              memory: 32Mi
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 65534
      securityContext:
        seccompProfile:
          type: RuntimeDefault
EOF

kubectl rollout status deployment/netpol-server \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl rollout status deployment/netpol-client \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

echo "==> Verifying baseline connectivity"
wait_for_allowed "Baseline connectivity"

echo "==> Verifying default-deny enforcement"
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-server-ingress
  namespace: ${TEST_NAMESPACE}
spec:
  podSelector:
    matchLabels:
      app: netpol-server
  policyTypes:
    - Ingress
EOF

for attempt in {1..30}; do
  if [[ "$(
    kubectl get policyendpoints \
      --namespace "${TEST_NAMESPACE}" \
      --no-headers 2>/dev/null |
      wc -l
  )" -gt 0 ]]; then
    break
  fi
  if (( attempt == 30 )); then
    echo "No PolicyEndpoint was created for the test NetworkPolicy." >&2
    exit 1
  fi
  sleep 2
done

wait_for_denied "Default-deny enforcement"

echo "==> Verifying explicit allow recovery"
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-client-to-server
  namespace: ${TEST_NAMESPACE}
spec:
  podSelector:
    matchLabels:
      app: netpol-server
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: netpol-client
      ports:
        - protocol: TCP
          port: 8080
EOF

wait_for_allowed "Explicit allow recovery"

echo "EKS network-policy enforcement validation passed."

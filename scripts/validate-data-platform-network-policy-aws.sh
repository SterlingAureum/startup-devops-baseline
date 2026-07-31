#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
APPLICATION_NAME="${APPLICATION_NAME:-data-platform-network-policy-aws-dev}"
DATA_NAMESPACE="${DATA_NAMESPACE:-data-platform}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-cnpg-system}"
OPERATOR_DEPLOYMENT="${OPERATOR_DEPLOYMENT:-cnpg-cloudnative-pg}"
BARMAN_DEPLOYMENT="${BARMAN_DEPLOYMENT:-barman-cloud-plugin-barman-cloud}"
BARMAN_SERVICE="${BARMAN_SERVICE:-barman-cloud.cnpg-system.svc.cluster.local}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"
WAL_TIMEOUT_SECONDS="${WAL_TIMEOUT_SECONDS:-600}"
TEST_IMAGE="${TEST_IMAGE:-public.ecr.aws/docker/library/busybox:1.36.1}"
TEST_NAMESPACE="${TEST_NAMESPACE:-v082-data-platform-netpol-test-$$}"
TEST_NAMESPACE_CREATED="false"

for command in aws git grep jq kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

EXPECTED_REVISION="${EXPECTED_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"

if [[ ! "${TEST_NAMESPACE}" =~ ^v082-data-platform-netpol-test-[a-z0-9-]+$ ]]; then
  echo "TEST_NAMESPACE must use the v082-data-platform-netpol-test- prefix." >&2
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

assert_request_denied() {
  local description="$1"
  shift

  if "$@" >/dev/null 2>&1; then
    echo "${description} was unexpectedly allowed." >&2
    exit 1
  fi
}

tcp_check_from_postgres() {
  local pod="$1"
  local host="$2"
  local port="$3"

  kubectl exec \
    --namespace "${DATA_NAMESPACE}" \
    "${pod}" \
    --container postgres -- \
    bash -c \
      "timeout 8 bash -c '</dev/tcp/${host}/${port}'"
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Refreshing the data-platform NetworkPolicy Application"
kubectl annotate application "${APPLICATION_NAME}" \
  --namespace argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite >/dev/null

echo "==> Waiting for data-platform policies at ${EXPECTED_REVISION}"
wait_for_application

echo "==> Verifying policy resources"
for policy in \
  default-deny \
  allow-dns-egress \
  allow-demo-api-to-postgresql-baseline \
  allow-cnpg-operator-to-instances \
  allow-cnpg-instance-traffic \
  allow-kubernetes-api-to-cnpg-status \
  allow-cnpg-to-barman-plugin \
  allow-cnpg-to-kubernetes-api \
  allow-cnpg-public-https-egress; do
  kubectl get networkpolicy "${policy}" \
    --namespace "${DATA_NAMESPACE}" >/dev/null
done

if ! kubectl get policyendpoints.networking.k8s.aws \
  --namespace "${DATA_NAMESPACE}" \
  --output name | grep -q .; then
  echo "No PolicyEndpoint was created for data-platform." >&2
  exit 1
fi

echo "==> Verifying private Kubernetes API endpoint alignment"
CLUSTER_JSON="$(
  aws eks describe-cluster \
    --region "${AWS_REGION}" \
    --name "${CLUSTER_NAME}" \
    --output json
)"
if [[ "$(jq -r '.cluster.resourcesVpcConfig.endpointPrivateAccess' \
  <<<"${CLUSTER_JSON}")" != "true" ]]; then
  echo "The EKS private Kubernetes API endpoint is not enabled." >&2
  exit 1
fi

KUBERNETES_SERVICE_IP="$(
  kubectl get service kubernetes \
    --namespace default \
    --output jsonpath='{.spec.clusterIP}'
)"
if [[ -z "${KUBERNETES_SERVICE_IP}" ]]; then
  echo "The default/kubernetes Service does not have a ClusterIP." >&2
  exit 1
fi

mapfile -t API_ENDPOINT_IPS < <(
  kubectl get endpointslice \
    --namespace default \
    --selector kubernetes.io/service-name=kubernetes \
    --output json |
    jq -r '.items[].endpoints[].addresses[]' |
    sort -u
)
if (( ${#API_ENDPOINT_IPS[@]} == 0 )); then
  echo "No private Kubernetes API endpoints were resolved." >&2
  exit 1
fi

EXPECTED_API_EGRESS_CIDRS="$(
  {
    printf '%s/32\n' "${KUBERNETES_SERVICE_IP}"
    printf '%s/32\n' "${API_ENDPOINT_IPS[@]}"
  } | jq -Rsc 'split("\n") | map(select(length > 0)) | sort'
)"
POLICY_API_EGRESS_CIDRS="$(
  kubectl get networkpolicy allow-cnpg-to-kubernetes-api \
    --namespace "${DATA_NAMESPACE}" \
    --output json |
    jq -c '[.spec.egress[].to[]?.ipBlock.cidr] | sort'
)"
if [[ "${POLICY_API_EGRESS_CIDRS}" != "${EXPECTED_API_EGRESS_CIDRS}" ]]; then
  echo "The Kubernetes API egress CIDRs do not match the live endpoints." >&2
  echo "Live:   ${EXPECTED_API_EGRESS_CIDRS}" >&2
  echo "Policy: ${POLICY_API_EGRESS_CIDRS}" >&2
  exit 1
fi

EXPECTED_API_INGRESS_CIDRS="$(
  printf '%s/32\n' "${API_ENDPOINT_IPS[@]}" |
    jq -Rsc 'split("\n") | map(select(length > 0)) | sort'
)"
POLICY_API_INGRESS_CIDRS="$(
  kubectl get networkpolicy allow-kubernetes-api-to-cnpg-status \
    --namespace "${DATA_NAMESPACE}" \
    --output json |
    jq -c '[.spec.ingress[].from[]?.ipBlock.cidr] | sort'
)"
if [[ "${POLICY_API_INGRESS_CIDRS}" != "${EXPECTED_API_INGRESS_CIDRS}" ]]; then
  echo "The Kubernetes API ingress CIDRs do not match the live endpoints." >&2
  echo "Live:   ${EXPECTED_API_INGRESS_CIDRS}" >&2
  echo "Policy: ${POLICY_API_INGRESS_CIDRS}" >&2
  exit 1
fi

VPC_ID="$(jq -r '.cluster.resourcesVpcConfig.vpcId' <<<"${CLUSTER_JSON}")"
VPC_ENDPOINTS="$(
  aws ec2 describe-vpc-endpoints \
    --region "${AWS_REGION}" \
    --filters \
      "Name=vpc-id,Values=${VPC_ID}" \
      "Name=service-name,Values=com.amazonaws.${AWS_REGION}.s3,com.amazonaws.${AWS_REGION}.sts" \
    --output json
)"
if [[ "$(jq '.VpcEndpoints | length' <<<"${VPC_ENDPOINTS}")" != "0" ]]; then
  echo "S3 or STS VPC endpoints now exist; review the public-AWS egress policy." >&2
  exit 1
fi

echo "==> Verifying CloudNativePG control and replication paths"
kubectl rollout status "deployment/${OPERATOR_DEPLOYMENT}" \
  --namespace "${OPERATOR_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl rollout status "deployment/${BARMAN_DEPLOYMENT}" \
  --namespace "${OPERATOR_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${DATA_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

EXPECTED_INSTANCES="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${DATA_NAMESPACE}" \
    --output jsonpath='{.spec.instances}'
)"
READY_INSTANCES="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${DATA_NAMESPACE}" \
    --output jsonpath='{.status.readyInstances}'
)"
if [[ -z "${EXPECTED_INSTANCES}" ||
      "${READY_INSTANCES}" != "${EXPECTED_INSTANCES}" ]]; then
  echo "CloudNativePG does not have every expected instance ready." >&2
  exit 1
fi

PRIMARY_POD="$(
  kubectl get pods \
    --namespace "${DATA_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --field-selector status.phase=Running \
    --output jsonpath='{.items[0].metadata.name}'
)"
if [[ -z "${PRIMARY_POD}" ]]; then
  echo "Unable to resolve the current PostgreSQL primary Pod." >&2
  exit 1
fi

kubectl exec \
  --namespace "${DATA_NAMESPACE}" \
  "${PRIMARY_POD}" \
  --container postgres -- \
  bash -c 'command -v bash >/dev/null && command -v getent >/dev/null && command -v timeout >/dev/null'

STREAMING_REPLICAS="$(
  kubectl exec \
    --namespace "${DATA_NAMESPACE}" \
    "${PRIMARY_POD}" \
    --container postgres -- \
    psql -U postgres -d postgres -Atqc \
      "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming';"
)"
if [[ "${STREAMING_REPLICAS}" != "$((EXPECTED_INSTANCES - 1))" ]]; then
  echo "Not every PostgreSQL replica is streaming." >&2
  echo "Expected: $((EXPECTED_INSTANCES - 1))" >&2
  echo "Actual:   ${STREAMING_REPLICAS}" >&2
  exit 1
fi

"${ROOT_DIR}/scripts/validate-demo-api-postgresql.sh"

echo "==> Verifying Barman, Kubernetes API, S3, and STS egress"
BACKUP_BUCKET="$(
  terraform -chdir="${TF_DIR}" output -raw cnpg_backup_bucket_name
)"
if [[ -z "${BACKUP_BUCKET}" ]]; then
  echo "Terraform output cnpg_backup_bucket_name is empty." >&2
  exit 1
fi

kubectl exec \
  --namespace "${DATA_NAMESPACE}" \
  "${PRIMARY_POD}" \
  --container postgres -- \
  getent ahostsv4 "${BARMAN_SERVICE}" >/dev/null

tcp_check_from_postgres "${PRIMARY_POD}" "${BARMAN_SERVICE}" 9090
tcp_check_from_postgres \
  "${PRIMARY_POD}" \
  "${KUBERNETES_SERVICE_IP}" \
  443
tcp_check_from_postgres \
  "${PRIMARY_POD}" \
  "sts.${AWS_REGION}.amazonaws.com" \
  443
tcp_check_from_postgres \
  "${PRIMARY_POD}" \
  "${BACKUP_BUCKET}.s3.${AWS_REGION}.amazonaws.com" \
  443

echo "==> Verifying fresh WAL archival after isolation"
WAL_SEGMENT="$(
  kubectl exec \
    --namespace "${DATA_NAMESPACE}" \
    "${PRIMARY_POD}" \
    --container postgres -- \
    psql -U postgres -d postgres -Atqc \
      "SELECT pg_walfile_name(pg_current_wal_lsn());"
)"
if [[ ! "${WAL_SEGMENT}" =~ ^[0-9A-F]{24}$ ]]; then
  echo "Unexpected WAL segment name: ${WAL_SEGMENT}" >&2
  exit 1
fi

kubectl exec \
  --namespace "${DATA_NAMESPACE}" \
  "${PRIMARY_POD}" \
  --container postgres -- \
  psql -U postgres -d postgres -Atqc \
    "SELECT pg_switch_wal();" >/dev/null

deadline=$((SECONDS + WAL_TIMEOUT_SECONDS))
while true; do
  S3_KEYS="$(
    aws s3api list-objects-v2 \
      --bucket "${BACKUP_BUCKET}" \
      --prefix "${POSTGRES_CLUSTER}/" \
      --query 'Contents[].Key' \
      --output text
  )"
  if [[ "${S3_KEYS}" == *"${WAL_SEGMENT}"* ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for fresh WAL ${WAL_SEGMENT} in S3." >&2
    exit 1
  fi
  sleep 10
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

echo "==> Verifying unauthorized PostgreSQL ingress is denied"
assert_request_denied \
  "Cross-namespace access to PostgreSQL" \
  kubectl exec \
    --namespace "${TEST_NAMESPACE}" \
    deployment/netpol-client -- \
    nc -w 5 \
      "${POSTGRES_CLUSTER}-rw.${DATA_NAMESPACE}.svc.cluster.local" \
      5432

echo "==> Verifying unauthorized data-platform egress is denied"
kubectl exec \
  --namespace "${DATA_NAMESPACE}" \
  "${PRIMARY_POD}" \
  --container postgres -- \
  getent ahostsv4 \
    "netpol-server.${TEST_NAMESPACE}.svc.cluster.local" >/dev/null

assert_request_denied \
  "PostgreSQL egress to ${TEST_NAMESPACE}/netpol-server" \
  tcp_check_from_postgres \
    "${PRIMARY_POD}" \
    "netpol-server.${TEST_NAMESPACE}.svc.cluster.local" \
    8080

echo "data-platform NetworkPolicy aws-dev runtime validation passed."

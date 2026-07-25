#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
APPLICATION_NAME="${APPLICATION_NAME:-postgresql-baseline}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
STORAGE_CLASS="${STORAGE_CLASS:-gp3-cnpg}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-15m}"
EXPECTED_IMAGE="ghcr.io/cloudnative-pg/postgresql:17.10-202607200905-system-bookworm@sha256:4c1e15c27bb33361d847db66e6516a9432a7388f8a5404e06eaa2d665f5836f6"

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

echo "==> Checking PostgreSQL Argo CD Application"
kubectl get application "${APPLICATION_NAME}" -n argocd >/dev/null
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

echo "==> Checking gp3 StorageClass contract"
PROVISIONER="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.provisioner}'
)"
VOLUME_TYPE="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.parameters.type}'
)"
IOPS="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.parameters.iops}'
)"
THROUGHPUT="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.parameters.throughput}'
)"
ENCRYPTED="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.parameters.encrypted}'
)"
FILESYSTEM="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.parameters.csi\.storage\.k8s\.io/fstype}'
)"
BINDING_MODE="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.volumeBindingMode}'
)"
ALLOW_EXPANSION="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.allowVolumeExpansion}'
)"
RECLAIM_POLICY="$(
  kubectl get storageclass "${STORAGE_CLASS}" \
    --output jsonpath='{.reclaimPolicy}'
)"

if [[ "${PROVISIONER}" != "ebs.csi.aws.com" || \
      "${VOLUME_TYPE}" != "gp3" || \
      "${IOPS}" != "3000" || \
      "${THROUGHPUT}" != "125" || \
      "${ENCRYPTED}" != "true" || \
      "${FILESYSTEM}" != "ext4" || \
      "${BINDING_MODE}" != "WaitForFirstConsumer" || \
      "${ALLOW_EXPANSION}" != "true" || \
      "${RECLAIM_POLICY}" != "Delete" ]]; then
  echo "The ${STORAGE_CLASS} StorageClass does not match the v0.6.1 contract." >&2
  exit 1
fi

echo "==> Waiting for PostgreSQL Cluster"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

INSTANCES="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.instances}'
)"
IMAGE_NAME="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.imageName}'
)"
CLUSTER_STORAGE_CLASS="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.storage.storageClass}'
)"
CLUSTER_STORAGE_SIZE="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.storage.size}'
)"
NODE_SELECTOR="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.affinity.nodeSelector.workload}'
)"
DATABASE="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.bootstrap.initdb.database}'
)"
OWNER="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.bootstrap.initdb.owner}'
)"
CPU_REQUEST="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.resources.requests.cpu}'
)"
CPU_LIMIT="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.resources.limits.cpu}'
)"
MEMORY_REQUEST="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.resources.requests.memory}'
)"
MEMORY_LIMIT="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.resources.limits.memory}'
)"
SHARED_BUFFERS="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.postgresql.parameters.shared_buffers}'
)"

if [[ "${INSTANCES}" != "1" || \
      "${IMAGE_NAME}" != "${EXPECTED_IMAGE}" || \
      "${CLUSTER_STORAGE_CLASS}" != "${STORAGE_CLASS}" || \
      "${CLUSTER_STORAGE_SIZE}" != "20Gi" || \
      "${NODE_SELECTOR}" != "system" || \
      "${DATABASE}" != "app" || \
      "${OWNER}" != "app" || \
      "${CPU_REQUEST}" != "500m" || \
      "${CPU_LIMIT}" != "500m" || \
      "${MEMORY_REQUEST}" != "1Gi" || \
      "${MEMORY_LIMIT}" != "1Gi" || \
      "${SHARED_BUFFERS}" != "256MB" ]]; then
  echo "The PostgreSQL Cluster spec does not match the v0.6.1 contract." >&2
  exit 1
fi

echo "==> Checking generated application credentials"
APP_SECRET="${POSTGRES_CLUSTER}-app"
kubectl get secret "${APP_SECRET}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null
for key in username password host port dbname uri; do
  value="$(
    kubectl get secret "${APP_SECRET}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output "jsonpath={.data.${key}}"
  )"
  if [[ -z "${value}" ]]; then
    echo "Generated application Secret is missing key: ${key}" >&2
    exit 1
  fi
done

echo "==> Checking PostgreSQL Pod and placement"
mapfile -t POSTGRES_PODS < <(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
    --field-selector status.phase=Running \
    --output name
)
if (( ${#POSTGRES_PODS[@]} != 1 )); then
  echo "Expected one running PostgreSQL Pod, found ${#POSTGRES_PODS[@]}." >&2
  exit 1
fi

POSTGRES_POD="${POSTGRES_PODS[0]#pod/}"
POSTGRES_NODE="$(
  kubectl get pod "${POSTGRES_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.nodeName}'
)"
QOS_CLASS="$(
  kubectl get pod "${POSTGRES_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.qosClass}'
)"
WORKLOAD_LABEL="$(
  kubectl get node "${POSTGRES_NODE}" \
    --output jsonpath='{.metadata.labels.workload}'
)"
NODEPOOL_LABEL="$(
  kubectl get node "${POSTGRES_NODE}" \
    --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}'
)"

if [[ "${QOS_CLASS}" != "Guaranteed" || \
      "${WORKLOAD_LABEL}" != "system" || \
      -n "${NODEPOOL_LABEL}" ]]; then
  echo "PostgreSQL is not running with Guaranteed QoS on a stable system node." >&2
  exit 1
fi

echo "==> Checking PVC, PV, and EBS volume"
mapfile -t POSTGRES_PVCS < <(
  kubectl get pvc \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
    --output name
)
if (( ${#POSTGRES_PVCS[@]} != 1 )); then
  echo "Expected one PostgreSQL PVC, found ${#POSTGRES_PVCS[@]}." >&2
  exit 1
fi

POSTGRES_PVC="${POSTGRES_PVCS[0]#persistentvolumeclaim/}"
PVC_PHASE="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.phase}'
)"
PVC_STORAGE_CLASS="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.storageClassName}'
)"
PVC_CAPACITY="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.capacity.storage}'
)"
PV_NAME="$(
  kubectl get pvc "${POSTGRES_PVC}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.volumeName}'
)"

if [[ "${PVC_PHASE}" != "Bound" || \
      "${PVC_STORAGE_CLASS}" != "${STORAGE_CLASS}" || \
      "${PVC_CAPACITY}" != "20Gi" || \
      -z "${PV_NAME}" ]]; then
  echo "PostgreSQL PVC is not bound to the expected 20Gi gp3 storage." >&2
  exit 1
fi

CSI_DRIVER="$(
  kubectl get pv "${PV_NAME}" \
    --output jsonpath='{.spec.csi.driver}'
)"
VOLUME_ID="$(
  kubectl get pv "${PV_NAME}" \
    --output jsonpath='{.spec.csi.volumeHandle}'
)"

if [[ "${CSI_DRIVER}" != "ebs.csi.aws.com" || "${VOLUME_ID}" != vol-* ]]; then
  echo "PostgreSQL PV is not backed by the AWS EBS CSI driver." >&2
  exit 1
fi

read -r EBS_TYPE EBS_ENCRYPTED EBS_SIZE EBS_IOPS EBS_THROUGHPUT EBS_STATE <<< "$(
  aws ec2 describe-volumes \
    --region "${AWS_REGION}" \
    --volume-ids "${VOLUME_ID}" \
    --query 'Volumes[0].[VolumeType,Encrypted,Size,Iops,Throughput,State]' \
    --output text
)"

if [[ "${EBS_TYPE}" != "gp3" || \
      "${EBS_ENCRYPTED}" != "True" || \
      "${EBS_SIZE}" != "20" || \
      "${EBS_IOPS}" != "3000" || \
      "${EBS_THROUGHPUT}" != "125" || \
      "${EBS_STATE}" != "in-use" ]]; then
  echo "EBS volume ${VOLUME_ID} does not match the encrypted gp3 contract." >&2
  exit 1
fi

echo "==> Checking PostgreSQL connection"
DATABASE_NAME="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${POSTGRES_POD}" -- \
    psql -U postgres -d app -Atqc 'SELECT current_database();'
)"
SERVER_VERSION="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${POSTGRES_POD}" -- \
    psql -U postgres -d app -Atqc 'SHOW server_version;'
)"

if [[ "${DATABASE_NAME}" != "app" || "${SERVER_VERSION}" != 17.10* ]]; then
  echo "PostgreSQL connection or pinned server version validation failed." >&2
  exit 1
fi

echo "CloudNativePG PostgreSQL persistence baseline validation passed."

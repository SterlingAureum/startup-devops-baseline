#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
APPLICATION_NAME="${APPLICATION_NAME:-postgresql-baseline}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
DATABASE_NODE_POOL="${DATABASE_NODE_POOL:-database-ondemand}"
STORAGE_CLASS="${STORAGE_CLASS:-gp3-cnpg}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-1200}"
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
  echo "The ${STORAGE_CLASS} StorageClass does not match the v0.6.2 contract." >&2
  exit 1
fi

echo "==> Waiting for the three-instance PostgreSQL Cluster"
kubectl wait \
  --for=condition=Ready \
  "cluster/${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
while [[ "$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.readyInstances}'
)" != "3" ]]; do
  if (( SECONDS >= deadline )); then
    kubectl get cluster,pods,pvc \
      --namespace "${POSTGRES_NAMESPACE}" || true
    echo "Timed out waiting for three ready PostgreSQL instances." >&2
    exit 1
  fi
  sleep 10
done

echo "==> Checking PostgreSQL HA specification"
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
TOLERATION="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.affinity.tolerations[0].key}={.spec.affinity.tolerations[0].value}:{.spec.affinity.tolerations[0].effect}'
)"
ANTI_AFFINITY="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.affinity.enablePodAntiAffinity}:{.spec.affinity.podAntiAffinityType}:{.spec.affinity.topologyKey}'
)"
ZONE_AFFINITY="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[0].matchExpressions[0].key}:{.spec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[0].matchExpressions[0].operator}:{.spec.affinity.nodeAffinity.requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[0].matchExpressions[0].values[*]}'
)"
TOPOLOGY_SPREAD="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.topologySpreadConstraints[0].maxSkew}:{.spec.topologySpreadConstraints[0].minDomains}:{.spec.topologySpreadConstraints[0].topologyKey}:{.spec.topologySpreadConstraints[0].whenUnsatisfiable}:{.spec.topologySpreadConstraints[0].labelSelector.matchLabels.cnpg\.io/cluster}'
)"
SYNC_REPLICATION="$(
  kubectl get cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.spec.postgresql.synchronous.method}:{.spec.postgresql.synchronous.number}:{.spec.postgresql.synchronous.dataDurability}'
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

if [[ "${INSTANCES}" != "3" || \
      "${IMAGE_NAME}" != "${EXPECTED_IMAGE}" || \
      "${CLUSTER_STORAGE_CLASS}" != "${STORAGE_CLASS}" || \
      "${CLUSTER_STORAGE_SIZE}" != "20Gi" || \
      "${NODE_SELECTOR}" != "database" || \
      "${TOLERATION}" != "dedicated=database:NoSchedule" || \
      "${ANTI_AFFINITY}" != "true:required:kubernetes.io/hostname" || \
      "${ZONE_AFFINITY}" != \
        "topology.kubernetes.io/zone:In:us-east-1a us-east-1b" || \
      "${TOPOLOGY_SPREAD}" != \
        "1:2:topology.kubernetes.io/zone:DoNotSchedule:${POSTGRES_CLUSTER}" || \
      "${SYNC_REPLICATION}" != "any:1:required" || \
      "${DATABASE}" != "app" || \
      "${OWNER}" != "app" || \
      "${CPU_REQUEST}" != "500m" || \
      "${CPU_LIMIT}" != "500m" || \
      "${MEMORY_REQUEST}" != "1Gi" || \
      "${MEMORY_LIMIT}" != "1Gi" || \
      "${SHARED_BUFFERS}" != "256MB" ]]; then
  echo "The PostgreSQL Cluster spec does not match the v0.6.2 HA contract." >&2
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

echo "==> Checking PostgreSQL services"
for service_name in \
  "${POSTGRES_CLUSTER}-rw" \
  "${POSTGRES_CLUSTER}-ro" \
  "${POSTGRES_CLUSTER}-r"; do
  kubectl get service "${service_name}" \
    --namespace "${POSTGRES_NAMESPACE}" >/dev/null
done

echo "==> Checking persistent database NodeClaims"
kubectl wait \
  --for=condition=Ready \
  nodeclaim \
  --selector "karpenter.sh/nodepool=${DATABASE_NODE_POOL}" \
  --timeout="${WAIT_TIMEOUT}"
mapfile -t DATABASE_NODECLAIMS < <(
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${DATABASE_NODE_POOL}" \
    --output name
)
mapfile -t DATABASE_NODES < <(
  kubectl get nodes \
    --selector "karpenter.sh/nodepool=${DATABASE_NODE_POOL}" \
    --output name
)
if (( ${#DATABASE_NODECLAIMS[@]} != 3 || ${#DATABASE_NODES[@]} != 3 )); then
  echo "Expected three database NodeClaims and three database nodes." >&2
  exit 1
fi

echo "==> Checking PostgreSQL Pods, roles, nodes, and zones"
kubectl wait \
  --for=condition=Ready \
  pod \
  --namespace "${POSTGRES_NAMESPACE}" \
  --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
  --timeout="${WAIT_TIMEOUT}"

mapfile -t POSTGRES_PODS < <(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
    --field-selector status.phase=Running \
    --output name
)
if (( ${#POSTGRES_PODS[@]} != 3 )); then
  echo "Expected three running PostgreSQL Pods, found ${#POSTGRES_PODS[@]}." >&2
  exit 1
fi

declare -A POSTGRES_NODES=()
declare -A POSTGRES_ZONES=()
declare -A POD_ZONES=()
PRIMARY_POD=""
PRIMARY_COUNT=0
REPLICA_COUNT=0

for pod_resource in "${POSTGRES_PODS[@]}"; do
  pod_name="${pod_resource#pod/}"
  pod_role="$(
    kubectl get pod "${pod_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.metadata.labels.cnpg\.io/instanceRole}'
  )"
  pod_node="$(
    kubectl get pod "${pod_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.nodeName}'
  )"
  qos_class="$(
    kubectl get pod "${pod_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.status.qosClass}'
  )"
  workload_label="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.workload}'
  )"
  nodepool_label="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}'
  )"
  capacity_type="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/capacity-type}'
  )"
  pod_zone="$(
    kubectl get node "${pod_node}" \
      --output jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}'
  )"

  if [[ "${qos_class}" != "Guaranteed" || \
        "${workload_label}" != "database" || \
        "${nodepool_label}" != "${DATABASE_NODE_POOL}" || \
        "${capacity_type}" != "on-demand" || \
        -z "${pod_zone}" ]]; then
    echo "PostgreSQL Pod ${pod_name} has invalid capacity placement." >&2
    exit 1
  fi

  POSTGRES_NODES["${pod_node}"]=1
  POSTGRES_ZONES["${pod_zone}"]=$(( ${POSTGRES_ZONES["${pod_zone}"]:-0} + 1 ))
  POD_ZONES["${pod_name}"]="${pod_zone}"

  case "${pod_role}" in
    primary)
      PRIMARY_POD="${pod_name}"
      PRIMARY_COUNT=$((PRIMARY_COUNT + 1))
      ;;
    replica)
      REPLICA_COUNT=$((REPLICA_COUNT + 1))
      ;;
    *)
      echo "Unexpected PostgreSQL role ${pod_role} on ${pod_name}." >&2
      exit 1
      ;;
  esac
done

if (( ${#POSTGRES_NODES[@]} != 3 || \
      ${#POSTGRES_ZONES[@]} != 2 || \
      PRIMARY_COUNT != 1 || \
      REPLICA_COUNT != 2 )); then
  echo "PostgreSQL does not have 1 primary and 2 replicas across 3 nodes and 2 AZs." >&2
  exit 1
fi

for zone_count in "${POSTGRES_ZONES[@]}"; do
  if (( zone_count < 1 || zone_count > 2 )); then
    echo "PostgreSQL AZ distribution exceeds the required 2+1 maximum skew." >&2
    exit 1
  fi
done

echo "==> Checking all PostgreSQL PVCs, PVs, and EBS volumes"
mapfile -t POSTGRES_PVCS < <(
  kubectl get pvc \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
    --output name
)
if (( ${#POSTGRES_PVCS[@]} != 3 )); then
  echo "Expected three PostgreSQL PVCs, found ${#POSTGRES_PVCS[@]}." >&2
  exit 1
fi

for pvc_resource in "${POSTGRES_PVCS[@]}"; do
  pvc_name="${pvc_resource#persistentvolumeclaim/}"
  pvc_phase="$(
    kubectl get pvc "${pvc_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.status.phase}'
  )"
  pvc_storage_class="$(
    kubectl get pvc "${pvc_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.storageClassName}'
  )"
  pvc_capacity="$(
    kubectl get pvc "${pvc_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.status.capacity.storage}'
  )"
  pv_name="$(
    kubectl get pvc "${pvc_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.volumeName}'
  )"

  if [[ "${pvc_phase}" != "Bound" || \
        "${pvc_storage_class}" != "${STORAGE_CLASS}" || \
        "${pvc_capacity}" != "20Gi" || \
        -z "${pv_name}" || \
        -z "${POD_ZONES["${pvc_name}"]:-}" ]]; then
    echo "PVC ${pvc_name} does not match its PostgreSQL instance." >&2
    exit 1
  fi

  csi_driver="$(
    kubectl get pv "${pv_name}" \
      --output jsonpath='{.spec.csi.driver}'
  )"
  volume_id="$(
    kubectl get pv "${pv_name}" \
      --output jsonpath='{.spec.csi.volumeHandle}'
  )"
  if [[ "${csi_driver}" != "ebs.csi.aws.com" || "${volume_id}" != vol-* ]]; then
    echo "PV ${pv_name} is not backed by the AWS EBS CSI driver." >&2
    exit 1
  fi

  read -r \
    ebs_type \
    ebs_encrypted \
    ebs_size \
    ebs_iops \
    ebs_throughput \
    ebs_state \
    ebs_zone <<< "$(
      aws ec2 describe-volumes \
        --region "${AWS_REGION}" \
        --volume-ids "${volume_id}" \
        --query 'Volumes[0].[VolumeType,Encrypted,Size,Iops,Throughput,State,AvailabilityZone]' \
        --output text
    )"

  if [[ "${ebs_type}" != "gp3" || \
        "${ebs_encrypted}" != "True" || \
        "${ebs_size}" != "20" || \
        "${ebs_iops}" != "3000" || \
        "${ebs_throughput}" != "125" || \
        "${ebs_state}" != "in-use" || \
        "${ebs_zone}" != "${POD_ZONES["${pvc_name}"]}" ]]; then
    echo "EBS volume for ${pvc_name} violates the gp3 or AZ contract." >&2
    exit 1
  fi
done

echo "==> Checking PostgreSQL connection and synchronous replication"
DATABASE_NAME="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${PRIMARY_POD}" -- \
    psql -U postgres -d app -Atqc 'SELECT current_database();'
)"
SERVER_VERSION="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${PRIMARY_POD}" -- \
    psql -U postgres -d app -Atqc 'SHOW server_version;'
)"
PRIMARY_RECOVERY_STATE="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${PRIMARY_POD}" -- \
    psql -U postgres -d app -Atqc 'SELECT pg_is_in_recovery();'
)"
REPLICATION_COUNTS="$(
  kubectl exec \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    "${PRIMARY_POD}" -- \
    psql -U postgres -d app -AtF '|' -c \
    "SELECT count(*),
            count(*) FILTER (WHERE state = 'streaming'),
            count(*) FILTER (WHERE sync_state IN ('sync', 'quorum'))
       FROM pg_stat_replication;"
)"
IFS='|' read -r TOTAL_REPLICAS STREAMING_REPLICAS SYNCHRONOUS_REPLICAS \
  <<< "${REPLICATION_COUNTS}"

if [[ "${DATABASE_NAME}" != "app" || \
      "${SERVER_VERSION}" != 17.10* || \
      "${PRIMARY_RECOVERY_STATE}" != "f" || \
      "${TOTAL_REPLICAS}" != "2" || \
      "${STREAMING_REPLICAS}" != "2" || \
      "${SYNCHRONOUS_REPLICAS}" -lt 1 ]]; then
  echo "PostgreSQL connection or synchronous replication validation failed." >&2
  exit 1
fi

for pod_resource in "${POSTGRES_PODS[@]}"; do
  pod_name="${pod_resource#pod/}"
  if [[ "${pod_name}" == "${PRIMARY_POD}" ]]; then
    continue
  fi
  replica_recovery_state="$(
    kubectl exec \
      --namespace "${POSTGRES_NAMESPACE}" \
      --container postgres \
      "${pod_name}" -- \
      psql -U postgres -d app -Atqc 'SELECT pg_is_in_recovery();'
  )"
  if [[ "${replica_recovery_state}" != "t" ]]; then
    echo "PostgreSQL replica ${pod_name} is not in recovery." >&2
    exit 1
  fi
done

echo "CloudNativePG PostgreSQL cross-AZ HA and persistence validation passed."

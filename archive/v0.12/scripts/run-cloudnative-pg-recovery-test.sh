#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
SOURCE_CLUSTER="${SOURCE_CLUSTER:-postgresql-baseline}"
SOURCE_OBJECT_STORE="${SOURCE_OBJECT_STORE:-postgresql-baseline-backup}"
SHARED_SERVICE_ACCOUNT="${SHARED_SERVICE_ACCOUNT:-postgresql-baseline}"
RECOVERY_NODE_POOL="${RECOVERY_NODE_POOL:-database-recovery-ondemand}"
LATEST_CLUSTER="${LATEST_CLUSTER:-postgresql-recovery-latest}"
PITR_CLUSTER="${PITR_CLUSTER:-postgresql-recovery-pitr}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-ghcr.io/cloudnative-pg/postgresql:17.10-202607200905-system-bookworm@sha256:4c1e15c27bb33361d847db66e6516a9432a7388f8a5404e06eaa2d665f5836f6}"
BACKUP_TIMEOUT_SECONDS="${BACKUP_TIMEOUT_SECONDS:-1800}"
RECOVERY_TIMEOUT_SECONDS="${RECOVERY_TIMEOUT_SECONDS:-1800}"
WAL_TIMEOUT_SECONDS="${WAL_TIMEOUT_SECONDS:-600}"
CLEANUP_TIMEOUT_SECONDS="${CLEANUP_TIMEOUT_SECONDS:-900}"
RUN_ID="$(date -u +%Y%m%d%H%M%S)"
BACKUP_NAME="postgresql-recovery-${RUN_ID}"
BASE_MARKER="v0.6.4-${RUN_ID}-base"
KEEP_MARKER="v0.6.4-${RUN_ID}-keep"
EXCLUDE_MARKER="v0.6.4-${RUN_ID}-exclude"

for command in aws grep kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

cat <<EOF
WARNING: this test performs two isolated PostgreSQL recovery drills.

It writes three validation markers to ${POSTGRES_NAMESPACE}/${SOURCE_CLUSTER},
creates one physical base backup, and provisions temporary On-Demand recovery
capacity. It then:

1. restores a separate cluster to the latest archived state;
2. deletes its Cluster, PVC, EBS volume, and temporary node;
3. restores another separate cluster to a captured PITR target;
4. deletes the second recovery stack.

The source Cluster and its three persistent volumes are not deleted or
restarted.

Type 'restore-and-cleanup' to continue:
EOF

if [[ "${CONFIRM_POSTGRES_RECOVERY:-}" == "restore-and-cleanup" ]]; then
  confirmation="restore-and-cleanup"
else
  read -r confirmation
fi

if [[ "${confirmation}" != "restore-and-cleanup" ]]; then
  echo "CloudNativePG recovery test cancelled."
  exit 0
fi

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}"

BACKUP_BUCKET="$(
  terraform -chdir="${TF_DIR}" output -raw cnpg_backup_bucket_name
)"
if [[ -z "${BACKUP_BUCKET}" ]]; then
  echo "Terraform output cnpg_backup_bucket_name is empty." >&2
  exit 1
fi

source_primary_pod() {
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${SOURCE_CLUSTER},cnpg.io/instanceRole=primary" \
    --output jsonpath='{.items[0].metadata.name}'
}

source_sql() {
  local primary_pod
  primary_pod="$(source_primary_pod)"
  if [[ -z "${primary_pod}" ]]; then
    echo "Unable to resolve the source PostgreSQL primary Pod." >&2
    return 1
  fi
  kubectl exec "${primary_pod}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    -- psql -U postgres -d app -v ON_ERROR_STOP=1 -Atqc "$1"
}

wait_for_archived_wal() {
  local wal_segment
  local deadline
  local s3_keys

  wal_segment="$(
    source_sql "
      SELECT pg_walfile_name(
        pg_logical_emit_message(
          false,
          'v064-recovery',
          clock_timestamp()::text
        )
      );
    "
  )"
  if [[ ! "${wal_segment}" =~ ^[0-9A-F]{24}$ ]]; then
    echo "Unexpected WAL segment name: ${wal_segment}" >&2
    return 1
  fi
  source_sql "SELECT pg_switch_wal();" >/dev/null

  echo "==> Waiting for WAL segment ${wal_segment} in S3"
  deadline=$((SECONDS + WAL_TIMEOUT_SECONDS))
  while true; do
    s3_keys="$(
      aws s3api list-objects-v2 \
        --bucket "${BACKUP_BUCKET}" \
        --prefix "postgresql-baseline/" \
        --query 'Contents[].Key' \
        --output text
    )"
    if [[ "${s3_keys}" == *"${wal_segment}"* ]]; then
      break
    fi
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for WAL segment ${wal_segment} in S3." >&2
      return 1
    fi
    sleep 10
  done
}

recovery_volume_ids() {
  local cluster_name="$1"
  local pvc_resource
  local pvc_name
  local pv_name
  local volume_id

  while IFS= read -r pvc_resource; do
    [[ -n "${pvc_resource}" ]] || continue
    pvc_name="${pvc_resource#persistentvolumeclaim/}"
    pv_name="$(
      kubectl get pvc "${pvc_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.spec.volumeName}' 2>/dev/null || true
    )"
    [[ -n "${pv_name}" ]] || continue
    volume_id="$(
      kubectl get pv "${pv_name}" \
        --output jsonpath='{.spec.csi.volumeHandle}' 2>/dev/null || true
    )"
    if [[ "${volume_id}" == vol-* ]]; then
      printf '%s\n' "${volume_id}"
    fi
  done < <(
    kubectl get pvc \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${cluster_name}" \
      --output name 2>/dev/null || true
  )
}

wait_for_volume_deletion() {
  local volume_id="$1"
  local deadline=$((SECONDS + CLEANUP_TIMEOUT_SECONDS))
  while [[ "$(
    aws ec2 describe-volumes \
      --region "${AWS_REGION}" \
      --filters "Name=volume-id,Values=${volume_id}" \
      --query 'length(Volumes)' \
      --output text
  )" != "0" ]]; do
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for recovery EBS volume ${volume_id} deletion." >&2
      return 1
    fi
    sleep 10
  done
}

wait_for_recovery_capacity_cleanup() {
  local deadline=$((SECONDS + CLEANUP_TIMEOUT_SECONDS))
  while [[ -n "$(
    kubectl get nodeclaims \
      --selector "karpenter.sh/nodepool=${RECOVERY_NODE_POOL}" \
      --output name 2>/dev/null
  )" ]] || [[ -n "$(
    kubectl get nodes \
      --selector "karpenter.sh/nodepool=${RECOVERY_NODE_POOL}" \
      --output name 2>/dev/null
  )" ]]; do
    if (( SECONDS >= deadline )); then
      kubectl get nodeclaims,nodes \
        --selector "karpenter.sh/nodepool=${RECOVERY_NODE_POOL}" || true
      echo "Timed out waiting for temporary recovery capacity cleanup." >&2
      return 1
    fi
    sleep 10
  done
}

diagnose_recovery_cluster() {
  local cluster_name="$1"
  local pod_resource

  echo "==> Recovery diagnostics for ${cluster_name}" >&2
  kubectl get jobs,pods,pvc \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${cluster_name}" \
    --output wide \
    --show-labels >&2 || true
  kubectl describe cluster "${cluster_name}" \
    --namespace "${POSTGRES_NAMESPACE}" >&2 || true
  kubectl describe jobs \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${cluster_name}" >&2 || true

  while IFS= read -r pod_resource; do
    [[ -n "${pod_resource}" ]] || continue
    echo "==> Logs for ${pod_resource}" >&2
    kubectl logs "${pod_resource}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --all-containers \
      --prefix \
      --timestamps \
      --tail=-1 >&2 || true
  done < <(
    kubectl get pods \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${cluster_name}" \
      --output name 2>/dev/null || true
  )

  echo "==> Recent ${POSTGRES_NAMESPACE} events" >&2
  kubectl get events \
    --namespace "${POSTGRES_NAMESPACE}" \
    --sort-by='.lastTimestamp' 2>/dev/null |
    tail -n 100 >&2 || true
}

recovery_job_failed() {
  local cluster_name="$1"
  local job_conditions

  job_conditions="$(
    kubectl get jobs \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${cluster_name}" \
      --output jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Failed")].status}{"\n"}{end}' \
      2>/dev/null || true
  )"
  grep -q $'\tTrue$' <<<"${job_conditions}"
}

cleanup_recovery_cluster() {
  local cluster_name="$1"
  local volume_ids=()

  mapfile -t volume_ids < <(recovery_volume_ids "${cluster_name}")

  if kubectl get cluster "${cluster_name}" \
    --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
    echo "==> Deleting recovery Cluster ${cluster_name}"
    kubectl delete cluster "${cluster_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --wait=true \
      --timeout=20m
  fi

  kubectl delete pvc \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${cluster_name}" \
    --ignore-not-found=true \
    --wait=true \
    --timeout=20m 2>/dev/null || true

  for volume_id in "${volume_ids[@]}"; do
    echo "==> Waiting for recovery EBS volume ${volume_id} deletion"
    wait_for_volume_deletion "${volume_id}"
  done

  wait_for_recovery_capacity_cleanup
}

cleanup_on_exit() {
  local exit_code=$?
  local cleanup_failed=0
  trap - EXIT
  set +e
  cleanup_recovery_cluster "${LATEST_CLUSTER}" || cleanup_failed=1
  cleanup_recovery_cluster "${PITR_CLUSTER}" || cleanup_failed=1
  if (( exit_code != 0 )); then
    if (( cleanup_failed == 0 )); then
      echo "Recovery test failed; test-owned recovery resources were cleaned up." >&2
    else
      echo "Recovery test failed and automatic cleanup was incomplete." >&2
      echo "Inspect the two recovery Clusters, their PVCs, and the recovery NodePool." >&2
    fi
  fi
  exit "${exit_code}"
}
trap cleanup_on_exit EXIT

echo "==> Checking recovery prerequisites"
kubectl wait \
  --for=condition=Ready \
  "cluster/${SOURCE_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout=20m
kubectl wait \
  --for=jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'=True \
  "cluster/${SOURCE_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" \
  --timeout=20m
kubectl wait \
  --for=condition=Ready \
  "nodepool/${RECOVERY_NODE_POOL}" \
  --timeout=10m
kubectl get objectstore "${SOURCE_OBJECT_STORE}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null
kubectl get serviceaccount "${SHARED_SERVICE_ACCOUNT}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null

for recovery_cluster in "${LATEST_CLUSTER}" "${PITR_CLUSTER}"; do
  if kubectl get cluster "${recovery_cluster}" \
    --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
    echo "Recovery Cluster ${recovery_cluster} already exists." >&2
    echo "Remove the previous test resources before starting a new drill." >&2
    exit 1
  fi
done
if [[ -n "$(
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${RECOVERY_NODE_POOL}" \
    --output name
)" ]]; then
  echo "The recovery NodePool is not idle before the test." >&2
  exit 1
fi

SOURCE_CLUSTER_UID="$(
  kubectl get cluster "${SOURCE_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
SOURCE_STORAGE_CONTRACT="$(
  while IFS= read -r pvc_resource; do
    pvc_name="${pvc_resource#persistentvolumeclaim/}"
    pvc_uid="$(
      kubectl get pvc "${pvc_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.metadata.uid}'
    )"
    pv_name="$(
      kubectl get pvc "${pvc_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.spec.volumeName}'
    )"
    volume_id="$(
      kubectl get pv "${pv_name}" \
        --output jsonpath='{.spec.csi.volumeHandle}'
    )"
    printf '%s:%s:%s:%s\n' \
      "${pvc_name}" "${pvc_uid}" "${pv_name}" "${volume_id}"
  done < <(
    kubectl get pvc \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${SOURCE_CLUSTER}" \
      --output name | sort
  )
)"

echo "==> Writing the pre-backup recovery marker"
source_sql "
  CREATE TABLE IF NOT EXISTS public.platform_recovery_validation (
    marker text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
  );
  INSERT INTO public.platform_recovery_validation (marker)
  VALUES ('${BASE_MARKER}')
  ON CONFLICT (marker) DO NOTHING;
" >/dev/null
wait_for_archived_wal

echo "==> Creating deterministic recovery base backup ${BACKUP_NAME}"
kubectl create --namespace "${POSTGRES_NAMESPACE}" -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: ${BACKUP_NAME}
  labels:
    app.kubernetes.io/part-of: startup-devops-baseline
    platform.startup.dev/test: v0.6.4
spec:
  cluster:
    name: ${SOURCE_CLUSTER}
  method: plugin
  pluginConfiguration:
    name: barman-cloud.cloudnative-pg.io
  target: prefer-standby
EOF

deadline=$((SECONDS + BACKUP_TIMEOUT_SECONDS))
while true; do
  backup_phase="$(
    kubectl get backup "${BACKUP_NAME}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.status.phase}'
  )"
  case "${backup_phase}" in
    completed)
      break
      ;;
    failed)
      kubectl describe backup "${BACKUP_NAME}" \
        --namespace "${POSTGRES_NAMESPACE}" >&2
      echo "The v0.6.4 recovery base backup failed." >&2
      exit 1
      ;;
  esac
  if (( SECONDS >= deadline )); then
    kubectl describe backup "${BACKUP_NAME}" \
      --namespace "${POSTGRES_NAMESPACE}" >&2
    echo "Timed out waiting for the v0.6.4 recovery base backup." >&2
    exit 1
  fi
  sleep 10
done

echo "==> Writing the marker that PITR must preserve"
source_sql "
  INSERT INTO public.platform_recovery_validation (marker)
  VALUES ('${KEEP_MARKER}')
  ON CONFLICT (marker) DO NOTHING;
" >/dev/null

PITR_TARGET_TIME="$(
  source_sql "
    SELECT to_char(
      clock_timestamp() AT TIME ZONE 'UTC',
      'YYYY-MM-DD HH24:MI:SS.US'
    ) || '+00';
  "
)"
if [[ ! "${PITR_TARGET_TIME}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00$ ]]; then
  echo "Unexpected PITR target timestamp: ${PITR_TARGET_TIME}" >&2
  exit 1
fi

sleep 2
echo "==> Writing the marker that PITR must exclude"
source_sql "
  INSERT INTO public.platform_recovery_validation (marker)
  VALUES ('${EXCLUDE_MARKER}')
  ON CONFLICT (marker) DO NOTHING;
" >/dev/null
wait_for_archived_wal

apply_recovery_cluster() {
  local cluster_name="$1"
  local target_time="${2:-}"
  local recovery_target=""

  if [[ -n "${target_time}" ]]; then
    recovery_target="$(
      printf '      recoveryTarget:\n        targetTime: "%s"\n' "${target_time}"
    )"
  fi

  kubectl apply --namespace "${POSTGRES_NAMESPACE}" -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: ${cluster_name}
  labels:
    app.kubernetes.io/part-of: startup-devops-baseline
    platform.startup.dev/test: v0.6.4
spec:
  instances: 1
  imageName: ${POSTGRES_IMAGE}
  serviceAccountName: ${SHARED_SERVICE_ACCOUNT}
  enableSuperuserAccess: false
  bootstrap:
    recovery:
      source: origin
${recovery_target}
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        enabled: true
        parameters:
          barmanObjectName: ${SOURCE_OBJECT_STORE}
          serverName: ${SOURCE_CLUSTER}
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 500m
      memory: 1Gi
  affinity:
    nodeSelector:
      workload: database-recovery
    tolerations:
      - key: dedicated
        operator: Equal
        value: database-recovery
        effect: NoSchedule
  storage:
    storageClass: gp3-cnpg
    size: 20Gi
EOF
}

wait_for_recovery_cluster() {
  local cluster_name="$1"
  local started_at="$2"
  local deadline=$((SECONDS + RECOVERY_TIMEOUT_SECONDS))
  local phase
  local ready_status

  while true; do
    ready_status="$(
      kubectl get cluster "${cluster_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.status.conditions[?(@.type=="Ready")].status}' \
        2>/dev/null || true
    )"
    if [[ "${ready_status}" == "True" ]]; then
      break
    fi

    phase="$(
      kubectl get cluster "${cluster_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.status.phase}' 2>/dev/null || true
    )"
    if recovery_job_failed "${cluster_name}" || \
       [[ "${phase}" == *unrecoverable* ]]; then
      diagnose_recovery_cluster "${cluster_name}"
      echo "Recovery Cluster ${cluster_name} entered a terminal failure state." >&2
      return 1
    fi

    if (( SECONDS >= deadline )); then
      diagnose_recovery_cluster "${cluster_name}"
      echo "Timed out waiting for recovery Cluster ${cluster_name}." >&2
      return 1
    fi
    sleep 10
  done

  kubectl wait \
    --for=condition=Ready \
    pod \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${cluster_name},cnpg.io/podRole=instance" \
    --timeout=20m

  recovery_seconds=$(( $(date +%s) - started_at ))
  echo "Recovery Cluster ${cluster_name} became Ready in ${recovery_seconds}s."
}

recovery_sql() {
  local cluster_name="$1"
  local sql="$2"
  local pod_name
  pod_name="$(
    kubectl get pods \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${cluster_name},cnpg.io/instanceRole=primary" \
      --output jsonpath='{.items[0].metadata.name}'
  )"
  kubectl exec "${pod_name}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --container postgres \
    -- psql -U postgres -d app -v ON_ERROR_STOP=1 -Atqc "${sql}"
}

validate_recovery_placement() {
  local cluster_name="$1"
  local pod_name
  local node_name
  local node_pool
  local capacity_type
  local service_account
  local pvc_name
  local storage_contract
  local pv_name
  local volume_id
  local volume_contract

  pod_name="$(
    kubectl get pods \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${cluster_name},cnpg.io/podRole=instance" \
      --output jsonpath='{.items[0].metadata.name}'
  )"
  node_name="$(
    kubectl get pod "${pod_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.nodeName}'
  )"
  node_pool="$(
    kubectl get node "${node_name}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/nodepool}'
  )"
  capacity_type="$(
    kubectl get node "${node_name}" \
      --output jsonpath='{.metadata.labels.karpenter\.sh/capacity-type}'
  )"
  service_account="$(
    kubectl get pod "${pod_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.serviceAccountName}'
  )"
  pvc_name="$(
    kubectl get pvc \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${cluster_name}" \
      --output jsonpath='{.items[0].metadata.name}'
  )"
  storage_contract="$(
    kubectl get pvc "${pvc_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.storageClassName}:{.status.capacity.storage}'
  )"
  pv_name="$(
    kubectl get pvc "${pvc_name}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      --output jsonpath='{.spec.volumeName}'
  )"
  volume_id="$(
    kubectl get pv "${pv_name}" \
      --output jsonpath='{.spec.csi.volumeHandle}'
  )"
  volume_contract="$(
    aws ec2 describe-volumes \
      --region "${AWS_REGION}" \
      --volume-ids "${volume_id}" \
      --query 'Volumes[0].[Encrypted,VolumeType]' \
      --output text
  )"

  if [[ "${node_pool}" != "${RECOVERY_NODE_POOL}" || \
        "${capacity_type}" != "on-demand" || \
        "${service_account}" != "${SHARED_SERVICE_ACCOUNT}" || \
        "${storage_contract}" != "gp3-cnpg:20Gi" || \
        "${volume_id}" != vol-* || \
        "${volume_contract}" != $'True\tgp3' ]]; then
    echo "Recovery Cluster ${cluster_name} violated its placement, IRSA, or storage contract." >&2
    exit 1
  fi
}

echo "==> Restoring an independent Cluster to the latest archived state"
latest_started_at="$(date +%s)"
apply_recovery_cluster "${LATEST_CLUSTER}"
wait_for_recovery_cluster "${LATEST_CLUSTER}" "${latest_started_at}"
validate_recovery_placement "${LATEST_CLUSTER}"

for marker in "${BASE_MARKER}" "${KEEP_MARKER}" "${EXCLUDE_MARKER}"; do
  marker_count="$(
    recovery_sql "${LATEST_CLUSTER}" \
      "SELECT count(*) FROM public.platform_recovery_validation WHERE marker = '${marker}';"
  )"
  if [[ "${marker_count}" != "1" ]]; then
    echo "Latest recovery is missing expected marker ${marker}." >&2
    exit 1
  fi
done
echo "Latest-state recovery data validation passed."
cleanup_recovery_cluster "${LATEST_CLUSTER}"

echo "==> Restoring an independent Cluster to ${PITR_TARGET_TIME}"
pitr_started_at="$(date +%s)"
apply_recovery_cluster "${PITR_CLUSTER}" "${PITR_TARGET_TIME}"
wait_for_recovery_cluster "${PITR_CLUSTER}" "${pitr_started_at}"
validate_recovery_placement "${PITR_CLUSTER}"

for marker in "${BASE_MARKER}" "${KEEP_MARKER}"; do
  marker_count="$(
    recovery_sql "${PITR_CLUSTER}" \
      "SELECT count(*) FROM public.platform_recovery_validation WHERE marker = '${marker}';"
  )"
  if [[ "${marker_count}" != "1" ]]; then
    echo "PITR recovery is missing expected marker ${marker}." >&2
    exit 1
  fi
done
excluded_count="$(
  recovery_sql "${PITR_CLUSTER}" \
    "SELECT count(*) FROM public.platform_recovery_validation WHERE marker = '${EXCLUDE_MARKER}';"
)"
if [[ "${excluded_count}" != "0" ]]; then
  echo "PITR recovery incorrectly contains post-target marker ${EXCLUDE_MARKER}." >&2
  exit 1
fi
echo "Point-in-time recovery data validation passed."
cleanup_recovery_cluster "${PITR_CLUSTER}"

echo "==> Confirming the source Cluster and storage were untouched"
CURRENT_SOURCE_CLUSTER_UID="$(
  kubectl get cluster "${SOURCE_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
CURRENT_SOURCE_STORAGE_CONTRACT="$(
  while IFS= read -r pvc_resource; do
    pvc_name="${pvc_resource#persistentvolumeclaim/}"
    pvc_uid="$(
      kubectl get pvc "${pvc_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.metadata.uid}'
    )"
    pv_name="$(
      kubectl get pvc "${pvc_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.spec.volumeName}'
    )"
    volume_id="$(
      kubectl get pv "${pv_name}" \
        --output jsonpath='{.spec.csi.volumeHandle}'
    )"
    printf '%s:%s:%s:%s\n' \
      "${pvc_name}" "${pvc_uid}" "${pv_name}" "${volume_id}"
  done < <(
    kubectl get pvc \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster=${SOURCE_CLUSTER}" \
      --output name | sort
  )
)"
READY_INSTANCES="$(
  kubectl get cluster "${SOURCE_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.readyInstances}'
)"
SOURCE_MARKER_COUNT="$(
  source_sql "
    SELECT count(*)
      FROM public.platform_recovery_validation
     WHERE marker IN ('${BASE_MARKER}', '${KEEP_MARKER}', '${EXCLUDE_MARKER}');
  "
)"

if [[ "${CURRENT_SOURCE_CLUSTER_UID}" != "${SOURCE_CLUSTER_UID}" || \
      "${CURRENT_SOURCE_STORAGE_CONTRACT}" != "${SOURCE_STORAGE_CONTRACT}" || \
      "${READY_INSTANCES}" != "3" || \
      "${SOURCE_MARKER_COUNT}" != "3" ]]; then
  echo "The source PostgreSQL Cluster changed during the recovery drill." >&2
  exit 1
fi

trap - EXIT
echo "CloudNativePG latest recovery, PITR, data integrity, and cleanup validation passed."
echo "Base backup: ${POSTGRES_NAMESPACE}/${BACKUP_NAME}"
echo "PITR target: ${PITR_TARGET_TIME}"

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ENVIRONMENT="${AWS_ENVIRONMENT:-aws-dev}"
# shellcheck source=scripts/aws-environment-context.sh
source "${ROOT_DIR}/scripts/aws-environment-context.sh"
configure_aws_environment_context

if [[ "${AWS_ENVIRONMENT}" == "aws-prod" ]]; then
  echo "This portfolio destroy entrypoint refuses aws-prod." >&2
  exit 1
fi

ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
POSTGRES_APPLICATION="${POSTGRES_APPLICATION:-postgresql-baseline}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
POSTGRES_STORAGE_CLASS="${POSTGRES_STORAGE_CLASS:-gp3-cnpg}"
DEMO_DATABASE_SECRET="${DEMO_DATABASE_SECRET:-demo-api-postgresql}"
ALB_WAIT_SECONDS="${ALB_WAIT_SECONDS:-600}"
KARPENTER_WAIT_SECONDS="${KARPENTER_WAIT_SECONDS:-600}"
EBS_WAIT_SECONDS="${EBS_WAIT_SECONDS:-600}"
RECONCILE_DNS_SCRIPT="${ROOT_DIR}/scripts/reconcile-demo-api-dns.sh"
DESTROY_DEPENDENCY_SCRIPT="${ROOT_DIR}/scripts/converge-aws-destroy-dependencies.sh"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'ERROR: required command not found: %s
' "$1" >&2
    exit 1
  }
}

for command_name in aws jq kubectl terraform; do
  require_command "${command_name}"
done

[[ -x "${DESTROY_DEPENDENCY_SCRIPT}" ]] || {
  echo "Required destroy dependency helper is not executable." >&2
  exit 1
}

cat <<EOF
WARNING: this operation will destroy the ${AWS_ENVIRONMENT} environment.

Cluster: ${CLUSTER_NAME}
Region: ${AWS_REGION}
Terraform directory: ${TF_DIR}

Expected resources include EKS, EC2 nodes, NAT Gateway, VPC, ALB-related
resources, applications, and the CloudNativePG S3 backup bucket.

The ${AWS_ENVIRONMENT} backup bucket uses force_destroy=true. Terraform will permanently
delete all base backups, WAL archives, current objects, and noncurrent object
versions.
EOF

if [[ "${AWS_ENVIRONMENT}" == "aws-dev" ]]; then
  expected_confirmation="destroy-with-backups"
else
  expected_confirmation="destroy-aws-test-with-backups"
fi
if [[ -n "${CONFIRM_AWS_ENVIRONMENT_DESTROY:-}" ]]; then
  confirmation="${CONFIRM_AWS_ENVIRONMENT_DESTROY}"
  echo "Confirmation supplied through CONFIRM_AWS_ENVIRONMENT_DESTROY; continuing."
else
  read -r -p "Type '${expected_confirmation}' to continue: " confirmation
fi
if [[ "${confirmation}" != "${expected_confirmation}" ]]; then
  echo "Destroy cancelled."
  exit 0
fi

DESTROY_VPC_ID="$(terraform -chdir="${TF_DIR}" output -raw vpc_id 2>/dev/null || true)"
if [[ -n "${DESTROY_VPC_ID}" && ! "${DESTROY_VPC_ID}" =~ ^vpc-[0-9a-f]+$ ]]; then
  echo "Terraform returned an invalid destroy VPC identity." >&2
  exit 1
fi

CLUSTER_AVAILABLE=false
EKS_PUBLIC_ACCESS_CIDRS_JSON="[]"
if cluster_json="$(aws eks describe-cluster \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" \
  --output json 2>&1)"; then
  CLUSTER_AVAILABLE=true
  EKS_PUBLIC_ACCESS_CIDRS_JSON="$(jq -c \
    '.cluster.resourcesVpcConfig.publicAccessCidrs' <<<"${cluster_json}")"
  jq --exit-status '
    type == "array" and length > 0 and
    all(.[]; test("^[0-9./]+$") and . != "0.0.0.0/0")
  ' <<<"${EKS_PUBLIC_ACCESS_CIDRS_JSON}" >/dev/null || {
    echo "The live EKS public endpoint allowlist is empty, open, or invalid." >&2
    exit 1
  }
elif grep -q 'ResourceNotFoundException' <<<"${cluster_json}"; then
  echo "EKS cluster ${CLUSTER_NAME} is already absent."
  echo "Skipping Kubernetes pre-destroy cleanup and resuming Terraform teardown."
else
  echo "Unable to determine whether EKS cluster ${CLUSTER_NAME} exists:" >&2
  printf '%s\n' "${cluster_json}" >&2
  exit 1
fi

if [[ "${CLUSTER_AVAILABLE}" == "true" ]]; then
  aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}"

EBS_PVC_RECORDS=()
while IFS= read -r pvc_record; do
  [[ -n "${pvc_record}" ]] || continue
  EBS_PVC_RECORDS+=("${pvc_record}")
done < <(
  kubectl get pv -o json | jq -r '
    .items[]
    | select(.spec.csi.driver == "ebs.csi.aws.com")
    | select(.spec.claimRef.namespace != null)
    | select(.spec.claimRef.name != null)
    | [
        .spec.claimRef.namespace,
        .spec.claimRef.name,
        .spec.csi.volumeHandle
      ]
    | @tsv
  '
)
printf 'Captured %s EBS-backed PVC identity record(s).\n' "${#EBS_PVC_RECORDS[@]}"

ROOT_APPLICATION_EXISTS=false
if kubectl get application "${ROOT_APPLICATION}" -n "${ARGOCD_NAMESPACE}" >/dev/null 2>&1; then
  ROOT_APPLICATION_EXISTS=true
  echo "==> Suspending root Application automation"
  kubectl patch application "${ROOT_APPLICATION}" \
    --namespace "${ARGOCD_NAMESPACE}" \
    --type merge \
    --patch '{"spec":{"syncPolicy":{"automated":null}}}'
fi

if kubectl get application "${POSTGRES_APPLICATION}" \
  -n "${ARGOCD_NAMESPACE}" >/dev/null 2>&1; then
  echo "==> Suspending PostgreSQL Application automation"
  kubectl patch application "${POSTGRES_APPLICATION}" \
    --namespace "${ARGOCD_NAMESPACE}" \
    --type merge \
    --patch '{"spec":{"syncPolicy":{"automated":null}}}'
fi

POSTGRES_VOLUME_IDS=()
if kubectl get namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
  while IFS= read -r pvc_resource; do
    [[ -n "${pvc_resource}" ]] || continue
    pvc_name="${pvc_resource#persistentvolumeclaim/}"
    pv_name="$(
      kubectl get pvc "${pvc_name}" \
        --namespace "${POSTGRES_NAMESPACE}" \
        --output jsonpath='{.spec.volumeName}'
    )"
    [[ -n "${pv_name}" ]] || continue
    volume_id="$(
      kubectl get pv "${pv_name}" \
        --output jsonpath='{.spec.csi.volumeHandle}'
    )"
    if [[ "${volume_id}" == vol-* ]]; then
      POSTGRES_VOLUME_IDS+=("${volume_id}")
    fi
  done < <(
    kubectl get pvc \
      --namespace "${POSTGRES_NAMESPACE}" \
      --selector "cnpg.io/cluster" \
      --output name
  )
fi

if kubectl get cluster "${POSTGRES_CLUSTER}" \
  --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; then
  echo "==> Deleting PostgreSQL Cluster and persistent storage"
  kubectl delete cluster "${POSTGRES_CLUSTER}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --wait=true \
    --timeout=15m
fi

kubectl delete pvc \
  --namespace "${POSTGRES_NAMESPACE}" \
  --selector "cnpg.io/cluster=${POSTGRES_CLUSTER}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout=15m 2>/dev/null || true
kubectl delete namespace "${POSTGRES_NAMESPACE}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout=15m
kubectl delete storageclass "${POSTGRES_STORAGE_CLASS}" \
  --ignore-not-found=true

for volume_id in "${POSTGRES_VOLUME_IDS[@]}"; do
  echo "==> Waiting for PostgreSQL EBS volume ${volume_id} to be deleted"
  deadline=$((SECONDS + EBS_WAIT_SECONDS))
  while [[ "$(
    aws ec2 describe-volumes \
      --region "${AWS_REGION}" \
      --filters "Name=volume-id,Values=${volume_id}" \
      --query 'length(Volumes)' \
      --output text
  )" != "0" ]]; do
    if (( SECONDS >= deadline )); then
      echo "ERROR: timed out waiting for EBS volume ${volume_id} deletion." >&2
      exit 1
    fi
    sleep 15
  done
done

for smoke_namespace in karpenter-smoke karpenter-spot-smoke karpenter-fis-smoke; do
  kubectl delete namespace "${smoke_namespace}" \
    --ignore-not-found=true \
    --wait=false
done

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

echo "==> Deleting the demo-api Route 53 Alias before the ALB"
AWS_REGION="${AWS_REGION}" \
CLUSTER_NAME="${CLUSTER_NAME}" \
DEMO_HOSTNAME="${DEMO_HOSTNAME}" \
DNS_ACTION=delete \
  "${RECONCILE_DNS_SCRIPT}"

if [[ "${ROOT_APPLICATION_EXISTS}" == "true" ]]; then
  echo "==> Deleting the Root Application and waiting for child pruning"
  kubectl delete application "${ROOT_APPLICATION}" \
    --namespace "${ARGOCD_NAMESPACE}" \
    --wait=true \
    --timeout=15m
else
  echo "Root Application not found; continuing."
fi

echo "==> Deleting every captured EBS-backed PVC"
for pvc_record in "${EBS_PVC_RECORDS[@]}"; do
  IFS=$'\t' read -r pvc_namespace pvc_name volume_id <<<"${pvc_record}"
  [[ "${volume_id}" == vol-* ]] || {
    echo "Refusing invalid captured EBS volume identity: ${volume_id}" >&2
    exit 1
  }
  if kubectl get namespace "${pvc_namespace}" >/dev/null 2>&1; then
    kubectl delete pvc "${pvc_name}" \
      --namespace "${pvc_namespace}" \
      --ignore-not-found=true \
      --wait=true \
      --timeout=15m
  fi
done

if kubectl get namespace "${APP_NAMESPACE}" >/dev/null 2>&1; then
  kubectl delete ingress --all -n "${APP_NAMESPACE}" --ignore-not-found=true --wait=false
  kubectl delete secret "${DEMO_DATABASE_SECRET}" \
    --namespace "${APP_NAMESPACE}" \
    --ignore-not-found=true
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
fi

run_dependency_convergence() {
  local mode="$1"
  [[ -n "${DESTROY_VPC_ID}" ]] || return 0
  AWS_ENVIRONMENT="${AWS_ENVIRONMENT}" \
  DESTROY_VPC_ID="${DESTROY_VPC_ID}" \
  INTERNAL_AWS_DESTROY_DEPENDENCY_TOKEN="converge-reviewed-destroy-dependencies" \
    "${DESTROY_DEPENDENCY_SCRIPT}" "${mode}"
}

run_terraform_destroy() {
  terraform -chdir="${TF_DIR}" destroy \
    -var="eks_public_access_cidrs=${EKS_PUBLIC_ACCESS_CIDRS_JSON}"
}

assert_retry_state_is_vpc_only() {
  local remaining_state unexpected_state
  remaining_state="$(terraform -chdir="${TF_DIR}" state list)"
  unexpected_state="$(sed '/^$/d' <<<"${remaining_state}" | grep -Ev \
    '^module\.vpc\.aws_(subnet\.(private|public)\[|vpc\.this$)' || true)"
  if [[ -n "${unexpected_state}" ]]; then
    echo "Terraform destroy failed with non-VPC state remaining:" >&2
    printf '%s\n' "${unexpected_state}" >&2
    echo "Refusing automatic dependency convergence and retry." >&2
    return 1
  fi
}

run_dependency_convergence pre-terraform

if run_terraform_destroy; then
  run_dependency_convergence post-success
else
  terraform_destroy_exit=$?
  echo "Terraform destroy exited ${terraform_destroy_exit}; inspecting exact residual state." >&2
  assert_retry_state_is_vpc_only
  run_dependency_convergence post-failure
  echo "Known dynamic dependencies converged. Review the new Terraform plan and confirm again."
  run_terraform_destroy
  run_dependency_convergence post-success
fi

echo "==> Retiring Karpenter Instant Fleet request records"
TAGGED_FLEET_JSON="$(aws resourcegroupstaggingapi get-resources \
  --region "${AWS_REGION}" \
  --resource-type-filters ec2:fleet \
  --tag-filters \
    "Key=Project,Values=${PROJECT_NAME}" \
    "Key=Environment,Values=${ENVIRONMENT_SHORT}" \
  --output json)"
while IFS= read -r fleet_id; do
  [[ -n "${fleet_id}" ]] || continue
  if fleet_json="$(aws ec2 describe-fleets \
    --region "${AWS_REGION}" \
    --fleet-ids "${fleet_id}" \
    --output json 2>&1)"; then
    fleet_type="$(jq -r '.Fleets[0].Type // empty' <<<"${fleet_json}")"
    fleet_state="$(jq -r '.Fleets[0].FleetState // empty' <<<"${fleet_json}")"
    case "${fleet_state}" in
      deleted|deleted_terminating)
        echo "EC2 Fleet ${fleet_id} is already terminal (${fleet_state})."
        ;;
      active)
        if [[ "${fleet_type}" != "instant" ]]; then
          echo "Refusing to delete unexpected active EC2 Fleet ${fleet_id} (${fleet_type:-unknown})." >&2
          exit 1
        fi
        echo "Deleting terminal-capacity Instant Fleet record ${fleet_id}."
        aws ec2 delete-fleets \
          --region "${AWS_REGION}" \
          --fleet-ids "${fleet_id}" \
          --terminate-instances >/dev/null
        ;;
      *)
        echo "EC2 Fleet ${fleet_id} has unexpected state ${fleet_state:-unknown}." >&2
        exit 1
        ;;
    esac
  elif grep -q 'InvalidFleetId\.NotFound' <<<"${fleet_json}"; then
    echo "EC2 Fleet ${fleet_id} has already expired."
  else
    echo "Unable to classify EC2 Fleet ${fleet_id}:" >&2
    printf '%s\n' "${fleet_json}" >&2
    exit 1
  fi
done < <(
  jq -r '.ResourceTagMappingList[].ResourceARN' <<<"${TAGGED_FLEET_JSON}" |
    sed -n 's#^.*/\(fleet-[[:alnum:]-]*\)$#\1#p'
)

echo "${AWS_ENVIRONMENT} destroy completed."
echo "Next: AWS_ENVIRONMENT=${AWS_ENVIRONMENT} ./scripts/validate-aws-cost-cleanup.sh"

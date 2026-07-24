#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
NODE_CLASS_NAME="${FIS_NODE_CLASS_NAME:-application-fis}"
NODE_POOL_NAME="${FIS_NODE_POOL_NAME:-application-spot-fis}"
TEST_NAMESPACE="${TEST_NAMESPACE:-karpenter-fis-smoke}"
TEST_DEPLOYMENT="${TEST_DEPLOYMENT:-karpenter-fis-spot-test}"
TEST_MANIFEST="${TEST_MANIFEST:-${ROOT_DIR}/examples/karpenter/fis-spot-interruption-test.yaml}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-15m}"
REPLACEMENT_TIMEOUT_SECONDS="${REPLACEMENT_TIMEOUT_SECONDS:-900}"
SCALE_IN_TIMEOUT_SECONDS="${SCALE_IN_TIMEOUT_SECONDS:-1200}"
EXPERIMENT_TIMEOUT_SECONDS="${EXPERIMENT_TIMEOUT_SECONDS:-900}"
TEST_APPLIED=false
EXPERIMENT_ID=""

for command in aws kubectl terraform; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

fis_nodeclaims() {
  kubectl get nodeclaims \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
    --output name
}

fis_nodes() {
  kubectl get nodes \
    --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
    --output name
}

cleanup_on_exit() {
  local exit_code=$?

  if [[ -n "${EXPERIMENT_ID}" ]]; then
    local experiment_state
    experiment_state="$(
      aws fis get-experiment \
        --region "${AWS_REGION}" \
        --id "${EXPERIMENT_ID}" \
        --query 'experiment.state.status' \
        --output text 2>/dev/null || true
    )"
    if [[ "${experiment_state}" == "initiating" || "${experiment_state}" == "running" ]]; then
      aws fis stop-experiment \
        --region "${AWS_REGION}" \
        --id "${EXPERIMENT_ID}" >/dev/null 2>&1 || true
    fi
  fi

  if [[ "${TEST_APPLIED}" == "true" ]]; then
    echo "==> Cleaning up the FIS Spot test workload"
    kubectl delete -f "${TEST_MANIFEST}" \
      --ignore-not-found=true \
      --wait=false >/dev/null 2>&1 || true
    kubectl delete nodeclaim \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
      --ignore-not-found=true \
      --wait=false >/dev/null 2>&1 || true
  fi

  exit "${exit_code}"
}
trap cleanup_on_exit EXIT

cat <<EOF
WARNING: this drill starts a real AWS FIS experiment.

One EC2 Spot instance tagged for ${NODE_POOL_NAME} will receive an interruption
notice and will be terminated. The test creates temporary EC2 and EBS charges.
The interruption cannot be undone after EC2 accepts it.

Type 'interrupt' to continue:
EOF

if [[ "${CONFIRM_FIS_INTERRUPT:-}" == "interrupt" ]]; then
  confirmation="interrupt"
else
  read -r confirmation
fi

if [[ "${confirmation}" != "interrupt" ]]; then
  echo "FIS Spot interruption drill cancelled."
  exit 0
fi

"${ROOT_DIR}/scripts/validate-karpenter-interruption.sh"
"${ROOT_DIR}/scripts/validate-karpenter-fis.sh"

TEMPLATE_ID="$(
  terraform -chdir="${TF_DIR}" output -raw \
    karpenter_fis_experiment_template_id
)"
TARGET_TAG_KEY="$(
  terraform -chdir="${TF_DIR}" output -raw \
    karpenter_fis_target_tag_key
)"
TARGET_TAG_VALUE="$(
  terraform -chdir="${TF_DIR}" output -raw \
    karpenter_fis_target_tag_value
)"

if [[ -n "$(fis_nodeclaims)" ]] || [[ -n "$(fis_nodes)" ]]; then
  echo "The FIS drill requires an empty ${NODE_POOL_NAME} baseline." >&2
  exit 1
fi

ACTIVE_EXPERIMENTS="$(
  aws fis list-experiments \
    --region "${AWS_REGION}" \
    --query "length(experiments[?experimentTemplateId=='${TEMPLATE_ID}' && (state.status=='initiating' || state.status=='running')])" \
    --output text
)"

if [[ "${ACTIVE_EXPERIMENTS}" != "0" ]]; then
  echo "An experiment from template ${TEMPLATE_ID} is already active." >&2
  exit 1
fi

echo "==> Applying isolated FIS Spot workload"
kubectl apply -f "${TEST_MANIFEST}"
TEST_APPLIED=true

if ! kubectl rollout status "deployment/${TEST_DEPLOYMENT}" \
  --namespace "${TEST_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"; then
  kubectl get pods -n "${TEST_NAMESPACE}" -o wide || true
  kubectl get nodeclaims || true
  kubectl get events -n "${TEST_NAMESPACE}" \
    --sort-by='.metadata.creationTimestamp' || true
  echo "FIS test capacity was not provisioned before the timeout." >&2
  exit 1
fi

ORIGINAL_POD="$(
  kubectl get pods \
    --namespace "${TEST_NAMESPACE}" \
    --selector "app.kubernetes.io/name=${TEST_DEPLOYMENT}" \
    --output jsonpath='{.items[0].metadata.name}'
)"
ORIGINAL_POD_UID="$(
  kubectl get pod "${ORIGINAL_POD}" \
    --namespace "${TEST_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
ORIGINAL_NODE="$(
  kubectl get pod "${ORIGINAL_POD}" \
    --namespace "${TEST_NAMESPACE}" \
    --output jsonpath='{.spec.nodeName}'
)"
ORIGINAL_NODECLAIM="$(
  kubectl get node "${ORIGINAL_NODE}" \
    --output jsonpath='{.metadata.labels.karpenter\.sh/nodeclaim}'
)"
ORIGINAL_PROVIDER_ID="$(
  kubectl get node "${ORIGINAL_NODE}" \
    --output jsonpath='{.spec.providerID}'
)"
ORIGINAL_INSTANCE_ID="${ORIGINAL_PROVIDER_ID##*/}"

if [[ "${ORIGINAL_INSTANCE_ID}" != i-* || -z "${ORIGINAL_NODECLAIM}" ]]; then
  echo "Could not resolve the original EC2 instance or NodeClaim." >&2
  exit 1
fi

ORIGINAL_LIFECYCLE="$(
  aws ec2 describe-instances \
    --region "${AWS_REGION}" \
    --instance-ids "${ORIGINAL_INSTANCE_ID}" \
    --query 'Reservations[0].Instances[0].InstanceLifecycle' \
    --output text
)"
ORIGINAL_TARGET_TAG="$(
  aws ec2 describe-tags \
    --region "${AWS_REGION}" \
    --filters \
      "Name=resource-id,Values=${ORIGINAL_INSTANCE_ID}" \
      "Name=key,Values=${TARGET_TAG_KEY}" \
    --query 'Tags[0].Value' \
    --output text
)"

if [[ "${ORIGINAL_LIFECYCLE}" != "spot" || \
      "${ORIGINAL_TARGET_TAG}" != "${TARGET_TAG_VALUE}" ]]; then
  echo "The original node is not the expected tag-isolated Spot target." >&2
  exit 1
fi

mapfile -t TARGET_INSTANCE_IDS < <(
  aws ec2 describe-instances \
    --region "${AWS_REGION}" \
    --filters \
      "Name=tag:${TARGET_TAG_KEY},Values=${TARGET_TAG_VALUE}" \
      "Name=instance-state-name,Values=running" \
      "Name=instance-lifecycle,Values=spot" \
    --query 'Reservations[].Instances[].InstanceId' \
    --output text |
    tr '\t' '\n'
)

if (( ${#TARGET_INSTANCE_IDS[@]} != 1 )) || \
   [[ "${TARGET_INSTANCE_IDS[0]}" != "${ORIGINAL_INSTANCE_ID}" ]]; then
  echo "FIS target resolution is not limited to the original Spot instance." >&2
  printf 'Resolved targets: %s\n' "${TARGET_INSTANCE_IDS[*]:-none}" >&2
  exit 1
fi

echo "==> Starting AWS FIS experiment against ${ORIGINAL_INSTANCE_ID}"
EXPERIMENT_ID="$(
  aws fis start-experiment \
    --region "${AWS_REGION}" \
    --experiment-template-id "${TEMPLATE_ID}" \
    --tags "Name=${CLUSTER_NAME}-karpenter-spot-drill" \
    --query 'experiment.id' \
    --output text
)"

if [[ -z "${EXPERIMENT_ID}" || "${EXPERIMENT_ID}" == "None" ]]; then
  echo "AWS FIS did not return an experiment ID." >&2
  exit 1
fi

echo "==> Waiting for the experiment to start"
deadline=$((SECONDS + EXPERIMENT_TIMEOUT_SECONDS))
while true; do
  EXPERIMENT_STATE="$(
    aws fis get-experiment \
      --region "${AWS_REGION}" \
      --id "${EXPERIMENT_ID}" \
      --query 'experiment.state.status' \
      --output text
  )"

  case "${EXPERIMENT_STATE}" in
    running|completed)
      break
      ;;
    failed|stopped|cancelled)
      EXPERIMENT_REASON="$(
        aws fis get-experiment \
          --region "${AWS_REGION}" \
          --id "${EXPERIMENT_ID}" \
          --query 'experiment.state.reason' \
          --output text
      )"
      echo "AWS FIS experiment ${EXPERIMENT_STATE}: ${EXPERIMENT_REASON}" >&2
      exit 1
      ;;
  esac

  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for AWS FIS experiment to start." >&2
    exit 1
  fi
  sleep 10
done

echo "==> Waiting for Karpenter replacement and Pod rescheduling"
REPLACEMENT_POD=""
REPLACEMENT_NODE=""
deadline=$((SECONDS + REPLACEMENT_TIMEOUT_SECONDS))
while [[ -z "${REPLACEMENT_NODE}" ]]; do
  while IFS='|' read -r pod_uid pod_name node_name ready_status; do
    if [[ -n "${pod_uid}" && \
          "${pod_uid}" != "${ORIGINAL_POD_UID}" && \
          "${node_name}" != "${ORIGINAL_NODE}" && \
          "${ready_status}" == "True" ]]; then
      REPLACEMENT_POD="${pod_name}"
      REPLACEMENT_NODE="${node_name}"
      break
    fi
  done < <(
    kubectl get pods \
      --namespace "${TEST_NAMESPACE}" \
      --selector "app.kubernetes.io/name=${TEST_DEPLOYMENT}" \
      --output jsonpath='{range .items[?(@.status.phase=="Running")]}{.metadata.uid}{"|"}{.metadata.name}{"|"}{.spec.nodeName}{"|"}{range .status.conditions[?(@.type=="Ready")]}{.status}{end}{"\n"}{end}'
  )

  if [[ -n "${REPLACEMENT_NODE}" ]]; then
    break
  fi
  if (( SECONDS >= deadline )); then
    kubectl get pods -n "${TEST_NAMESPACE}" -o wide || true
    kubectl get nodes \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" || true
    kubectl get nodeclaims \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" || true
    echo "Timed out waiting for a Ready Pod on a replacement node." >&2
    exit 1
  fi
  sleep 10
done

REPLACEMENT_PROVIDER_ID="$(
  kubectl get node "${REPLACEMENT_NODE}" \
    --output jsonpath='{.spec.providerID}'
)"
REPLACEMENT_INSTANCE_ID="${REPLACEMENT_PROVIDER_ID##*/}"
REPLACEMENT_LIFECYCLE="$(
  aws ec2 describe-instances \
    --region "${AWS_REGION}" \
    --instance-ids "${REPLACEMENT_INSTANCE_ID}" \
    --query 'Reservations[0].Instances[0].InstanceLifecycle' \
    --output text
)"
REPLACEMENT_TARGET_TAG="$(
  aws ec2 describe-tags \
    --region "${AWS_REGION}" \
    --filters \
      "Name=resource-id,Values=${REPLACEMENT_INSTANCE_ID}" \
      "Name=key,Values=${TARGET_TAG_KEY}" \
    --query 'Tags[0].Value' \
    --output text
)"

if [[ "${REPLACEMENT_INSTANCE_ID}" == "${ORIGINAL_INSTANCE_ID}" || \
      "${REPLACEMENT_LIFECYCLE}" != "spot" || \
      "${REPLACEMENT_TARGET_TAG}" != "${TARGET_TAG_VALUE}" ]]; then
  echo "The replacement Pod is not running on a new tag-isolated Spot instance." >&2
  exit 1
fi

echo "==> Waiting for experiment completion and original instance termination"
deadline=$((SECONDS + EXPERIMENT_TIMEOUT_SECONDS))
while true; do
  EXPERIMENT_STATE="$(
    aws fis get-experiment \
      --region "${AWS_REGION}" \
      --id "${EXPERIMENT_ID}" \
      --query 'experiment.state.status' \
      --output text
  )"
  ORIGINAL_INSTANCE_STATE="$(
    aws ec2 describe-instances \
      --region "${AWS_REGION}" \
      --instance-ids "${ORIGINAL_INSTANCE_ID}" \
      --query 'Reservations[0].Instances[0].State.Name' \
      --output text
  )"

  if [[ "${EXPERIMENT_STATE}" == "completed" && \
        "${ORIGINAL_INSTANCE_STATE}" == "terminated" ]]; then
    break
  fi
  if [[ "${EXPERIMENT_STATE}" == "failed" || \
        "${EXPERIMENT_STATE}" == "stopped" || \
        "${EXPERIMENT_STATE}" == "cancelled" ]]; then
    echo "AWS FIS experiment ended in state ${EXPERIMENT_STATE}." >&2
    exit 1
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for FIS completion and EC2 termination." >&2
    exit 1
  fi
  sleep 10
done

deadline=$((SECONDS + 120))
while kubectl get nodeclaim "${ORIGINAL_NODECLAIM}" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "The interrupted NodeClaim still exists after instance termination." >&2
    exit 1
  fi
  sleep 5
done

echo "==> Replacement validated"
printf 'Experiment: %s\n' "${EXPERIMENT_ID}"
printf 'Original:   %s (%s)\n' "${ORIGINAL_NODE}" "${ORIGINAL_INSTANCE_ID}"
printf 'Replacement:%s (%s), Pod %s\n' \
  "${REPLACEMENT_NODE}" "${REPLACEMENT_INSTANCE_ID}" "${REPLACEMENT_POD}"

echo "==> Removing the temporary workload"
kubectl delete -f "${TEST_MANIFEST}" \
  --ignore-not-found=true \
  --wait=true \
  --timeout="${WAIT_TIMEOUT}"
TEST_APPLIED=false

echo "==> Waiting for consolidation-driven scale-in"
deadline=$((SECONDS + SCALE_IN_TIMEOUT_SECONDS))
while [[ -n "$(fis_nodeclaims)" ]] || [[ -n "$(fis_nodes)" ]]; do
  if (( SECONDS >= deadline )); then
    echo "FIS test scale-in timed out; deleting test NodeClaims." >&2
    kubectl delete nodeclaim \
      --selector "karpenter.sh/nodepool=${NODE_POOL_NAME}" \
      --wait=true \
      --timeout="${WAIT_TIMEOUT}" || true
    exit 1
  fi
  sleep 15
done

EXPERIMENT_ID=""
echo "Karpenter AWS FIS Spot interruption and replacement validation passed."

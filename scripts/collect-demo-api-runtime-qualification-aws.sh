#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${ENVIRONMENT:-}"
RELEASE_ID="${RELEASE_ID:-}"
CONTROL_PLANE_SHA="${CONTROL_PLANE_SHA:-}"
EXPECTED_SOURCE_COMMIT="${EXPECTED_SOURCE_COMMIT:-}"
EXPECTED_IMAGE_DIGEST="${EXPECTED_IMAGE_DIGEST:-}"
EXPECTED_RELEASE_FILE_SHA256="${EXPECTED_RELEASE_FILE_SHA256:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"
OUTPUT_FILE="${OUTPUT_FILE:-}"
WORKFLOW_RUN_ID="${GITHUB_RUN_ID:-1}"
WORKFLOW_RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
RUNNER_NAME_VALUE="${RUNNER_NAME:-local-runtime-executor}"

for command in aws curl git jq kubectl python3 sha256sum; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

case "${ENVIRONMENT}" in
  aws-dev)
    CLUSTER_NAME="startup-devops-baseline-dev"
    ARGO_APPLICATION="demo-api-aws-dev"
    WORKLOAD_KIND="Deployment"
    INGRESS_HOSTNAME="demo.dev.aureumstack.com"
    ;;
  aws-test)
    CLUSTER_NAME="startup-devops-baseline-test"
    ARGO_APPLICATION="demo-api-aws-test"
    WORKLOAD_KIND="Rollout"
    INGRESS_HOSTNAME="demo.test.aureumstack.com"
    ;;
  *)
    echo "Trusted runtime qualification permits only aws-dev and aws-test." >&2
    exit 1
    ;;
esac

RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/${ENVIRONMENT}.yaml"
OUTPUT_FILE="${OUTPUT_FILE:-${ROOT_DIR}/artifacts/runtime-qualification/${ENVIRONMENT}/${RELEASE_ID}.json}"
WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

write_result() {
  local status="$1"
  local reason="$2"
  local runtime_facts="${3:-}"
  local caller_arn="${AWS_CALLER_ARN:-}"
  local arguments=(
    --environment "${ENVIRONMENT}"
    --release-id "${RELEASE_ID}"
    --control-plane-sha "${CONTROL_PLANE_SHA}"
    --expected-source-commit "${EXPECTED_SOURCE_COMMIT}"
    --expected-image-digest "${EXPECTED_IMAGE_DIGEST}"
    --expected-release-file-sha256 "${EXPECTED_RELEASE_FILE_SHA256}"
    --release-file "${RELEASE_FILE}"
    --status "${status}"
    --reason "${reason}"
    --runner-name "${RUNNER_NAME_VALUE}"
    --workflow-run-id "${WORKFLOW_RUN_ID}"
    --workflow-run-attempt "${WORKFLOW_RUN_ATTEMPT}"
    --aws-caller-arn "${caller_arn}"
    --output "${OUTPUT_FILE}"
  )
  if [[ -n "${runtime_facts}" ]]; then
    arguments+=(--runtime-facts "${runtime_facts}")
  fi
  "${ROOT_DIR}/scripts/write-demo-api-runtime-qualification.py" "${arguments[@]}" >/dev/null
  echo "status=${status}"
  echo "reason=${reason}"
  echo "result=${OUTPUT_FILE}"
}

LOCAL_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
if [[ "${GITHUB_REF:-refs/heads/main}" != "refs/heads/main" || \
      "${LOCAL_SHA}" != "${CONTROL_PLANE_SHA}" ]]; then
  write_result blocked main_advanced
  exit 0
fi
REMOTE_MAIN="$(git -C "${ROOT_DIR}" ls-remote origin refs/heads/main | awk '{print $1}')"
if [[ "${REMOTE_MAIN}" != "${CONTROL_PLANE_SHA}" ]]; then
  write_result blocked main_advanced
  exit 0
fi

if ! AWS_CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text 2>/dev/null)"; then
  AWS_CALLER_ARN=""
  write_result blocked oidc_denied
  exit 0
fi
export AWS_CALLER_ARN

set +e
aws eks describe-cluster --region "${AWS_REGION}" --name "${CLUSTER_NAME}" \
  >"${WORK_DIR}/cluster.json" 2>"${WORK_DIR}/cluster.err"
describe_status=$?
set -e
if ((describe_status != 0)); then
  if grep -Eq 'ResourceNotFoundException|No cluster found' "${WORK_DIR}/cluster.err"; then
    write_result blocked environment_absent
  else
    write_result blocked oidc_denied
  fi
  exit 0
fi

export KUBECONFIG="${WORK_DIR}/kubeconfig"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}" \
  --kubeconfig "${KUBECONFIG}" >/dev/null
set +e
runtime_read="$(kubectl --request-timeout=15s auth can-i get pods -n startup-apps 2>/dev/null)"
runtime_read_status=$?
set -e
if ((runtime_read_status != 0)); then
  write_result blocked endpoint_unreachable
  exit 0
fi
if [[ "${runtime_read}" != "yes" ]]; then
  write_result failed rbac_boundary_failed
  exit 1
fi

for denied_check in \
  "get secrets -n startup-apps" \
  "create deployments.apps -n startup-apps" \
  "create pods/exec -n startup-apps"; do
  read -r -a arguments <<<"${denied_check}"
  if [[ "$(kubectl auth can-i "${arguments[@]}")" != "no" ]]; then
    write_result failed rbac_boundary_failed
    exit 1
  fi
done

if ! kubectl -n argocd get application "${ARGO_APPLICATION}" -o json \
  >"${WORK_DIR}/application.json"; then
  write_result failed argo_not_converged
  exit 1
fi
if ! jq --exit-status --arg revision "${CONTROL_PLANE_SHA}" '
  .spec.source.targetRevision == "main" and
  .status.sync.status == "Synced" and
  .status.health.status == "Healthy" and
  .status.sync.revision == $revision
' "${WORK_DIR}/application.json" >/dev/null; then
  write_result failed argo_not_converged
  exit 1
fi
ARGO_REVISION="$(jq -r '.status.sync.revision' "${WORK_DIR}/application.json")"

ROLLOUT_PHASE="not-applicable"
ANALYSIS_RUN_NAME=""
ANALYSIS_RUN_PHASE="not-applicable"
if [[ "${WORKLOAD_KIND}" == "Deployment" ]]; then
  if ! kubectl -n startup-apps get deployment demo-api -o json \
    >"${WORK_DIR}/workload.json"; then
    write_result failed rollout_unhealthy
    exit 1
  fi
  if ! jq --exit-status '
    (.status.observedGeneration | tostring) == (.metadata.generation | tostring) and
    .status.readyReplicas == .spec.replicas and
    .status.updatedReplicas == .spec.replicas and
    .status.availableReplicas == .spec.replicas
  ' "${WORK_DIR}/workload.json" >/dev/null; then
    write_result failed rollout_unhealthy
    exit 1
  fi
else
  if ! kubectl -n startup-apps get rollouts.argoproj.io demo-api -o json \
    >"${WORK_DIR}/workload.json"; then
    write_result failed rollout_unhealthy
    exit 1
  fi
  if ! jq --exit-status '
    (.status.observedGeneration | tostring) == (.metadata.generation | tostring) and
    .status.phase == "Healthy" and
    .status.currentPodHash == .status.stableRS and
    .status.availableReplicas == .spec.replicas and
    .status.updatedReplicas == .spec.replicas
  ' "${WORK_DIR}/workload.json" >/dev/null; then
    write_result failed rollout_unhealthy
    exit 1
  fi
  ROLLOUT_PHASE="Healthy"
  kubectl -n startup-apps get analysisruns.argoproj.io -o json \
    >"${WORK_DIR}/analysis-runs.json"
  ANALYSIS_RUN_NAME="$(jq -r \
    --arg environment "${ENVIRONMENT}" \
    --arg digest "${EXPECTED_IMAGE_DIGEST}" \
    --arg source "${EXPECTED_SOURCE_COMMIT}" '
      [.items[]
       | select(.status.phase == "Successful")
       | select(any(.spec.args[]?; .name == "expected-environment" and .value == $environment))
       | select(any(.spec.args[]?; .name == "image-digest" and .value == $digest))
       | select(any(.spec.args[]?; .name == "source-commit" and .value == $source))]
      | sort_by(.metadata.creationTimestamp) | last | .metadata.name // empty
    ' "${WORK_DIR}/analysis-runs.json")"
  if [[ -z "${ANALYSIS_RUN_NAME}" ]]; then
    write_result failed analysis_failed
    exit 1
  fi
  ANALYSIS_RUN_PHASE="Successful"
fi

if ! jq --exit-status \
  --arg environment "${ENVIRONMENT}" \
  --arg digest "${EXPECTED_IMAGE_DIGEST}" \
  --arg source "${EXPECTED_SOURCE_COMMIT}" '
    .metadata.annotations["platform.startup.dev/environment"] == $environment and
    .metadata.annotations["platform.startup.dev/image-digest"] == $digest and
    .metadata.annotations["platform.startup.dev/source-commit"] == $source
  ' "${WORK_DIR}/workload.json" >/dev/null; then
  write_result failed digest_mismatch
  exit 1
fi

kubectl -n startup-apps get pods \
  -l app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api \
  -o json >"${WORK_DIR}/pods.json"
READY_POD_COUNT="$(jq -r '[.items[] | select(.status.phase == "Running") | select(all(.status.containerStatuses[]?; .ready == true))] | length' "${WORK_DIR}/pods.json")"
TOTAL_POD_COUNT="$(jq -r '.items | length' "${WORK_DIR}/pods.json")"
if [[ "${READY_POD_COUNT}" == "0" || "${READY_POD_COUNT}" != "${TOTAL_POD_COUNT}" ]]; then
  write_result failed rollout_unhealthy
  exit 1
fi
if ! jq --exit-status --arg digest "${EXPECTED_IMAGE_DIGEST}" '
  all(.items[]; all(.status.containerStatuses[]?; .imageID | endswith("@" + $digest)))
' "${WORK_DIR}/pods.json" >/dev/null; then
  write_result failed digest_mismatch
  exit 1
fi
OBSERVED_IMAGE_IDS="$(jq -c '[.items[].status.containerStatuses[]?.imageID] | unique' "${WORK_DIR}/pods.json")"

for endpoint in health ready version; do
  if ! curl --fail --silent --show-error --retry 3 --retry-delay 2 \
    "https://${INGRESS_HOSTNAME}/${endpoint}" >"${WORK_DIR}/${endpoint}.json"; then
    write_result failed https_validation_failed
    exit 1
  fi
done
APPLICATION_VERSION="$(python3 - "${RELEASE_FILE}" <<'PY'
from pathlib import Path
import json, sys
for raw in Path(sys.argv[1]).read_text().splitlines():
    if raw.startswith("  applicationVersion:"):
        print(json.loads(raw.split(":", 1)[1].strip()))
        break
PY
)"
if ! jq --exit-status '.status == "ok"' "${WORK_DIR}/health.json" >/dev/null || \
   ! jq --exit-status '.status == "ready" and .database == "ok"' "${WORK_DIR}/ready.json" >/dev/null || \
   ! jq --exit-status --arg environment "${ENVIRONMENT}" --arg version "${APPLICATION_VERSION}" \
      '.environment == $environment and .version == $version' "${WORK_DIR}/version.json" >/dev/null; then
  write_result failed https_validation_failed
  exit 1
fi

jq -n \
  --arg argo_application "${ARGO_APPLICATION}" \
  --arg argo_revision "${ARGO_REVISION}" \
  --arg workload_kind "${WORKLOAD_KIND}" \
  --arg rollout_phase "${ROLLOUT_PHASE}" \
  --arg analysis_name "${ANALYSIS_RUN_NAME}" \
  --arg analysis_phase "${ANALYSIS_RUN_PHASE}" \
  --arg hostname "${INGRESS_HOSTNAME}" \
  --argjson ready_pods "${READY_POD_COUNT}" \
  --argjson image_ids "${OBSERVED_IMAGE_IDS}" '
  {
    argoApplication: $argo_application,
    argoRevision: $argo_revision,
    workloadKind: $workload_kind,
    workloadName: "demo-api",
    rolloutPhase: $rollout_phase,
    analysisRunName: $analysis_name,
    analysisRunPhase: $analysis_phase,
    httpsHostname: $hostname,
    readyPodCount: $ready_pods,
    observedImageIds: $image_ids,
    checks: [
      "argocd-synced-healthy",
      "release-annotations-match",
      "all-pods-ready",
      "immutable-pod-image-id-match",
      "https-health",
      "https-ready-database",
      "https-version-identity",
      "read-only-rbac-boundary"
    ]
  }
' >"${WORK_DIR}/runtime-facts.json"

write_result qualified all_checks_passed "${WORK_DIR}/runtime-facts.json"

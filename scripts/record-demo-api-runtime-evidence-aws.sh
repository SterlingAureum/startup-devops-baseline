#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${ENVIRONMENT:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"
EVIDENCE_ACTOR="${EVIDENCE_ACTOR:-}"
EVIDENCE_ID="${EVIDENCE_ID:-$(date -u +%Y%m%d%H%M%S)}"
NAMESPACE="startup-apps"
WORKLOAD_NAME="demo-api"

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
  aws-prod)
    CLUSTER_NAME="startup-devops-baseline-prod"
    ARGO_APPLICATION="demo-api-aws-prod"
    WORKLOAD_KIND="Rollout"
    INGRESS_HOSTNAME="demo.prod.aureumstack.com"
    ;;
  *)
    echo "Set ENVIRONMENT to aws-dev, aws-test, or aws-prod." >&2
    exit 1
    ;;
esac

if [[ -z "${EVIDENCE_ACTOR}" ]]; then
  echo "Set EVIDENCE_ACTOR to the GitHub login collecting this evidence." >&2
  exit 1
fi
if [[ ! "${EVIDENCE_ID}" =~ ^[0-9]{14}$ ]]; then
  echo "EVIDENCE_ID must use UTC YYYYMMDDHHMMSS digits." >&2
  exit 1
fi

if [[ "$(git -C "${ROOT_DIR}" branch --show-current)" != "main" ]]; then
  echo "Runtime evidence must be collected from the main branch." >&2
  exit 1
fi
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain --untracked-files=no)" ]]; then
  echo "Tracked files must be clean before runtime evidence collection." >&2
  exit 1
fi
git -C "${ROOT_DIR}" fetch --no-tags origin \
  "+refs/heads/main:refs/remotes/origin/main"
REPOSITORY_REVISION="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
if [[ "${REPOSITORY_REVISION}" != "$(git -C "${ROOT_DIR}" rev-parse origin/main)" ]]; then
  echo "Local main must exactly match origin/main before evidence collection." >&2
  exit 1
fi

RELEASE_FILE="${ROOT_DIR}/apps/demo-api/helm/values/releases/${ENVIRONMENT}.yaml"
mapfile -t RELEASE_IDENTITY < <(python3 - "${RELEASE_FILE}" <<'PY'
from pathlib import Path
import json
import sys

section = None
values = {}
for raw in Path(sys.argv[1]).read_text().splitlines():
    if not raw.strip() or raw.lstrip().startswith("#"):
        continue
    indent = len(raw) - len(raw.lstrip())
    stripped = raw.strip()
    if indent == 0 and stripped.endswith(":"):
        section = stripped[:-1]
    elif indent == 2 and section and ":" in stripped:
        key, value = stripped.split(":", 1)
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = json.loads(value)
        values[(section, key)] = value
    else:
        raise SystemExit("Unsupported release values structure.")
for field in (
    ("image", "repository"), ("image", "tag"), ("image", "digest"),
    ("release", "applicationVersion"), ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
):
    print(values[field])
PY
)
IMAGE_REPOSITORY="${RELEASE_IDENTITY[0]}"
IMAGE_TAG="${RELEASE_IDENTITY[1]}"
IMAGE_DIGEST="${RELEASE_IDENTITY[2]}"
APPLICATION_VERSION="${RELEASE_IDENTITY[3]}"
SOURCE_COMMIT="${RELEASE_IDENTITY[4]}"
BUILD_WORKFLOW_RUN_ID="${RELEASE_IDENTITY[5]}"
EXPECTED_IMAGE="${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"

WORK_DIR="$(mktemp -d)"
cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

echo "==> Configuring EKS context for ${CLUSTER_NAME}"
aws eks update-kubeconfig --region "${AWS_REGION}" --name "${CLUSTER_NAME}" >/dev/null
CURRENT_CONTEXT="$(kubectl config current-context)"
if [[ "${CURRENT_CONTEXT}" != *"${CLUSTER_NAME}"* ]]; then
  echo "Current Kubernetes context does not identify ${CLUSTER_NAME}." >&2
  exit 1
fi

echo "==> Verifying Argo CD desired and observed revision"
kubectl -n argocd get application "${ARGO_APPLICATION}" -o json \
  >"${WORK_DIR}/application.json"
jq --exit-status \
  --arg revision "${REPOSITORY_REVISION}" \
  '.spec.source.targetRevision == "main" and
   .status.sync.status == "Synced" and
   .status.health.status == "Healthy" and
   .status.sync.revision == $revision' \
  "${WORK_DIR}/application.json" >/dev/null
ARGO_REVISION="$(jq -r '.status.sync.revision' "${WORK_DIR}/application.json")"

echo "==> Verifying live workload and immutable release annotations"
if [[ "${WORKLOAD_KIND}" == "Deployment" ]]; then
  kubectl -n "${NAMESPACE}" get deployment "${WORKLOAD_NAME}" -o json \
    >"${WORK_DIR}/workload.json"
  jq --exit-status \
    '.status.observedGeneration == .metadata.generation and
     .status.readyReplicas == .spec.replicas and
     .status.updatedReplicas == .spec.replicas and
     .status.availableReplicas == .spec.replicas' \
    "${WORK_DIR}/workload.json" >/dev/null
  ROLLOUT_PHASE="not-applicable"
  ANALYSIS_RUN_NAME=""
  ANALYSIS_RUN_PHASE="not-applicable"
  ALB_ACTION_SHA256=""
else
  kubectl -n "${NAMESPACE}" get rollouts.argoproj.io "${WORKLOAD_NAME}" -o json \
    >"${WORK_DIR}/workload.json"
  jq --exit-status \
    '.status.observedGeneration == .metadata.generation and
     .status.phase == "Healthy" and
     .status.currentPodHash == .status.stableRS and
     .status.availableReplicas == .spec.replicas and
     .status.updatedReplicas == .spec.replicas' \
    "${WORK_DIR}/workload.json" >/dev/null
  ROLLOUT_PHASE="$(jq -r '.status.phase' "${WORK_DIR}/workload.json")"

  kubectl -n "${NAMESPACE}" get analysisruns.argoproj.io -o json \
    >"${WORK_DIR}/analysis-runs.json"
  ANALYSIS_RUN_NAME="$(jq -r \
    --arg environment "${ENVIRONMENT}" \
    --arg version "${APPLICATION_VERSION}" \
    --arg digest "${IMAGE_DIGEST}" \
    --arg source "${SOURCE_COMMIT}" '
      [ .items[]
        | select(.status.phase == "Successful")
        | select(any(.spec.args[]?; .name == "expected-environment" and .value == $environment))
        | select(any(.spec.args[]?; .name == "expected-version" and .value == $version))
        | select(any(.spec.args[]?; .name == "image-digest" and .value == $digest))
        | select(any(.spec.args[]?; .name == "source-commit" and .value == $source))
      ] | sort_by(.metadata.creationTimestamp) | last | .metadata.name // empty
    ' "${WORK_DIR}/analysis-runs.json")"
  if [[ -z "${ANALYSIS_RUN_NAME}" ]]; then
    echo "No successful AnalysisRun matches the current release identity." >&2
    exit 1
  fi
  ANALYSIS_RUN_PHASE="Successful"

  kubectl -n "${NAMESPACE}" get ingress "${WORKLOAD_NAME}" -o json \
    >"${WORK_DIR}/ingress.json"
  ALB_ACTION="$(jq -r '.metadata.annotations["alb.ingress.kubernetes.io/actions.demo-api-stable"] // empty' "${WORK_DIR}/ingress.json")"
  if [[ -z "${ALB_ACTION}" ]]; then
    echo "Argo Rollouts managed ALB action annotation is missing." >&2
    exit 1
  fi
  jq --exit-status '
    (.ForwardConfig.TargetGroups // .forwardConfig.targetGroups) as $groups |
    ($groups | map((.Weight // .weight) | tonumber) | add) == 100 and
    any($groups[]; (.ServiceName // .serviceName) == "demo-api-stable" and ((.Weight // .weight) | tonumber) == 100) and
    all($groups[]; if (.ServiceName // .serviceName) == "demo-api-canary" then ((.Weight // .weight) | tonumber) == 0 else true end)
  ' <<<"${ALB_ACTION}" >/dev/null
  ALB_ACTION_SHA256="$(printf '%s' "${ALB_ACTION}" | sha256sum | awk '{print $1}')"
fi

jq --exit-status \
  --arg environment "${ENVIRONMENT}" \
  --arg tag "${IMAGE_TAG}" \
  --arg digest "${IMAGE_DIGEST}" \
  --arg version "${APPLICATION_VERSION}" \
  --arg source "${SOURCE_COMMIT}" \
  --arg build_run "${BUILD_WORKFLOW_RUN_ID}" '
    .metadata.annotations["platform.startup.dev/environment"] == $environment and
    .metadata.annotations["platform.startup.dev/image-tag"] == $tag and
    .metadata.annotations["platform.startup.dev/image-digest"] == $digest and
    .metadata.annotations["platform.startup.dev/application-version"] == $version and
    .metadata.annotations["platform.startup.dev/source-commit"] == $source and
    .metadata.annotations["platform.startup.dev/workflow-run-id"] == $build_run
  ' "${WORK_DIR}/workload.json" >/dev/null

echo "==> Verifying ready Pods use the exact promoted digest"
kubectl -n "${NAMESPACE}" get pods \
  -l app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api \
  -o json >"${WORK_DIR}/pods.json"
READY_POD_COUNT="$(jq -r '[.items[] | select(.status.phase == "Running") | select(all(.status.containerStatuses[]?; .ready == true))] | length' "${WORK_DIR}/pods.json")"
TOTAL_POD_COUNT="$(jq -r '.items | length' "${WORK_DIR}/pods.json")"
if [[ "${READY_POD_COUNT}" == "0" || "${READY_POD_COUNT}" != "${TOTAL_POD_COUNT}" ]]; then
  echo "Every selected demo-api Pod must be Running and ready." >&2
  exit 1
fi
jq --exit-status --arg image "${EXPECTED_IMAGE}" \
  'all(.items[]; all(.spec.containers[]; .image == $image))' \
  "${WORK_DIR}/pods.json" >/dev/null

echo "==> Verifying the public HTTPS runtime identity"
curl --fail --silent --show-error --retry 5 --retry-delay 3 \
  "https://${INGRESS_HOSTNAME}/health" >"${WORK_DIR}/health.json"
curl --fail --silent --show-error --retry 5 --retry-delay 3 \
  "https://${INGRESS_HOSTNAME}/ready" >"${WORK_DIR}/ready.json"
curl --fail --silent --show-error --retry 5 --retry-delay 3 \
  "https://${INGRESS_HOSTNAME}/version" >"${WORK_DIR}/version.json"
jq --exit-status '.status == "ok"' "${WORK_DIR}/health.json" >/dev/null
READY_STATUS="$(jq -r '.status' "${WORK_DIR}/ready.json")"
READY_DATABASE="$(jq -r '.database' "${WORK_DIR}/ready.json")"
OBSERVED_ENVIRONMENT="$(jq -r '.environment' "${WORK_DIR}/version.json")"
OBSERVED_VERSION="$(jq -r '.version' "${WORK_DIR}/version.json")"
if [[ "${READY_STATUS}" != "ready" || "${READY_DATABASE}" != "ok" || \
      "${OBSERVED_ENVIRONMENT}" != "${ENVIRONMENT}" || \
      "${OBSERVED_VERSION}" != "${APPLICATION_VERSION}" ]]; then
  echo "Public HTTPS readiness or release identity did not converge." >&2
  exit 1
fi

OUTPUT_FILE="${ROOT_DIR}/evidence/demo-api/runtime/${ENVIRONMENT}/${EVIDENCE_ID}.json"
ENVIRONMENT="${ENVIRONMENT}" \
RELEASE_FILE="${RELEASE_FILE}" \
OUTPUT_FILE="${OUTPUT_FILE}" \
EVIDENCE_ID="${EVIDENCE_ID}" \
EVIDENCE_ACTOR="${EVIDENCE_ACTOR}" \
REPOSITORY_REVISION="${REPOSITORY_REVISION}" \
CLUSTER_NAME="${CLUSTER_NAME}" \
ARGO_APPLICATION="${ARGO_APPLICATION}" \
ARGO_REVISION="${ARGO_REVISION}" \
WORKLOAD_KIND="${WORKLOAD_KIND}" \
WORKLOAD_NAME="${WORKLOAD_NAME}" \
ROLLOUT_PHASE="${ROLLOUT_PHASE}" \
ANALYSIS_RUN_NAME="${ANALYSIS_RUN_NAME}" \
ANALYSIS_RUN_PHASE="${ANALYSIS_RUN_PHASE}" \
INGRESS_HOSTNAME="${INGRESS_HOSTNAME}" \
ALB_ACTION_SHA256="${ALB_ACTION_SHA256}" \
OBSERVED_IMAGE="${EXPECTED_IMAGE}" \
READY_STATUS="${READY_STATUS}" \
READY_DATABASE="${READY_DATABASE}" \
OBSERVED_ENVIRONMENT="${OBSERVED_ENVIRONMENT}" \
OBSERVED_VERSION="${OBSERVED_VERSION}" \
READY_POD_COUNT="${READY_POD_COUNT}" \
  "${ROOT_DIR}/scripts/write-demo-api-runtime-evidence.sh"

EXPECTED_ENVIRONMENT="${ENVIRONMENT}" \
EXPECTED_EVIDENCE_ID="${EVIDENCE_ID}" \
EVIDENCE_FILE="${OUTPUT_FILE}" \
RELEASE_FILE="${RELEASE_FILE}" \
  "${ROOT_DIR}/scripts/validate-demo-api-runtime-evidence.sh"

echo "Runtime evidence is ready for an evidence-only pull request:"
echo "  ${OUTPUT_FILE}"

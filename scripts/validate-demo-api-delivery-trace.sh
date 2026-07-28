#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
CONFIGURE_KUBECONFIG="${CONFIGURE_KUBECONFIG:-true}"
ARGO_NAMESPACE="${ARGO_NAMESPACE:-argocd}"
ARGO_APPLICATION="${ARGO_APPLICATION:-demo-api-aws-dev}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_DEPLOYMENT="${DEMO_DEPLOYMENT:-demo-api}"
VALUES_PATH="${VALUES_PATH:-apps/demo-api/helm/values-aws-dev.yaml}"
PROMOTION_REVISION="${PROMOTION_REVISION:-HEAD}"
EXPECTED_SOURCE_REPOSITORY="${EXPECTED_SOURCE_REPOSITORY:-SterlingAureum/startup-devops-baseline}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in git jq kubectl python3; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

if [[ "${CONFIGURE_KUBECONFIG}" == "true" ]]; then
  command -v aws >/dev/null 2>&1 || {
    echo "Required command not found: aws" >&2
    exit 1
  }

  echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
  aws eks update-kubeconfig \
    --region "${AWS_REGION}" \
    --name "${EKS_CLUSTER_NAME}" >/dev/null
fi

PROMOTION_REVISION="$(
  git -C "${ROOT_DIR}" rev-parse "${PROMOTION_REVISION}^{commit}"
)" || {
  echo "Could not resolve the promotion Git revision." >&2
  exit 1
}

if [[ ! "${PROMOTION_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Promotion revision must resolve to a full Git commit SHA." >&2
  exit 1
fi

git -C "${ROOT_DIR}" cat-file -e \
  "${PROMOTION_REVISION}:${VALUES_PATH}" 2>/dev/null || {
  echo "${VALUES_PATH} is missing from promotion revision ${PROMOTION_REVISION}." >&2
  exit 1
}

PROMOTION_PARENT="$(
  git -C "${ROOT_DIR}" rev-parse "${PROMOTION_REVISION}^1"
)" || {
  echo "Promotion revision does not have a parent commit." >&2
  exit 1
}

mapfile -t PROMOTION_FILES < <(
  git -C "${ROOT_DIR}" diff \
    --name-only \
    "${PROMOTION_PARENT}" \
    "${PROMOTION_REVISION}"
)
if (( ${#PROMOTION_FILES[@]} != 1 )) || \
   [[ "${PROMOTION_FILES[0]}" != "${VALUES_PATH}" ]]; then
  echo "Promotion revision must change only ${VALUES_PATH}." >&2
  printf 'Promotion file: %s\n' "${PROMOTION_FILES[@]}" >&2
  exit 1
fi

mapfile -t TRACE_VALUES < <(
  git -C "${ROOT_DIR}" show "${PROMOTION_REVISION}:${VALUES_PATH}" |
    python3 -c '
import json
import sys

section = None
values = {}
for raw in sys.stdin:
    line = raw.rstrip("\n")
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if not line.startswith(" ") and stripped.endswith(":"):
        section = stripped[:-1]
        continue
    if section is None or not line.startswith("  ") or ":" not in stripped:
        continue
    key, value = stripped.split(":", 1)
    value = value.strip()
    if value.startswith("\"") and value.endswith("\""):
        value = json.loads(value)
    elif value.startswith(chr(39)) and value.endswith(chr(39)):
        value = value[1:-1].replace(chr(39) * 2, chr(39))
    values[(section, key)] = value

for field in (
    ("image", "repository"),
    ("image", "tag"),
    ("image", "digest"),
    ("env", "APP_VERSION"),
    ("delivery", "sourceRepository"),
    ("delivery", "sourceCommit"),
    ("delivery", "workflowRunId"),
):
    print(values.get(field, ""))
'
)

if (( ${#TRACE_VALUES[@]} != 7 )); then
  echo "Could not parse the aws-dev delivery identity." >&2
  exit 1
fi

IMAGE_REPOSITORY="${TRACE_VALUES[0]}"
IMAGE_TAG="${TRACE_VALUES[1]}"
IMAGE_DIGEST="${TRACE_VALUES[2]}"
APP_VERSION="${TRACE_VALUES[3]}"
SOURCE_REPOSITORY="${TRACE_VALUES[4]}"
SOURCE_COMMIT="${TRACE_VALUES[5]}"
WORKFLOW_RUN_ID="${TRACE_VALUES[6]}"
IMAGE_REFERENCE="${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"

if [[ -z "${IMAGE_REPOSITORY}" || \
      ! "${IMAGE_TAG}" =~ ^sha-[0-9a-f]{7}$ || \
      ! "${IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ || \
      "${APP_VERSION}" != "${IMAGE_TAG}" || \
      "${SOURCE_REPOSITORY}" != "${EXPECTED_SOURCE_REPOSITORY}" || \
      ! "${SOURCE_COMMIT}" =~ ^[0-9a-f]{40}$ || \
      "${IMAGE_TAG}" != "sha-${SOURCE_COMMIT:0:7}" || \
      -z "${WORKFLOW_RUN_ID}" ]]; then
  echo "The Git delivery identity contract is invalid." >&2
  exit 1
fi

git -C "${ROOT_DIR}" cat-file -e "${SOURCE_COMMIT}^{commit}" 2>/dev/null || {
  echo "Source commit ${SOURCE_COMMIT} is not available in the local repository." >&2
  echo "Fetch the repository history and retry." >&2
  exit 1
}

echo "==> Waiting for the Argo CD Application"
kubectl wait \
  --for=jsonpath='{.status.sync.status}'=Synced \
  "application/${ARGO_APPLICATION}" \
  --namespace "${ARGO_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=jsonpath='{.status.health.status}'=Healthy \
  "application/${ARGO_APPLICATION}" \
  --namespace "${ARGO_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

ARGO_JSON="$(
  kubectl get application "${ARGO_APPLICATION}" \
    --namespace "${ARGO_NAMESPACE}" \
    --output json
)"
ARGO_REVISION="$(jq -r '.status.sync.revision // empty' <<< "${ARGO_JSON}")"

if [[ "${ARGO_REVISION}" != "${PROMOTION_REVISION}" ]]; then
  echo "Argo CD is not synced to promotion revision ${PROMOTION_REVISION}." >&2
  echo "Current Argo CD revision: ${ARGO_REVISION:-<empty>}" >&2
  exit 1
fi

jq --exit-status \
  --arg values_file "$(basename "${VALUES_PATH}")" \
  '
    .spec.source.path == "apps/demo-api/helm" and
    (.spec.source.helm.valueFiles | index($values_file) != null)
  ' <<< "${ARGO_JSON}" >/dev/null || {
  echo "The Argo CD Application does not use the expected Helm values file." >&2
  exit 1
}

echo "==> Checking the live Deployment identity"
kubectl rollout status "deployment/${DEMO_DEPLOYMENT}" \
  --namespace "${DEMO_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"

DEPLOYMENT_JSON="$(
  kubectl get deployment "${DEMO_DEPLOYMENT}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"

jq --exit-status \
  --arg image_tag "${IMAGE_TAG}" \
  --arg image_digest "${IMAGE_DIGEST}" \
  --arg image_reference "${IMAGE_REFERENCE}" \
  --arg app_version "${APP_VERSION}" \
  --arg source_repository "${SOURCE_REPOSITORY}" \
  --arg source_commit "${SOURCE_COMMIT}" \
  --arg workflow_run_id "${WORKFLOW_RUN_ID}" \
  '
    .metadata.labels["app.kubernetes.io/version"] == $app_version and
    .metadata.annotations["platform.startup.dev/image-tag"] == $image_tag and
    .metadata.annotations["platform.startup.dev/image-digest"] == $image_digest and
    .metadata.annotations["platform.startup.dev/application-version"] == $app_version and
    .metadata.annotations["platform.startup.dev/source-repository"] == $source_repository and
    .metadata.annotations["platform.startup.dev/source-commit"] == $source_commit and
    .metadata.annotations["platform.startup.dev/workflow-run-id"] == $workflow_run_id and
    .spec.template.metadata.annotations["platform.startup.dev/image-tag"] == $image_tag and
    .spec.template.metadata.annotations["platform.startup.dev/image-digest"] == $image_digest and
    .spec.template.metadata.annotations["platform.startup.dev/source-commit"] == $source_commit and
    (
      [.spec.template.spec.containers[]
        | select(.name == "demo-api")
        | .image][0]
    ) == $image_reference and
    (
      [.spec.template.spec.containers[]
        | select(.name == "demo-api")
        | .env[]
        | select(.name == "APP_VERSION")
        | .value][0]
    ) == $app_version and
    .status.observedGeneration == .metadata.generation and
    .status.updatedReplicas == .spec.replicas and
    .status.availableReplicas == .spec.replicas
  ' <<< "${DEPLOYMENT_JSON}" >/dev/null || {
  echo "The live Deployment does not match the Git delivery identity." >&2
  exit 1
}

echo "==> Checking Pod image IDs and runtime versions"
PODS_JSON="$(
  kubectl get pods \
    --namespace "${DEMO_NAMESPACE}" \
    --selector "app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api" \
    --output json
)"
EXPECTED_REPLICAS="$(jq -r '.spec.replicas' <<< "${DEPLOYMENT_JSON}")"
POD_COUNT="$(jq -r '.items | length' <<< "${PODS_JSON}")"

if [[ "${POD_COUNT}" != "${EXPECTED_REPLICAS}" ]]; then
  echo "Expected ${EXPECTED_REPLICAS} demo-api Pods, found ${POD_COUNT}." >&2
  exit 1
fi

jq --exit-status \
  --arg image_digest "${IMAGE_DIGEST}" \
  --arg image_reference "${IMAGE_REFERENCE}" \
  --arg source_commit "${SOURCE_COMMIT}" \
  --arg workflow_run_id "${WORKFLOW_RUN_ID}" \
  '
    (.items | length > 0) and
    all(
      .items[];
      (
        [.status.conditions[]?
          | select(.type == "Ready")
          | .status][0]
      ) == "True" and
      .metadata.annotations["platform.startup.dev/source-commit"] == $source_commit and
      .metadata.annotations["platform.startup.dev/workflow-run-id"] == $workflow_run_id and
      (
        [.spec.containers[]
          | select(.name == "demo-api")
          | .image][0]
      ) == $image_reference and
      (
        (
          [.status.containerStatuses[]?
            | select(.name == "demo-api")
            | .imageID][0] // ""
        )
        | endswith("@" + $image_digest)
      )
    )
  ' <<< "${PODS_JSON}" >/dev/null || {
  echo "One or more Pods do not match the digest or delivery metadata." >&2
  exit 1
}

mapfile -t DEMO_PODS < <(
  jq -r '.items[].metadata.name' <<< "${PODS_JSON}"
)
for pod in "${DEMO_PODS[@]}"; do
  VERSION_JSON="$(
    kubectl exec \
      --namespace "${DEMO_NAMESPACE}" \
      "${pod}" -- \
      python -c \
        'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/version", timeout=10).read().decode())'
  )"

  jq --exit-status \
    --arg version "${APP_VERSION}" \
    '
      .name == "demo-api" and
      .environment == "aws-dev" and
      .version == $version
    ' <<< "${VERSION_JSON}" >/dev/null || {
    echo "Pod ${pod} reports an unexpected /version identity." >&2
    exit 1
  }
done

echo
echo "demo-api delivery trace:"
echo "  source_commit=${SOURCE_COMMIT}"
echo "  image_tag=${IMAGE_TAG}"
echo "  image_digest=${IMAGE_DIGEST}"
echo "  workflow_run_id=${WORKFLOW_RUN_ID}"
echo "  promotion_commit=${PROMOTION_REVISION}"
echo "  argocd_revision=${ARGO_REVISION}"
echo "  pod_image=${IMAGE_REFERENCE}"
echo "  application_version=${APP_VERSION}"
echo "demo-api delivery traceability validation passed."

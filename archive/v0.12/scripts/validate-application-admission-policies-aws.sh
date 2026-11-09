#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"
POLICY_MESSAGE_IMAGE="must use an immutable sha256 digest image reference"
POLICY_MESSAGE_RESOURCES="must define cpu and memory requests and limits"

for command in aws git grep kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

EXPECTED_REVISION="${EXPECTED_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"

wait_for_application() {
  local application="$1"
  local expected_revision="$2"

  kubectl wait \
    --for=jsonpath='{.status.sync.revision}'="${expected_revision}" \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}"
  kubectl wait \
    --for=jsonpath='{.status.sync.status}'=Synced \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}"
  kubectl wait \
    --for=jsonpath='{.status.health.status}'=Healthy \
    "application/${application}" \
    --namespace argocd \
    --timeout="${WAIT_TIMEOUT}"
}

render_pod() {
  local namespace="$1"
  local name="$2"
  local image="$3"
  local include_requests="$4"
  local include_limits="$5"

  cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${name}
  namespace: ${namespace}
spec:
  automountServiceAccountToken: false
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: test
      image: ${image}
      command: ["sh", "-c", "sleep 30"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
EOF
  if [[ "${include_requests}" == "true" || "${include_limits}" == "true" ]]; then
    cat <<'EOF'
      resources:
EOF
  fi
  if [[ "${include_requests}" == "true" ]]; then
    cat <<'EOF'
        requests:
          cpu: 10m
          memory: 32Mi
EOF
  fi
  if [[ "${include_limits}" == "true" ]]; then
    cat <<'EOF'
        limits:
          cpu: 50m
          memory: 64Mi
EOF
  fi
}

render_deployment() {
  local namespace="$1"
  local name="$2"
  local image="$3"
  local include_requests="$4"
  local include_limits="$5"

  cat <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${name}
  namespace: ${namespace}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${name}
  template:
    metadata:
      labels:
        app: ${name}
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: test
          image: ${image}
          command: ["sh", "-c", "sleep 30"]
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
EOF
  if [[ "${include_requests}" == "true" || "${include_limits}" == "true" ]]; then
    cat <<'EOF'
          resources:
EOF
  fi
  if [[ "${include_requests}" == "true" ]]; then
    cat <<'EOF'
            requests:
              cpu: 10m
              memory: 32Mi
EOF
  fi
  if [[ "${include_limits}" == "true" ]]; then
    cat <<'EOF'
            limits:
              cpu: 50m
              memory: 64Mi
EOF
  fi
}

assert_admitted() {
  local description="$1"
  local manifest
  local output

  manifest="$(cat)"
  if ! output="$(
    printf '%s\n' "${manifest}" | kubectl create --dry-run=server -f - 2>&1
  )"; then
    echo "${description} was unexpectedly rejected:" >&2
    echo "${output}" >&2
    exit 1
  fi
}

assert_admitted_with_resource_defaults() {
  local description="$1"
  local expected_defaults="$2"
  local manifest
  local actual_defaults

  manifest="$(cat)"
  if ! actual_defaults="$(
    printf '%s\n' "${manifest}" |
      kubectl create \
        --dry-run=server \
        -f - \
        -o 'jsonpath={.spec.containers[0].resources.requests.cpu}{" "}{.spec.containers[0].resources.requests.memory}{" "}{.spec.containers[0].resources.limits.cpu}{" "}{.spec.containers[0].resources.limits.memory}' \
        2>&1
  )"; then
    echo "${description} was unexpectedly rejected:" >&2
    echo "${actual_defaults}" >&2
    exit 1
  fi

  if [[ "${actual_defaults}" != "${expected_defaults}" ]]; then
    echo "${description} did not receive the expected LimitRange defaults." >&2
    echo "Expected: ${expected_defaults}" >&2
    echo "Actual:   ${actual_defaults:-missing}" >&2
    exit 1
  fi
}

assert_rejected() {
  local description="$1"
  local expected_message="$2"
  local manifest
  local output

  manifest="$(cat)"
  if output="$(
    printf '%s\n' "${manifest}" | kubectl create --dry-run=server -f - 2>&1
  )"; then
    echo "${description} was unexpectedly admitted." >&2
    exit 1
  fi
  if ! grep -F "${expected_message}" <<<"${output}" >/dev/null; then
    echo "${description} was rejected for an unexpected reason:" >&2
    echo "${output}" >&2
    exit 1
  fi
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Refreshing application admission policies"
kubectl annotate application application-admission-policies-aws-dev \
  --namespace argocd \
  argocd.argoproj.io/refresh=hard \
  --overwrite >/dev/null

echo "==> Waiting for application admission policies at ${EXPECTED_REVISION}"
wait_for_application \
  application-admission-policies-aws-dev \
  "${EXPECTED_REVISION}"

echo "==> Verifying policy and binding resources"
for name in \
  startup-application-pods.security.startup.dev \
  startup-application-workloads.security.startup.dev; do
  kubectl get validatingadmissionpolicy "${name}" >/dev/null
  kubectl get validatingadmissionpolicybinding "${name}" >/dev/null

  generation="$(
    kubectl get validatingadmissionpolicy "${name}" \
      -o jsonpath='{.metadata.generation}'
  )"
  kubectl wait \
    --for=jsonpath='{.status.observedGeneration}'="${generation}" \
    "validatingadmissionpolicy/${name}" \
    --timeout=60s >/dev/null

  expression_warnings="$(
    kubectl get validatingadmissionpolicy "${name}" \
      -o jsonpath='{.status.typeChecking.expressionWarnings[*].warning}'
  )"
  if [[ -n "${expression_warnings}" ]]; then
    echo "CEL type checking reported warnings for ${name}:" >&2
    echo "${expression_warnings}" >&2
    exit 1
  fi

  actions="$(
    kubectl get validatingadmissionpolicybinding "${name}" \
      -o jsonpath='{.spec.validationActions[*]}'
  )"
  if [[ " ${actions} " != *" Deny "* || " ${actions} " != *" Audit "* ]]; then
    echo "Binding ${name} does not enforce Deny and Audit: ${actions}" >&2
    exit 1
  fi
done

selector="$(
  kubectl get validatingadmissionpolicybinding \
    startup-application-pods.security.startup.dev \
    -o jsonpath='{.spec.matchResources.namespaceSelector.matchLabels.platform\.startup\.dev/tier}'
)"
if [[ "${selector}" != "application" ]]; then
  echo "Unexpected application policy namespace selector: ${selector:-missing}" >&2
  exit 1
fi

echo "==> Verifying the protected workload remains healthy"
kubectl rollout status deployment/demo-api \
  --namespace startup-apps \
  --timeout="${WAIT_TIMEOUT}"

TEST_IMAGE="$(
  kubectl get deployment demo-api \
    --namespace startup-apps \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
)"
if [[ ! "${TEST_IMAGE}" =~ @sha256:[0-9a-f]{64}$ ]]; then
  echo "The live demo-api image is not digest pinned: ${TEST_IMAGE}" >&2
  exit 1
fi
MUTABLE_IMAGE="${TEST_IMAGE%@*}:mutable"
LATEST_IMAGE="${TEST_IMAGE%@*}:latest"
LIMIT_RANGE_DEFAULTS="$(
  kubectl get limitrange startup-apps-containers \
    --namespace startup-apps \
    -o 'jsonpath={.spec.limits[?(@.type=="Container")].defaultRequest.cpu}{" "}{.spec.limits[?(@.type=="Container")].defaultRequest.memory}{" "}{.spec.limits[?(@.type=="Container")].default.cpu}{" "}{.spec.limits[?(@.type=="Container")].default.memory}'
)"
read -r \
  DEFAULT_REQUEST_CPU \
  DEFAULT_REQUEST_MEMORY \
  DEFAULT_LIMIT_CPU \
  DEFAULT_LIMIT_MEMORY \
  <<<"${LIMIT_RANGE_DEFAULTS}"
if [[ -z "${DEFAULT_REQUEST_CPU}" ||
      -z "${DEFAULT_REQUEST_MEMORY}" ||
      -z "${DEFAULT_LIMIT_CPU}" ||
      -z "${DEFAULT_LIMIT_MEMORY}" ]]; then
  echo "The startup-apps LimitRange does not define complete container defaults." >&2
  exit 1
fi

echo "==> Verifying digest-pinned, resource-bounded objects are admitted"
render_pod \
  startup-apps \
  admission-policy-compliant-pod \
  "${TEST_IMAGE}" \
  true \
  true |
  assert_admitted "A compliant Pod"
render_deployment \
  startup-apps \
  admission-policy-compliant-deployment \
  "${TEST_IMAGE}" \
  true \
  true |
  assert_admitted "A compliant Deployment"

echo "==> Verifying mutable and latest image tags are rejected"
render_pod \
  startup-apps \
  admission-policy-mutable-image \
  "${MUTABLE_IMAGE}" \
  true \
  true |
  assert_rejected "A mutable-tag Pod" "${POLICY_MESSAGE_IMAGE}"
render_deployment \
  startup-apps \
  admission-policy-latest-image \
  "${LATEST_IMAGE}" \
  true \
  true |
  assert_rejected "A latest-tag Deployment" "${POLICY_MESSAGE_IMAGE}"

echo "==> Verifying direct Pods receive LimitRange resource defaults"
render_pod \
  startup-apps \
  admission-policy-defaulted-resources \
  "${TEST_IMAGE}" \
  false \
  false |
  assert_admitted_with_resource_defaults \
    "A direct Pod without resources" \
    "${LIMIT_RANGE_DEFAULTS}"

echo "==> Verifying workload templates with missing resources are rejected"
render_deployment \
  startup-apps \
  admission-policy-missing-requests \
  "${TEST_IMAGE}" \
  false \
  true |
  assert_rejected "A Deployment without requests" "${POLICY_MESSAGE_RESOURCES}"
render_deployment \
  startup-apps \
  admission-policy-missing-limits \
  "${TEST_IMAGE}" \
  true \
  false |
  assert_rejected "A Deployment without limits" "${POLICY_MESSAGE_RESOURCES}"

echo "==> Verifying the data-platform namespace is outside application policy scope"
render_pod \
  data-platform \
  admission-policy-data-scope-check \
  "registry.k8s.io/pause:3.10" \
  true \
  true |
  assert_admitted "A resource-bounded data-platform Pod with a tagged image"

echo "application admission-policy aws-dev runtime validation passed."

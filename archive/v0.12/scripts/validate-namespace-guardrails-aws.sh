#!/usr/bin/env bash
set -Eeuo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-10m}"

for command in aws kubectl; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

assert_label() {
  local namespace="$1"
  local label="$2"
  local expected="$3"
  local actual

  actual="$(
    kubectl get namespace "${namespace}" \
      -o "jsonpath={.metadata.labels.${label//./\\.}}"
  )"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Unexpected ${namespace} label ${label}: ${actual:-missing}" >&2
    exit 1
  fi
}

wait_for_application() {
  local application="$1"

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

dry_run_pod() {
  local namespace="$1"
  local name="$2"
  local privileged="$3"
  local run_as_non_root="$4"
  local image="$5"

  kubectl create --dry-run=server -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${name}
  namespace: ${namespace}
spec:
  automountServiceAccountToken: false
  restartPolicy: Never
  securityContext:
    runAsNonRoot: ${run_as_non_root}
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: test
      image: ${image}
      command: ["sh", "-c", "sleep 30"]
      securityContext:
        allowPrivilegeEscalation: false
        privileged: ${privileged}
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 10m
          memory: 32Mi
        limits:
          cpu: 50m
          memory: 64Mi
EOF
}

echo "==> Configuring kubeconfig for ${CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" >/dev/null

echo "==> Waiting for namespace guardrail applications"
wait_for_application namespace-guardrails-aws-dev
wait_for_application postgresql-baseline
wait_for_application demo-api-aws-dev

echo "==> Verifying Pod Security Admission labels"
assert_label startup-apps pod-security.kubernetes.io/enforce restricted
assert_label startup-apps pod-security.kubernetes.io/enforce-version v1.30
assert_label startup-apps pod-security.kubernetes.io/warn restricted
assert_label startup-apps pod-security.kubernetes.io/audit restricted
assert_label data-platform pod-security.kubernetes.io/enforce baseline
assert_label data-platform pod-security.kubernetes.io/enforce-version v1.30
assert_label data-platform pod-security.kubernetes.io/warn restricted
assert_label data-platform pod-security.kubernetes.io/audit restricted

echo "==> Verifying quotas and default container limits"
kubectl get resourcequota startup-apps -n startup-apps
kubectl get limitrange startup-apps-containers -n startup-apps
kubectl get resourcequota data-platform -n data-platform
kubectl get limitrange data-platform-containers -n data-platform

echo "==> Verifying protected workloads remain healthy"
kubectl rollout status deployment/demo-api \
  --namespace startup-apps \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=condition=Ready \
  cluster.postgresql.cnpg.io/postgresql-baseline \
  --namespace data-platform \
  --timeout="${WAIT_TIMEOUT}"

TEST_IMAGE="$(
  kubectl get deployment demo-api \
    --namespace startup-apps \
    -o jsonpath='{.spec.template.spec.containers[0].image}'
)"
if [[ "${TEST_IMAGE}" != *@sha256:* ]]; then
  echo "The live demo-api image is not digest pinned: ${TEST_IMAGE}" >&2
  exit 1
fi

echo "==> Verifying a restricted-compliant Pod is admitted"
dry_run_pod \
  startup-apps \
  namespace-guardrails-compliant \
  false \
  true \
  "${TEST_IMAGE}" >/dev/null

echo "==> Verifying privileged Pods are rejected"
for namespace in startup-apps data-platform; do
  if dry_run_pod \
    "${namespace}" \
    "namespace-guardrails-privileged-${namespace}" \
    true \
    false \
    "${TEST_IMAGE}" >/dev/null 2>&1; then
    echo "Pod Security Admission accepted a privileged Pod in ${namespace}." >&2
    exit 1
  fi
done

echo "namespace guardrail aws-dev runtime validation passed."

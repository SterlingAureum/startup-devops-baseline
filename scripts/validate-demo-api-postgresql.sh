#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
EKS_CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
APPLICATION_NAME="${APPLICATION_NAME:-demo-api-aws-dev}"
POSTGRES_CLUSTER="${POSTGRES_CLUSTER:-postgresql-baseline}"
POSTGRES_NAMESPACE="${POSTGRES_NAMESPACE:-data-platform}"
SOURCE_SECRET="${SOURCE_SECRET:-postgresql-baseline-app}"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-startup-apps}"
DEMO_DEPLOYMENT="${DEMO_DEPLOYMENT:-demo-api}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-20m}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-1200}"

for command in aws kubectl jq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Configuring kubeconfig for ${EKS_CLUSTER_NAME}"
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${EKS_CLUSTER_NAME}"

echo "==> Checking the demo-api Argo CD Application"
kubectl get application "${APPLICATION_NAME}" --namespace argocd >/dev/null
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

echo "==> Checking the minimum cross-namespace credential"
SOURCE_JSON="$(
  kubectl get secret "${SOURCE_SECRET}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output json
)"
TARGET_JSON="$(
  kubectl get secret "${TARGET_SECRET}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"

SOURCE_VALUE="$(jq -r '.data["fqdn-uri"] // empty' <<< "${SOURCE_JSON}")"
SOURCE_UID="$(jq -r '.metadata.uid // empty' <<< "${SOURCE_JSON}")"
TARGET_VALUE="$(jq -r '.data.DATABASE_URL // empty' <<< "${TARGET_JSON}")"
TARGET_KEYS="$(jq -r '.data | keys | join(",")' <<< "${TARGET_JSON}")"
TARGET_SOURCE_NAMESPACE="$(
  jq -r '.metadata.annotations["platform.startup.dev/source-namespace"] // empty' \
    <<< "${TARGET_JSON}"
)"
TARGET_SOURCE_SECRET="$(
  jq -r '.metadata.annotations["platform.startup.dev/source-secret"] // empty' \
    <<< "${TARGET_JSON}"
)"
TARGET_SOURCE_UID="$(
  jq -r '.metadata.annotations["platform.startup.dev/source-secret-uid"] // empty' \
    <<< "${TARGET_JSON}"
)"

if [[ -z "${SOURCE_VALUE}" || "${TARGET_VALUE}" != "${SOURCE_VALUE}" || \
      "${TARGET_KEYS}" != "DATABASE_URL" || \
      "${TARGET_SOURCE_NAMESPACE}" != "${POSTGRES_NAMESPACE}" || \
      "${TARGET_SOURCE_SECRET}" != "${SOURCE_SECRET}" || \
      "${TARGET_SOURCE_UID}" != "${SOURCE_UID}" ]]; then
  echo "The demo-api credential does not match the minimum synchronization contract." >&2
  exit 1
fi

echo "==> Checking the demo-api database environment contract"
DEPLOYMENT_JSON="$(
  kubectl get deployment "${DEMO_DEPLOYMENT}" \
    --namespace "${DEMO_NAMESPACE}" \
    --output json
)"
ENV_CONTRACT="$(
  jq -r '
    .spec.template.spec.containers[]
    | select(.name == "demo-api")
    | .env as $env
    | [
        ($env[] | select(.name == "DATABASE_ENABLED") | .value),
        ($env[] | select(.name == "DATABASE_URL")
          | .valueFrom.secretKeyRef.name),
        ($env[] | select(.name == "DATABASE_URL")
          | .valueFrom.secretKeyRef.key),
        ($env[] | select(.name == "DATABASE_CONNECT_TIMEOUT_SECONDS") | .value),
        ($env[] | select(.name == "DATABASE_RETRY_ATTEMPTS") | .value),
        ($env[] | select(.name == "DATABASE_RETRY_DELAY_SECONDS") | .value)
      ]
    | join(":")
  ' <<< "${DEPLOYMENT_JSON}"
)"

if [[ "${ENV_CONTRACT}" != \
      "true:${TARGET_SECRET}:DATABASE_URL:2:3:1" ]]; then
  echo "The demo-api Deployment does not match the database environment contract." >&2
  exit 1
fi

echo "==> Waiting for demo-api Pods"
kubectl rollout status "deployment/${DEMO_DEPLOYMENT}" \
  --namespace "${DEMO_NAMESPACE}" \
  --timeout="${WAIT_TIMEOUT}"
kubectl wait \
  --for=condition=Ready \
  pod \
  --namespace "${DEMO_NAMESPACE}" \
  --selector "app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api" \
  --timeout="${WAIT_TIMEOUT}"

mapfile -t DEMO_PODS < <(
  kubectl get pods \
    --namespace "${DEMO_NAMESPACE}" \
    --selector "app.kubernetes.io/name=demo-api,app.kubernetes.io/instance=demo-api" \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#DEMO_PODS[@]} != 2 )); then
  echo "Expected two running demo-api Pods, found ${#DEMO_PODS[@]}." >&2
  exit 1
fi

echo "==> Resolving the current PostgreSQL primary and RW Service"
mapfile -t PRIMARY_PODS < <(
  kubectl get pods \
    --namespace "${POSTGRES_NAMESPACE}" \
    --selector "cnpg.io/cluster=${POSTGRES_CLUSTER},cnpg.io/instanceRole=primary" \
    --field-selector status.phase=Running \
    --output jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}'
)
if (( ${#PRIMARY_PODS[@]} != 1 )); then
  echo "Expected exactly one running PostgreSQL primary." >&2
  exit 1
fi

PRIMARY_POD="${PRIMARY_PODS[0]}"
PRIMARY_IP="$(
  kubectl get pod "${PRIMARY_POD}" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{.status.podIP}'
)"
mapfile -t RW_ENDPOINTS < <(
  kubectl get endpoints "${POSTGRES_CLUSTER}-rw" \
    --namespace "${POSTGRES_NAMESPACE}" \
    --output jsonpath='{range .subsets[*].addresses[*]}{.ip}{"\n"}{end}'
)
if (( ${#RW_ENDPOINTS[@]} != 1 )) || \
   [[ "${RW_ENDPOINTS[0]}" != "${PRIMARY_IP}" ]]; then
  echo "The PostgreSQL RW Service does not resolve only to the current primary." >&2
  exit 1
fi

echo "==> Checking each demo-api PostgreSQL endpoint"
for demo_pod in "${DEMO_PODS[@]}"; do
  deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
  while true; do
    health_json="$(
      kubectl exec \
        --namespace "${DEMO_NAMESPACE}" \
        "${demo_pod}" -- \
        python -c \
          'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/db/health", timeout=15).read().decode())' \
        2>/dev/null || true
    )"

    health_contract="$(
      jq -r '
        [
          .status // "",
          .database // "",
          .user // "",
	  ((.server_address // "") | split("/")[0]),
          (.server_port // "" | tostring),
          (.in_recovery | tostring)
        ] | join(":")
      ' <<< "${health_json:-{}}" 2>/dev/null || true
    )"

    if [[ "${health_contract}" == "ok:app:app:${PRIMARY_IP}:5432:false" ]]; then
      break
    fi

    if (( SECONDS >= deadline )); then
      echo "demo-api Pod ${demo_pod} did not connect to the current primary." >&2
      exit 1
    fi
    sleep 5
  done
done

echo "demo-api PostgreSQL connection validation passed."

#!/usr/bin/env bash
set -euo pipefail

SOURCE_NAMESPACE="${SOURCE_NAMESPACE:-data-platform}"
SOURCE_SECRET="${SOURCE_SECRET:-postgresql-baseline-app}"
SOURCE_KEY="${SOURCE_KEY:-fqdn-uri}"
TARGET_NAMESPACE="${TARGET_NAMESPACE:-startup-apps}"
TARGET_SECRET="${TARGET_SECRET:-demo-api-postgresql}"
TARGET_KEY="${TARGET_KEY:-DATABASE_URL}"

for command in kubectl jq; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command}" >&2
    exit 1
  }
done

echo "==> Checking the CloudNativePG application credential"
kubectl get secret "${SOURCE_SECRET}" \
  --namespace "${SOURCE_NAMESPACE}" >/dev/null

SOURCE_VALUE="$(
  kubectl get secret "${SOURCE_SECRET}" \
    --namespace "${SOURCE_NAMESPACE}" \
    --output json |
    jq -r --arg key "${SOURCE_KEY}" '.data[$key] // empty'
)"
SOURCE_UID="$(
  kubectl get secret "${SOURCE_SECRET}" \
    --namespace "${SOURCE_NAMESPACE}" \
    --output jsonpath='{.metadata.uid}'
)"
SOURCE_RESOURCE_VERSION="$(
  kubectl get secret "${SOURCE_SECRET}" \
    --namespace "${SOURCE_NAMESPACE}" \
    --output jsonpath='{.metadata.resourceVersion}'
)"

if [[ -z "${SOURCE_VALUE}" || -z "${SOURCE_UID}" || \
      -z "${SOURCE_RESOURCE_VERSION}" ]]; then
  echo "The source credential is missing ${SOURCE_KEY} or identity metadata." >&2
  exit 1
fi

echo "==> Synchronizing the minimum credential into ${TARGET_NAMESPACE}"
kubectl create namespace "${TARGET_NAMESPACE}" \
  --dry-run=client \
  --output yaml | kubectl apply -f -

TEMP_FILE="$(mktemp)"
chmod 600 "${TEMP_FILE}"
trap 'rm -f "${TEMP_FILE}"' EXIT

kubectl get secret "${SOURCE_SECRET}" \
  --namespace "${SOURCE_NAMESPACE}" \
  --output json |
  jq \
    --arg namespace "${TARGET_NAMESPACE}" \
    --arg name "${TARGET_SECRET}" \
    --arg source_namespace "${SOURCE_NAMESPACE}" \
    --arg source_name "${SOURCE_SECRET}" \
    --arg source_uid "${SOURCE_UID}" \
    --arg source_resource_version "${SOURCE_RESOURCE_VERSION}" \
    --arg source_key "${SOURCE_KEY}" \
    --arg target_key "${TARGET_KEY}" \
    '{
      apiVersion: "v1",
      kind: "Secret",
      metadata: {
        name: $name,
        namespace: $namespace,
        labels: {
          "app.kubernetes.io/name": "demo-api",
          "app.kubernetes.io/part-of": "startup-devops-baseline",
          "platform.startup.dev/credential-purpose": "postgresql"
        },
        annotations: {
          "platform.startup.dev/managed-by": "sync-demo-api-postgresql-secret",
          "platform.startup.dev/source-namespace": $source_namespace,
          "platform.startup.dev/source-secret": $source_name,
          "platform.startup.dev/source-secret-uid": $source_uid,
          "platform.startup.dev/source-resource-version": $source_resource_version
        }
      },
      type: "Opaque",
      data: {
        ($target_key): .data[$source_key]
      }
    }' > "${TEMP_FILE}"

if [[ "$(jq -r --arg key "${TARGET_KEY}" '.data[$key] // empty' "${TEMP_FILE}")" \
      != "${SOURCE_VALUE}" ]]; then
  echo "The rendered target credential does not match the source value." >&2
  exit 1
fi

kubectl apply -f "${TEMP_FILE}" >/dev/null

TARGET_VALUE="$(
  kubectl get secret "${TARGET_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json |
    jq -r --arg key "${TARGET_KEY}" '.data[$key] // empty'
)"
TARGET_KEYS="$(
  kubectl get secret "${TARGET_SECRET}" \
    --namespace "${TARGET_NAMESPACE}" \
    --output json |
    jq -r '.data | keys | join(",")'
)"

if [[ "${TARGET_VALUE}" != "${SOURCE_VALUE}" || \
      "${TARGET_KEYS}" != "${TARGET_KEY}" ]]; then
  echo "The target Secret does not contain exactly the synchronized credential." >&2
  exit 1
fi

echo "demo-api PostgreSQL credential synchronization passed."
echo "The credential value was not printed or committed to Git."

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
DEMO_APP_NAME="${DEMO_APP_NAME:-demo-api}"
GUARDRAILS_APP_NAME="${GUARDRAILS_APP_NAME:-namespace-guardrails}"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

# shellcheck source=scripts/lib/argocd-operation.sh
source "${ROOT_DIR}/scripts/lib/argocd-operation.sh"

require_cmd() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
}

wait_for_application() {
  local application_name="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))

  until kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" >/dev/null 2>&1; do
    if [ "${SECONDS}" -ge "${deadline}" ]; then
      echo "ERROR: timed out waiting for Application/${application_name}." >&2
      exit 1
    fi
    sleep 2
  done
}

assert_head_revision() {
  local application_name="$1"
  local revision
  revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.spec.source.targetRevision}')"
  if [ "${revision}" != "HEAD" ]; then
    echo "ERROR: Application/${application_name} did not return to HEAD: ${revision:-<empty>}." >&2
    exit 1
  fi
}

set_application_automation() {
  local application_name="$1"
  local mode="$2"

  if [ "${mode}" = "manual" ]; then
    kubectl -n "${ARGOCD_NAMESPACE}" patch application "${application_name}" \
      --type merge \
      -p '{"spec":{"syncPolicy":{"automated":null}}}' >/dev/null
  else
    kubectl -n "${ARGOCD_NAMESPACE}" patch application "${application_name}" \
      --type merge \
      -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}' >/dev/null
  fi
}

sync_application_if_needed() {
  local application_name="$1"
  local sync_status

  wait_for_application_idle "${application_name}"
  argocd app get "${application_name}" --hard-refresh >/dev/null
  sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.sync.status}')"
  if [ "${sync_status}" != "Synced" ]; then
    run_argocd_mutation_with_retry \
      "${application_name}" \
      argocd app sync "${application_name}"
  fi
  wait_for_application_idle "${application_name}"
}

for command_name in argocd kubectl; do
  require_cmd "${command_name}"
done

validate_argocd_operation_settings

cd "${ROOT_DIR}"

echo "==> Restoring the declarative local HEAD baseline through the Root App-of-Apps"
TARGET_REVISION=HEAD \
GIT_TARGET_REVISION=HEAD \
ROOT_SYNC_MODE=manual \
LOCAL_IMAGE_ENABLED=false \
REPO_URL="${REPO_URL}" \
  "${ROOT_DIR}/scripts/deploy-root-app.sh"

sync_application_if_needed "${ROOT_APP_NAME}"

wait_for_application "${GUARDRAILS_APP_NAME}"
wait_for_application "${DEMO_APP_NAME}"
sync_application_if_needed "${GUARDRAILS_APP_NAME}"
sync_application_if_needed "${DEMO_APP_NAME}"

set_application_automation "${ROOT_APP_NAME}" automated

assert_head_revision "${ROOT_APP_NAME}"
assert_head_revision "${GUARDRAILS_APP_NAME}"
assert_head_revision "${DEMO_APP_NAME}"

root_child_revision="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.source.helm.parameters[?(@.name=="git.targetRevision")].value}')"
if [ "${root_child_revision}" != "HEAD" ]; then
  echo "ERROR: Root-rendered child revision did not return to HEAD: ${root_child_revision:-<empty>}." >&2
  exit 1
fi

root_local_image_enabled="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.source.helm.parameters[?(@.name=="demoApi.localImage.enabled")].value}')"
if [ "${root_local_image_enabled}" != "false" ]; then
  echo "ERROR: Root local-image mode was not disabled." >&2
  exit 1
fi

helm_parameter_names="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" -o jsonpath='{range .spec.source.helm.parameters[*]}{.name}{"\n"}{end}')"
if [ -n "${helm_parameter_names}" ]; then
  echo "ERROR: demo-api still has live Helm parameters after declarative HEAD restoration:" >&2
  printf '%s\n' "${helm_parameter_names}" >&2
  exit 1
fi

self_heal="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.syncPolicy.automated.selfHeal}')"
if [ "${self_heal}" != "true" ]; then
  echo "ERROR: Root automated self-heal was not restored." >&2
  exit 1
fi

root_sync_status="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.status.sync.status}')"
if [ "${root_sync_status}" != "Synced" ]; then
  echo "ERROR: Root did not remain Synced after declarative HEAD restoration: ${root_sync_status:-<empty>}." >&2
  exit 1
fi

echo "Local GitOps HEAD baseline restored."
echo "Root and same-repository children use HEAD, local image parameters are empty, and Root automation is enabled."

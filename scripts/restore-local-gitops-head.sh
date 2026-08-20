#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
ROOT_APP_NAME="${ROOT_APP_NAME:-startup-devops-root}"
DEMO_APP_NAME="${DEMO_APP_NAME:-demo-api}"
GUARDRAILS_APP_NAME="${GUARDRAILS_APP_NAME:-namespace-guardrails}"
REPO_URL="${REPO_URL:-https://github.com/SterlingAureum/startup-devops-baseline.git}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

require_cmd() {
  local command_name="$1"
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: ${command_name}" >&2
    exit 1
  }
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

wait_for_application_idle() {
  local application_name="$1"
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  local idle_observations=0
  local operation
  local phase

  while [ "${SECONDS}" -lt "${deadline}" ]; do
    operation="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.operation}' 2>/dev/null || true)"
    phase="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${application_name}" -o jsonpath='{.status.operationState.phase}' 2>/dev/null || true)"
    if [ -z "${operation}" ] && [ "${phase}" != "Running" ]; then
      idle_observations=$((idle_observations + 1))
      if [ "${idle_observations}" -ge 2 ]; then
        return 0
      fi
    else
      idle_observations=0
      argocd app wait "${application_name}" --operation --timeout "${WAIT_TIMEOUT_SECONDS}" >/dev/null || true
    fi
    sleep 1
  done

  echo "ERROR: timed out waiting for Application/${application_name} to become idle." >&2
  exit 1
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
    argocd app sync "${application_name}"
  fi
  wait_for_application_idle "${application_name}"
}

remove_all_demo_parameters() {
  local parameter_name

  while IFS= read -r parameter_name; do
    [ -n "${parameter_name}" ] || continue
    echo "Removing local demo-api Helm parameter: ${parameter_name}"
    argocd app unset "${DEMO_APP_NAME}" -p "${parameter_name}"
  done < <(
    kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" \
      -o jsonpath='{range .spec.source.helm.parameters[*]}{.name}{"\n"}{end}'
  )
}

for command_name in argocd kubectl; do
  require_cmd "${command_name}"
done

cd "${ROOT_DIR}"

echo "==> Restoring the declarative local HEAD baseline"
TARGET_REVISION=HEAD \
ROOT_SYNC_MODE=manual \
REPO_URL="${REPO_URL}" \
  "${ROOT_DIR}/scripts/deploy-root-app.sh"

sync_application_if_needed "${ROOT_APP_NAME}"

set_application_automation "${GUARDRAILS_APP_NAME}" manual
set_application_automation "${DEMO_APP_NAME}" manual
wait_for_application_idle "${GUARDRAILS_APP_NAME}"
wait_for_application_idle "${DEMO_APP_NAME}"

remove_all_demo_parameters

for application_name in "${GUARDRAILS_APP_NAME}" "${DEMO_APP_NAME}"; do
  sync_application_if_needed "${application_name}"
  set_application_automation "${application_name}" automated
done

set_application_automation "${ROOT_APP_NAME}" automated

assert_head_revision "${ROOT_APP_NAME}"
assert_head_revision "${GUARDRAILS_APP_NAME}"
assert_head_revision "${DEMO_APP_NAME}"

helm_parameter_names="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${DEMO_APP_NAME}" -o jsonpath='{range .spec.source.helm.parameters[*]}{.name}{"\n"}{end}')"
if [ -n "${helm_parameter_names}" ]; then
  echo "ERROR: demo-api still has live Helm parameters after HEAD restoration:" >&2
  printf '%s\n' "${helm_parameter_names}" >&2
  exit 1
fi

self_heal="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${ROOT_APP_NAME}" -o jsonpath='{.spec.syncPolicy.automated.selfHeal}')"
if [ "${self_heal}" != "true" ]; then
  echo "ERROR: root automated self-heal was not restored." >&2
  exit 1
fi

echo "Local GitOps HEAD baseline restored."
echo "The demo-api image and Helm parameters now come only from the HEAD declaration."

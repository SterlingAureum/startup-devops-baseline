#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGOCD_NAMESPACE="${ARGOCD_NAMESPACE:-argocd}"
OBSERVABILITY_NAMESPACE="${OBSERVABILITY_NAMESPACE:-observability}"
APP_NAMESPACE="${APP_NAMESPACE:-startup-apps}"
EVENTS_PVC="${EVENTS_PVC:-observability-events-collector-storage}"
WORK_DIR="$(mktemp -d)"
CURRENT_STAGE="preflight"

cleanup() {
  rm -rf -- "${WORK_DIR}"
}
trap cleanup EXIT

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

for command_name in bash jq kubectl tee; do
  command -v "${command_name}" >/dev/null 2>&1 \
    || fail "required command not found: ${command_name}"
done

emit_failure_diagnostics() {
  local status="$1"
  echo "ERROR: v0.11.6.1.3 stage failed: ${CURRENT_STAGE} (exit ${status})." >&2
  echo "==> Argo CD Application diagnostics" >&2
  kubectl -n "${ARGOCD_NAMESPACE}" get application \
    startup-devops-root monitoring logging-loki logging-alloy logging-alloy-events \
    -o wide >&2 2>/dev/null || true
  echo "==> Observability workload diagnostics" >&2
  kubectl -n "${OBSERVABILITY_NAMESPACE}" get pod,pvc -o wide >&2 2>/dev/null || true
  echo "==> Events collector diagnostics" >&2
  kubectl -n "${OBSERVABILITY_NAMESPACE}" logs \
    deployment/observability-events-collector -c alloy --tail=80 >&2 2>/dev/null || true
  echo "The failing stage output was streamed above; temporary diagnostics will now be cleaned." >&2
}

run_stage() {
  local name="$1"
  shift
  local status
  CURRENT_STAGE="${name}"
  echo "==> Running v0.11.6.1.3 stage: ${CURRENT_STAGE}"
  if "$@" 2>&1 | tee "${WORK_DIR}/${CURRENT_STAGE}.log"; then
    echo "PASS: ${CURRENT_STAGE}"
    return 0
  else
    status="${PIPESTATUS[0]}"
    emit_failure_diagnostics "${status}"
    exit "${status}"
  fi
}

assert_application_healthy() {
  local name="$1"
  local sync
  local health
  sync="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" \
    -o jsonpath='{.status.sync.status}')"
  health="$(kubectl -n "${ARGOCD_NAMESPACE}" get application "${name}" \
    -o jsonpath='{.status.health.status}')"
  [ "${sync}" = "Synced" ] && [ "${health}" = "Healthy" ] \
    || fail "Application/${name} is not Synced/Healthy: sync=${sync:-unknown} health=${health:-unknown}"
}

final_state_check() {
  local name
  for name in startup-devops-root monitoring logging-loki logging-alloy logging-alloy-events; do
    assert_application_healthy "${name}"
  done
  [ "$(kubectl -n "${OBSERVABILITY_NAMESPACE}" get pvc "${EVENTS_PVC}" \
    -o jsonpath='{.status.phase}')" = "Bound" ] \
    || fail "Events position PVC is not Bound after end-to-end acceptance."
  kubectl -n "${APP_NAMESPACE}" get events -o json \
    | jq -e '[.items[] | select(.metadata.name | startswith("v011612-"))] | length == 0' \
      >/dev/null \
    || fail "temporary v0.11.6.1.2 acceptance Events remain after strict cleanup."
  echo "PASS: Applications are healthy, the Events PVC is Bound, and no temporary acceptance Event remains."
}

run_stage platform-baseline "${ROOT_DIR}/scripts/validate.sh"
run_stage pod-log-runtime "${ROOT_DIR}/scripts/check-local-logging-runtime.sh"
run_stage events-grafana-runtime "${ROOT_DIR}/scripts/check-local-events-grafana.sh"
run_stage final-state final_state_check

echo "v0.11.6.1 local structured logs, Pod collection, Kubernetes Events, Loki persistence, Grafana query, strict cleanup, and repeatable end-to-end acceptance passed."
